"""The scoring sheet: generous judge labels, the gold-word rule, the adversarial rule, blinded strict
labels, both runs apart, the paired comparison against arm A, and latency and token cost per arm.

Strict scoring has two parts (TK-6): the gold-word rule is the floor, and blinded strict labels, given
later, are the reported figure. Until they are given the blinded columns say "pending".
"""
import json
import os
import random
import re
from statistics import mean

from .arms import FLOOR, SLOTS
from .formats import NOT_MENTIONED, estimate_tokens
from .label import LABEL, LabelMissing
from .runner import KIT, check_identical, settings_differ

SEED = 7          # the paired bootstrap seed (TK-18)
BOOTSTRAP = 2000  # resamples
SHEET_SEED = 99   # the blinded sheet's shuffle, as kit_tools/judge_sheet.py uses

_GOLD_STOP = frozenset("""a an the of in on at to and or for by with from as is are was were be been it its
his her their this that""".split())


def _tokens(text):
    out = []
    for w in re.findall(r"[a-z0-9]+", str(text).lower()):
        m = re.fullmatch(r"(\d+)(st|nd|rd|th)", w)
        out.append(m.group(1) if m else w)
    return out


def generous(reply):
    """The judge's label: the reply begins with CORRECT."""
    return isinstance(reply, str) and reply.strip().upper().startswith("CORRECT")


def says_not_mentioned(pred):
    """True if the answer contains the words "not mentioned", side by side."""
    if not isinstance(pred, str):
        return False
    words, want = _tokens(pred), NOT_MENTIONED.split()
    return any(words[i:i + len(want)] == want for i in range(len(words)))


def adversarial(pred):
    """The fixed adversarial rule: correct only if the answer says "not mentioned"."""
    return says_not_mentioned(pred)


def strict(pred, gold):
    """The gold-word rule: every content word of the gold answer is in the answer. Never credits "not mentioned"."""
    if not isinstance(pred, str) or says_not_mentioned(pred):
        return False
    words = [w for w in _tokens(gold) if w not in _GOLD_STOP] or _tokens(gold)
    have = set(_tokens(pred))
    return bool(words) and all(w in have for w in words)


def score(row):
    """Generous and strict labels for one row. Adversarial rows use the fixed rule for both; the judge is not consulted."""
    if row["category"] == "adversarial":
        ok = adversarial(row["pred"])
        return dict(generous=ok, strict=ok)
    return dict(generous=generous(row.get("judge")) if row.get("pred") is not None else False,
                strict=strict(row.get("pred"), row["gold"]))


def _pct(values):
    values = list(values)
    return round(100 * sum(map(bool, values)) / len(values), 1) if values else None


def _mean(values, places=6):
    values = [v for v in values if v is not None]
    return round(mean(values), places) if values else None


def _check_labels(rows, calls, state):
    """Decide whether the records come from a simulated run, and refuse any record of one without the label."""
    records = list(rows) + list(calls)
    labelled = [r.get("label") == LABEL for r in records]
    if state is not None:
        simulated = state.get("simulated") is not False or any(labelled)
    elif any(labelled) or not records:
        simulated = True
    else:
        raise LabelMissing("no record carries the label and no run state was given; pass state= to show the run is not simulated")
    if simulated and not all(labelled):
        raise LabelMissing("run records of simulated arms must all carry the label")
    return simulated


def bootstrap_diff(pairs, seed=SEED, n=BOOTSTRAP):
    """Paired bootstrap of (other − A) in points, from (a, other) pairs of 0/1 labels. Returns (points, (low, high))."""
    pairs = [(int(bool(a)), int(bool(b))) for a, b in pairs]
    if not pairs:
        return None, (None, None)
    rng = random.Random(seed)
    diffs = [b - a for a, b in pairs]
    point = 100 * sum(diffs) / len(diffs)
    draws = sorted(100 * sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n))
    low, high = draws[int(0.025 * (n - 1))], draws[int(round(0.975 * (n - 1)))]
    return round(point, 1), (round(low, 1), round(high, 1))


