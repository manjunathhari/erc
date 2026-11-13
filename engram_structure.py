"""Engram structure layer (base 2): checked who -> what links, each tied to the exact sentence it came from.

Base 1 (P0) keeps every sentence and finds the right ones by search. This layer adds a small list of facts that can be
followed link to link at answer time ("Calvin -> Dave", "Dave -> Boston"), for questions whose answer needs two steps.
It is the fact path that took MemoryAgentBench multi-hop from 19 to 56 (arm B), moved out of the ERC test bridge with
every ERC call removed, and stored in P1.

Writing, when a chat is saved:
  1. P0 saves every sentence, as in base 1 (unchanged).
  2. The P2 gate picks the speaker's sentences that may hold a lasting fact (`gate`).
  3. A writer model proposes, per picked sentence, a subject and an object copied from it (`writer_prompt`, `parse_proposals`).
  4. Fixed rules accept or reject each proposal (`StructureLayer.file`):
       - the object is copied word for word from the sentence;
       - the object is not a bare or relative date ("the 17th", "last week");
       - P2's fact checker (open-predicate mode): the subject resolves from the sentence, the object is supported,
         no negation, "maybe" or question near it, not the assistant speaking for the user;
       - who-rule: the subject is the speaker, or is named in the sentence (P2's attribution check, with "named but
         not the speaker" accepted rather than held for review).
     Doubtful proposals go to P1's review queue, which nothing reads as a fact. No model judges its own output.
  5. Accepted facts are stored in P1 with their source sentence, the date said, and every version: a newer object for
     the same subject and the same wording marks the older fact superseded (kept, with its end date).

Reading, for a question (no model): the walk starts from the subjects named in the question and from facts whose
sentence the base 1 search already found, and follows subject -> object links up to `hops` steps, every version, oldest
first. The model is shown each reached fact as its original sentence with its date (`facts_section`), never a paraphrase.

P1's delete cascade applies: deleting a sentence through ChatMemory.forget_sentence invalidates the facts resting on it,
so the walk no longer reaches them.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterable

from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, REJECTED, UNCERTAIN, Candidate, FactValidator, SourceLine
from engram_knowledge.interpreter import _speaker_role, interpret
from engram_knowledge.learning import evaluate
from engram_knowledge.learning_queue import FACT_TYPE
from engram_knowledge.models import Entity, FactEvidence, FactWithEvidence, KnowledgeFact, normalize_name

RULES_VERSION = "base2-1"
MONTHS = "january february march april may june july august september october november december".split()

# ---------- 2. the gate ----------

def gate(speaker: str, text: str, date: str = "", people: Iterable[str] = ()) -> tuple[bool, str]:
    """P2.1 interpreter + P2.2 policy on one sentence. True only for a 'candidate' (not review, not ignore).
    Returns (picked, content kind); the kind is a hint for the P1 fact type.
    `people` names the people in the chat (WR-A, rule S1), so a named speaker counts as a person talking about their
    own life. An assistant, system or tool label in it is dropped first: it never counts as a person (W16). With no
    `people`, every decision is as before."""
    people = tuple(p for p in people if _speaker_role(p) == "other")
    parsed = interpret(speaker, text, date=date, people=people)
    decision = evaluate(parsed)
    return decision.decision == "candidate" and decision.keep_as == "none", decision.content_kind


# ---------- 3. the writer ----------
WRITER_PROMPT = """Each line below is one sentence a person said in a conversation, with its line id. For each line that states a lasting fact (something the person or someone they mention has, is, did, plans, likes or is called), copy from that line:
- "subject": who or what the fact is about, exactly as written in the line ("I" when it is the speaker; e.g. "my sister", "Max");
- "object": the specific thing the line states about the subject (a name, place, item, number or activity), copied word for word from the line, as short as possible.

Skip lines that only give a feeling, a reaction, an opinion about something else, a wish or a maybe, a question, or small talk. Write at most one fact per line and never use words that are not in the line.

Return a JSON object {{"facts": [{{"line": "<line id>", "subject": "...", "object": "..."}}, ...]}}. If no line states a lasting fact, return {{"facts": []}}.

