"""StubMemory: an in-memory fake of the memory interface (D-A5). It is not Engram.

It matches by shared content words, ranks by the number of words matched, then by newer date, then by id, and
fills the token budget greedily. Rules it keeps (section 4.3):
- a fact is never given without every one of its source excerpts (D-A6); a fact that does not fit with them is
  left out and recorded in `excluded_facts`;
- space for the budget-exclusion notice is reserved in every trial while choosing (D-A13);
- every memory considered is traced exactly once, given or dropped, with a reason (R2-A);
- ids come from counters, are kept on disk with the traces when a path is given, and are never reused (IF-6, IF-7).
`seed_fact` stands in for facts the engine would make. It is a test helper, not part of the interface.
"""
import dataclasses
import json
import os
import re

from .contract import (MemoryInterface, Turn, IngestResult, Excerpt, Fact, ProfileResult, FeedbackResult, Unavailable,
                       TraceEntry, AuditTrace, ModelContext, RetrievalResult, ROLES, VALIDATED, UNCERTAIN,
                       E_NO_MEMORY, E_NO_MATCH, E_SPEAKER, E_NO_SPEAKER, E_BUDGET, R_EMPTY_TEXT,
                       NOT_UNTIL_B8, NOT_UNTIL_B9)
from .render import count_tokens, render_context

STATE_VERSION = 1
OVER_BUDGET = "over budget"
WHY_EXCERPT = "excerpt matched the question"
WHY_FACT = "fact matched the question"
WHY_FACT_LEFT_OUT = "; omitted: the fact with its supporting sentence did not fit"

FIRST_PERSON = frozenset({"i", "me", "my", "mine", "myself"})     # IF-11: speaker decides who these are
STOP = frozenset("""a an the and or but of to in on at for with from by as is are was were be been being am do does
did have has had will would can could should may might must shall i me my mine myself you your yours he him his
she her hers it its we us our ours they them their theirs this that these those what where when who whom which why
how there here not no yes so if then than too very just s m t d ll ve re""".split())


def _words(text):
    text = text.lower().replace("’", "'")
    text = re.sub(r"'s\b", "", text)
    return re.findall(r"[a-z0-9]+", text)


def _content(text):
    return {w for w in _words(text) if w not in STOP}


def _natural(identifier):
    m = re.fullmatch(r"(\D*)(\d+)", identifier)
    return (m.group(1), int(m.group(2)), "") if m else (identifier, -1, identifier)


def _ranked(items):
    """items: (memory, id, date, matched). Most words first, then newer date, then id."""
    items = sorted(items, key=lambda x: _natural(x[1]))
    items.sort(key=lambda x: (len(x[3]), x[2] or ""), reverse=True)
    return items