def paired_vs_a(scored, seed=SEED):
    """Each arm and the floor against arm A, paired by question and run, on the gold-word rule."""
    by = {}
    for r in scored:
        by.setdefault(r["arm"], {})[(r["qid"], r["run"])] = r["strict"]
    if "A" not in by:
        return {}
    out = {}
    for arm in by:
        if arm == "A":
            continue
        keys = sorted(set(by["A"]) & set(by[arm]))
        points, (low, high) = bootstrap_diff([(by["A"][k], by[arm][k]) for k in keys], seed=seed)
        out[arm] = dict(points=points, interval_95=[low, high], pairs=len(keys), seed=seed, rule="gold-word rule",
                        resamples=BOOTSTRAP)
    return out


def _arm_summary(arm, rows, calls, runs, ingest):
    per_run = {n: [r for r in rows if r["run"] == n] for n in range(1, runs + 1)}
    by_q = {}
    for r in rows:
        by_q.setdefault(r["qid"], {})[r["run"]] = (r["generous"], r["strict"])
    agree = [len(set(v.values())) == 1 for v in by_q.values() if len(v) == runs]
    cats = sorted({r["category"] for r in rows})
    ok_calls = [c for c in calls if c.get("ok")]

    def call_tokens(c, reported_only=False):
        p, d = c.get("prompt_tokens"), c.get("completion_tokens")
        if reported_only:
            return (p or 0) + (d or 0) if (p is not None or d is not None) else None
        return (p if p is not None else c.get("prompt_tokens_est", estimate_tokens(c.get("prompt")))) + \
               (d if d is not None else c.get("completion_tokens_est", estimate_tokens(c.get("reply"))))

    reported = [call_tokens(c, True) for c in ok_calls]
    return dict(
        questions=len(by_q),
        generous={n: _pct(r["generous"] for r in rs) for n, rs in per_run.items()},
        strict={n: _pct(r["strict"] for r in rs) for n, rs in per_run.items()},
        strict_blind={n: None for n in per_run},
        runs_agree=_pct(agree),
        by_category={c: _pct(r["strict"] for r in rows if r["category"] == c) for c in cats},
        by_category_generous={c: _pct(r["generous"] for r in rows if r["category"] == c) for c in cats},
        evidence_found=_mean([r["evidence_found"] for r in rows], 3),
        ingest_secs=(ingest or {}).get(arm),
        retrieve_secs=_mean(r["retrieve_secs"] for r in rows),
        answer_secs=_mean(r["answer_secs"] for r in rows),
        context_tokens=_mean((r["context_tokens"] for r in rows), 1),
        answer_tokens=_mean((r["answer_tokens"] for r in rows), 1),
        tokens_all_calls=sum(call_tokens(c) for c in ok_calls),
        tokens_all_calls_reported=sum(x for x in reported if x is not None) if any(x is not None for x in reported) else None,
        tokens_all_calls_est=sum(c.get("prompt_tokens_est", 0) + c.get("completion_tokens_est", 0) for c in ok_calls),
        calls=len(calls),
        failed_calls=sum(1 for c in calls if not c.get("ok")),
    )


def summarise(rows, calls, runs, finished, state=None):
    """Score a run's records. A stopped run is scored only on questions complete in every arm and run."""
    simulated = _check_labels(rows, calls, state)
    check_identical(rows, finished=finished)
    order = list(SLOTS) + [FLOOR]
    present = state["arms"] if state and state.get("arms") else sorted({r["arm"] for r in rows}, key=order.index)
    need = {(a, n) for a in present for n in range(1, runs + 1)}
    have = {}
    for r in rows:
        have.setdefault(r["qid"], set()).add((r["arm"], r["run"]))
    complete = [q for q in dict.fromkeys(r["qid"] for r in rows) if need <= have[q]]
    scored = []
    for r in rows:
        if r["qid"] in complete:
            scored.append(dict(arm=r["arm"], qid=r["qid"], run=r["run"], conversation=r["conversation"],
                               category=r["category"], question=r["question"], gold=r["gold"], pred=r["pred"],
                               evidence_found=r["evidence_found"], retrieve_secs=r["retrieve_secs"],
                               answer_secs=r["answer_secs"], context_tokens=r["context_tokens"],
                               answer_tokens=r["answer_tokens"], **score(r)))
    ingest = state.get("ingest") if state else None
    out = {}
    for a in present:
        out[a] = _arm_summary(a, [s for s in scored if s["arm"] == a], [c for c in calls if c.get("arm") == a], runs, ingest)
    # The floor is reported beside arms A to D, never among them.
    floor = out.pop(FLOOR, None)
    first = rows[0] if rows else {}
    settings = {}
    for c in calls:
        s = settings.setdefault(c.get("kind"), dict(calls=0, reported=0, matching_freeze=0, requested=[], effective=[]))
        s["calls"] += 1
        if c.get("requested") is not None and c["requested"] not in s["requested"]:
            s["requested"].append(c["requested"])
        if c.get("effective") is not None:
            s["reported"] += 1
            if c["effective"] not in s["effective"]:
                s["effective"].append(c["effective"])
            if c.get("requested") is not None and not settings_differ(c["requested"], c["effective"]):
                s["matching_freeze"] += 1
    summary = dict(kit=KIT, simulated=simulated, finished=bool(finished), runs=runs,
                   complete_questions=len(complete), complete=complete, arms=out, floor=floor,
                   vs_A=paired_vs_a(scored), answer_model=first.get("answer_model"),
                   judge_model=first.get("judge_model"), question_set=first.get("question_set"),
                   calls_total=len(calls), call_settings=settings, scored=scored)
    if simulated:
        summary["label"] = LABEL
    return summary


