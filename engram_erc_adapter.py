"""Engram -> ERC adapter (implements ADAPTER_REQUIREMENTS.md).

Reads P1 records (filed by the base-2 structure layer) and the sentences they rest on, turns each into one ERC
Proposition with subject = entity, predicate = relation, object = value and a real validity interval, lets ERC decide
which versions conflict, and builds the text the answer model reads with ERC's verdict governing every line of it.
Writes nothing; calls no model.

    adapter = Adapter(memory)                       # memory: engram_chat.ChatMemory (or anything with .db, .find, .text_of)
    text, info = adapter.context_for("Where does Asha live?")
    info["withheld"]                                # sentences ERC kept out, each with the fact that replaced it
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from engram_erc.contracts import Proposition, TimeInterval
from engram_erc.knowledge_graph import KnowledgeEdge, KnowledgeNode, KnowledgeNodeKind, KnowledgeRelation, build_knowledge_graph
from engram_erc.primitives.contradiction import find_contradictions

VERSION = "adapter-1"
U = timezone.utc

# ---------- R1/R2: relation table (sentence pattern -> relation). Data, versioned; grows with observed misses. ----------
# (regex, relation, entity group, value group). FIRST = the speaker. Patterns are tried in order; first match wins.
FIRST = "__speaker__"
RELATIONS: list[tuple[str, str, int | str, int]] = [
    # preferences (multi-valued, polarity-bearing)
    (r"^I (?:no longer|don'?t|do not) (?:like|enjoy|drink|eat|use|watch|read|play) (.+?)(?: any ?more| any longer)?\.?$", "likes-", FIRST, 1),
    (r"^I (?:stopped|quit|gave up) (?:liking |drinking |eating |using |watching |reading |playing )?(.+?)\.?$", "likes-", FIRST, 1),
    (r"^I (?:really |absolutely )?(?:like|love|enjoy|adore|am a fan of|am fond of) (.+?)\.?$", "likes", FIRST, 1),
    (r"^I prefer (.+?)\.?$", "prefers", FIRST, 1),
    (r"^I (?:dislike|hate|can'?t stand) (.+?)\.?$", "dislikes", FIRST, 1),
    (r"^I (?:usually |always |often )?(?:drink|eat|order|take) (.+?)\.?$", "likes", FIRST, 1),
    (r"^My favou?rite (.+?) is (.+?)\.?$", "favourite", FIRST, "1+2"),
    # plans
    (r"^I (?:plan|am planning|intend|want) to (.+?)\.?$", "plans", FIRST, 1),
    # first-person states (functional)
    (r"^I live in (.+?)\.?$", "lives_in", FIRST, 1),
    (r"^I (?:moved|have moved) to (.+?)\.?$", "lives_in", FIRST, 1),
    (r"^I work (?:at|for) (.+?)\.?$", "works_at", FIRST, 1),
    (r"^I (?:drive|own|have) (?:a |an )?(.+?)\.?$", "owns", FIRST, 1),
    (r"^My (sister|brother|wife|husband|partner|mother|father|son|daughter|boss|manager|doctor|dog|cat) is (?:called |named )?(.+?)\.?$", "rel", FIRST, "1+2"),
    (r"^My (sister|brother|wife|husband|partner|mother|father|son|daughter|boss|manager|doctor)'?s name is (.+?)\.?$", "rel", FIRST, "1+2"),
    # third-person states (functional)
    (r"^(.+?) lives in (.+?)\.?$", "lives_in", 1, 2),
    (r"^(.+?) (?:moved|has moved) to (.+?)\.?$", "lives_in", 1, 2),
    (r"^(.+?) works (?:at|for) (.+?)\.?$", "works_at", 1, 2),
    (r"^(.+?) is (?:now )?(?:the )?(?:CEO|head|manager|director|chairperson|coach|lead) of (.+?)\.?$", "leads", 1, 2),
    (r"^(.+?) is (?:head)?quartered in (.+?)\.?$", "headquarters", 1, 2),
    (r"^The headquarters of (.+?) (?:is|are) (?:located )?in (.+?)\.?$", "headquarters", 1, 2),
    (r"^(.+?) is married to (.+?)\.?$", "spouse", 1, 2),
    (r"^(.+?) is in (.+?)\.?$", "located_in", 1, 2),
    (r"^(.+?) was born in (.+?)\.?$", "birthplace", 1, 2),
    (r"^(.+?) speaks (.+?)\.?$", "speaks", 1, 2),
    (r"^(.+?) (?:drives|owns|has) (?:a |an )?(.+?)\.?$", "owns", 1, 2),
    (r"^(.+?) is (?:a |an )?(.+?) by profession\.?$", "profession", 1, 2),
    (r"^(.+?) is (?:a |an )(.+?)\.?$", "is_a", 1, 2),
    (r"^The capital of (.+?) is (.+?)\.?$", "capital", 1, 2),
    (r"^(.+?)'s (\w+) is (.+?)\.?$", "poss", 1, "2+3"),
]
_RELATIONS = [(re.compile(p, re.I), rel, e, v) for p, rel, e, v in RELATIONS]
MULTI_VALUED = frozenset({"likes", "dislikes", "prefers", "plans", "speaks", "owns", "visited", "works_on", "favourite"})
PROFILE_TYPES = ("preference",)
CARRIERS = re.compile(r"^(?:the )?(?:country|city|sport|religion|language|field|position|continent) of ", re.I)


def norm(text: str) -> str:
    """Lower-case, no diacritics, no punctuation, no articles, no carrier words (R2)."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    t = CARRIERS.sub("", t.strip())
    t = re.sub(r"[^a-z0-9 ]+", " ", t.lower().replace("'s ", " "))
    return " ".join(w for w in t.split() if w not in ("a", "an", "the"))


