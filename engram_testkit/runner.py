"""The run record: the same questions and answer model for every arm, every call saved, a hard cap,
retries, stop-and-save, resume, and two runs of every question.

A callable is called as call(prompt, max_tokens=..., temperature=..., reasoning=...) -> (text, usage, secs),
names its model in .model, and reports the settings it actually used in usage["effective"] =
{model, max_tokens, temperature, reasoning}. The kit names no model: the run freeze does (IF-8). A callable
that cannot take the settings is refused before any call; a call whose reported settings differ from the
freeze, or are missing, is saved as a failed call and stops the run (build revision 2).

Output folder (outside any git repository, TK-13):
  state.json     the run's state, freeze, audit and stop reason
  answers.jsonl  one row per arm, question and run
  calls.jsonl    every try of every call
"""
import copy
import inspect
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Optional

from . import formats as F
from .arms import FLOOR, Registry, binding
from .audit import audit_record, check_audit, question_set_sha
from .label import label_for

KIT = "Engram Comparative Conversation Test Kit"

# Copied word for word from vps_kit.py (TK-4: the frozen answer prompt for Stages 4 to 6; TK-5: the judge wording).
ANSWER = """Below are excerpts from past conversations. Answer the question using only them, in as few words as you can. Resolve relative dates using the date in brackets. If they do not contain the answer, reply exactly: not mentioned

Excerpts:
{ctx}

Question: {q}
Answer:"""

JUDGE = """Your task is to label an answer to a question as 'CORRECT' or 'WRONG'. The gold answer will usually be concise. The generated answer might be much longer, but be generous: as long as it touches on the same topic as the gold answer, count it as CORRECT. For time questions, count it as CORRECT if it refers to the same date or time period, whatever the format.

Question: {q}
Gold answer: {gold}
Generated answer: {pred}

Reply with only CORRECT or WRONG."""

NO_EXCERPTS = "(no excerpts)"  # the context given when an arm returns nothing, as vps_kit's "none" system does
FREEZE_FIELDS = ("model", "max_tokens", "temperature", "reasoning")
SETTINGS = ("max_tokens", "temperature", "reasoning")  # passed to the callable on every call
FREEZE_PARTS = ("answer", "judge")
RUNS = 2
CALLS_PER_QUESTION = 2  # one answer, one judge
MAX_TRIES = 3


class FreezeError(ValueError):
    """The run freeze is missing, incomplete, or does not match the callables."""


class CallableRefused(FreezeError):
    """A callable cannot be used: it does not name its model, or cannot take the frozen settings."""


class EffectiveMismatch(FreezeError):
    """A callable reported settings other than the frozen ones, or reported none."""


class AskedOnBreach(ValueError):
    """An arm returned a turn that cannot be shown to come on or before the question's asked_on date."""


class NotIdentical(ValueError):
    """Rows or sessions do not share one question set, one answer model, or the same questions."""


class InsideRepository(PermissionError):
    """The output folder is inside a git repository. Run records hold conversation text."""


class CapReached(Exception):
    """The call cap is spent."""


def cap_for(arms, questions, runs=RUNS, calls=CALLS_PER_QUESTION):
    """The call cap: arms x questions x runs x calls per question, plus 50 %, rounded up (TK-7)."""
    return math.ceil(arms * questions * runs * calls * 3 / 2)


def inside_repository(path):
    """True if the path, or any folder above it, holds a .git entry."""
    here = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return True
        up = os.path.dirname(here)
        if up == here:
            return False
        here = up


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def check_identical(rows, finished=True):
    """One answer model, one judge model and one question set on every row; on a finished run, every arm
    asked the same questions in the same runs. Returns True or raises NotIdentical."""
    for field, words in (("answer_model", "answer model"), ("judge_model", "judge model"), ("question_set", "question set")):
        seen = {r.get(field) for r in rows}
        if len(seen) > 1:
            raise NotIdentical(f"rows carry more than one {words}: {sorted(map(str, seen))}")
    if finished:
        asked = {}
        for r in rows:
            asked.setdefault(r["arm"], set()).add((r["qid"], r["run"]))
        if len({frozenset(v) for v in asked.values()}) > 1:
            raise NotIdentical("the arms were not asked the same questions in the same runs")
    return True


@dataclass
class RunConfig:
    out_dir: str
    call_cap: int
    freeze: Optional[dict] = None
    audit: Optional[dict] = None
    runs: int = RUNS
    max_tries: int = MAX_TRIES