def _same_person(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.strip().casefold() == b.strip().casefold()


class StubMemory(MemoryInterface):
    def __init__(self, path=None):
        self._path = path
        self._excerpts = {}                       # excerpt id -> Excerpt, in the order stored
        self._facts = {}                          # fact id -> Fact
        self._traces = {}                         # trace id -> AuditTrace
        self._counters = {"excerpt": 0, "trace": 0}
        if path is not None and os.path.exists(path):
            self._load()

    # ---- keeping state on disk (IF-7) ----
    def _load(self):
        with open(self._path, encoding="utf-8") as fh:
            state = json.load(fh)
        self._counters = {k: int(v) for k, v in state["counters"].items()}
        for e in state["excerpts"]:
            self._excerpts[e["excerpt_id"]] = Excerpt(**e)
        for f in state["facts"]:
            self._facts[f["fact_id"]] = Fact(**{**f, "sources": tuple(f["sources"])})
        for t in state["traces"]:
            entries = tuple(TraceEntry(**{**x, "matched": tuple(x["matched"])}) for x in t["entries"])
            self._traces[t["trace_id"]] = AuditTrace(t["trace_id"], t["question"], entries, t["empty_reason"])

    def _save(self):
        if self._path is None:
            return
        state = {"version": STATE_VERSION, "counters": self._counters,
                 "excerpts": [dataclasses.asdict(e) for e in self._excerpts.values()],
                 "facts": [dataclasses.asdict(f) for f in self._facts.values()],
                 "traces": [dataclasses.asdict(t) for t in self._traces.values()]}
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False)
        os.replace(tmp, self._path)

    def _next_id(self, kind, prefix):
        self._counters[kind] += 1
        return f"{prefix}{self._counters[kind]}"

    # ---- ingest (C01, C02) ----
    def ingest(self, turn):
        if not isinstance(turn, Turn):
            raise ValueError("ingest takes one Turn")
        if turn.role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, not {turn.role!r}")
        if not isinstance(turn.text, str) or not isinstance(turn.speaker, str):
            raise ValueError("speaker and text must be text")
        if not turn.text.strip():
            return IngestResult((), R_EMPTY_TEXT)
        eid = self._next_id("excerpt", "e")
        self._excerpts[eid] = Excerpt(eid, turn.speaker, turn.role, turn.text, turn.date, turn.ref)
        self._save()
        return IngestResult((eid,), "")

    def seed_fact(self, fact):
        """Test helper: a fact as the engine would make it. Its sources must be stored user-role excerpts."""
        if not isinstance(fact, Fact):
            raise ValueError("seed_fact takes a Fact")
        if fact.fact_id in self._facts:
            raise ValueError(f"fact id {fact.fact_id!r} is already used")
        if fact.status not in (VALIDATED, UNCERTAIN):
            raise ValueError(f"status must be {VALIDATED!r} or {UNCERTAIN!r}")
        sources = tuple(fact.sources)
        if not sources:
            raise ValueError("a fact needs at least one source excerpt")
        for s in sources:
            if s not in self._excerpts:
                raise ValueError(f"unknown source excerpt {s!r}")
            if self._excerpts[s].role != "user":
                raise ValueError("the assistant's words are never the source of a fact")
        self._facts[fact.fact_id] = dataclasses.replace(fact, sources=sources)
        self._save()

    # ---- retrieve (C03, C06) ----
    def retrieve(self, question, budget, speaker=None):
        if not isinstance(question, str) or not question.strip():
            raise ValueError("the question must be non-empty text")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
            raise ValueError(f"the budget must be a whole number above 0, not {budget!r}")
        if speaker is not None and not isinstance(speaker, str):
            raise ValueError("speaker must be text or None")
        tid = self._next_id("trace", "t")
        prof = self._profile_result()
        asked = _content(question)
        first_person = bool(FIRST_PERSON & set(_words(question)))

        if not self._excerpts and not self._facts:
            return self._empty(tid, question, budget, prof, E_NO_MEMORY)
        if first_person and speaker is None:
            return self._empty(tid, question, budget, prof, E_NO_SPEAKER)
        only = speaker if first_person else None

        facts, excerpts, any_match = [], [], False
        for f in self._facts.values():
            m = asked & _content(f"{f.subject} {f.statement}")
            if m:
                any_match = True
                if only is None or _same_person(f.subject, only):
                    facts.append((f, f.fact_id, f.date, m))
        for e in self._excerpts.values():
            m = asked & _content(e.text)
            if m:
                any_match = True
                if only is None or _same_person(e.speaker, only):
                    excerpts.append((e, e.excerpt_id, e.date, m))
        if not facts and not excerpts:
            return self._empty(tid, question, budget, prof, E_SPEAKER if any_match else E_NO_MATCH)
        facts = _ranked(facts)
        owners = {}                               # source excerpt id -> the matching facts that rest on it
        for f, fid, _, _ in facts:
            for s in f.sources:
                owners.setdefault(s, [])
                if fid not in owners[s]:
                    owners[s].append(fid)
        standalone = _ranked([x for x in excerpts if x[1] not in owners])

        def fits(fs, us, es):
            trial = ModelContext(tid, question, tuple(fs), tuple(es), tuple(us), prof, 0, budget)
            return count_tokens(render_context(trial, notice=True)) <= budget      # the notice's space is reserved

        given_f, given_u, given_e, given_ids = [], [], [], set()
        excluded, omitted, entries, traced = [], [], [], set()
        for f, fid, _, m in facts:
            srcs = [self._excerpts[s] for s in dict.fromkeys(f.sources) if s not in given_ids]
            validated = f.status == VALIDATED
            trial_f = given_f + [f] if validated else given_f
            trial_u = given_u if validated else given_u + [f]
            if fits(trial_f, trial_u, given_e + srcs):
                given_f, given_u = trial_f, trial_u
                given_e += srcs
                given_ids.update(e.excerpt_id for e in srcs)
                entries.append(TraceEntry("fact", fid, WHY_FACT, tuple(sorted(m)), True))
            else:
                excluded.append(fid)
                entries.append(TraceEntry("fact", fid, WHY_FACT + WHY_FACT_LEFT_OUT, tuple(sorted(m)), False,
                                          OVER_BUDGET))
        for f, fid, _, _ in facts:
            for s in dict.fromkeys(f.sources):
                if s in traced:
                    continue
                traced.add(s)
                entries.append(self._source_entry(s, owners[s], asked, s in given_ids))
        for e, eid, _, m in standalone:
            if fits(given_f, given_u, given_e + [e]):
                given_e.append(e)
                given_ids.add(eid)
                entries.append(TraceEntry("excerpt", eid, WHY_EXCERPT, tuple(sorted(m)), True))
            else:
                omitted.append(eid)               # D-A18: a standalone match left out for budget
                entries.append(TraceEntry("excerpt", eid, WHY_EXCERPT, tuple(sorted(m)), False, OVER_BUDGET))

        if given_f or given_u or given_e:
            ctx = ModelContext(tid, question, tuple(given_f), tuple(given_e), tuple(given_u), prof, 0, budget, "",
                               tuple(excluded), tuple(omitted))
            ctx = dataclasses.replace(ctx, tokens=count_tokens(render_context(ctx)))
            reason = ""
        else:                                     # D-A19: the empty block carries the notice and is counted
            ctx = ModelContext(tid, question, (), (), (), prof, 0, budget, E_BUDGET, tuple(excluded), tuple(omitted))
            used = count_tokens(render_context(ctx))
            ctx = dataclasses.replace(ctx, tokens=used, over_budget=used > budget)
            reason = E_BUDGET
        return self._keep(ctx, AuditTrace(tid, question, tuple(entries), reason))

    def _source_entry(self, s, fact_ids, asked, included):
        names = ", ".join(fact_ids)
        label = f"source of fact {names}" if len(fact_ids) == 1 else f"source of facts {names}"
        matched = tuple(sorted(asked & _content(self._excerpts[s].text)))
        if included:
            return TraceEntry("excerpt", s, label, matched, True)
        dropped = ", which was dropped" if len(fact_ids) == 1 else ", which were dropped"
        return TraceEntry("excerpt", s, label + dropped, matched, False, OVER_BUDGET)

    def _empty(self, tid, question, budget, prof, reason):
        """Nothing considered: no memory, no match or no speaker. No notice, 0 tokens (D-A19)."""
        ctx = ModelContext(tid, question, (), (), (), prof, 0, budget, reason)
        return self._keep(ctx, AuditTrace(tid, question, (), reason))

    def _keep(self, ctx, trace):
        self._traces[trace.trace_id] = trace
        self._save()
        return RetrievalResult(ctx, trace)

    # ---- the calls not built yet: structured answers, never raised silently, never fabricated ----
    @staticmethod
    def _profile_result():
        return ProfileResult(False, (), (), NOT_UNTIL_B8)

    def profile(self, speaker):
        if not isinstance(speaker, str):
            raise ValueError("speaker must be text")
        return self._profile_result()

    def feedback(self, trace_id, memory_id, useful):
        if not isinstance(useful, bool):
            raise ValueError("useful must be True or False (IF-18)")
        if not isinstance(trace_id, str) or not isinstance(memory_id, str):
            raise ValueError("trace_id and memory_id must be text")
        return FeedbackResult(False, NOT_UNTIL_B9)

    def trace(self, trace_id):
        return self._traces.get(trace_id)

    def forget(self, memory_id):
        return Unavailable("forget")

    def access(self, principal, memory_id):
        return Unavailable("access")