def relate(sentence: str, speaker: str) -> tuple[str, str, str, bool] | None:
    """(entity, relation, value, polarity) from one sentence, or None when no pattern matches."""
    s = (sentence or "").strip()
    for rx, rel, eg, vg in _RELATIONS:
        m = rx.match(s)
        if not m: continue
        ent = speaker if eg == FIRST else m.group(eg)
        if isinstance(vg, str):  # "1+2": relation gets the first group, value the second
            a, b = vg.split("+"); rel = f"{rel}:{norm(m.group(int(a)))}"; val = m.group(int(b))
        else:
            val = m.group(vg)
        pol = not rel.endswith("-")
        return norm(ent), rel.rstrip("-"), norm(val), pol
    return None


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
    note: str = ""              # P1 note ("replaced by fact_x")
    intervals: list = field(default_factory=list)   # [(start, end)] per statement after ERC; current(as_of) = any contains as_of


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
            "SELECT r.fact_id, e.canonical_name, r.predicate, r.object_value, r.fact_type, r.status, r.valid_from, r.valid_to, r.recorded_at, r.note "
            "FROM knowledge_records r JOIN entities e ON e.entity_id = r.subject_id "
            "WHERE r.status IN ('active','superseded') AND r.validation_status='accepted' ORDER BY r.recorded_at, r.fact_id").fetchall()
        for fid, ent_name, pred, obj, ftype, status, vf, vt, rec, note in rows:
            sids = [int(x[0]) for x in self.db.execute("SELECT source_id FROM record_evidence WHERE fact_id=? AND evidence_role='supports' ORDER BY CAST(source_id AS INTEGER)", (fid,))]
            if not sids: continue
            srow = self.db.execute("SELECT speaker, text, date FROM sentences WHERE sid=?", (sids[0],)).fetchone()
            if not srow: continue
            speaker, text, date_said = srow
            r = relate(text, speaker)
            if r: entity, relation, value, pol = r
            else: entity, relation, value, pol = norm(ent_name), pred, norm(obj), True   # R12: fall back to base 2's key
            if entity in ("i", "me", "my") or (speaker and entity == norm(speaker)): entity = norm(speaker)
            f = Fact(fid, entity, relation, value, pol, ftype, status, _day(vf), _day(vt), rec, sids, text, date_said, speaker, len(sids), note=note or "")
            st.facts[fid] = f
            for s in sids: st.by_sid.setdefault(s, []).append(fid)
            st.groups.setdefault((entity, relation), []).append(fid)
        self._retractions(st)
        self._supersede(st)
        self._graph(st)
        return st

    def _retractions(self, st: State):
        """Base 2 sends a negated sentence ("I no longer like X") to P1's review queue, so a retraction never becomes a
        fact. The adapter reads those queue items whose sentence matches a polarity-false pattern and adds them as
        polarity=False propositions (never as facts to show), so ERC's polarity check can retire the earlier claim.
        Each one is logged; nothing is written (R10)."""
        rows = self.db.execute("SELECT q.review_id, q.candidate, s.sid FROM review_queue q JOIN review_sources s ON s.review_id=q.review_id").fetchall()
        for rid, cand, sid in rows:
            srow = self.db.execute("SELECT speaker, text, date FROM sentences WHERE sid=?", (sid,)).fetchone()
            if not srow: continue
            speaker, text, date_said = srow
            r = relate(text, speaker)
            if not r or r[3]: continue           # only polarity-false matches are retractions
            entity, relation, value, _ = r
            if entity in ("i", "me", "my"): entity = norm(speaker)
            try: ftype = json.loads(cand).get("kind") or "preference"
            except ValueError: ftype = "preference"
            day = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", date_said or "")
            start = None
            if day:
                months = ["january","february","march","april","may","june","july","august","september","october","november","december"]
                if day.group(2).lower() in months: start = datetime(int(day.group(3)), months.index(day.group(2).lower()) + 1, int(day.group(1)), tzinfo=U)
            fid = f"retraction:{rid}"
            f = Fact(fid, entity, relation, value, False, ftype, "retraction", start, None, "9999", [sid], text, date_said, speaker, 1)
            st.facts[fid] = f
            st.by_sid.setdefault(sid, []).append(fid)
            st.groups.setdefault((entity, relation), []).append(fid)
            st.log.append(("retraction_from_review_queue", rid, sid))

    # ---------- R3/R4: ERC decides conflicts over STATEMENTS; the adapter derives each fact's validity intervals ----------
    def _sent_day(self, sid: int) -> datetime | None:
        row = self.db.execute("SELECT date FROM sentences WHERE sid=?", (sid,)).fetchone()
        m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", (row and row[0]) or "")
        months = ["january","february","march","april","may","june","july","august","september","october","november","december"]
        if not m or m.group(2).lower() not in months: return None
        return datetime(int(m.group(3)), months.index(m.group(2).lower()) + 1, int(m.group(1)), tzinfo=U)

    def _supersede(self, st: State):
        """One ERC Proposition per supporting SENTENCE (a fact restated after a rival or a retraction is live again: F10).
        ERC finds the contradicting pairs; within each pair the later statement supersedes the earlier one, which closes the
        earlier statement's interval at the later one's start. A fact's intervals are those of its statements."""
        MIN = datetime.min.replace(tzinfo=U)
        for (entity, relation), fids in st.groups.items():
            functional = relation not in MULTI_VALUED and not relation.startswith(("likes", "dislikes", "prefers", "plans"))
            props, owner = [], {}
            for f in fids:
                x = st.facts[f]
                for sid in x.sids:
                    start = self._sent_day(sid) or x.start
                    end = st.as_of + timedelta(days=1) if start and start <= st.as_of else None
                    pid = f"{f}@{sid}"; owner[pid] = (f, sid, start)
                    vt = TimeInterval(start=start, end=end if end and end > start else None) if start else None
                    props.append(Proposition(id=pid, subject=entity, predicate=relation, object_value=x.value, polarity=x.polarity, source_refs=(f"sid:{sid}",), valid_time=vt))
            order = sorted(owner, key=lambda p: (owner[p][2] or MIN, st.facts[owner[p][0]].recorded_at, owner[p][1]))
            pos = {p: i for i, p in enumerate(order)}
            sup = {}
            if len(props) > 1:
                for c in find_contradictions(props, functional_predicates=frozenset([relation]) if functional else frozenset()):
                    old, new = (c.left_id, c.right_id) if pos[c.left_id] < pos[c.right_id] else (c.right_id, c.left_id)
                    if old in sup and pos[sup[old][0]] <= pos[new]: continue
                    sup[old] = (new, f"ERC {c.reason_code} ({c.certainty.value})")
            for f in fids:
                x = st.facts[f]; x.intervals = []
                mine = [p for p in order if owner[p][0] == f]
                for p in mine:
                    s0 = owner[p][2]
                    e0 = owner[sup[p][0]][2] if p in sup else None
                    if p in sup and e0 is None: e0 = s0        # undated newer statement: the older one is simply out
                    x.intervals.append((s0, e0))
                newest = mine[-1]
                if newest in sup:
                    x.superseded_by, x.reason = owner[sup[newest][0]][0], sup[newest][1]
                    x.end = owner[sup[newest][0]][2]
                else:
                    x.superseded_by, x.end = None, None
                    if x.status == "superseded":   # P1 says superseded, ERC found no live rival
                        m = re.search(r"replaced by (\S+)", x.note or "")
                        rival = m.group(1) if m else None
                        if rival and rival in st.facts and functional and self._alive_in_p1(rival):
                            x.superseded_by, x.reason, x.end = rival, "P1 status=superseded (rival in another adapter group)", self.facts_start(st, rival)
                            x.intervals = [(a, x.end) for a, _ in x.intervals]; st.log.append(("p1_only_supersession", f, rival))
                        else:   # F9: the replacing fact is gone (forgotten) or the relation is multi-valued -> reinstate
                            st.log.append(("p1_supersession_reinstated", f, rival, "multivalued" if not functional else "rival_gone"))

    def _alive_in_p1(self, fid: str) -> bool:
        row = self.db.execute("SELECT status FROM knowledge_records WHERE fact_id=?", (fid,)).fetchone()
        return bool(row) and row[0] in ("active", "superseded")

    def facts_start(self, st: State, fid: str):
        return st.facts[fid].start if fid in st.facts else None

    def current(self, st: State, f: Fact) -> bool:
        """Is f in force at st.as_of? (R6: history is reachable only by asking for it through as_of.)"""
        if f.intervals:
            return any((s is None or s <= st.as_of) and (e is None or e > st.as_of) for s, e in f.intervals)
        if f.start and f.start > st.as_of: return False
        if f.end and f.end <= st.as_of: return False
        return not f.superseded_by

    # ---------- R5: ERC graph over current facts ----------
    def _graph(self, st: State):
        nodes, edges, seen = [], [], set()
        for f in st.facts.values():
            if not self.current(st, f) or not f.polarity: continue
            for ent in (f.entity, f.value):
                if ent and ent not in seen:
                    seen.add(ent)
                    nodes.append(KnowledgeNode(node_ref=f"entity:{ent}", kind=KnowledgeNodeKind.ENTITY, label=ent, domain="memory", source_refs=tuple(f"sid:{s}" for s in f.sids), provenance_ref=VERSION))
            if f.entity and f.value and f.entity != f.value:
                edges.append(KnowledgeEdge(edge_ref=f"fact:{f.fact_id}", source_ref=f"entity:{f.entity}", target_ref=f"entity:{f.value}", relation=KnowledgeRelation.INVOLVES, source_refs=tuple(f"sid:{s}" for s in f.sids), provenance_ref=f.relation))
        st.graph = build_knowledge_graph(nodes, edges)
        st.index = defaultdict(list)
        for e in st.graph.edges: st.index[e.source_ref.split(":", 1)[1]].append(e.edge_ref.split(":", 1)[1])

    # words in a question that point at a relation (R5: question-guided walk; data, grows with observed misses)
    RELATION_WORDS = {"works_at": ("work", "works", "working", "company", "employer", "job"), "headquarters": ("headquartered", "headquarters", "hq", "based"),
                      "located_in": ("state", "country", "region", "located"), "lives_in": ("live", "lives", "living", "city", "where"),
                      "spouse": ("married", "spouse", "wife", "husband", "partner"), "capital": ("capital",), "leads": ("ceo", "head", "leads", "runs"),
                      "birthplace": ("born", "birthplace"), "owns": ("own", "owns", "drive", "drives", "car"), "speaks": ("speak", "speaks", "language"),
                      "profession": ("profession", "job", "do"), "is_a": ("what is", "who is")}

    def _relevant(self, relation: str, qwords: set) -> bool:
        if ":" in relation: return relation.split(":", 1)[1] in qwords        # poss:manager / rel:sister -> the role word
        return any(w in qwords for w in self.RELATION_WORDS.get(relation, (relation,)))

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
        rows = [f for f in st.facts.values() if f.fact_type in PROFILE_TYPES and self.current(st, f) and f.polarity]
        rows.sort(key=lambda f: (-f.evidence, f.start or datetime.min.replace(tzinfo=U)))
        return rows

    # ---------- R6/R8: assemble ----------
    def _line(self, f: Fact) -> str:
        return f"[{f.date_said}] {f.speaker}: {f.sentence}"

    def _tok(self, s: str) -> int: return max(1, len(s) // 4)

    def context_for(self, question: str, as_of: datetime | None = None) -> tuple[str, dict]:
        st = self.load(as_of or parse_as_of(question))
        sids, finfo = self.m.find(question)
        sids = list(sids)
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
                lines.append(l); u += t; shown_sids.update(f.sids); info["shown"].append(dict(fact=fid, entity=f.entity, relation=f.relation, value=f.value, sids=f.sids, valid=[f.start and f.start.date().isoformat(), f.end and f.end.date().isoformat()]))
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


__all__ = ["Adapter", "State", "Fact", "relate", "norm", "parse_as_of", "RELATIONS", "MULTI_VALUED", "VERSION"]
