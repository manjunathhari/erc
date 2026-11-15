"""Decides whether a candidate fact may be stored. Fixed rules only: a language model never judges its own output."""
import json
import re
from dataclasses import dataclass

from .database import KnowledgeBase
from .models import Entity, FactEvidence, FactWithEvidence, KnowledgeFact, RecordError, normalize_name, tidy

from .entity_resolver import EntityResolver, Resolution
from .normalizer import PREDICATE_CUES, PREDICATE_TYPES, content_stems, predicate, stem, stems, time_value, time_values_in, tokens

ACCEPTED, UNCERTAIN, REJECTED = "accepted", "uncertain", "rejected"
RULES_VERSION = "1"
NEGATION = set("not no never without none cannot cant dont doesnt didnt wont wasnt isnt arent werent havent hasnt hadnt neither nor".split()) | {"no longer"}
HYPOTHETICAL = set("if maybe might perhaps could would wish hope hoping thinking considering should wonder wondering".split())
OTHER_ACTOR = set("he she they his her their sister brother friend mom dad mother father son daughter husband wife cousin aunt uncle neighbor neighbour colleague boss".split())
RELATIONS = {"married_to", "parent_of", "friend_of"}
SHORT_WINDOW = 6
# OQ-1 (4A17): "am", "im" and "is" are in status's cue words, but alone they say nothing about a status ("I am allergic to
# penicillin"). For status only, they do not count as support; status's own state words (single, married ...) still do.
LINKING_ONLY = {"status": {"am", "im", "is"}}
# Step 3a: attended, visited and completed are sent to ERC as completed happenings, so a sentence supports one of them only if it
# states one: a completed form of the word, and nothing that makes it a habit ("every Sunday") or something still to come.
# "was" alone says nothing of attendance ("I was sick", "I was at home"): it counts only in the phrase "was there for".
COMPLETED_PHRASES = {"attended": ("was there for",)}
COMPLETED_FORMS = {"attended": {"attended", "went"}, "visited": {"visited", "went", "travelled", "traveled"}, "completed": {"completed", "finished", "graduated", "done"}}
RECURRING = set("every each daily weekly monthly yearly annually usually often regularly always sometimes generally normally occasionally frequently routinely "
                "weekends weekdays mornings evenings nights mondays tuesdays wednesdays thursdays fridays saturdays sundays".split())
NOT_YET = set("will gonna tomorrow next upcoming plan planning intend".split())
NOT_COMPLETED = "the source does not state a completed happening"
# Stage 2, Increment 1 (contract step WR-D; contract Amendment 7). Fixed word lists, matched on whole words with case
# ignored; any change to a list is an amendment. claude/engram-stage2-inc1-spec-draft3.md, section 4.
CONDITION, NEAR_MISS, PASSING = "the source states a condition", "the source states a near miss", "the source states a passing state"
LIST, PAIR, OPINION = "object is a list; each part needs its own proposal", "object may be two things", "an opinion about something else"
CONDITION_MARKERS = ("if", "unless", "in case", "as long as", "provided that", "providing that", "assuming", "suppose", "supposing")
NEAR_MISS_MARKERS = ("almost", "nearly", "came close to", "on the verge of")
AMOUNT_AFTER = set("a an all every everyone everything always half twice double".split())   # "almost ten years", "almost always"
COMPARISON_AFTER = set("as like here there".split())                                         # CP-2: "almost as old", "almost there"
MORE_NUMBERS = set("thirteen fourteen fifteen sixteen seventeen eighteen nineteen sixty seventy eighty ninety thousand million billion".split())
DAY_MARKERS = ("today", "tonight", "this morning", "this afternoon", "this evening", "right now", "at the moment", "for now", "for the time being")
MOOD_PHRASES = ("tired of", "sick of", "fed up with", "in the mood for")
STATE_WORDS = {w for w, kind in PREDICATE_TYPES.items() if kind != "event" and w != "plans"}   # the 13 vocabulary state words
MOOD_WORDS = {"likes", "dislikes", "hobby"}                                                     # D2-1, 7A3
OPINION_MARKERS = ("i think", "i believe", "i feel that", "i guess", "i reckon", "i find", "in my view", "in my opinion", "it seems", "seems to me")
NOT_OPINION_AFTER = {"i believe": {"in"}, "i think": {"of", "about"}}                           # CP-3
# E (4.6, TF-3): for started_job these cue words do not count on their own; one of the specific words must be there too.
GENERAL_ONLY = {"started_job": {"start", "started", "new", "joined"}}
SPECIFIC = {"started_job": set("job hired work working employed position role career company".split())}


