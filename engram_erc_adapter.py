"""Engram -> ERC adapter (ADAPTER_REQUIREMENTS.md). Base 3 edition.

Base 3 stores every statement in P1 as (entity, relation, value, polarity) with its own date, and ERC's supersession
verdict is already written there at filing time (engram_knowledge/verdict.py). So this adapter no longer re-reads
sentences for relations, no longer reads the review queue for retractions, and no longer overrides P1. What is left:

  read P1 statements -> ERC propositions with real time -> ERC verdicts at the question's `as_of` (history on request)
  -> ERC graph of current facts -> question-guided walk -> always-on preference profile -> gated excerpts -> context

Writes nothing; calls no model. Same memory + same question + same as_of => identical bytes.

    adapter = Adapter(memory)
    text, info = adapter.context_for("Where does Asha live?")
    info["withheld"]            # sentences kept out, each with the fact that replaced it and ERC's reason
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from engram_erc.contracts import Proposition, TimeInterval
from engram_erc.knowledge_graph import KnowledgeEdge, KnowledgeNode, KnowledgeNodeKind, KnowledgeRelation, build_knowledge_graph
from engram_erc.primitives.contradiction import find_contradictions
from engram_knowledge.relations import MULTI_VALUED, PROFILE_TYPES, RELATION_WORDS, is_multi_valued, norm, relate
from engram_knowledge import verdict as V

VERSION = "adapter-2"
U = timezone.utc


def parse_as_of(question: str) -> datetime | None:
    """'in March 2024' / 'in 2024' / 'before 2025' -> the last instant of that period, else None."""
    q = question.lower()
    m = re.search(r"\b(?:in|during|back in|as of) (january|february|march|april|may|june|july|august|september|october|november|december) (\d{4})\b", q)
    if m:
        mon = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"].index(m.group(1)) + 1
        y = int(m.group(2)); nxt = datetime(y + (mon == 12), mon % 12 + 1, 1, tzinfo=U)
        return nxt - timedelta(seconds=1)
    m = re.search(r"\b(?:in|during|back in|as of|before) (\d{4})\b", q)
    if m: return datetime(int(m.group(1)), 12, 31, 23, 59, 59, tzinfo=U)
    return None


def _day(s: str | None) -> datetime | None:
    try: return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=U) if s else None
    except ValueError: return None


@dataclass
class Fact:
    fact_id: str
    entity: str
    relation: str
    value: str
    polarity: bool
    fact_type: str
    status: str                 # P1 status
    start: datetime | None      # valid_from
    end: datetime | None        # valid_to from P1, or set by ERC supersession
    recorded_at: str
    sids: list[int]
    sentence: str
    date_said: str
    speaker: str
    evidence: int               # number of supporting sentences (repetition weight, R7)
    superseded_by: str | None = None
    reason: str = ""
    note: str = ""              # P1 note ("superseded by fact_x: ERC ...")
    hidden: bool = False        # an older statement of a claim shown through a newer one
    siblings: list = field(default_factory=list)   # fact ids of the statements collapsed into this one


@dataclass
class State:
    facts: dict = field(default_factory=dict)     # fact_id -> Fact
    by_sid: dict = field(default_factory=dict)    # sid -> [fact_id]
    groups: dict = field(default_factory=dict)    # (entity, relation) -> [fact_id] oldest first
    as_of: datetime | None = None
    graph: object = None
    log: list = field(default_factory=list)


class Adapter:
    def __init__(self, memory, hubs: tuple[str, ...] = ("user",), hops: int = 4, budget: int = 4000,
                 profile_share: float = 0.15, facts_share: float = 0.50):
        self.m, self.db = memory, memory.db
        self.hubs = {norm(h) for h in hubs}
        self.hops, self.budget, self.profile_share, self.facts_share = hops, budget, profile_share, facts_share

    # ---------- read P1 + sentences (R10: read-only) ----------
    def load(self, as_of: datetime | None = None) -> State:
        st = State(as_of=as_of or datetime.now(U))
        rows = self.db.execute(
            "SELECT r.fact_id, e.canonical_name, r.predicate, r.object_value, r.fact_type, r.status, r.valid_from, r.valid_to, r.recorded_at, r.note, r.metadata "
            "FROM knowledge_records r JOIN entities e ON e.entity_id = r.subject_id "
            "WHERE r.status IN ('active','superseded') AND r.validation_status='accepted' ORDER BY r.valid_from, r.recorded_at, r.fact_id").fetchall()
        for fid, ent_name, pred, obj, ftype, status, vf, vt, rec, note, meta in rows:
            sids = [int(x[0]) for x in self.db.execute("SELECT source_id FROM record_evidence WHERE fact_id=? AND evidence_role='supports' ORDER BY CAST(source_id AS INTEGER)", (fid,))]
            if not sids: continue
            srow = self.db.execute("SELECT speaker, text, date FROM sentences WHERE sid=?", (sids[-1],)).fetchone()
            if not srow: continue
            speaker, text, date_said = srow
            try: md = json.loads(meta or "{}")
            except ValueError: md = {}
            if "relation_version" in md or "polarity" in md:            # base 3 record: relation and polarity are stored
                entity, relation, value, pol = norm(ent_name), pred, norm(obj), bool(md.get("polarity", True))
            else:                                                        # base 2 record: read the sentence once (legacy)
                r = relate(text, speaker)
                entity, relation, value, pol = r if r else (norm(ent_name), pred, norm(obj), True)
            if entity in ("i", "me", "my") or (speaker and entity == norm(speaker)): entity = norm(speaker)
            f = Fact(fid, entity, relation, value, pol, ftype, status, _day(vf), _day(vt), rec, sids, text, date_said, speaker, len(sids), note=note or "")
            st.facts[fid] = f
            for sd in sids: st.by_sid.setdefault(sd, []).append(fid)
            st.groups.setdefault((entity, relation), []).append(fid)
        self._supersede(st)
        self._collapse(st)
        self._graph(st)
        return st

    def _supersede(self, st: State):
        """ERC's verdict at the question's as_of. P1 already holds the verdict for 'now'; it is recomputed here only so a
        question about the past sees what was current then. One proposition per record: a record is one statement."""
        MIN = datetime.min.replace(tzinfo=U)
        for (entity, relation), fids in st.groups.items():
            fids.sort(key=lambda f: (st.facts[f].start or MIN, st.facts[f].recorded_at))
            rows = [dict(fact_id=f, value=st.facts[f].value, status=st.facts[f].status, valid_from=st.facts[f].start.date().isoformat() if st.facts[f].start else None,
                         valid_to=None, recorded_at=st.facts[f].recorded_at, polarity=st.facts[f].polarity, note="") for f in fids]
            verdict = V.decide(rows, relation, st.as_of)
            for f in fids:
                x = st.facts[f]; new, reason, end = verdict[f]
                x.superseded_by, x.reason = new, reason
                x.end = _day(end) if new else None
                if x.status == "superseded" and not new: st.log.append(("p1_superseded_but_live_at_as_of", f))

    def _collapse(self, st: State):
        """Same claim stated more than once (base 3 links them by same_claim_as): show the newest live statement once,
        count the others as evidence, keep the earliest start. The hidden statements' sentences are listed on the shown
        one (siblings) so the excerpt step does not show the claim twice."""
        seen = {}
        for f in st.facts.values():   # facts arrive oldest first
            key = (f.entity, f.relation, f.value, f.polarity)
            keep = seen.get(key)
            if keep is None: seen[key] = f; continue
            if self.current(st, f) or not self.current(st, keep):   # newer wins when it is live, or when neither is
                f.evidence += keep.evidence; f.start = min([d for d in (f.start, keep.start) if d], default=f.start)
                f.siblings += [keep.fact_id] + keep.siblings; keep.hidden = True; seen[key] = f
            else:
                keep.evidence += f.evidence; keep.siblings.append(f.fact_id); f.hidden = True

    def current(self, st: State, f: Fact) -> bool:
        """Is f in force at st.as_of? (R6: history is reachable only by asking for it through as_of.)"""
        if f.start and f.start > st.as_of: return False
        if f.end and f.end <= st.as_of: return False
        return not (f.superseded_by and not f.end)

    # ---------- R5: ERC graph over current facts ----------
    def _graph(self, st: State):
        nodes, edges, seen = [], [], set()
        for f in st.facts.values():
            if f.hidden or not self.current(st, f) or not f.polarity: continue
            for ent in (f.entity, f.value):
                if ent and ent not in seen:
                    seen.add(ent)
                    nodes.append(KnowledgeNode(node_ref=f"entity:{ent}", kind=KnowledgeNodeKind.ENTITY, label=ent, domain="memory", source_refs=tuple(f"sid:{s}" for s in f.sids), provenance_ref=VERSION))
            if f.entity and f.value and f.entity != f.value:
                edges.append(KnowledgeEdge(edge_ref=f"fact:{f.fact_id}", source_ref=f"entity:{f.entity}", target_ref=f"entity:{f.value}", relation=KnowledgeRelation.INVOLVES, source_refs=tuple(f"sid:{s}" for s in f.sids), provenance_ref=f.relation))
        st.graph = build_knowledge_graph(nodes, edges)
        st.index = defaultdict(list)
        for e in st.graph.edges: st.index[e.source_ref.split(":", 1)[1]].append(e.edge_ref.split(":", 1)[1])

    def _relevant(self, relation: str, qwords: set) -> bool:
        if ":" in relation: return relation.split(":", 1)[1] in qwords        # poss:manager / rel:sister -> the role word
        return any(w in qwords for w in RELATION_WORDS.get(relation, (relation,)))

    def walk(self, st: State, question: str, seed_sids=()) -> list[str]:
        q = f" {norm(question)} "
        qwords = set(q.split())
        guided = any(self._relevant(rel, qwords) for (_, rel) in st.groups)   # does the question name any relation we know?
        start = [s for s in sorted(st.index, key=len, reverse=True) if len(s) >= 3 and s not in self.hubs and f" {s} " in q]
        hub_seeds, out, seen_f, seen_e = [], [], set(), set(start)
        # a hub's relational facts ("my sister is Asha" -> rel:sister) are seeds when the question names the relation
        for (ent, rel), fids in st.groups.items():
            if ent in self.hubs and ":" in rel and f" {rel.split(':', 1)[1]} " in q:
                hub_seeds += [f for f in fids if self.current(st, st.facts[f])]
        for sid in seed_sids:
            for fid in st.by_sid.get(sid, []):
                f = st.facts[fid]
                if not self.current(st, f): continue
                if f.entity in self.hubs: hub_seeds.append(fid)
                elif f.entity not in seen_e: seen_e.add(f.entity); start.append(f.entity)
        frontier = list(start); ranked = []   # (depth, 0 relevant / 1 not, order) -> fact
        for step in range(max(1, self.hops)):
            nxt = []
            def take(fid, depth):
                if fid in seen_f: return
                f = st.facts[fid]; rel_ok = self._relevant(f.relation, qwords)
                seen_f.add(fid); ranked.append(((depth, 0 if rel_ok else 1, len(ranked)), fid))
                v = f.value   # expand through this value only if the fact is relevant (or the walk is unguided)
                if (rel_ok or not guided) and v and v not in seen_e and v not in self.hubs and v in st.index: seen_e.add(v); nxt.append(v)
            for ent in frontier:
                for fid in st.index.get(ent, []): take(fid, step)
            if step == 0:
                for fid in hub_seeds: take(fid, 0)
            if not nxt: break
            frontier = nxt
        return [fid for _, fid in sorted(ranked)]

    # ---------- R7: profile ----------
    def profile(self, st: State) -> list[Fact]:
        rows = [f for f in st.facts.values() if f.fact_type in PROFILE_TYPES and not f.hidden and self.current(st, f) and f.polarity]
        rows.sort(key=lambda f: (-f.evidence, f.start or datetime.min.replace(tzinfo=U)))
        return rows

    # ---------- R6/R8: assemble ----------
    def _line(self, f: Fact) -> str:
        return f"[{f.date_said}] {f.speaker}: {f.sentence}"

    def _tok(self, s: str) -> int: return max(1, len(s) // 4)

    def context_for(self, question: str, as_of: datetime | None = None) -> tuple[str, dict]:
        st = self.load(as_of or parse_as_of(question))
        try: sids = list(self.m.find(question)[0])
        except ZeroDivisionError: sids = []   # base 1 (frozen): find() divides by zero when no chat has been indexed yet (F8)
        parts, used, shown_sids, info = [], 0, set(), dict(as_of=st.as_of.isoformat(), shown=[], withheld=[], profile=[], sections={})
        # linked facts first (they decide how much room is left), shown after the profile in the output
        reached = self.walk(st, question, seed_sids=sids[:10])
        facts_part = ""
        if reached:
            lines, b = ["[Linked facts from memory, current as of the question's date: original sentences with the date each was said]"], int(self.budget * self.facts_share)
            u = self._tok(lines[0])
            for fid in reached:
                f = st.facts[fid]
                if f.sids[0] in shown_sids: continue
                l = f"- {self._line(f)}"; t = self._tok(l)
                if u + t > b: break
                lines.append(l); u += t; shown_sids.update(f.sids)
                for sib in f.siblings: shown_sids.update(st.facts[sib].sids)
                info["shown"].append(dict(fact=fid, entity=f.entity, relation=f.relation, value=f.value, sids=f.sids, valid=[f.start and f.start.date().isoformat(), f.end and f.end.date().isoformat()]))
            if len(lines) > 1: facts_part = "\n".join(lines); used += u; info["sections"]["facts"] = u
        # profile (R7): its floor is profile_share; when the walk left room it may grow, keeping a reserve for excerpts
        prof = self.profile(st)
        if prof:
            reserve = int(self.budget * 0.20)
            b = max(int(self.budget * self.profile_share), self.budget - used - reserve)
            lines = ["[What the user has said about their tastes and habits, most repeated first]"]
            u = self._tok(lines[0])
            for f in prof:
                l = f"- {self._line(f)}"; t = self._tok(l)
                if u + t > b: continue
                lines.append(l); u += t; shown_sids.update(f.sids); info["profile"].append(f.fact_id)
                for sib in f.siblings: shown_sids.update(st.facts[sib].sids)
            if len(lines) > 1: parts.append("\n".join(lines)); used += u; info["sections"]["profile"] = u
        if facts_part: parts.append(facts_part)
        # gated excerpts
        keep, u = [], 0
        for sid in sids:
            if sid in shown_sids: continue
            stale = [st.facts[f] for f in st.by_sid.get(sid, []) if not self.current(st, st.facts[f])]
            live = [f for f in st.by_sid.get(sid, []) if self.current(st, st.facts[f])]
            if stale and not live:
                f0 = stale[0]
                why = f0.reason or ("not yet true at as_of" if f0.start and f0.start > st.as_of else "ended before as_of" if f0.end and f0.end <= st.as_of else "retracted" if not f0.polarity else "")
                info["withheld"].append(dict(sid=sid, fact=f0.fact_id, replaced_by=f0.superseded_by, reason=why)); continue
            t = self.m._tokens(sid) + 8
            if used + u + t > self.budget: break
            keep.append(sid); u += t
        if keep: parts.append(self.m.text_of(sorted(keep))); info["sections"]["excerpts"] = u
        info["sids"] = sids; info["reached"] = len(reached)
        return "\n\n".join(parts) or "(nothing found)", info

    def explain(self, st: State, fact_id: str) -> dict:
        f = st.facts[fact_id]
        return dict(entity=f.entity, relation=f.relation, value=f.value, polarity=f.polarity, sids=f.sids, sentence=f.sentence,
                    valid_from=f.start and f.start.date().isoformat(), valid_to=f.end and f.end.date().isoformat(),
                    current=self.current(st, f), superseded_by=f.superseded_by, reason=f.reason, evidence=f.evidence)


__all__ = ["Adapter", "State", "Fact", "relate", "norm", "parse_as_of", "MULTI_VALUED", "VERSION"]