def blinded_sheet(scored, seed=SHEET_SEED):
    """Rows for blinded strict labelling: arms hidden, order shuffled with a fixed seed.
    Returns (sheet rows, key), the key giving each id as [arm, conversation, question id, run]."""
    rows = list(scored)
    random.Random(seed).shuffle(rows)
    sheet, key = [], {}
    for n, r in enumerate(rows):
        sid = f"a{n}"
        sheet.append(dict(id=sid, cat=r["category"], q=r["question"], gold=r["gold"],
                          pred=r["pred"] if r["pred"] is not None else ""))
        key[sid] = [r["arm"], r["conversation"], r["qid"], r["run"]]
    return sheet, key


def apply_blind_labels(summary, key, labels):
    """Put blinded strict labels into the summary, by arm and run. An arm and run with any row unlabelled stays pending."""
    tally = {}
    for sid, (arm, _conv, _qid, run) in key.items():
        tally.setdefault((arm, int(run)), []).append(labels.get(sid, {}).get("strict"))
    for (arm, run), got in tally.items():
        part = summary["floor"] if arm == FLOOR else summary["arms"].get(arm)
        if part is None:
            continue
        part["strict_blind"][run] = None if any(g is None for g in got) else _pct(got)
    return summary


def _require_label(summary):
    if summary.get("simulated") is not False and summary.get("label") != LABEL:
        raise LabelMissing("the summary of a simulated run must carry the label")


def write_summary(summary, path):
    _require_label(summary)
    body = {k: v for k, v in summary.items() if k != "scored"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=1, ensure_ascii=False)
    return path


def write_sheet(summary, path):
    """Write sheet.jsonl, sheet.jsonl.key.json and sheet.jsonl.header.json in kit_tools/judge_sheet.py's layout.
    In the key file the arm is third, where judge_sheet.py reads the system."""
    _require_label(summary)
    sheet, key = blinded_sheet(summary["scored"])
    with open(path, "w", encoding="utf-8") as f:
        for r in sheet:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    file_key = {sid: [conv, qid, arm, run] for sid, (arm, conv, qid, run) in key.items()}
    with open(path + ".key.json", "w", encoding="utf-8") as f:
        json.dump(file_key, f)
    header = dict(kit=KIT, simulated=summary.get("simulated") is not False, rows=len(sheet), shuffle_seed=SHEET_SEED,
                  key_layout="[conversation, question id, arm, run]; the arm is third, where judge_sheet.py reads the system",
                  labels="{id: {generous: 0 or 1, strict: 0 or 1}}; score with: python kit_tools/judge_sheet.py score "
                         + os.path.basename(path) + " labels.json",
                  question_set=summary.get("question_set"), answer_model=summary.get("answer_model"))
    if header["simulated"]:
        header["label"] = summary["label"]
    with open(path + ".header.json", "w", encoding="utf-8") as f:
        json.dump(header, f, indent=1, ensure_ascii=False)
    return path


def key_from_file(file_key):
    """Turn a sheet's key file ([conversation, question id, arm, run]) into the in-memory key ([arm, conversation, question id, run])."""
    return {sid: [arm, conv, qid, run] for sid, (conv, qid, arm, run) in file_key.items()}
