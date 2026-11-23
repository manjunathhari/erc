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
from dataclasses import dataclass, field, replace
from typing import Iterable

from engram_knowledge.database import KnowledgeBase
from engram_knowledge.entity_resolver import entity_for
from engram_knowledge import relations as _R
from engram_knowledge import kinds as _K
from engram_knowledge.fact_validator import ACCEPTED, CONDITION, CONDITION_MARKERS, PASSING, REJECTED, UNCERTAIN, Candidate, FactValidator, NOT_COMPLETED, SourceLine, _has
from engram_knowledge.interpreter import _speaker_role, interpret
from engram_knowledge.learning import evaluate
from engram_knowledge.learning_queue import FACT_TYPE
from engram_knowledge.models import Entity, FactEvidence, FactWithEvidence, KnowledgeFact, RecordError, normalize_name
from engram_knowledge.normalizer import PREDICATE_CUES, PREDICATE_TYPES, stem, time_value, tokens
from engram_knowledge.transition import slot_of

RULES_VERSION = "base2-1"
MONTHS = "january february march april may june july august september october november december".split()

# ---------- 2. the gate ----------

# Stage 2, Increment 3: the first filter (frozen specification claude/engram-stage2-inc3-spec-draft6.md, sections 2 to 4).
A7_HOLD = "the source gives someone else's words"          # DQ-5; the plain apostrophe U+0027 (his answer at 20:36)
FILTER_NOTES = ("unresolved_context_reference", "uncertain_or_conditional_content", "unsupported_content_kind",
                "attribution_not_confirmed", "interpreter_flagged_for_review")          # section 3.2: the only notes
_DROPPED = ("non_user_speaker", "short_reply", "interaction_not_memory_content")        # A3 (1), (4), (5), (6); DQ-2
_STILL_HELD = ("correction_requires_target_resolution", "speaker_role_unknown")       # A6; DQ-1
_PASSED_NOW = ("not_about_the_speaker",)                                                # S2-11
# Section 3.1, list L-G (DQ-3): greeting, thanks and acknowledgement words stripped from the start of the sentence.
_LG = (r"hey|hi|hiya|hello|yo|good\s+morning|good\s+afternoon|good\s+evening|thanks|thank\s+you|thx|ty|wow|whoa|oh|ooh|"
       r"aw|aww|yay|yeah|yes|yep|ok|okay|sure|cool|great|nice|awesome|amazing|congrats|congratulations|haha|lol|omg|"
       r"so|really|totally|absolutely|definitely|indeed|right|exactly|true|agreed|sounds\s+good|that's\s+(?:great|awesome|"
       r"amazing|cool|so\s+cool|wonderful|lovely|sweet|so\s+sweet)|glad|me\s+too|same|bye|see\s+you|take\s+care|cheers|"
       r"much|so\s+much|a\s+lot|again")


@dataclass(frozen=True)
class FilterResult:
    """The first filter's result for one sentence (section 4.1, DQ-6)."""
    passes: bool      # the writer sees the sentence
    kind: str         # today's content kind, unchanged
    note: str         # one of FILTER_NOTES, or ""
    hold: str         # A7_HOLD, or ""
    reason: str       # today's first reason code, always kept


def words_after_greeting(text: str, names: Iterable[str]) -> int:
    """Section 3.1: the words left after removing, from the start and repeatedly, L-G words and the chat's names with the
    punctuation and spaces that follow them. The sentence itself is never cut."""
    t = (text or "").replace("’", "'")
    nm = "|".join(re.escape(n) for n in names if n)
    lead = re.compile(rf"^\s*(?:(?:{_LG}){'|' + nm if nm else ''})\b[\s,!.?:;~-]*", re.I)
    prev = None
    while prev != t:
        prev, t = t, lead.sub("", t, count=1)
    return len(re.findall(r"[A-Za-z0-9']+", t))


def first_filter(speaker: str, text: str, date: str = "", people: Iterable[str] = ()) -> FilterResult:
    """Stage 2, Increment 3 (section 2): today's interpreter and evaluate, run exactly as gate ran them, read through the
    decisions A3 to A7a, CF-1, CF-2 and DQ-1 to DQ-3. A reason code the table does not name keeps today's answer."""
    people = tuple(p for p in people if _speaker_role(p) == "other")                 # W16: assistant labels dropped first
    parsed = interpret(speaker, text, date=date, people=people)
    decision = evaluate(parsed)
    reason = decision.reason_codes[0] if decision.reason_codes else ""
    kind = decision.content_kind
    today = decision.decision == "candidate" and decision.keep_as == "none"
    if today: return FilterResult(True, kind, "", "", reason)
    if reason in _DROPPED or reason in _STILL_HELD: return FilterResult(False, kind, "", "", reason)
    if reason == "social_or_acknowledgement":                                         # A3 (2), (3) and A4
        return FilterResult(words_after_greeting(text, people) >= 4, kind, "", "", reason)
    if reason in _PASSED_NOW: return FilterResult(True, kind, "", "", reason)
    if reason == "externally_attributed_statement": return FilterResult(True, kind, "", A7_HOLD, reason)   # A7, A7a
    if reason in FILTER_NOTES: return FilterResult(True, kind, reason, "", reason)    # A5, CF-2, DQ-2
    return FilterResult(today, kind, "", "", reason)