def _at(words, phrase):
    """Where a marker begins in a sentence's words. Whole words only: "if" is not found in "life"."""
    p = phrase.split()
    return [i for i in range(len(words) - len(p) + 1) if words[i:i + len(p)] == p]


def _has(words, markers):
    return any(_at(words, m) for m in markers)


def _near_miss(words):
    for m in NEAR_MISS_MARKERS:
        for i in _at(words, m):
            after = words[i + 1] if " " not in m and i + 1 < len(words) else ""   # the exception is for "almost" and "nearly" only
            amount = after.lstrip("$")[:1].isdigit() or after in MORE_NUMBERS or after in AMOUNT_AFTER
            if not (amount or after in COMPARISON_AFTER): return True
    return False


def _opinion(words):
    for m in OPINION_MARKERS:
        for i in _at(words, m):
            after = (words[i + len(m.split()):] or [""])[0]
            if after not in NOT_OPINION_AFTER.get(m, ()): return True
    return False


def _separators(obj):
    """S6 (4.4; 7A2, 7A4): what joins the parts of an object. A comma between two digits ("1,200") is not counted."""
    o = (obj or "").lower()
    commas = len(re.findall(r",(?!(?<=\d,)\d)", o))
    joins = o.count(";") + len(re.findall(r"(?<![\w&])(?:and|or|plus|&)(?![\w&])", o)) + len(re.findall(r"\bas\s+well\s+as\b", o))
    return commas, joins


@dataclass(frozen=True)
class SourceLine:
    sid: int
    speaker: str
    text: str
    date: str = ""


@dataclass(frozen=True)
class Candidate:
    subject: str
    predicate: str
    object: str
    source_sids: tuple = ()
    time: str = ""
    method: str = ""
    version: str = ""
    raw: str = ""
    end: str = ""          # WR-B (A2): a stated end; checked against the source like the time


@dataclass(frozen=True)
class Decision:
    verdict: str
    reasons: tuple = ()
    subject: Resolution | None = None
    predicate: str = ""
    time: str | None = None
    end: str | None = None


