"""Read-only adapter: the knowledge layers (P1 to P5) as an ERC ReasoningRequest. It writes nothing and keeps nothing.

How P1 facts become ERC propositions, so that ERC sees what the knowledge layers see:
- Time: a fact the state engine plays in a slot takes that period's span, the same span P1 uses to call conflicts. A period still
  open is closed one day after `as_of`, so two values held at once are a definite contradiction in ERC, as they are a conflict in P1.
  Any other fact takes its stated valid_from and valid_to. A fact with no date at all has no valid time: unknown, never invented.
- as_of: the request is for one point in time. A fact whose span starts after `as_of` is left out, and so is a fact whose span
  ended before it ("ended before as_of"): history is asked for by asking with a past `as_of`, which is what keeps a replaced fact
  out of a present conclusion until ERC itself reasons about time (step 1B). `task_type` only selects ERC's strategy; it does not
  change what the adapter sends. Timeline and cross-period questions are not implemented.
- Unknown time: a fact with no valid time stays in and is marked "valid_time: unknown", and it also gets the qualifying state record
  below, so any conclusion resting on it is at most provisional: missing dates do not mean a fact is timeless, false or useless;
  they mean ERC cannot establish that it held at `as_of`, and the record says so (metadata "qualified_for").
- Entities: the subject is the entity id. A text object becomes an entity id only when exactly one entity has that name or alias.
- Eligibility is decided inside the walk (step 1A): a fact that is left out for its state or its dates is never a bridge to the
  entity it points at, so no fact enters the request by a route the policy would refuse.
- Fact state (step 1 of the adapter, 10 Nov 2026): one explicit table, STATE_RULES, maps (status, validation_status, source_type)
  to what ERC is told. Only an active, accepted, explicit fact is an assertion that can support an accepted conclusion. An inferred,
  pending or needs-review fact is a hypothesis, and gets a second, metadata-only evidence record ("state:<fact id>") linked as
  *qualifying*, so ERC's gate can make its conclusion at most provisional; the source sentence stays *supporting* evidence, and the
  state record is an adapter control signal that ERC never counts as support. A disputed fact is left out (Engram holds no opposing
  claim, and none is invented). A superseded fact is history: sent only with the end date Engram holds, otherwise left out. Rejected,
  retracted and invalidated facts are left out. Any combination not in the table is left out as "unmapped state": the table fails
  closed. Every left-out fact is reported with its reason, its state and what it needs. Plans are left out: a plan is never a state.
- Functional predicates: P1's single-valued slots, and the predicates that open or close them.
- Evidence: one Evidence per source sentence, linked to each fact it supports, contradicts or qualifies, so a sentence counts once.
- Enrichment (B2a, 10 Nov 2026; claude/erc-b2a-spec.md): information Engram holds and ERC does not yet read travels beside what
  is sent, and changes nothing that is sent. (1) Sentence evidence carries the day it was said: `observed_at` is the first instant
  of that day, a date anchor and not a claim about the hour, and metadata "observed_latest" is the day's last instant. A sentence
  with no readable date gets neither. (2) A state's interval keeps its start and end and gains `start_latest` / `end_earliest`
  where Engram holds a *stated* year or month: bounds are inclusive, and a stated day stays exact until the zone is declared.
  (3) Qualifiers "start_basis" (stated, first_said) and "end_basis" (the state engine's own end_kind: open, stated, closed,
  replaced; or adjusted, the adapter's one-day minimum) say where each boundary came from; a boundary that is absent gets no
  label. A first-said start, a closed or
  replaced end, an adjusted end and every event get a label and no bound: correcting them is B2b, after ERC reads the fields (B3).
  Every instant made from a calendar day comes from `_day`, in DAY_ZONE.
- Ids: the request id is a digest of the entity, as_of, task, every fact used (id, status, validation, source type, recorded_at) and
  the rule set. This is the interim step 1 fingerprint; step 4 replaces it with the canonical one (evidence refs and roles, temporal
  fields, rule contents, adapter and ERC versions).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from typing import NamedTuple

from engram_erc import Evidence, EvidenceKind, EvidenceLink, EvidenceRelation, Proposition, PropositionKind, ReasoningRequest, SourceKind, TimeInterval
from engram_knowledge.models import FactWithEvidence
from engram_knowledge.state_engine import COUNTED, StateEngine
from engram_knowledge.temporal import said_on, span
from engram_knowledge.transition import CLOSES, OPENS, SINGLE, slot_of

FUNCTIONAL = frozenset(SINGLE) | frozenset(p for p, s in {**OPENS, **CLOSES}.items() if s in SINGLE)
EVENTS = frozenset(p for p, s in {**OPENS, **CLOSES}.items() if p != s)  # started_job, moved_to, left_job...: a happening, not a state
ONE_DAY = dt.timedelta(days=1)
FETCHED = COUNTED + ("superseded",)  # superseded facts are read as history; retracted and invalidated never
# The observations that build the periods the adapter dates facts by: active, accepted (and, in the engine, explicit). A fact the
# adapter leaves out (disputed) or sends only as a hypothesis (pending, needs_review) must not open or close a period of a fact it
# treats as established. Such a fact, if it has no stated date, is then "valid time unknown" and can only support a provisional conclusion.
PLAYED = dict(statuses=("active",), validations=("accepted",))


# The zone a stated calendar day is read in. Engram's dates carry no zone, so this is the adapter's assumption, held in one place:
# UTC, undeclared, until the zone is declared at B2b (TAD-04). Nothing else in the adapter names a zone for a stated day.
DAY_ZONE = dt.timezone.utc
LAST_INSTANT = ONE_DAY - dt.timedelta(microseconds=1)  # from a day's first instant to its last: bounds are inclusive (B1)


def _day(value: dt.date) -> dt.datetime:
    """The one place a calendar day becomes an instant: its first instant in DAY_ZONE."""
    return dt.datetime(value.year, value.month, value.day, tzinfo=DAY_ZONE)


def _start(stated: str | None) -> dt.datetime | None:
    return _day(span(stated)[0]) if stated else None


def _end(stated: str | None) -> dt.datetime | None:
    """Half-open: the day after the last day the stated date could mean."""
    return _day(span(stated)[1]) + ONE_DAY if stated else None


def _coarse(stated: str | None) -> bool:
    """Stated to the year or the month. A stated day stays exact in B2a: its own window needs the declared zone (B2b)."""
    return bool(stated) and len(stated.split("-")) < 3


def _start_latest(stated: str | None) -> dt.datetime | None:
    """The latest instant a start stated only to a year or month could be: the last instant of that period."""
    return _day(span(stated)[1]) + LAST_INSTANT if _coarse(stated) else None


def _end_earliest(stated: str | None) -> dt.datetime | None:
    """The earliest an end stated only to a year or month could be. The last day the state held lies in that period, and the end is
    the first instant it no longer holds: so no earlier than the day after the period's first day."""
    return _day(span(stated)[0]) + ONE_DAY if _coarse(stated) else None


