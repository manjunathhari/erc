"""Read-only adapter: the knowledge layers (P1 to P5) as an ERC ReasoningRequest. It writes nothing and keeps nothing.

How P1 facts become ERC propositions, so that ERC sees what the knowledge layers see:
- Time: a fact the state engine plays in a slot takes that period's span, the same span P1 uses to call conflicts. A period still
  open is closed one day after `as_of`, so two values held at once are a definite contradiction in ERC, as they are a conflict in P1.
  Any other fact takes its stated valid_from and valid_to. A fact with no date at all has no valid time: unknown, never invented.
- as_of: a fact whose span starts after `as_of` is left out. Facts that ended before it stay in, as history.
- Entities: the subject is the entity id. A text object becomes an entity id only when exactly one entity has that name or alias.
- Kinds: a stated fact is an assertion, an inferred one a hypothesis. Plans are left out: a plan is never a state.
- Functional predicates: P1's single-valued slots, and the predicates that open or close them.
- Evidence: one Evidence per source sentence, linked to each fact it supports, contradicts or qualifies, so a sentence counts once.
- Ids: the request id is a digest of the entity, as_of, task, every fact used and the rule set, so a different rule set or different
  facts give a different request id, and so a different ERC result id.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass

from engram_erc import Evidence, EvidenceKind, EvidenceLink, EvidenceRelation, Proposition, PropositionKind, ReasoningRequest, SourceKind, TimeInterval
from engram_knowledge.models import FactWithEvidence
from engram_knowledge.state_engine import COUNTED, StateEngine
from engram_knowledge.temporal import span
from engram_knowledge.transition import CLOSES, OPENS, SINGLE, slot_of

FUNCTIONAL = frozenset(SINGLE) | frozenset(p for p, s in {**OPENS, **CLOSES}.items() if s in SINGLE)
ONE_DAY = dt.timedelta(days=1)


def _day(value: dt.date) -> dt.datetime:
    return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)


def _start(stated: str | None) -> dt.datetime | None:
    return _day(span(stated)[0]) if stated else None


def _end(stated: str | None) -> dt.datetime | None:
    """Half-open: the day after the last day the stated date could mean."""
    return _day(span(stated)[1]) + ONE_DAY if stated else None


@dataclass(frozen=True)
class AdaptedRequest:
    request: ReasoningRequest
    functional_predicates: frozenset
    fact_ids: tuple           # the P1 facts behind each proposition, in order
    left_out: tuple           # (fact_id, reason) for facts not passed to ERC


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

    def _facts(self, entity_id: str, hops: int) -> list[FactWithEvidence]:
        seen, frontier, out = set(), [entity_id], []
        for _ in range(hops + 1):
            nxt = []
            for ent in frontier:
                if ent in seen: continue
                seen.add(ent)
                for x in self.kb.about_entity(ent, statuses=COUNTED, source_types=None):
                    if x.fact.validation_status == "rejected": continue
                    out.append(x)
                    obj = x.fact.object_entity_id or self._resolved(x.fact)
                    if obj: nxt.append(obj)
            frontier = nxt
        return out

    def _resolved(self, fact) -> str | None:
        if fact.object_entity_id or fact.object_type != "text" or not fact.object_value: return fact.object_entity_id
        return self.kb.resolve(fact.object_value)

    # ---------- time ----------
    def _periods(self, entity_id: str) -> dict:
        """fact_id -> (start, end, open) from the state engine's periods for every slot of this entity."""
        out = {}
        for slot in sorted({slot_of(x.fact.predicate) for x in self.kb.about_entity(entity_id, statuses=COUNTED) if slot_of(x.fact.predicate)}):
            for p in self.engine.get_history(entity_id, slot)["periods"]:
                for fid in p.fact_ids:
                    out[fid] = (p.start or p.first_said, p.end, p.end_kind == "open")
        return out

    def _interval(self, fact, periods: dict, as_of: dt.datetime) -> TimeInterval | None:
        if fact.fact_id in periods:
            start, end, still_open = periods[fact.fact_id]
        else:
            start, end, still_open = fact.valid_from, fact.valid_to, fact.valid_to is None
        begin = _start(start)
        if begin is None and end is None: return None
        finish = _end(end) if end else (as_of + ONE_DAY if still_open and begin else None)
        if begin and finish and finish <= begin: finish = begin + ONE_DAY
        return TimeInterval(begin, finish)

    # ---------- the request ----------
    def request_for(self, entity: str, *, task_type: str = "state_question", as_of: dt.datetime | None = None,
                    ruleset=None, hops: int = 1) -> AdaptedRequest:
        as_of = as_of or dt.datetime.now(dt.timezone.utc)
        if as_of.tzinfo is None: raise ValueError("as_of must include a time zone")
        root = self.entity_id(entity)
        records = self._facts(root, hops)
        periods = {}
        for ent in dict.fromkeys(x.fact.subject_id for x in records):
            periods.update(self._periods(ent))
        props, links, evidence, used, left_out = [], [], {}, [], []
        for x in records:
            f = x.fact
            if f.fact_type == "plan":
                left_out.append((f.fact_id, "plan")); continue
            interval = self._interval(f, periods, as_of)
            if interval and interval.start and interval.start > as_of:
                left_out.append((f.fact_id, "starts after as_of")); continue
            pid = f"fact:{f.fact_id}"
            sids = []
            for e in x.evidence:
                eid = f"sentence:{e.source_id}"
                evidence.setdefault(eid, Evidence(id=eid, source_ref=eid, source_kind=SourceKind.ENGRAM_MEMORY, evidence_kind=EvidenceKind.OBSERVATION))
                links.append(EvidenceLink(eid, pid, EvidenceRelation(e.evidence_role)))
                sids.append(eid)
            props.append(Proposition(
                id=pid, subject=f.subject_id, predicate=f.predicate,
                object_value=self._resolved(f) or f.value,
                kind=PropositionKind.ASSERTION if f.source_type == "explicit" else PropositionKind.HYPOTHESIS,
                source_refs=tuple(dict.fromkeys(sids)), valid_time=interval,
                qualifiers={"status": f.status, "validation_status": f.validation_status, "fact_type": f.fact_type}))
            used.append(f.fact_id)
        digest = hashlib.sha256(json.dumps(dict(
            entity=root, as_of=as_of.isoformat(), task=task_type,
            facts=sorted((x.fact.fact_id, x.fact.status, x.fact.recorded_at) for x in records if x.fact.fact_id in used),
            rules=None if ruleset is None else [ruleset.version] + sorted((r.rule_id, r.version) for r in ruleset.rules),
        ), sort_keys=True).encode()).hexdigest()[:24]
        request = ReasoningRequest(id=f"erc_req_{digest}", task_type=task_type, propositions=tuple(props),
                                   evidence=tuple(evidence.values()), evidence_links=tuple(dict.fromkeys(links)),
                                   context_refs=(f"entity:{root}",), as_of=as_of)
        return AdaptedRequest(request, FUNCTIONAL, tuple(used), tuple(left_out))