def gate(speaker: str, text: str, date: str = "", people: Iterable[str] = ()) -> tuple[bool, str]:
    """Whether the writer sees the sentence, and its content kind (a hint for the P1 fact type). Since Stage 2, Increment 3
    both come from `first_filter` (section 4.1). `people` names the people in the chat (WR-A, rule S1), so a named speaker
    counts as a person talking about their own life. An assistant, system or tool label in it is dropped first: it never
    counts as a person (W16)."""
    r = first_filter(speaker, text, date, people)
    return r.passes, r.kind


# ---------- 2b. dates stated in the sentence (WR-B, rules TD1 to TD10) ----------

_SHORT = dict(jan="january", feb="february", mar="march", apr="april", jun="june", jul="july", aug="august",
              sep="september", sept="september", oct="october", nov="november", dec="december")
_DATE = re.compile(r"\[([^\]]+)\]|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:" + "|".join(MONTHS) + r")\s+\d{4}|\b(?:" + "|".join(MONTHS)
                   + r")\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\b(?:" + "|".join(MONTHS) + r")\s+\d{4}|\b\d{4}-\d{2}(?:-\d{2})?\b|\b(?:19|20)\d{2}\b", re.I)
_ROLE = (("start", re.compile(r"\b(?:since|from|starting|beginning)\s*$", re.I)),
         ("end", re.compile(r"\b(?:until|till|to|through)\s*$", re.I)))


def stated_dates(text: str, date_said: str = "") -> tuple[tuple[str, str], ...]:
    """The dates a sentence states, each with its role (start, end or event), read by fixed rules. TD1: relative words are
    resolved from the said day by the existing reader (engram_chat.with_dates); TD8: short month names are read; TD9: a month or
    day with no year gives nothing; TD6: a vague expression gives nothing; TD5: dates whose roles do not settle give nothing;
    TD7: the said day itself is never returned unless the sentence states it."""
    import engram_chat as E   # imported here: engram_chat imports this module
    t = re.sub(r"\b(" + "|".join(_SHORT) + r")\.?(?=\s+(?:\d{1,2}(?:st|nd|rd|th)?\s+)?\d{4}\b)", lambda m: _SHORT[m[1].lower()], text, flags=re.I)
    t = re.sub(r"\b(?:early|mid|late)[\s-]+((?:19|20)\d{2})\b", r"\1", t, flags=re.I)
    shown = E.with_dates(t, date_said) if date_said else t
    found = []
    for m in _DATE.finditer(shown):
        inner = m.group(1)
        if inner is not None and re.search(r"\b(?:before|after|between)\b", inner, re.I): return ()  # vague ("a few weeks before ...")
        value = time_value(inner if inner is not None else m.group(0))
        if not value and inner is not None:  # a season of a known year ("last summer [summer 2024]"): the year
            y = re.fullmatch(r"\D*((?:19|20)\d{2})\D*", inner)
            value = y[1] if y else None
        if not value: continue
        before = shown[:m.start()]
        if inner is not None:  # the role word stands before the relative expression, not before its bracket
            before = re.sub(r"\S+(?:\s+\S+){0,3}\s*$", "", before) if not re.search(r"\b(?:since|from|until|till)\s+\S+(?:\s+\S+){0,3}\s*$", before, re.I) else re.sub(r"(since|from|until|till)\s+\S+(?:\s+\S+){0,3}\s*$", r"\1", before, flags=re.I)
        role = next((r for r, rx in _ROLE if rx.search(before)), "event")
        if role == "end" and re.search(r"\bto\s*$", before, re.I) and not any(r == "start" for _, r in found): role = "event"
        found.append((value, role))
    roles = [r for _, r in found]
    if not found: return ()
    if len(found) == 1: return tuple(found)
    if sorted(roles) in (["end", "start"],): return tuple(found)
    return ()


# ---------- 3. the writer ----------
VOCABULARY_WORDS = ", ".join(PREDICATE_TYPES)   # the 31 words, read from the vocabulary in code (WR-C, 1.2)

# Stage 2, Increment 5 (3.4, O-4): version B of the prompt document, Draft 3 (claude/engram-stage2-inc5-prompt-draft3.md,
# SHA-256 3b3dbda0...dde7764), made by its two approved changes: the "subject_kind" field line after the subject line (PQ-1),
# and "subject_kind" directly after "subject" in the JSON shape (PQ-2). Approved texts: WRITER_PROMPT 0a7a0718...6fe878;
# BLOCK_PROMPT, built from it by Increment 4's replacements below, unchanged, 34360fa9...0c2fc7.