Lines:
{lines}"""


def writer_prompt(lines: Iterable[tuple[str, str]]) -> str:
    """lines: (line_id, sentence) for the gated sentences of one chat."""
    return WRITER_PROMPT.format(lines="\n".join(f"{i} {t}" for i, t in lines))


def parse_proposals(reply: str, valid_lines: set[str]) -> list[dict]:
    """Writer reply -> [{line, subject, object}]. Unknown line ids and empty fields are dropped; one per line; never raises."""
    try:
        m = re.search(r"\{.*\}", reply or "", re.S)
        rows = json.loads(m.group(0)).get("facts", []) if m else []
    except (ValueError, AttributeError):
        return []
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict): continue
        line, subj, obj = str(r.get("line", "")).strip(), str(r.get("subject", "")).strip(), str(r.get("object", "")).strip()
        if line not in valid_lines or line in seen or not subj or not obj: continue
        seen.add(line)
        out.append(dict(line=line, subject=subj[:120], object=obj[:200]))
    return out


# ---------- 4. the rules ----------
_DAY = r"(?:\d{1,2}(?:st|nd|rd|th)?|first|second|third|fourth|fifth|tenth|twentieth|thirtieth)"
_WEEKDAY = r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?"
_RELATIVE = re.compile(
    rf"^(?:on |by |since |from |until |at )?(?:the )?(?:{_DAY}"                          # "the 17th", "on the 3rd"
    rf"|(?:last|next|this|that|every) (?:{_WEEKDAY}|week|weekend|month|year|night|time|morning|evening|summer|winter|spring|fall|autumn)"
    rf"|{_WEEKDAY}|today|tonight|yesterday|tomorrow|recently|lately|soon|now|then|earlier|later|ago"
    rf"|(?:a |one |two |three |few |several |\d+ )?(?:days?|weeks?|months?|years?)(?: ago)?"
    rf"|(?:a )?(?:couple|few) (?:of )?(?:days|weeks|months|years) ago)$", re.I)


def is_partial_date(obj: str) -> bool:
    """True for an object that is only a bare or relative time ('the 17th', 'last week', 'Tuesday'). Such an object is
    not a usable fact on its own: a date must be complete (the sentence's own date is kept separately) or left out."""
    return bool(_RELATIVE.match(" ".join(obj.lower().replace(",", " ").split())))


def copied(obj: str, sentence: str) -> bool:
    """The object appears in the sentence word for word (case and spacing aside; words must be whole)."""
    o = " ".join(obj.lower().split())
    s = " ".join((sentence or "").lower().replace("’", "'").split())
    return bool(o) and re.search(r"(?<![a-z0-9])" + re.escape(o.replace("’", "'")) + r"(?![a-z0-9])", s) is not None


def _norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower().replace("’", "'").replace("'s ", " "))
    return " ".join(w for w in text.split() if w not in ("a", "an", "the"))


def version_key(sentence: str, obj: str) -> str:
    """The sentence with the object blanked out. Two versions of one fact share it ("I have 3 bikes" / "I have 4 bikes")."""
    i = sentence.lower().rfind(obj.lower())
    return _norm(sentence[:i] + " _ " + sentence[i + len(obj):] if i >= 0 else sentence)[:300] or "_"