class FactValidator:
    def __init__(self, kb, open_predicate=False):
        """open_predicate=True (the structure layer, base 2): predicates are not from the fixed list, so the list and its
        cue words are skipped; every other check is the same. Fixed by the code that builds the checker, never per call."""
        self.resolver = EntityResolver(kb)
        self.open_predicate = bool(open_predicate)

    def validate(self, candidate, source_sentences):
        """1 entity references, 2 predicate and object, 3 source support, 4 negation and attribution. Returns a Decision."""
        open_predicate = self.open_predicate
        reject, unsure = [], []
        word = tidy(candidate.predicate) if open_predicate else predicate(candidate.predicate)
        lines = list(source_sentences)
        if not lines: reject.append("no source sentence")
        if any(s is None for s in candidate.source_sids) or len(lines) != len(candidate.source_sids): reject.append("a cited sentence does not exist")
        if open_predicate:
            if not word: reject.append("no predicate")
        elif word not in PREDICATE_TYPES: reject.append(f"predicate not allowed: {word}")
        wanted = content_stems(candidate.object)
        if not wanted: reject.append("object is empty or has no meaning alone")

        who = self.resolver.resolve(candidate.subject, lines)
        if who.status == "absent" or not normalize_name(candidate.subject): reject.append(who.why)
        elif who.status in ("unresolved", "ambiguous"): unsure.append(who.why)
        if reject: return Decision(REJECTED, tuple(reject), who, word)

        # Source support: only the cited sentences count, and every word of a short object must be there.
        said = [(s, stems(s.text)) for s in lines]
        everywhere = {w for _, st in said for w in st}
        share = sum(w in everywhere for w in wanted) / len(wanted)
        if share < (1 if len(wanted) <= 3 else .75): return Decision(REJECTED, ("object not found in its source",), who, word)
        holder = next((s for s, st in said if wanted[0] in st), lines[0])

        # A message can hold many sentences. The one holding the object is the one that must state the fact.
        sentence = next((x for x in re.split(r"(?<=[.!?])\s+|\n+", holder.text) if wanted[0] in stems(x)), holder.text)
        held = stems(sentence)

        # Predicate: does that sentence use a word for this kind of fact?
        cues = set() if open_predicate else {stem(w) for w in PREDICATE_CUES.get(word, "").split() if w not in LINKING_ONLY.get(word, ())}
        supported = not cues or bool(cues & set(held))
        if supported and word in GENERAL_ONLY:   # E: a general cue alone does not say it
            supported = bool((cues - {stem(w) for w in GENERAL_ONLY[word]}) & set(held)) or bool(SPECIFIC[word] & set(tokens(sentence)))
        if not supported: unsure.append(f"nothing in the source says {word}")
        if not open_predicate and word in COMPLETED_FORMS:
            said_words, run = set(tokens(sentence)), " " + " ".join(tokens(sentence)) + " "
            stated = COMPLETED_FORMS[word] & said_words or any(f" {p} " in run for p in COMPLETED_PHRASES.get(word, ()))
            if not stated or RECURRING & said_words or NOT_YET & said_words or " going to " in run: unsure.append(NOT_COMPLETED)

        # Negation and uncertainty near the object.
        at = held.index(wanted[0])
        near = tokens(sentence)[max(0, at - SHORT_WINDOW):at + 1]
        said_plain = re.sub(r"[’']", "", sentence.lower())
        if word != "dislikes" and (NEGATION & set(near) or "no longer" in said_plain or "used to" in said_plain): unsure.append("the source may negate this")
        if word != "plans" and HYPOTHETICAL & set(near): unsure.append("the source may be hypothetical")
        if sentence.rstrip().endswith("?"): unsure.append("the source is a question")

        # Stage 2, Increment 1: a condition, a near miss, one thing as object, an opinion about something else, a passing state.
        spoken = tokens(sentence)
        if _has(spoken, CONDITION_MARKERS): unsure.append(CONDITION)
        if _near_miss(spoken): unsure.append(NEAR_MISS)
        commas, joins = _separators(candidate.object)
        if commas + joins >= 2: return Decision(REJECTED, (LIST,), who, word)
        if joins == 1: unsure.append(PAIR)
        about_speaker = normalize_name(who.name) == normalize_name(holder.speaker) or bool(who.entity_id) and self.resolver.kb.resolve(holder.speaker) == who.entity_id
        if _opinion(spoken) and not about_speaker: unsure.append(OPINION)
        # S5 is applied after the word-support check, to a vocabulary word the sentence supports (I1-5, 7A3).
        day, mood = _has(spoken, DAY_MARKERS), _has(spoken, MOOD_PHRASES)
        if not open_predicate and supported and (word in STATE_WORDS and day or word in MOOD_WORDS and mood): unsure.append(PASSING)

        # Attribution: is this the subject's own statement?
        if normalize_name(holder.speaker) == "assistant" and normalize_name(who.name) != "assistant":
            unsure.append("said by the assistant, not the subject")
        elif who.status != "unresolved":
            speaker_is_subject = normalize_name(holder.speaker) == normalize_name(who.name) or self.resolver.kb.resolve(holder.speaker) == who.entity_id and who.entity_id
            first = {"i", "im", "ive", "ill", "id", "my", "me", "we", "our", "us"}
            words = set(tokens(sentence))
            names_subject = bool(set(tokens(who.name)) & words)
            if speaker_is_subject:
                before = set(tokens(sentence)[:at + 1])
                if not first & words and "you" in words: unsure.append("the speaker is talking about someone else")
                elif OTHER_ACTOR & before and not {"i", "im", "ive", "we"} & before: unsure.append("this may be about someone else the speaker mentions")
            elif not names_subject: return Decision(REJECTED, ("the speaker of the source is someone else",), who, word)
            else: unsure.append("reported by someone else, not the subject")

        # Time must come from the source.
        when = until = None
        in_source = set().union(*(time_values_in(s.text, s.date) for s in lines))
        if tidy(candidate.time):
            when = time_value(candidate.time)
            if when is None: unsure.append("time is not a plain date")
            elif when not in in_source: unsure.append("time is not in the source")
        if tidy(candidate.end):
            until = time_value(candidate.end)
            if until is None: unsure.append("end is not a plain date")
            elif until not in in_source: unsure.append("end is not in the source")
        return Decision(UNCERTAIN if unsure else ACCEPTED, tuple(unsure), who, word, when, until)


