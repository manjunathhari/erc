"""Read-only adapter: the knowledge layers (P1 to P5) as an ERC ReasoningRequest. It writes nothing and keeps nothing.

How P1 facts become ERC propositions, so that ERC sees what the knowledge layers see:
- Time: a fact the state engine plays in a slot takes that period's dates, the same dates P1 uses to call conflicts. Any other
  fact takes its stated valid_from and valid_to. A fact with no date at all has no valid time: unknown, never invented.
- What is sent says no more than Engram holds (B2b, 11 Nov 2026; claude/erc-b2b-spec.md). A state still going is sent as still
  going (`end_unbounded`), with no end date: two values held at once then overlap for certain, as they are a conflict in P1. The
  day a value was first said is not its start but the latest it can have begun (`start_latest` alone). A date that closed or
  replaced a period is an exact end only if it was stated; if it was only the day a sentence was said, it is the latest the
  state can have ended (`end_is_upper_bound`). An event is an occurrence (`occurred`), never a period. No date is ever moved to
  make an interval valid, and nothing that is sent depends on `as_of`.
- as_of: the request is for one point in time. A fact known only from after `as_of` is left out ("starts after as_of"), and so
  is a fact whose end Engram holds at or before it ("ended before as_of"): history is asked for by asking with a past `as_of`,
  which is what keeps a replaced fact out of a present conclusion until ERC itself reasons about time. These guards read
  Engram's dates, not the interval that is sent, and compare instants. A period whose end is not after its start is never
  eligible: if its start was stated, its dates are inconsistent and that is the reason given. `task_type` only selects ERC's
  strategy; it does not change what the adapter sends. Timeline and cross-period questions are not implemented.
- Zone: every calendar day becomes an instant in one zone, a setting of each adapter (`day_zone`: an IANA name or a ZoneInfo;
  UTC when not given), fixed for the adapter's life, never taken from the machine, and reported on the adapted request. A day
  begins at the earliest instant whose local date is that day and ends one microsecond before the next day begins. A day that
  does not exist in the zone gives no instant: the fact's time is then not established, and the date is never moved.
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
  replaced) say where each boundary came from; a boundary that is absent gets no label.
  Every instant made from a calendar day comes from `_day`, in the adapter's zone.
- Ids: the request id is a digest of the entity, as_of, task, every fact used (id, status, validation, source type, recorded_at) and
  the rule set. This is the interim step 1 fingerprint; step 4 replaces it with the canonical one (evidence refs and roles, temporal
  fields, rule contents, adapter and ERC versions).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import zoneinfo
from dataclasses import dataclass
from typing import NamedTuple

from engram_erc import (Evidence, EvidenceKind, EvidenceLink, EvidenceRelation, Occurrence, Proposition, PropositionKind, ReasoningRequest,
                        SourceKind, TimeInterval)
from engram_knowledge.models import FactWithEvidence, normalize_name
from engram_knowledge.state_engine import COUNTED, StateEngine
from engram_knowledge.temporal import said_on, span, step_before
from engram_knowledge.transition import CLOSES, OPENS, SINGLE, slot_of

FUNCTIONAL = frozenset(SINGLE) | frozenset(p for p, s in {**OPENS, **CLOSES}.items() if s in SINGLE)
EVENTS = frozenset(p for p, s in {**OPENS, **CLOSES}.items() if p != s)  # started_job, moved_to, left_job...: a happening, not a state
ONE_DAY = dt.timedelta(days=1)
FETCHED = COUNTED + ("superseded",)  # superseded facts are read as history; retracted and invalidated never
# The observations that build the periods the adapter dates facts by: active, accepted (and, in the engine, explicit). A fact the
# adapter leaves out (disputed) or sends only as a hypothesis (pending, needs_review) must not open or close a period of a fact it
# treats as established. Such a fact, if it has no stated date, is then "valid time unknown" and can only support a provisional conclusion.
PLAYED = dict(statuses=("active",), validations=("accepted",))


# The zone a calendar day is read in when an adapter is given none: UTC. An adapter reads this once, when it is built, and never
# changes it. Production code sets the zone through `day_zone`; replacing this value is a seam kept for one existing test.
DAY_ZONE = dt.timezone.utc
UTC = dt.timezone.utc                      # the one timeline on which instants are compared
MICROSECOND = dt.timedelta(microseconds=1)
INCONSISTENT = "period dates inconsistent"  # a period Engram assembled whose stated start is at or after its end
NOT_IN_ZONE = "date not in zone"            # a calendar day that has no instant in the adapter's zone


class NoSuchDay(ValueError):
    """A calendar day that has no instant in the zone (Pacific/Apia skipped 30 December 2011)."""


def resolve_zone(day_zone=None):
    """(the zone, the name it is reported by). `day_zone` is an IANA zone name or a ZoneInfo; anything else is refused, and
    nothing is ever replaced by UTC. Given none, the module default is read now and reported as UTC, or by its own fixed name."""
    if day_zone is None:
        zone = DAY_ZONE
        return zone, ("UTC" if zone is dt.timezone.utc else getattr(zone, "key", None) or zone.tzname(None))
    if isinstance(day_zone, zoneinfo.ZoneInfo) and day_zone.key: return day_zone, day_zone.key
    if isinstance(day_zone, str) and day_zone:
        try: return zoneinfo.ZoneInfo(day_zone), day_zone
        except (KeyError, ValueError, OSError): pass
    raise ValueError(f"day_zone must be an IANA time zone name or a ZoneInfo, not {day_zone!r}")


def _day(value: dt.date, zone) -> dt.datetime:
    """The one place a calendar day becomes an instant: the earliest instant whose local date in the zone is that day. Usually
    local midnight; where a clock change skips midnight, the first time that did occur, as a valid local time. A day with no
    instant in the zone raises NoSuchDay: it is never moved to a neighbouring day."""
    first = dt.datetime(value.year, value.month, value.day, tzinfo=zone).astimezone(UTC).astimezone(zone)
    if first.date() != value: raise NoSuchDay(value.isoformat())
    return first


def _after(value: dt.date, zone) -> dt.datetime:
    """The first instant after a calendar day: the first instant of the next day that has one."""
    _day(value, zone)
    following = value + ONE_DAY
    while True:
        try: return _day(following, zone)
        except NoSuchDay: following += ONE_DAY


def _last(value: dt.date, zone) -> dt.datetime:
    """A day's last instant (bounds are inclusive): one microsecond before the next day begins, taken as an instant. Never the
    first instant plus 24 hours, or plus 23:59:59.999999 on the clock: a day can be shorter or longer than that."""
    return (_after(value, zone).astimezone(UTC) - MICROSECOND).astimezone(zone)


def _start(stated: str | None, zone) -> dt.datetime | None:
    return _day(span(stated)[0], zone) if stated else None


def _end(stated: str | None, zone) -> dt.datetime | None:
    """Half-open: the first instant after the last day the stated date could mean."""
    return _after(span(stated)[1], zone) if stated else None


def _coarse(stated: str | None) -> bool:
    """Stated to the year or the month. A state stated to the day stays exact: states hold by whole calendar days."""
    return bool(stated) and len(stated.split("-")) < 3


def _start_latest(stated: str | None, zone) -> dt.datetime | None:
    """The latest instant a start stated only to a year or month could be: the last instant of that period."""
    return _last(span(stated)[1], zone) if _coarse(stated) else None


def _end_earliest(stated: str | None, zone) -> dt.datetime | None:
    """The earliest an end stated only to a year or month could be. The last day the state held lies in that period, and the end is
    the first instant it no longer holds: so no earlier than the first instant after the period's first day."""
    return _after(span(stated)[0], zone) if _coarse(stated) else None


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