def iso_day(date_said: str) -> str | None:
    """'2:15 pm on 3 March, 2023' -> '2023-03-03'. None when the date cannot be read."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", date_said or "")
    if not m or m.group(2).lower() not in MONTHS: return None
    return f"{int(m.group(3)):04d}-{MONTHS.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}"


@dataclass
class Outcome:
    verdict: str                 # accepted, uncertain or rejected
    reasons: tuple = ()
    fact_id: str | None = None   # set when stored (or when it added evidence to a fact already stored)
    review_id: str | None = None


class StructureLayer:
    """Files writer proposals into P1 on ChatMemory's own database, and reads them back as a graph for the walk."""

    def __init__(self, db):
        self.db = db
        self.kb = KnowledgeBase(db)
        self.validator = FactValidator(self.kb, open_predicate=True)

    def line(self, sid: int) -> SourceLine | None:
        row = self.db.execute("SELECT sid, speaker, text, date FROM sentences WHERE sid=?", (sid,)).fetchone()
        return SourceLine(*row) if row else None

    def check(self, sid: int, subject: str, obj: str) -> tuple[str, tuple, object]:
        """The fixed rules for one proposal. Returns (verdict, reasons, P2 decision or None)."""
        src = self.line(sid)
        if src is None: return REJECTED, ("the cited sentence does not exist",), None
        if not copied(obj, src.text): return REJECTED, ("object not copied word for word from the sentence",), None
        if is_partial_date(obj): return REJECTED, ("object is only a partial or relative date",), None
        cand = Candidate(subject, version_key(src.text, obj), obj, (sid,), method="structure", version=RULES_VERSION)
        d = self.validator.validate(cand, [src])
        if d.verdict == REJECTED: return REJECTED, d.reasons, d
        # Who-rule: the subject is the speaker, or is named in the sentence. P2's attribution check already rejects a
        # subject who is neither ("the speaker of the source is someone else"); it sends "named but not the speaker" to
        # review, and the who-rule accepts that (the user telling us about their sister is a fact about the sister).
        doubts = tuple(r for r in d.reasons if r != "reported by someone else, not the subject")
        return (UNCERTAIN if doubts else ACCEPTED), doubts, d

    def file(self, sid: int, subject: str, obj: str, kind: str = "") -> Outcome:
        """Checks one proposal and stores it: accepted -> a P1 fact; uncertain -> P1's review queue; rejected -> nothing."""
        verdict, reasons, d = self.check(sid, subject, obj)
        if verdict == REJECTED: return Outcome(REJECTED, reasons)
        src = self.line(sid)
        if verdict == UNCERTAIN:
            item = dict(subject=subject, object=obj, source_sids=[sid], method="structure", version=RULES_VERSION)
            return Outcome(UNCERTAIN, reasons, review_id=self.kb.add_review(json.dumps(item), list(reasons), [sid]))
        who = d.subject.entity_id or self.kb.add_entity(Entity.create(d.subject.name, "unknown")).entity_id
        key, day = version_key(src.text, obj), iso_day(src.date)
        mine = self.kb.about_entity(who, statuses=("active", "superseded"))
        same = [x for x in mine if normalize_name(x.fact.object_value or "") == normalize_name(obj) and x.fact.predicate == key]
        if same:  # the same fact said again: more evidence, not a second fact
            if not any(e.source_id == str(sid) for e in same[0].evidence):
                self.kb.add_evidence(FactEvidence.create(same[0].fact.fact_id, sid, extraction_method="structure", extraction_version=RULES_VERSION))
            return Outcome(ACCEPTED, (), fact_id=same[0].fact.fact_id)
        fact = KnowledgeFact.create(who, key, "text", FACT_TYPE.get(kind, "observation"), "explicit", object_value=obj,
                                    validation_status="accepted", valid_from=day,
                                    metadata=dict(checked_by="rules " + RULES_VERSION, said_on=src.date))
        stored = self.kb.add(FactWithEvidence(fact, (FactEvidence.create(fact.fact_id, sid, extraction_method="structure", extraction_version=RULES_VERSION),)))
        for old in mine:  # a newer value for the same subject and wording replaces the older one; the old one is kept
            if old.fact.status == "active" and old.fact.predicate == key:
                ends = day if day and (not old.fact.valid_from or day >= old.fact.valid_from) else None
                self.kb.set_status(old.fact.fact_id, "superseded", note=f"replaced by {fact.fact_id}", valid_to=ends)
        return Outcome(ACCEPTED, (), fact_id=stored.fact.fact_id)

    def graph(self) -> "FactGraph":
        """Every active or superseded fact with its subject, object and source sentences. Invalidated and
        needs-review facts (after a deletion) are left out."""
        rows = self.db.execute(
            "SELECT r.fact_id, e.canonical_name, r.object_value, r.status, r.valid_from, r.recorded_at FROM knowledge_records r "
            "JOIN entities e ON e.entity_id = r.subject_id WHERE r.status IN ('active','superseded') "
            "AND r.metadata LIKE ? ORDER BY r.recorded_at, r.fact_id", ('%"checked_by": "rules ' + RULES_VERSION + '"%',)).fetchall()
        facts = {}
        for fid, subj, obj, status, vf, rec in rows:
            sids = [int(r[0]) for r in self.db.execute("SELECT source_id FROM record_evidence WHERE fact_id=? AND evidence_role='supports' ORDER BY CAST(source_id AS INTEGER)", (fid,))]
            if sids: facts[fid] = dict(subject=_norm(subj), object=_norm(obj), status=status, valid_from=vf, sids=sids)
        return FactGraph(facts)