WRITER_PROMPT = """Each line below is one sentence a person said in a conversation, with its line id. For each fact a line states that lasts (something the person or someone they mention has, is, did, plans, likes or is called), copy from that line:
- "subject": who or what the fact is about, as written in the line ("I" when it is the speaker; e.g. "my sister", "Max"). When the speaker names a thing of their own, such as "my job", "my home" or "my move", the fact is about the speaker: write "I";
- "subject_kind": what the subject is, one of: person, animal, place, organisation, thing. Leave it out when the line does not make this clear;
- "word": the one word from this list that says what kind of fact it is, or "other" if none fits: {words};
- "object": the specific thing the line states about the subject (a name, place, item, number or activity), copied word for word from the line, as short as possible.

Skip lines that only give a feeling, a reaction, an opinion about something else, a wish or a maybe, a question, or small talk. A line may state more than one fact: give each its own entry. When a line lists several things, such as "tea, coffee and juice", give each thing its own entry and never put the list in one object. Never use words that are not in the line.

Return a JSON object {{"facts": [{{"line": "<line id>", "subject": "...", "subject_kind": "...", "word": "...", "object": "..."}}, ...]}}. If no line states a lasting fact, return {{"facts": []}}.

Lines:
{lines}"""


def writer_prompt(lines: Iterable[tuple[str, str]]) -> str:
    """lines: (line_id, sentence) for the gated sentences of one chat."""
    return WRITER_PROMPT.format(words=VOCABULARY_WORDS, lines="\n".join(f"{i} {t}" for i, t in lines))


def vocabulary_word(word) -> str:
    """The writer's word tidied ("Works_At " -> "works_at"); anything outside the vocabulary is "other"."""
    w = str(word or "").strip().lower()
    return w if w in PREDICATE_TYPES else "other"


def parse_proposals(reply: str, valid_lines: set[str], block_lines: set[str] | None = None) -> list[dict]:
    """Writer reply -> [{line, subject, word, object}]. Unknown line ids and empty fields are dropped; a line may give several
    proposals (WP-2), and only an exact repeat is dropped; any date in the reply is ignored (4A16); never raises.
    Stage 2, Increment 4 (N8 (b)): with block_lines (every line id of the reading's block), a proposal is dropped only when the
    reply is unreadable, its subject or object is empty, or its line is not in block_lines; "subject_from" is kept as given,
    whatever it is, and the fixed checks decide. Without block_lines, exactly today's behaviour.
    Stage 2, Increment 5 (R-1): a "subject_kind" the reply gives is kept exactly as received, in both modes (no trimming; a
    value that is not one of the five is kept too); `StructureLayer.file` decides. A reply without it parses as today."""
    try:
        m = re.search(r"\{.*\}", reply or "", re.S)
        rows = json.loads(m.group(0)).get("facts", []) if m else []
    except (ValueError, AttributeError):
        return []
    allowed = valid_lines if block_lines is None else set(block_lines)
    out, seen = [], []   # Increment 5 (R-1, his C-5): a list, compared by value, so a kept list or object value cannot raise
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict): continue
        line, subj, obj = str(r.get("line", "")).strip(), str(r.get("subject", "")).strip(), str(r.get("object", "")).strip()
        if line not in allowed or not subj or not obj: continue
        row = dict(line=line, subject=subj[:120], word=vocabulary_word(r.get("word")), object=obj[:200])
        if block_lines is not None and r.get("subject_from") is not None: row["subject_from"] = str(r["subject_from"]).strip()
        if "subject_kind" in r: row["subject_kind"] = r["subject_kind"]   # Increment 5, R-1: exactly as received, whatever it is
        if tuple(row.values()) in seen: continue
        seen.append(tuple(row.values()))
        out.append(row)
    return out


# ---------- 3b. reading a block of conversation (Stage 2, Increment 4) ----------
# Frozen specification claude/engram-stage2-inc4-spec-draft5-revision2.md (sections 2 to 4), contract Amendment 9.

@dataclass(frozen=True)
class BlockLine:
    """One line of a chat's block, in one reading (section 2.1, B-1 to B-6)."""
    line_id: str
    speaker: str
    text: str
    citable: bool     # said by the reading speaker and passed by the first filter (B-3)
    kind: str         # the first filter's content kind, for citable lines; "" otherwise


def _is_person(speaker: str) -> bool:
    """B-2, W16: a speaker who is not an assistant, system or tool label (read from the label alone, as first_filter does)."""
    return _speaker_role(speaker) not in ("assistant", "system", "tool")


def readings(lines, date: str = "", people: Iterable[str] = ()) -> list[tuple[str, list[BlockLine]]]:
    """B-1 to B-5. lines: the chat's (line_id, speaker, text) in order. One (reading speaker, block) per person speaker, in the
    order they first speak. In a reading, a line is citable when the reading speaker said it and the first filter passes it;
    every other line is read-only. Assistant, system and tool lines are not in the block."""
    people = tuple(people)
    kept = [(str(i), sp, t) for i, sp, t in lines if _is_person(sp)]
    order = list(dict.fromkeys(sp for _, sp, _ in kept))
    out = []
    for who in order:
        block = []
        for i, sp, t in kept:
            r = first_filter(sp, t, date, people) if sp == who else None
            block.append(BlockLine(i, sp, t, bool(r and r.passes), r.kind if r and r.passes else ""))
        out.append((who, block))
    return out