class Dated(NamedTuple):
    """A state fact's dates as Engram holds them: its period's, or its own when it is outside every slot."""
    start: str | None                 # stated
    said: str | None                  # the day it was first said
    end: str | None
    end_kind: str                     # the state engine's word: open, stated, closed, replaced
    end_only_said: bool               # the date that closed or replaced it was not stated, only the day a sentence was said


class Timing(NamedTuple):
    """What is sent for a fact's time, and the two instants the as_of guards read (Engram's dates, not what is sent)."""
    sent: TimeInterval | Occurrence | None   # a state's interval, an event's occurrence, or None: no time is established
    labels: dict                             # start_basis and end_basis, where there is such a boundary
    known_from: dt.datetime | None           # the first instant of the earliest day the fact is known from
    ended: dt.datetime | None                # the end Engram holds: the first instant the state no longer held
    note: str = ""                           # INCONSISTENT or NOT_IN_ZONE


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
    day_zone: str             # the zone every calendar day was read in. The request id does not carry it: keep the two together


class KnowledgeAdapter:
    def __init__(self, kb, day_zone=None):
        self.kb = kb
        self.engine = StateEngine(kb)
        self.zone, self.day_zone = resolve_zone(day_zone)  # fixed for the life of this adapter; nothing process-wide is written

    # ---------- which facts ----------
    def entity_id(self, entity: str) -> str:
        """An entity id, or the one entity with this name. Two with one name is for a person to settle, so it is refused."""
        if self.kb.entity(entity): return entity
        found = self.kb.find(entity)
        if len(found) != 1: raise LookupError(f"{len(found)} entities are called {entity!r}; pass the entity id")
        return found[0]

    def _facts(self, entity_id: str, hops: int, as_of: dt.datetime) -> tuple[list, list]:
        """Walks from the entity, deciding each fact's eligibility (state, then dates) before it can lead anywhere.
        Returns ([(record, rule, timing)], [LeftOut]). Only a fact that is sent can expand the walk.
        The date guards read Engram's dates (Timing.known_from and Timing.ended) and compare instants: `as_of` may be written
        in any offset, and two times in one zone object would otherwise be compared on the clock."""
        seen, frontier, eligible, left_out, periods = set(), [entity_id], [], [], {}
        now = as_of.astimezone(UTC)
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
                    timing = self._timing(x, periods)
                    if timing.note == INCONSISTENT:  # before the date guards, so that the reason given is the true one
                        left_out.append(LeftOut(f.fact_id, INCONSISTENT, state, "resolution")); continue
                    if rule.action == "history" and not (f.valid_to and timing.ended):
                        left_out.append(LeftOut(f.fact_id, "superseded: end date unknown", state, "date")); continue
                    if timing.known_from and timing.known_from.astimezone(UTC) > now:
                        left_out.append(LeftOut(f.fact_id, "starts after as_of", state, "a later as_of")); continue
                    if timing.ended and timing.ended.astimezone(UTC) <= now:
                        left_out.append(LeftOut(f.fact_id, "ended before as_of", state, "a past as_of")); continue
                    eligible.append((x, rule, timing))
                    obj = f.object_entity_id or self._resolved(f)
                    if obj: nxt.append(obj)
            frontier = nxt
        return eligible, left_out

    def _resolved(self, fact) -> str | None:
        if fact.object_entity_id or fact.object_type != "text" or not fact.object_value: return fact.object_entity_id
        return self.kb.resolve(fact.object_value)

    # ---------- time ----------
    def _periods(self, entity_id: str) -> dict:
        """fact_id -> Dated, from the state engine's periods for every slot of this entity.
        Only state facts are dated by their period. An event fact (a predicate whose slot is another predicate: started_job, left_job,
        moved_to...) is filed in a period as provenance but is not true throughout it, and the period's start may predate it (an event
        appended to an existing same-value period); it is dated by _event_date from its own observation instead."""
        out = {}
        for slot in sorted({slot_of(x.fact.predicate) for x in self.kb.about_entity(entity_id, statuses=PLAYED["statuses"]) if slot_of(x.fact.predicate)}):
            periods = self.engine.get_history(entity_id, slot, **PLAYED)["periods"]
            records = {fid: self.kb.get(fid) for p in periods for fid in p.fact_ids}
            for p in periods:
                only_said = self._end_only_said(p, periods, records)
                for fid in p.fact_ids:
                    if records[fid].fact.predicate not in EVENTS:
                        out[fid] = Dated(p.start, p.first_said, p.end, p.end_kind, only_said)
        return out

    def _end_only_said(self, p, periods, records) -> bool:
        """Whether the date that closed or replaced a period was only the day a sentence was said. The adapter does not re-play the
        slot and alters no date: it reads the provenance of a date Engram has already set, from the facts Engram filed.
        Closed: the closing statement is in the period; it either states its date or it does not.
        Replaced: the replacing statement is in another period, so it is found among the slot's facts: a fact of another value,
        not a closing statement, sharing a speaker with this period, whose date is the step after this period's end. Every such
        fact is considered together, never the first one found: if any states the date, the date is stated. If none does, or
        none is found, it was only said: the weaker claim."""
        if p.end_kind == "closed":
            return not any(x.fact.valid_from for x in (records[i] for i in p.fact_ids)
                           if x.fact.predicate in CLOSES and self._placed(x)[0] == p.end)
        if p.end_kind != "replaced": return False
        candidates = []
        for q in periods:
            if normalize_name(q.value) == normalize_name(p.value): continue
            for x in (records[i] for i in q.fact_ids):
                when, speakers = self._placed(x)
                if x.fact.predicate not in CLOSES and when and step_before(when) == p.end and speakers & p.sources: candidates.append(x.fact)
        return not any(f.valid_from for f in candidates)

    def _placed(self, x) -> tuple[str | None, set]:
        """(the date the state engine places a statement at: its stated valid_from, else the earliest day it was said; who said it)."""
        said, speakers = [], set()
        for e in x.evidence:
            if e.evidence_role != "supports" or e.source_kind != "sentence": continue
            row = self.kb.db.execute("SELECT speaker, date FROM sentences WHERE sid=?", (int(e.source_id),)).fetchone()
            if not row: continue
            speakers.add(normalize_name(row[0]))
            day = said_on(row[1])
            if day: said.append(day)
        said.sort(key=lambda d: span(d)[0])
        return x.fact.valid_from or (said[0] if said else None), speakers

    def _event_date(self, x) -> str | None:
        """The date an event is known by: its stated valid_from, else the day its earliest supporting sentence was said (the same
        rule the state engine uses to place an observation). Never the period's boundary, which another observation may have set.
        Only a sentence linked as *supporting* evidence counts: one that merely qualifies or contradicts says nothing of when."""
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
        instant, so the whole day stays visible. A sentence with no readable date gets neither: nothing is invented. Nor does a
        sentence said on a day that does not exist in the adapter's zone.
        The source is the sentence's own date, never the fact's recorded_at."""
        if e.source_kind != "sentence": return {}
        row = self.kb.db.execute("SELECT date FROM sentences WHERE sid=?", (int(e.source_id),)).fetchone()
        day = said_on(row[0]) if row else None
        if not day or not self._in_zone(day): return {}  # a said day that does not exist in the zone cannot be read either
        first, last = span(day)
        return {"observed_at": _day(first, self.zone), "metadata": {"observed_latest": _last(last, self.zone).isoformat()}}

    @staticmethod
    def _time_kind(fact) -> str:
        return "event" if fact.predicate in EVENTS else "state"

    def _in_zone(self, stated: str) -> bool:
        """Whether both ends of a stated day, month or year have an instant in the adapter's zone."""
        try:
            _day(span(stated)[0], self.zone); _day(span(stated)[1], self.zone)
        except NoSuchDay: return False
        return True

    def _timing(self, x, periods: dict) -> Timing:
        """What is sent for a fact's time, and what the as_of guards read. Nothing here depends on as_of, and no date is moved to
        make an interval valid. A required day that does not exist in the zone gives no instant: the fact's whole time is then not
        established, and no partial interval is sent from the boundary that does exist."""
        try:
            return self._occurrence(x) if x.fact.predicate in EVENTS else self._state_time(x.fact, periods)
        except NoSuchDay:
            return Timing(None, {}, None, None, NOT_IN_ZONE)

    def _occurrence(self, x) -> Timing:
        """An event is an occurrence, never a period. A stated date is the window it happened in: the whole of the stated day,
        month or year. A date that was only said is not when it happened: the event is one of Engram's completed happenings,
        told in a supporting sentence, so it happened no later than the day it was told, and nothing more is known."""
        date = self._event_date(x)
        if not date: return Timing(None, {}, None, None)
        first, last = _day(span(date)[0], self.zone), _last(span(date)[1], self.zone)
        if x.fact.valid_from: return Timing(Occurrence(first, last), {"start_basis": "stated"}, first, None)
        return Timing(Occurrence(None, last), {"start_basis": "first_said"}, first, None)

    def _state_time(self, fact, periods: dict) -> Timing:
        """A state's interval, from the dates Engram holds. Engram can hold a stated end with no stated start and no readable
        first-said day: the interval then has no start of any kind and carries no "start_basis"."""
        zone = self.zone
        dated = periods.get(fact.fact_id)
        in_period = dated is not None
        if dated is None:  # outside every slot: the fact's own dates. A fact with a start and no end is still going
            dated = Dated(fact.valid_from, None, fact.valid_to, "stated" if fact.valid_to else "open", False)
        said, said_missing = dated.said, False
        if said and not self._in_zone(said): said, said_missing = None, True  # as a said date that cannot be read
        known = dated.start or said
        if known is None and dated.end is None:  # undated, or open with no start of any kind: time unknown, never "still going"
            return Timing(None, {}, None, None, NOT_IN_ZONE if said_missing else "")
        known_from, ended = _start(known, zone), _end(dated.end, zone)
        if known_from and ended and ended.astimezone(UTC) <= known_from.astimezone(UTC):  # the end is not after the start: never eligible
            if dated.start and in_period: return Timing(None, {}, None, None, INCONSISTENT)  # the period's dates, never one fact's own
            return Timing(None, {}, known_from, ended)  # first said at or after its own end: the date guards leave it out at any as_of
        labels = {"start_basis": "stated" if dated.start else "first_said", "end_basis": dated.end_kind}
        if known is None: del labels["start_basis"]  # an end with no start at all: there is no start for a label to describe
        begin = _start(dated.start, zone)  # a first-said day is never a start
        latest = _start_latest(dated.start, zone) if dated.start else (_last(span(said)[1], zone) if said else None)
        if dated.end is None:
            return Timing(TimeInterval(begin, start_latest=latest, end_unbounded=True), labels, known_from, None)
        stated_end = dated.end_kind == "stated" or (dated.end_kind == "closed" and not dated.end_only_said)
        earliest = _end_earliest(dated.end, zone) if stated_end else None  # a replaced end is Engram's own inference: no window
        return Timing(TimeInterval(begin, ended, start_latest=latest, end_earliest=earliest, end_is_upper_bound=dated.end_only_said),
                      labels, known_from, ended)

    # ---------- the request ----------
    @staticmethod
    def _state(f) -> dict:
        return {"status": f.status, "validation_status": f.validation_status, "source_type": f.source_type}

    def request_for(self, entity: str, *, task_type: str = "state_question", as_of: dt.datetime | None = None,
                    ruleset=None, hops: int = 1) -> AdaptedRequest:
        as_of = as_of or dt.datetime.now(dt.timezone.utc)
        if as_of.tzinfo is None: raise ValueError("as_of must include a time zone")
        root = self.entity_id(entity)
        eligible, left_out = self._facts(root, hops, as_of)
        props, links, evidence, used = [], [], {}, []
        for x, rule, timing in eligible:
            f, sent = x.fact, timing.sent
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
            if sent is None: qualified_for.append("valid time unknown")
            if sent is None and timing.note: qualified_for.append(timing.note)  # why it is unknown, when there is a reason to give
            if rule.state_record or sent is None:  # the fact's state, as qualifying evidence: a control signal, never support
                sid = f"state:{f.fact_id}"
                evidence[sid] = Evidence(id=sid, source_ref=sid, source_kind=SourceKind.ENGRAM_MEMORY, evidence_kind=EvidenceKind.OTHER,
                                         metadata={**state, "valid_time": "unknown" if sent is None else "known", "qualified_for": tuple(qualified_for),
                                                   "adapter_control": True})
                links.append(EvidenceLink(sid, pid, EvidenceRelation.QUALIFIES))
            props.append(Proposition(
                id=pid, subject=f.subject_id, predicate=f.predicate,
                object_value=self._resolved(f) or f.value,
                kind=rule.kind, source_refs=tuple(dict.fromkeys(sids)),
                valid_time=sent if isinstance(sent, TimeInterval) else None, occurred=sent if isinstance(sent, Occurrence) else None,
                qualifiers={**state, "fact_type": f.fact_type, "time_kind": self._time_kind(f), "valid_time": "unknown" if sent is None else "known",
                            **timing.labels}))
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
        return AdaptedRequest(request, FUNCTIONAL, tuple(used), tuple(left_out), self.day_zone)