# ---------- the fact-state table ----------
class StateRule(NamedTuple):
    action: str                       # "send", "history" or "leave_out"
    kind: PropositionKind | None      # for send/history
    state_record: bool                # a qualifying "state:" evidence record goes with the proposition
    reason: str = ""                  # for leave_out
    needs: str = ""                   # for leave_out: validation, resolution, date or mapping update


class LeftOut(NamedTuple):
    fact_id: str
    reason: str
    state: dict                       # status, validation_status, source_type
    needs: str


ASSERT = StateRule("send", PropositionKind.ASSERTION, False)
HYPOTHESIS = StateRule("send", PropositionKind.HYPOTHESIS, True)
HISTORY_ASSERT = StateRule("history", PropositionKind.ASSERTION, False)
HISTORY_HYPOTHESIS = StateRule("history", PropositionKind.HYPOTHESIS, True)
DISPUTED = StateRule("leave_out", None, False, "disputed: needs resolution", "resolution")
REJECTED = StateRule("leave_out", None, False, "validation rejected", "none")
GONE = StateRule("leave_out", None, False, "retracted or invalidated", "none")
UNMAPPED = StateRule("leave_out", None, False, "unmapped state", "mapping update")

STATE_RULES: dict[tuple[str, str, str], StateRule] = {}
for _v in ("accepted", "pending"):
    for _s in ("explicit", "inferred"):
        _checked = _v == "accepted" and _s == "explicit"
        STATE_RULES["active", _v, _s] = ASSERT if _checked else HYPOTHESIS
        STATE_RULES["needs_review", _v, _s] = HYPOTHESIS
        STATE_RULES["disputed", _v, _s] = DISPUTED
        STATE_RULES["superseded", _v, _s] = HISTORY_ASSERT if _checked else HISTORY_HYPOTHESIS
        STATE_RULES["retracted", _v, _s] = GONE
        STATE_RULES["invalidated", _v, _s] = GONE