# Section 4, the block prompt: approved as Draft 2 (claude/engram-stage2-inc4-block-prompt-draft2.md), his word of
# 21 November 2026, 08:05. Template SHA-256 273eacee2c0f01e4c7f21179699e721b5821b45be963641e29479f04c706071d.
_BORROW = ('Give facts only from lines that are not marked (read only). Below, a person\'s name also means a relation without a '
           'name, such as "my sister". A name may be copied from a line of either speaker; a relation without a name may be '
           'copied only from a line said by the same speaker as the line that states the fact. If a line names a person only '
           'as he, she, him, her, his or hers, you may copy that person\'s name from one other line of the chat and give that '
           'line\'s id as "subject_from". Copy the name word for word. Never copy anything else from another line.')
# Built from today's prompt by fixed replacements (P-1 to P-7 of the approved Draft 2), so every rule of today's prompt is
# kept by construction (section 4) and appears once in this file.
BLOCK_PROMPT = (WRITER_PROMPT
    .replace("Each line below is one sentence a person said in a conversation, with its line id. For each fact a line states "
             "that lasts (something the person or", "Each line below is one sentence said in a conversation, shown with its "
             "line id and who said it. For each fact a line states that lasts (something its speaker or")                # P-1, P-2
    .replace('("I" when it is the speaker;', '("I" when it is the line\'s speaker;')                                      # P-3
    .replace("\n\nReturn a JSON object", "\n\n" + _BORROW + "\n\nReturn a JSON object")                                # P-4, P-7
    .replace('"object": "..."}}, ...]}}.', '"object": "...", "subject_from": "<line id>"}}, ...]}}. Leave out "subject_from" '
             'when the subject is not copied from another line.'))                                                    # P-5, P-6


def block_prompt(block: Iterable[BlockLine]) -> str:
    """The writer's prompt for one reading (section 4): each line as "<id> <speaker>: <sentence>", a read-only line with
    "(read only)" after its id. WRITER_PROMPT and writer_prompt are unchanged (N7)."""
    shown = "\n".join(f"{b.line_id} {'' if b.citable else '(read only) '}{b.speaker}: {b.text}" for b in block)
    return BLOCK_PROMPT.format(words=VOCABULARY_WORDS, lines=shown)


# Section 2.6: the reason strings, exact, with the plain apostrophe U+0027.
READ_ONLY = "the sentence is shown for reading only"                  # 2a
NAME_IS_MAIN = "the name's line is the main line"                     # 2b
NAME_NOT_HERE = "the name's line is not in this chat"                 # 2b'
NO_REFERENCE = "the sentence does not refer to a person"              # 2c
RELATION_OTHER = "a relation is borrowed only from the same speaker"  # 2d
NEARER_NAME = "another name is as near or nearer"                     # 2e
REFERENCE_WORDS = re.compile(r"(?<![\w'])(?:he|she|him|her|his|hers)(?![\w'])", re.I)   # 2.4, N2 (a); "they" does not count (N4)
_WEEKDAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
# 2.5, list L-NN: never a name.
L_NN = ({"i", "i'm", "i've", "i'd", "i'll", "ok", "okay", "oh", "wow", "hey", "hi", "hello", "thanks", "thank", "yes", "yeah", "no",
         "god", "mr", "mrs", "ms", "dr"} | set(_WEEKDAYS) | set(MONTHS)
        | {w for w in re.findall(r"[a-z']+", _LG) if len(w) > 1})
_NAME_KINDS = ("one", "several", "family")                            # L2a, L2b, L3a (N9 (b))


def _relation_names(text: str) -> list[str]:
    """2.5: "my" + a relation word of L2a, L2b or L3a with no name given ("my sister"), as "my <relation>"."""
    words = _R._words(text)
    out = []
    for i, w in enumerate(words):
        if w.lower() != "my": continue
        for k in range(1, 5):
            part = words[i + 1:i + 1 + k]
            if len(part) < k or "," in part: break
            rel = _R.read_relation(part)
            if rel is None: continue
            if rel.kind in _NAME_KINDS and not rel.name:
                nxt = words[i + 1 + k] if i + 1 + k < len(words) else ""
                named = nxt[:1].isupper() and _R.read_relation(part + [nxt.strip("'")])
                if not (named and named.name): out.append("my " + rel.relation)
            break
    return out


def _capital_names(text: str, speakers: set, later: set) -> list[str]:
    """2.5 (N1 (a)): runs of words each beginning with a capital letter, a trailing "'s" dropped, that are not a speaker, not
    on L-NN, and not the first word of their line unless the same word appears elsewhere in the chat not first in its line."""
    t = (text or "").replace("\u2019", "'")
    runs, cur, last = [], [], None
    for n, m in enumerate(re.finditer(r"[A-Za-z][A-Za-z'-]*", t)):
        w = re.sub(r"'s$", "", m.group(0))
        out = not w[:1].isupper() or w.lower() in L_NN or w.lower() in speakers or (n == 0 and w not in later)
        if out or not (cur and t[last:m.start()].strip() == ""):
            if cur: runs.append(" ".join(cur))
            cur = [] if out else [w]
        else:
            cur.append(w)
        last = m.end()
    if cur: runs.append(" ".join(cur))
    return runs


def _later_words(texts) -> set:
    """Capitalised words that appear somewhere not first in their line."""
    out = set()
    for t in texts:
        for n, m in enumerate(re.finditer(r"[A-Za-z][A-Za-z'-]*", (t or "").replace("\u2019", "'"))):
            if n: out.add(re.sub(r"'s$", "", m.group(0)))
    return out