def takes_settings(fn):
    """True if the callable accepts max_tokens, temperature and reasoning as keyword arguments."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    if any(p.kind is p.VAR_KEYWORD for p in params):
        return True
    names = {p.name for p in params if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    return set(SETTINGS) <= names


def expected_settings(freeze, kind):
    """What a call of this kind must use, and report: the frozen model and settings."""
    return {f: freeze[kind][f] for f in FREEZE_FIELDS}


def settings_differ(expected, effective):
    """A list of differences between the frozen settings and the reported ones; empty if they match."""
    if not isinstance(effective, dict):
        return ["no effective settings reported"]
    out = []
    for f in FREEZE_FIELDS:
        if f not in effective:
            out.append(f"{f}: not reported")
            continue
        want, got = expected[f], effective[f]
        if want != got or isinstance(want, bool) != isinstance(got, bool):
            out.append(f"{f}: frozen {want!r}, used {got!r}")
    return out


def _plain(value):
    """The value as it reads back from JSON, so a resumed session compares like with like."""
    return json.loads(json.dumps(value))


def check_freeze(freeze, answer, judge):
    """Every part names model, max_tokens, temperature and reasoning; each callable names the frozen model and
    can take the frozen settings."""
    for kind, fn in (("answer", answer), ("judge", judge)):
        model = getattr(fn, "model", None)
        if not isinstance(model, str) or not model:
            raise CallableRefused(f"the {kind} callable must name its model in .model")
        if not takes_settings(fn):
            raise CallableRefused(f"the {kind} callable cannot take max_tokens, temperature and reasoning; "
                                  "the freeze could not be applied or checked")
    if not isinstance(freeze, dict):
        raise FreezeError("a run needs a freeze: {answer: {model, max_tokens, temperature, reasoning}, judge: {...}}")
    for kind in FREEZE_PARTS:
        part = freeze.get(kind)
        if not isinstance(part, dict):
            raise FreezeError(f"the freeze has no '{kind}' part")
        for field in FREEZE_FIELDS:
            if part.get(field) is None:
                raise FreezeError(f"the {kind} freeze lacks '{field}'")
        if not isinstance(part["max_tokens"], int) or part["max_tokens"] < 1:
            raise FreezeError(f"the {kind} freeze's 'max_tokens' must be a positive whole number")
    for kind, fn in (("answer", answer), ("judge", judge)):
        if freeze[kind]["model"] != fn.model:
            raise FreezeError(f"the {kind} callable names {fn.model!r} but the freeze names {freeze[kind]['model']!r}")


class _Budget:
    def __init__(self, cap, used):
        self.cap, self.used = cap, used

    def spend(self):
        if self.used >= self.cap:
            raise CapReached(f"call cap reached: {self.used} of {self.cap} calls used")
        self.used += 1


class _Run:
    def __init__(self, registry, conversations, questions, answer, judge, config):
        self.cfg = config
        self.out = config.out_dir
        self.state_path = os.path.join(self.out, "state.json")
        self.answers_path = os.path.join(self.out, "answers.jsonl")
        self.calls_path = os.path.join(self.out, "calls.jsonl")
        self.answer, self.judge = answer, judge
        self.conversations = conversations
        self.all_questions = list(questions)
        self.arms = registry.items()
        self.label = label_for([a for _, a in self.arms])
        self.question_set = question_set_sha(self.all_questions)
        self.freeze = copy.deepcopy(config.freeze)
        self.asked = []
        self.ingest = {}
        self.done = set()
        self.sessions = 1
        self.budget = None

    # --- checks before anything is written -------------------------------------------------------
    def check(self):
        if inside_repository(self.out):
            raise InsideRepository(f"{self.out} is inside a git repository; keep run records outside it (TK-13)")
        if not self.arms:
            raise ValueError("no arm is bound")
        if not isinstance(self.cfg.runs, int) or self.cfg.runs < 1:
            raise ValueError("runs must be a positive whole number")
        check_freeze(self.cfg.freeze, self.answer, self.judge)
        # Conversations first: a real conversation is refused as real data, not for a question's missing asked_on.
        for c in self.conversations.values():
            F.validate_conversation(c)
        for q in self.all_questions:
            F.validate_question(q, self.conversations)
        self.asked = check_audit(self.cfg.audit, self.all_questions)
        self.audit = audit_record(self.cfg.audit)

    def resume(self):
        """Rows already in answers.jsonl are skipped, and the cap counts every call of every session."""
        if not os.path.exists(self.state_path):
            return set(), 0, 1
        with open(self.state_path, encoding="utf-8") as f:
            old = json.load(f)
        self._same(old, "question_set", self.question_set)
        self._same(old, "freeze", self.freeze)
        self._same(old, "arms", [k for k, _ in self.arms])
        self._same(old, "runs", self.cfg.runs)
        self._same(old, "asked", [q["id"] for q in self.asked])
        self._same_settings(read_jsonl(self.calls_path))
        done = {(r["arm"], r["qid"], r["run"]) for r in read_jsonl(self.answers_path)}
        return done, len(read_jsonl(self.calls_path)), old.get("sessions", 1) + 1

    def _same(self, old, field, now):
        if _plain(old.get(field)) != _plain(now):
            raise NotIdentical(f"cannot resume into {self.out}: the {field.replace('_', ' ')} differs from the earlier session")

    def _same_settings(self, calls):
        """Every earlier call asked for, and reported, exactly the frozen settings."""
        for c in calls:
            want = _plain(expected_settings(self.freeze, c["kind"]))
            if _plain(c.get("requested")) != want:
                raise NotIdentical(f"cannot resume into {self.out}: an earlier {c['kind']} call asked for other settings")
            if c.get("effective") is not None and settings_differ(want, c["effective"]):
                raise NotIdentical(f"cannot resume into {self.out}: an earlier {c['kind']} call used other settings "
                                   f"({'; '.join(settings_differ(want, c['effective']))}); start a new output folder")
            if c.get("ok") and c.get("effective") is None:
                raise NotIdentical(f"cannot resume into {self.out}: an earlier {c['kind']} call reported no settings")

    # --- records -------------------------------------------------------------------------------
    def _write(self, path, record):
        if self.label:
            record = dict(record, label=self.label)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

    def save_state(self, stopped, reason):
        state = dict(kit=KIT, simulated=self.label is not None, stopped=stopped, reason=reason,
                     runs=self.cfg.runs, sessions=self.sessions, calls_used=self.budget.used if self.budget else 0,
                     call_cap=self.cfg.call_cap, max_tries=self.cfg.max_tries,
                     answer_model=self.freeze["answer"]["model"], judge_model=self.freeze["judge"]["model"],
                     freeze=self.freeze, audit=self.audit, question_set=self.question_set,
                     questions=len(self.all_questions), asked=[q["id"] for q in self.asked],
                     arms=[k for k, _ in self.arms], bindings={k: binding(a) for k, a in self.arms},
                     floor=any(k == FLOOR for k, _ in self.arms), ingest=self.ingest,
                     rows_done=len(self.done), saved_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        if self.label:
            state = dict(state, label=self.label)
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1, ensure_ascii=False)
        os.replace(tmp, self.state_path)
        return state

    # --- calls ---------------------------------------------------------------------------------
    def call(self, kind, key, q, run, prompt):
        """Up to max_tries tries; every try spends one call of the cap and is saved at once.
        Returns (text, record of the good try) or (None, error text)."""
        fn = self.answer if kind == "answer" else self.judge
        part = self.freeze[kind]
        max_tokens = self.freeze[kind]["max_tokens"]
        settings = dict(max_tokens=max_tokens, temperature=part["temperature"], reasoning=part["reasoning"])
        expected = expected_settings(self.freeze, kind)
        rec = None
        for attempt in range(1, self.cfg.max_tries + 1):
            self.budget.spend()
            rec = dict(arm=key, qid=q["id"], run=run, kind=kind, model=fn.model, attempt=attempt,
                       max_tokens=max_tokens, requested=expected, effective=None, prompt=prompt,
                       prompt_tokens_est=F.estimate_tokens(prompt))
            start = time.perf_counter()
            try:
                text, usage, reported = fn(prompt, **settings)
                if not isinstance(text, str):
                    raise TypeError(f"the {kind} callable returned {type(text).__name__}, not text")
            except Exception as e:  # a failed try: saved, counted, tried again
                rec.update(ok=False, reply=None, error=f"{type(e).__name__}: {e}", secs=round(time.perf_counter() - start, 6))
                self._write(self.calls_path, rec)
                continue
            except BaseException as e:  # an interruption: saved, then raised
                rec.update(ok=False, reply=None, error=f"{type(e).__name__}: {e}", secs=round(time.perf_counter() - start, 6))
                self._write(self.calls_path, rec)
                raise
            usage = usage if isinstance(usage, dict) else {}
            rec.update(ok=True, reply=text, error=None, secs=round(time.perf_counter() - start, 6),
                       reported_secs=reported, prompt_tokens=usage.get("prompt_tokens"),
                       completion_tokens=usage.get("completion_tokens"), completion_tokens_est=F.estimate_tokens(text))
            effective = usage.get("effective")
            rec["effective"] = effective
            differ = settings_differ(expected, effective)
            if differ:
                # The reply was made under other settings than the frozen ones: saved as a failed call, then the run stops.
                rec.update(ok=False, error="EffectiveMismatch: " + "; ".join(differ))
                self._write(self.calls_path, rec)
                raise EffectiveMismatch(f"the {kind} callable did not use the frozen settings: {'; '.join(differ)}")
            self._write(self.calls_path, rec)
            return text, rec
        rec = dict(rec, error=f"all {self.cfg.max_tries} tries failed; last: {rec['error']}")
        return None, rec

    def check_asked_on(self, key, q, turn_ids):
        """No returned turn may come after the question's asked_on date. A turn that is not in the question's
        conversation, or whose date cannot be read, cannot be shown to come before it, so it breaches too."""
        turns = {t["id"]: t for t in self.conversations[q["conversation"]]["turns"]}
        late = [t for t in turn_ids if t not in turns or (F.turn_day(turns[t]["date"]) or "9999") > q["asked_on"]]
        if late:
            raise AskedOnBreach(f"arm {key} returned turns {late} for question {q['id']}, asked on {q['asked_on']}")

    def ask(self, key, arm, q, run):
        """One row: retrieve, answer, and judge unless the question is adversarial."""
        start = time.perf_counter()
        got = arm.retrieve(q["question"], conversation=q["conversation"], asked_on=q.get("asked_on"))
        retrieve_secs = round(time.perf_counter() - start, 6)
        turn_ids = list(got.turn_ids)
        if q.get("asked_on"):
            self.check_asked_on(key, q, turn_ids)
        prompt = ANSWER.format(ctx=got.context or NO_EXCERPTS, q=q["question"])
        pred, info = self.call("answer", key, q, run, prompt)
        row = dict(arm=key, qid=q["id"], run=run, conversation=q["conversation"], category=q["category"],
                   question=q["question"], gold=q["gold"], asked_on=q.get("asked_on"), pred=pred, judge=None,
                   error=None, judge_error=None, retrieved=turn_ids, context_tokens=got.tokens,
                   retrieve_secs=retrieve_secs, answer_model=self.freeze["answer"]["model"],
                   judge_model=self.freeze["judge"]["model"], question_set=self.question_set)
        # Answer-call latency is the last try's; tokens as reported when both counts are given, else estimated.
        row["answer_secs"] = info["secs"]
        if pred is None:
            row.update(error=info["error"], answer_tokens_reported=None, answer_tokens_est=info["prompt_tokens_est"])
        else:
            reported = (info.get("prompt_tokens"), info.get("completion_tokens"))
            row["answer_tokens_reported"] = sum(reported) if None not in reported else None
            row["answer_tokens_est"] = info["prompt_tokens_est"] + info["completion_tokens_est"]
        row["answer_tokens"] = row["answer_tokens_reported"] if row["answer_tokens_reported"] is not None else row["answer_tokens_est"]
        ev = set(q["evidence"])
        row["evidence_found"] = None if q["category"] == "adversarial" else len(ev & set(turn_ids)) / len(ev)
        if pred is not None and q["category"] != "adversarial":
            reply, info = self.call("judge", key, q, run, JUDGE.format(q=q["question"], gold=q["gold"], pred=pred))
            row["judge"] = reply
            if reply is None:
                row["judge_error"] = info["error"]
        self._write(self.answers_path, row)
        self.done.add((key, q["id"], run))

    # --- the run -------------------------------------------------------------------------------
    def go(self):
        self.check()
        self.done, used, self.sessions = self.resume()
        self.budget = _Budget(self.cfg.call_cap, used)
        os.makedirs(self.out, exist_ok=True)
        try:
            self.save_state(True, "session started; not finished")
            for key, arm in self.arms:
                start = time.perf_counter()
                arm.reset()
                for c in self.conversations.values():
                    arm.ingest(c)
                self.ingest[key] = round(time.perf_counter() - start, 6)
            # Question first, then arm, then run: a stop leaves every earlier question complete in every arm.
            for q in self.asked:
                for key, arm in self.arms:
                    for run in range(1, self.cfg.runs + 1):
                        if (key, q["id"], run) not in self.done:
                            self.ask(key, arm, q, run)
        except CapReached as e:
            return self.save_state(True, str(e))
        except BaseException as e:
            self.save_state(True, f"{type(e).__name__}: {e}")
            raise
        return self.save_state(False, "finished")


def run(registry, conversations, questions, answer, judge, config):
    """Run every asked question through every bound arm, config.runs times. Returns the saved state."""
    if not isinstance(registry, Registry):
        raise TypeError("arms must be given as a Registry")
    return _Run(registry, conversations, questions, answer, judge, config).go()