for _st in ("active", "needs_review", "disputed", "superseded", "retracted", "invalidated"):
    for _s in ("explicit", "inferred"):
        STATE_RULES[_st, "rejected", _s] = REJECTED


def map_state(status: str, validation_status: str, source_type: str) -> StateRule:
    """What ERC is told about a fact in this state. A combination the table does not list is left out, never sent."""
    return STATE_RULES.get((status, validation_status, source_type), UNMAPPED)


@dataclass(frozen=True)
class AdaptedRequest:
    request: ReasoningRequest
    functional_predicates: frozenset
    fact_ids: tuple           # the P1 facts behind each proposition, in order
    left_out: tuple           # LeftOut for every fact not passed to ERC


class KnowledgeAdapter:
    def __init__(self, kb):
        self.kb = kb
        self.engine = StateEngine(kb)

    # ---------- which facts ----------
    def entity_id(self, entity: str) -> str:
        """An entity id, or the one entity with this name. Two with one name is for a person to settle, so it is refused."""
        if self.kb.entity(entity): return entity
        found = self.kb.find(entity)
        if len(found) != 1: raise LookupError(f"{len(found)} entities are called {entity!r}; pass the entity id")
        return found[0]

    def _facts(self, entity_id: str, hops: int, as_of: dt.datetime) -> tuple[list, list, dict]:
        """Walks from the entity, deciding each fact's eligibility (state, then dates) before it can lead anywhere.
        Returns ([(record, rule, interval)], [LeftOut], {fact_id: boundary labels}). Only a fact that is sent can expand the walk."""
        seen, frontier, eligible, left_out, periods, basis = set(), [entity_id], [], [], {}, {}
        for _ in range(hops + 1):
            nxt = []
            for ent in frontier:
                if ent in seen: continue
                seen.add(ent)
                periods.update(self._periods(ent))
                for x in self.kb.about_entity(ent, statuses=FETCHED, source_types=None):
                    f = x.fact
                    state = self._state(f)
                    if f.fact_type == "plan":
                        left_out.append(LeftOut(f.fact_id, "plan", state, "none")); continue
                    rule = map_state(f.status, f.validation_status, f.source_type)
                    if rule.action == "leave_out":
                        left_out.append(LeftOut(f.fact_id, rule.reason, state, rule.needs)); continue
                    interval, labels = self._interval(x, periods, as_of)
                    if rule.action == "history" and not (f.valid_to and interval and interval.end):
                        left_out.append(LeftOut(f.fact_id, "superseded: end date unknown", state, "date")); continue
                    if interval and interval.start and interval.start > as_of:
                        left_out.append(LeftOut(f.fact_id, "starts after as_of", state, "a later as_of")); continue
                    if interval and interval.end and interval.end <= as_of:
                        left_out.append(LeftOut(f.fact_id, "ended before as_of", state, "a past as_of")); continue
                    basis[f.fact_id] = labels
                    eligible.append((x, rule, interval))
                    obj = f.object_entity_id or self._resolved(f)
                    if obj: nxt.append(obj)
            frontier = nxt
        return eligible, left_out, basis

    def _resolved(self, fact) -> str | None:
        if fact.object_entity_id or fact.object_type != "text" or not fact.object_value: return fact.object_entity_id
        return self.kb.resolve(fact.object_value)

    # ---------- time ----------
    def _periods(self, entity_id: str) -> dict:
        """fact_id -> (start, end, open, start_basis, end_kind) from the state engine's periods for every slot of this entity.
        start_basis says whether the start is the period's stated start or only the day it was first said; end_kind is the state
        engine's own word for how the period ended (open, stated, closed, replaced).
        Only state facts are dated by their period. An event fact (a predicate whose slot is another predicate: started_job, left_job,
        moved_to...) is filed in a period as provenance but is not true throughout it, and the period's start may predate it (an event
        appended to an existing same-value period); it is dated by _event_date from its own observation instead."""
        out = {}
        for slot in sorted({slot_of(x.fact.predicate) for x in self.kb.about_entity(entity_id, statuses=PLAYED["statuses"]) if slot_of(x.fact.predicate)}):
            for p in self.engine.get_history(entity_id, slot, **PLAYED)["periods"]:
                for fid in p.fact_ids:
                    if self.kb.get(fid).fact.predicate not in EVENTS:
                        out[fid] = (p.start or p.first_said, p.end, p.end_kind == "open", "stated" if p.start else "first_said", p.end_kind)
        return out

    def _event_date(self, x) -> str | None:
        """When an event happened: its stated valid_from, else the day its earliest supporting sentence was said (the same rule the
        state engine uses to place an observation). Never the period's boundary, which another observation may have set."""
        if x.fact.valid_from: return x.fact.valid_from
        days = []
        for e in x.evidence:
            if e.evidence_role != "supports" or e.source_kind != "sentence": continue
            row = self.kb.db.execute("SELECT date FROM sentences WHERE sid=?", (int(e.source_id),)).fetchone()
            day = said_on(row[0]) if row else None
            if day: days.append(day)
        return min(days) if days else None

    def _observed(self, e) -> dict:
        """When a sentence was said, for its Evidence: `observed_at` is the first instant of the said day (a date anchor: Engram's
        reader keeps the day and drops the clock time, and no zone is stored) and metadata "observed_latest" is that day's last
        instant, so the whole day stays visible. A sentence with no readable date gets neither: nothing is invented.
        The source is the sentence's own date, never the fact's recorded_at."""
        if e.source_kind != "sentence": return {}
        row = self.kb.db.execute("SELECT date FROM sentences WHERE sid=?", (int(e.source_id),)).fetchone()
        day = said_on(row[0]) if row else None
        if not day: return {}
        first, last = span(day)
        return {"observed_at": _day(first), "metadata": {"observed_latest": (_day(last) + LAST_INSTANT).isoformat()}}

    @staticmethod
    def _time_kind(fact) -> str:
        return "event" if fact.predicate in EVENTS else "state"

    def _interval(self, x, periods: dict, as_of: dt.datetime) -> tuple[TimeInterval | None, dict]:
        """(the interval sent, the labels saying where its boundaries came from). The start and end are exactly what was sent before
        B2a. A bound is added only beside a boundary Engram holds as *stated* to a year or month; the labels are {} when there is
        no valid time. Engram can hold a stated end with no stated start and no readable first-said day: the interval then has no
        start, as before B2a, and carries no "start_basis"."""
        fact = x.fact
        if fact.predicate in EVENTS:  # an event happened on a day and does not stop having happened: no end, not "still open"
            begin = _start(self._event_date(x))
            labels = {"start_basis": "stated" if fact.valid_from else "first_said"} if begin else {}
            return TimeInterval(begin, None) if begin else None, labels
        if fact.fact_id in periods:
            start, end, still_open, start_basis, end_kind = periods[fact.fact_id]
        else:
            start, end, still_open = fact.valid_from, fact.valid_to, fact.valid_to is None
            start_basis, end_kind = "stated", "stated" if fact.valid_to else "open"
        begin = _start(start)
        if begin is None and end is None: return None, {}
        finish = _end(end) if end else (as_of + ONE_DAY if still_open and begin else None)
        adjusted = bool(begin and finish and finish <= begin)
        if adjusted: finish = begin + ONE_DAY
        end_basis = "adjusted" if adjusted else end_kind
        bounds = {"start_latest": _start_latest(start) if start_basis == "stated" else None,
                  "end_earliest": _end_earliest(end) if end_basis == "stated" else None}
        labels = {"start_basis": start_basis, "end_basis": end_basis}
        if begin is None: del labels["start_basis"]  # an end with no start at all: there is no start for a label to describe
        return TimeInterval(begin, finish, **bounds), labels

    # ---------- the request ----------
    @staticmethod
    def _state(f) -> dict:
        return {"status": f.status, "validation_status": f.validation_status, "source_type": f.source_type}

    def request_for(self, entity: str, *, task_type: str = "state_question", as_of: dt.datetime | None = None,
                    ruleset=None, hops: int = 1) -> AdaptedRequest:
        as_of = as_of or dt.datetime.now(dt.timezone.utc)
        if as_of.tzinfo is None: raise ValueError("as_of must include a time zone")
        root = self.entity_id(entity)
        eligible, left_out, basis = self._facts(root, hops, as_of)
        props, links, evidence, used = [], [], {}, []
        for x, rule, interval in eligible:
            f = x.fact
            state = self._state(f)
            pid = f"fact:{f.fact_id}"
            sids = []
            for e in x.evidence:
                eid = f"sentence:{e.source_id}"
                evidence.setdefault(eid, Evidence(id=eid, source_ref=eid, source_kind=SourceKind.ENGRAM_MEMORY, evidence_kind=EvidenceKind.OBSERVATION,
                                                  **self._observed(e)))
                links.append(EvidenceLink(eid, pid, EvidenceRelation(e.evidence_role)))
                sids.append(eid)
            qualified_for = []  # why ERC may not treat a conclusion resting on this fact as established
            if f.source_type == "inferred": qualified_for.append("source inferred")
            if f.validation_status == "pending": qualified_for.append("validation pending")
            if f.status == "needs_review": qualified_for.append("status needs_review")
            if interval is None: qualified_for.append("valid time unknown")
            if rule.state_record or interval is None:  # the fact's state, as qualifying evidence: a control signal, never support
                sid = f"state:{f.fact_id}"
                evidence[sid] = Evidence(id=sid, source_ref=sid, source_kind=SourceKind.ENGRAM_MEMORY, evidence_kind=EvidenceKind.OTHER,
                                         metadata={**state, "valid_time": "known" if interval else "unknown", "qualified_for": tuple(qualified_for),
                                                   "adapter_control": True})
                links.append(EvidenceLink(sid, pid, EvidenceRelation.QUALIFIES))
            props.append(Proposition(
                id=pid, subject=f.subject_id, predicate=f.predicate,
                object_value=self._resolved(f) or f.value,
                kind=rule.kind, source_refs=tuple(dict.fromkeys(sids)), valid_time=interval,
                qualifiers={**state, "fact_type": f.fact_type, "time_kind": self._time_kind(f), "valid_time": "known" if interval else "unknown",
                            **basis[f.fact_id]}))
            used.append(f.fact_id)
        digest = hashlib.sha256(json.dumps(dict(
            entity=root, as_of=as_of.isoformat(), task=task_type,
            facts=sorted((x.fact.fact_id, x.fact.status, x.fact.validation_status, x.fact.source_type, x.fact.recorded_at)
                         for x, _, _ in eligible),
            rules=None if ruleset is None else [ruleset.version] + sorted((r.rule_id, r.version) for r in ruleset.rules),
        ), sort_keys=True).encode()).hexdigest()[:24]
        request = ReasoningRequest(id=f"erc_req_{digest}", task_type=task_type, propositions=tuple(props),
                                   evidence=tuple(evidence.values()), evidence_links=tuple(dict.fromkeys(links)),
                                   context_refs=(f"entity:{root}",), as_of=as_of)
        return AdaptedRequest(request, FUNCTIONAL, tuple(used), tuple(left_out))