def names_in(text: str, speakers: Iterable[str], later: set) -> list[str]:
    """Every name a line holds (2.5): capitalised names, and relations without a name counted as names."""
    return _capital_names(text, {normalize_name(x) for x in speakers}, later) + _relation_names(text)


def _same_name(subject: str, name: str) -> bool:
    """The subject is that name: equal names, or a relation with a name whose name it is, or the same relation."""
    if normalize_name(subject) == normalize_name(name): return True
    read = _R.read_subject(subject)
    if read and read[0] == "my":
        rel = read[2]
        return normalize_name(rel.name) == normalize_name(name) if rel.name else normalize_name("my " + rel.relation) == normalize_name(name)
    return False


def nearest_ok(block: list[tuple], main: int, name: int, subject: str) -> bool:
    """2e (Q7 (4), N3 (a), D2-3): the name line is the one line, before or after, holding a name at the least distance; that
    line holds exactly one name; and the subject is that name. block: [(sid, speaker, text)] in order."""
    speakers = {sp for _, sp, _ in block}
    later = _later_words(t for _, _, t in block)
    at = [k for k, (sid, _, _) in enumerate(block) if sid == main][0]
    found = [(abs(k - at), k, names_in(t, speakers, later)) for k, (sid, _, t) in enumerate(block) if sid != main]
    found = [f for f in found if f[2]]
    if not found: return False
    least = min(d for d, _, _ in found)
    nearest = [f for f in found if f[0] == least]
    if len(nearest) != 1 or len(nearest[0][2]) != 1: return False
    _, k, (only,) = nearest[0]
    return block[k][0] == name and _same_name(subject, only)


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


def my_own(subject: str, word: str) -> bool:
    """RM-b (4A13, OQ-2): "my X" is the speaker when X is one of the word's own cue words ("my job" for works_at, "my home"
    for lives_in, "my move" for moved_to). "my sister" and "my daughter" are not, so they stay with the person named."""
    m = re.fullmatch(r"my\s+(\w+)", " ".join((subject or "").lower().split()))
    return bool(m) and stem(m[1]) in {stem(w) for w in PREDICATE_CUES.get(word, "").split()}