@dataclass
class FactGraph:
    facts: dict                                   # fact id -> {subject, object, status, valid_from, sids}
    by_subject: dict = field(default_factory=dict)
    by_sid: dict = field(default_factory=dict)

    def __post_init__(self):
        for fid, f in self.facts.items():  # dict order is storage order: oldest first
            self.by_subject.setdefault(f["subject"], []).append(fid)
            for s in f["sids"]: self.by_sid.setdefault(s, []).append(fid)


def walk(g: FactGraph, question: str, seed_sids: Iterable[int] = (), hops: int = 4, hubs: Iterable[str] = ()) -> list[str]:
    """Facts reached from the question, every version, oldest first within a subject. Starts at subjects named in the
    question (longest names first), then at facts whose sentence the search already found (seeds), and follows
    subject -> object links up to `hops` steps. A hub (a chat's speaker, e.g. "user") is never expanded wholesale: its
    facts enter only as seeds, so one person's hundreds of facts don't crowd out the links."""
    hub = {_norm(h) for h in hubs}
    q = f" {_norm(question)} "
    out, seen, frontier, seen_subj = [], set(), [], set()

    def take(fid):
        if fid in seen: return
        seen.add(fid); out.append(fid)
        o = g.facts[fid]["object"]
        if o and o not in seen_subj and o not in hub and o in g.by_subject:
            seen_subj.add(o); frontier.append(o)

    for s in sorted((s for s in g.by_subject if len(s) >= 3 and s not in hub and f" {s} " in q), key=len, reverse=True):
        if s not in seen_subj: seen_subj.add(s); frontier.append(s)
    hub_seeds = []
    for sid in seed_sids:
        for fid in g.by_sid.get(sid, []):
            s = g.facts[fid]["subject"]
            if s in hub: hub_seeds.append(fid)
            elif s not in seen_subj: seen_subj.add(s); frontier.append(s)
    for step in range(max(1, hops)):
        current, frontier[:] = list(frontier), []
        for s in current:
            for fid in g.by_subject.get(s, []): take(fid)
        if step == 0:  # the speaker's own facts the search found, after the named subjects; their objects lead on
            for fid in hub_seeds: take(fid)
        if not frontier: break
    return out


def facts_section(memory, g: FactGraph, fact_ids: list[str], budget: int,
                  head: str = "[Linked facts from memory: the original sentences, with the date each was said]") -> tuple[str, int]:
    """The reached facts as their original sentences (memory.text_of: date, speaker, words as said), each sentence once,
    in walk order, within `budget` tokens. Returns (text, tokens used); ("", 0) when nothing fits."""
    from engram_chat import count_tokens
    lines, shown = [head], set()
    for fid in fact_ids:
        for sid in g.facts[fid]["sids"]:
            if sid in shown: continue
            text = memory.text_of([sid])
            if count_tokens("\n".join(lines + [text])) > budget: continue
            lines.append(text); shown.add(sid)
    if len(lines) == 1: return "", 0
    out = "\n".join(lines)
    return out, count_tokens(out)


__all__ = ["RULES_VERSION", "gate", "WRITER_PROMPT", "writer_prompt", "parse_proposals", "is_partial_date", "copied",
           "version_key", "iso_day", "Outcome", "StructureLayer", "FactGraph", "walk", "facts_section"]