class KnowledgePipeline:
    """Candidate to validator, then to the knowledge store, the review queue, or nowhere."""

    def __init__(self, db):
        self.db = db
        self.kb = KnowledgeBase(db)
        self.validator = FactValidator(self.kb)

    def lines(self, candidate):
        found = []
        for sid in candidate.source_sids:
            row = self.db.execute("SELECT sid, speaker, text, date FROM sentences WHERE sid=?", (sid,)).fetchone() if isinstance(sid, int) else None
            if row: found.append(SourceLine(*row))
        return found

    def process(self, candidate):
        decision = self.validator.validate(candidate, self.lines(candidate))
        if decision.verdict == ACCEPTED: return decision, self._store(candidate, decision, "rules " + RULES_VERSION).fact.fact_id
        if decision.verdict == UNCERTAIN: return decision, self.kb.add_review(json.dumps(candidate.__dict__ | dict(source_sids=list(candidate.source_sids))), list(decision.reasons), list(candidate.source_sids))
        return decision, None

    def _store(self, candidate, decision, checked_by, entity_id=None):
        who = entity_id or decision.subject.entity_id or self.kb.add_entity(Entity.create(decision.subject.name, "unknown")).entity_id
        same = [x for x in self.kb.about(self.kb.entity(who).canonical_name, statuses=None) if x.fact.predicate == decision.predicate and normalize_name(x.fact.object_value) == normalize_name(candidate.object)]
        if same:
            for sid in candidate.source_sids: self.kb.add_evidence(FactEvidence.create(same[0].fact.fact_id, sid, extraction_method=candidate.method or None, extraction_version=candidate.version or None))
            return self.kb.get(same[0].fact.fact_id)
        target = self.kb.resolve(candidate.object) if decision.predicate in RELATIONS else None
        fact = KnowledgeFact.create(who, decision.predicate, "entity" if target else "text", PREDICATE_TYPES[decision.predicate], "explicit", object_value=None if target else candidate.object, object_entity_id=target,
                                    validation_status="accepted", valid_from=decision.time, valid_to=decision.end, metadata=dict(checked_by=checked_by))
        return self.kb.add(FactWithEvidence(fact, tuple(FactEvidence.create(fact.fact_id, s, extraction_method=candidate.method or None, extraction_version=candidate.version or None) for s in candidate.source_sids)))

    def approve(self, review_id, entity_name=None):
        """A person accepts a reviewed candidate, and may say which known entity it refers to. The source checks still apply."""
        item = self.kb.review(review_id)
        if item is None: raise RecordError("no such review item")
        data = json.loads(item["candidate"])
        if data.get("kind") == "sentence_envelope": raise RecordError("this review item is a sentence, not a fact: it needs who, what and which first")
        candidate = Candidate(**data | dict(source_sids=tuple(data["source_sids"])))
        decision = self.validator.validate(candidate, self.lines(candidate))
        if decision.verdict == REJECTED: raise RecordError("; ".join(decision.reasons))
        entity_id = self.kb.resolve(entity_name) if entity_name else decision.subject.entity_id
        if entity_name and not entity_id: raise RecordError("no entity by that name")
        if not entity_id and not decision.subject.name: raise RecordError("say which entity this refers to")
        stored = self._store(candidate, decision, "person", entity_id)
        self.kb.drop_review(review_id)
        return stored

    def decline(self, review_id):
        self.kb.drop_review(review_id)