def _kept(subject_kind) -> dict:
    """Increment 5 (P-2, P-6): the writer's kind as kept with a hold or review item, only when one was given."""
    return {} if subject_kind is None else dict(subject_kind=subject_kind)


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
        self.word_checker = FactValidator(self.kb)   # fixed-list mode: only its word-support check is used (RM-a)

    def line(self, sid: int) -> SourceLine | None:
        row = self.db.execute("SELECT sid, speaker, text, date FROM sentences WHERE sid=?", (sid,)).fetchone()
        return SourceLine(*row) if row else None

    def check(self, sid: int, subject: str, obj: str, name_line: int | None = None) -> tuple[str, tuple, object]:
        """The fixed rules for one proposal. Returns (verdict, reasons, P2 decision or None). name_line (Stage 2, Increment 4,
        Q7): a borrowed subject's name line, passed by `file` only when it is a line of the block; the resolver and the
        who-rule read it as well as the sentence. Every other check reads the sentence alone, as today."""
        src = self.line(sid)
        if src is None: return REJECTED, ("the cited sentence does not exist",), None
        if not copied(obj, src.text): return REJECTED, ("object not copied word for word from the sentence",), None
        if is_partial_date(obj): return REJECTED, ("object is only a partial or relative date",), None
        cand = Candidate(subject, version_key(src.text, obj), obj, (sid,), method="structure", version=RULES_VERSION)
        named = [self.line(name_line)] if name_line is not None and name_line != sid else []
        d = self.validator.validate_borrowed(cand, [src], named) if named else self.validator.validate(cand, [src])
        if d.verdict == REJECTED: return REJECTED, d.reasons, d
        # Who-rule: the subject is the speaker, or is named in the sentence. P2's attribution check already rejects a
        # subject who is neither ("the speaker of the source is someone else"); it sends "named but not the speaker" to
        # review, and the who-rule accepts that (the user telling us about their sister is a fact about the sister).
        doubts = tuple(r for r in d.reasons if r != "reported by someone else, not the subject")
        return (UNCERTAIN if doubts else ACCEPTED), doubts, d

    def word_supported(self, sid: int, subject: str, obj: str, word: str) -> str:
        """RM-a (4A12, 4A17): the shared checker's own support check for a vocabulary word, in fixed-list mode. Returns ""
        when the sentence supports the word, otherwise the checker's reason ("nothing in the source says <word>")."""
        d = self.word_checker.validate(Candidate(subject, word, obj, (sid,), method="structure", version=RULES_VERSION), [self.line(sid)])
        return next((r for r in d.reasons if r in (f"nothing in the source says {word}", NOT_COMPLETED)), "")

    def passing_state(self, sid: int, subject: str, obj: str, word: str) -> bool:
        """S5 (Stage 2, Increment 1; 7A1, 7A3): the shared checker's passing-state rule, in fixed-list mode. True only for a
        vocabulary state word the sentence supports; a word held back by the support check is never held by this rule."""
        return PASSING in self.word_checker.validate(Candidate(subject, word, obj, (sid,), method="structure", version=RULES_VERSION), [self.line(sid)]).reasons

    def filter_of(self, sid: int) -> FilterResult:
        """DQ-4 (a): the first filter's result for a stored sentence, from its speaker, text and date, with the speakers
        recorded in the same chat (in the order they were recorded) as the people; first_filter drops assistant labels."""
        speaker, text, date, chat = self.db.execute("SELECT speaker, text, date, chat FROM sentences WHERE sid=?", (sid,)).fetchone()
        people = tuple(r[0] for r in self.db.execute("SELECT speaker FROM sentences WHERE chat IS ? GROUP BY speaker ORDER BY MIN(sid)", (chat,)))
        return first_filter(speaker, text, date or "", people)

    def block_of(self, sid: int) -> tuple[list[tuple], tuple]:
        """The block of the stored chat a sentence is in (B-1, B-5): its person lines as (sid, speaker, text), in recorded
        order, and the chat's recorded speakers as the people (as filter_of works them out, DQ-4)."""
        chat = self.db.execute("SELECT chat FROM sentences WHERE sid=?", (sid,)).fetchone()
        if chat is None: return [], ()
        rows = self.db.execute("SELECT sid, speaker, text FROM sentences WHERE chat IS ? ORDER BY sid", (chat[0],)).fetchall()
        people = tuple(dict.fromkeys(sp for _, sp, _ in rows))
        return [(i, sp, t) for i, sp, t in rows if _is_person(sp)], people

    def _hold(self, sid, subject, obj, word, reasons, sids, noted=None, subject_kind=None):
        item = dict(subject=subject, object=obj, word=word, source_sids=list(sids), method="structure", version=RULES_VERSION, **(noted or {}), **_kept(subject_kind))
        return Outcome(UNCERTAIN, tuple(reasons), review_id=self.kb.add_review(json.dumps(item), list(reasons), list(sids)))

    def file(self, sid: int, subject: str, obj: str, kind: str = "", word: str = "", subject_from=None, reading=None, *, subject_kind=None) -> Outcome:
        """Checks one proposal and stores it: accepted -> a P1 fact; uncertain -> P1's review queue; rejected -> nothing.
        `word` is the writer's vocabulary word (WR-C); "" or "other" files the fact outside the vocabulary, by its wording.
        Dates come only from the sentence (WR-B, 4A16); the said day is never stored as a start or an end (TD7).
        Stage 2, Increment 4 (section 2.3, contract Amendment 9): `reading` is the reading speaker; `subject_from` is the name
        line's sentence id, or the line id as given when it is not a line of the chat. With both left out, today's path.
        Stage 2, Increment 5 (P-2, contract Amendment 10): `subject_kind` is the writer's kind; left out, None, or anything but
        one of the five exact values means no kind. It is kept with any hold or review item when given (P-6). A fact that would
        create a new entity with no kind decided is held, last (K-10, P-1)."""
        if subject_from is None and reading is None: return self._file_today(sid, subject, obj, kind, word, subject_kind=subject_kind)
        return self._file_block(sid, subject, obj, kind, word, subject_from, reading, subject_kind=subject_kind)

    def _file_block(self, sid, subject, obj, kind, word, subject_from, reading, subject_kind=None) -> Outcome:
        """Section 2.3: step 1 (today's checks; the name line read by the resolver and the who-rule, Q7), then steps 2a to 4,
        which only add a hold (Q10, D2-1), then step 5 as today. The first failing step in table order gives the reason."""
        word = vocabulary_word(word)
        in_vocab = word not in ("other",)
        subject = "I" if in_vocab and my_own(subject, word) else subject    # RM-b (4A13): "my job" is the speaker's
        block, people = self.block_of(sid)
        here = {i for i, _, _ in block}
        borrowed = subject_from is not None
        given = subject_from if isinstance(subject_from, int) else (int(subject_from) if str(subject_from).strip().isdigit() else None)
        name = given if borrowed and given in here and given != sid else None        # a valid name line of this block
        verdict, reasons, d = self.check(sid, subject, obj, name_line=name)
        if verdict == REJECTED: return Outcome(REJECTED, reasons)    # 1: a rejected proposal stays rejected, never queued (D2-1)
        src = self.line(sid)
        f = self.filter_of(sid)
        noted = dict(filter_note=f.note) if f.note else {}            # section 4.3: the note from the main line only
        sids = [sid] + ([name] if name is not None else [])
        if verdict == UNCERTAIN: return self._hold(sid, subject, obj, word, reasons, sids, noted, subject_kind)   # held at step 1: its reason
        held = None
        if reading is not None and not (src.speaker == reading and sid in here and f.passes): held = READ_ONLY     # 2a
        elif borrowed and given == sid: held = NAME_IS_MAIN                                                          # 2b
        elif borrowed and name is None: held = NAME_NOT_HERE                                                         # 2b'
        elif borrowed and not REFERENCE_WORDS.search(src.text): held = NO_REFERENCE                                 # 2c
        elif borrowed:
            read = _R.read_subject(subject)
            other = self.line(name).speaker != src.speaker
            if read and read[0] == "my" and not read[2].name and other: held = RELATION_OTHER                     # 2d
            elif not nearest_ok(block, sid, name, subject): held = NEARER_NAME                                      # 2e
            elif _has(tokens(self.line(name).text), CONDITION_MARKERS): held = CONDITION                            # 3
        if held: return self._hold(sid, subject, obj, word, [held], sids, noted, subject_kind)
        if f.hold or (name is not None and self.filter_of(name).hold):                                              # 4: A7
            return self._hold(sid, subject, obj, word, [A7_HOLD], sids, subject_kind=subject_kind)
        if borrowed and self._not_a_person(d, subject_kind):        # Increment 5, section 7 (10A5): "he" or "she" borrows only a person
            return self._hold(sid, subject, obj, word, [_K.BORROWED], sids, noted, subject_kind)
        return self._store(sid, subject, obj, kind, word, in_vocab, d, src, noted, name, subject_kind=subject_kind)

    def _not_a_person(self, d, subject_kind) -> bool:
        """Section 7, E-1: a borrowed name is known not to be a person's when it resolves to an existing entity of kind animal,
        place, organisation or thing, or the proposal's subject_kind is one of those. With no known kind, borrowed as today."""
        known = d.subject.entity_id and self.kb.entity(d.subject.entity_id).entity_type in _K.NOT_PERSON
        return bool(known) or _K.valid(subject_kind) in _K.NOT_PERSON

    def _file_today(self, sid: int, subject: str, obj: str, kind: str = "", word: str = "", subject_kind=None) -> Outcome:
        word = vocabulary_word(word)
        in_vocab = word != "other"
        if in_vocab and my_own(subject, word): subject = "I"          # RM-b (4A13): "my job" is the speaker's
        verdict, reasons, d = self.check(sid, subject, obj)
        if verdict == REJECTED: return Outcome(REJECTED, reasons)    # 1: a rejected proposal stays rejected, never queued
        src = self.line(sid)
        f = self.filter_of(sid)                                       # DQ-4 (a): worked out here, so no caller can skip it
        if f.hold:                                                    # 2: the A7 hold; nothing is stored
            item = dict(subject=subject, object=obj, word=word, source_sids=[sid], method="structure", version=RULES_VERSION, **_kept(subject_kind))
            return Outcome(UNCERTAIN, (f.hold,), review_id=self.kb.add_review(json.dumps(item), [f.hold], [sid]))
        noted = dict(filter_note=f.note) if f.note else {}            # section 4.3: the key only when there is a note
        if verdict == UNCERTAIN:
            item = dict(subject=subject, object=obj, word=word, source_sids=[sid], method="structure", version=RULES_VERSION, **noted, **_kept(subject_kind))
            return Outcome(UNCERTAIN, reasons, review_id=self.kb.add_review(json.dumps(item), list(reasons), [sid]))
        return self._store(sid, subject, obj, kind, word, in_vocab, d, src, noted, subject_kind=subject_kind)

    def _store(self, sid, subject, obj, kind, word, in_vocab, d, src, noted, name=None, subject_kind=None) -> Outcome:
        """Step 5, as today: word support, passing state, storing and versioning. A name line (Increment 4) is recorded with
        the role `qualifies` (Q6), and a borrowed subject's alias rests on it (Q9 (iii)). Increment 5: the K-10 hold, after
        every other hold (P-1), only when the fact would create a new entity (3.5); nothing is stored then."""
        sids = [sid] + ([name] if name is not None else [])
        held = self.word_supported(sid, subject, obj, word) if in_vocab else ""
        notes = (f"word held: {held}",) if held else ()
        if held: in_vocab = False                                     # RM-a: filed by its wording only
        if word != "other" and self.passing_state(sid, subject, obj, word):   # S5: after the word-support check
            item = dict(subject=subject, object=obj, word=word, source_sids=sids, method="structure", version=RULES_VERSION, **noted, **_kept(subject_kind))
            return Outcome(UNCERTAIN, (PASSING,), review_id=self.kb.add_review(json.dumps(item), [PASSING], sids))
        if not d.subject.entity_id:                                   # Increment 5, K-10 (3.5): a new entity needs a kind
            decided = _K.decide(d.subject, subject_kind)
            if decided is None: return self._hold(sid, subject, obj, word, [_K.no_kind(subject)], sids, noted, subject_kind)
            d = replace(d, subject=replace(d.subject, kind=decided))
        who = entity_for(self.kb, d.subject, sid if name is None else name)   # Increment 2: a relation and its scoped alias, created only now
        return self._write(sid, who, obj, kind, word, in_vocab, notes, src, noted, name)

    def _write(self, sid, who, obj, kind, word, in_vocab, notes, src, noted, name=None) -> Outcome:
        """Storing and versioning for the entity `who` (step 5, as today, moved here unchanged apart from versioning by speaker,
        Increment 5, section 6)."""
        wording = version_key(src.text, obj)
        key = word if in_vocab else wording
        dates = stated_dates(src.text, src.date)
        start = next((v for v, r in dates if r in ("start", "event")), None)
        end = next((v for v, r in dates if r == "end"), None)
        mine = self.kb.about_entity(who, statuses=("active", "superseded"))
        same = [x for x in mine if normalize_name(x.fact.object_value or "") == normalize_name(obj) and x.fact.predicate == key]
        if same:  # the same fact said again: more evidence, not a second fact
            if not any(e.source_id == str(sid) for e in same[0].evidence):
                self.kb.add_evidence(FactEvidence.create(same[0].fact.fact_id, sid, extraction_method="structure", extraction_version=RULES_VERSION))
            return Outcome(ACCEPTED, notes, fact_id=same[0].fact.fact_id)
        fact = KnowledgeFact.create(who, key, "text", PREDICATE_TYPES[key] if in_vocab else FACT_TYPE.get(kind, "observation"), "explicit",
                                    object_value=obj, validation_status="accepted", valid_from=start, valid_to=end,
                                    metadata=dict(checked_by="rules " + RULES_VERSION, said_on=src.date, wording=wording,
                                                  vocabulary="in" if in_vocab else "outside", **noted))
        evidence = (FactEvidence.create(fact.fact_id, sid, extraction_method="structure", extraction_version=RULES_VERSION),)
        if name is not None: evidence += (FactEvidence.create(fact.fact_id, name, evidence_role="qualifies", extraction_method="structure", extraction_version=RULES_VERSION),)
        stored = self.kb.add(FactWithEvidence(fact, evidence))
        if slot_of(key) is None:  # 4A15: a slotted word's replacement is the state engine's; every other fact keeps base 2's versioning
            for old in mine:  # a newer value for the same subject and wording replaces the older one; the old one is kept
                if old.fact.status == "active" and old.fact.predicate == key and (old.fact.metadata or {}).get("wording", old.fact.predicate) == wording \
                        and self._said_only_by(old, src.speaker):      # Increment 5, section 6 (10A3): only the same speaker's
                    self.kb.set_status(old.fact.fact_id, "superseded", note=f"replaced by {fact.fact_id}")   # TD7: no end stored
        return Outcome(ACCEPTED, notes, fact_id=stored.fact.fact_id)

    def _said_only_by(self, old, speaker) -> bool:
        """Section 6, E-3, D-11a: True when every sentence recorded as `supports` for the older fact was said by `speaker`. A
        `qualifies` name sentence is not counted; a fact supported by more than one speaker is never replaced."""
        sids = [e.source_id for e in old.evidence if e.evidence_role == "supports"]
        if not sids: return False
        for s in sids:
            row = self.db.execute("SELECT speaker FROM sentences WHERE sid=?", (int(s) if str(s).isdigit() else s,)).fetchone()
            if row is None or normalize_name(row[0]) != normalize_name(speaker): return False
        return True

    def approve_held(self, data: dict, entity_name=None, subject_kind=None) -> FactWithEvidence:
        """P-5, P-6: a person approves a fact base 2 held (called by KnowledgePipeline.approve). The fixed checks run again (a
        refusal is refused); the doubts that held it are the person's to overrule, as on the classic path. A known entity, or
        one named by the person, needs no kind; a new one takes the rules' or the lists' kind, else the writer's valid kind
        kept with the fact, else a valid `subject_kind` given here; with none, approval is refused with the K-10 reason."""
        sids = [int(x) for x in data.get("source_sids", [])]
        if not sids: raise RecordError("no source sentence")
        sid, name = sids[0], (sids[1] if len(sids) > 1 else None)
        subject, obj = data.get("subject", ""), data.get("object", "")
        word = vocabulary_word(data.get("word", ""))
        verdict, reasons, d = self.check(sid, subject, obj, name_line=name)
        if verdict == REJECTED: raise RecordError("; ".join(reasons))
        entity_id = self.kb.resolve(entity_name) if entity_name else d.subject.entity_id
        if entity_name and not entity_id: raise RecordError("no entity by that name")
        if not entity_id and not d.subject.name: raise RecordError("say which entity this refers to")
        if not entity_id:
            decided = _K.decide(d.subject, data.get("subject_kind"), subject_kind)
            if decided is None: raise RecordError(_K.no_kind(subject))
            d = replace(d, subject=replace(d.subject, kind=decided))
        unsupported = self.word_supported(sid, subject, obj, word) if word != "other" else ""   # RM-a, as when stored
        noted = (dict(filter_note=data["filter_note"]) if data.get("filter_note") else {}) | dict(approved_by="person")
        who = entity_id or entity_for(self.kb, d.subject, sid if name is None else name)
        out = self._write(sid, who, obj, "", word, word != "other" and not unsupported, (f"word held: {unsupported}",) if unsupported else (),
                          self.line(sid), noted, name)
        return self.kb.get(out.fact_id)

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


__all__ = ["RULES_VERSION", "gate", "BlockLine", "readings", "BLOCK_PROMPT", "block_prompt", "stated_dates", "VOCABULARY_WORDS", "WRITER_PROMPT", "writer_prompt", "vocabulary_word", "parse_proposals", "my_own", "is_partial_date", "copied",
           "version_key", "iso_day", "Outcome", "StructureLayer", "FactGraph", "walk", "facts_section"]
