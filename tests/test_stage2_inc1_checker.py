"""Stage 2, Increment 1 (contract step WR-D, with contract Amendment 7): the checker additions.

Frozen specification and test plan: claude/engram-stage2-inc1-spec-draft3.md, frozen 15 November 2026
(SHA-256 b3dafe8802e2a0d51a565af946984385dbf534877cc580612818370c7301f65e). Section numbers below are that document's.

  S3  a condition is held, anywhere in the sentence, for every word including plans           (4.1, I1-1)
  S4  a near miss is held, unless "almost" or "nearly" is followed by an amount or a comparison (4.2, CP-2)
  S5  a passing state is held: a day marker on a fact filed under a vocabulary state word; a mood phrase on a fact filed
      under likes, dislikes or hobby. Applied after the word-support check. "now" alone is not a marker
                                                                               (4.3, I1-2, I1-5, CP-1, D2-1, 7A1, 7A3)
  S6  an object is one thing: a list of three or more is refused, a pair joined by one word or by a semicolon is held,
      a single comma is one thing                              (4.4, I1-3, 7A2; Amendment 1 to this text, TF-1; 7A4)
  S7  an opinion about something other than the speaker is held                                (4.5, CP-3)
  E   started_job needs a specific word, not only a general cue; otherwise the fact is filed by its wording (4.6, I1-4)
  P   one sentence is added to the writer's prompt, and nothing else in it changes             (5, I1-6, P-1)

Fixed, hand-written proposals only; no model is called. Every sentence is made up or is already in this repository's
tests. None is LoCoMo text.

TESTS FIRST. This file is written before the build. Until Increment 1 is built, every test whose name begins
test_change, test_reason, test_classic, test_held, test_refused, test_reach_held, test_forms, test_two_rules,
test_separators[...held/refused], test_general_cue_alone and test_prompt is expected to FAIL; every control passes.
"""
import hashlib

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, REJECTED, UNCERTAIN, Candidate, KnowledgePipeline

SAID = "2:15 pm on 12 June, 2025"

# The fixed reason texts (section 4). A held item says why in exactly these words.
CONDITION = "the source states a condition"
NEAR_MISS = "the source states a near miss"
PASSING = "the source states a passing state"
LIST = "object is a list; each part needs its own proposal"
PAIR = "object may be two things"
OPINION = "an opinion about something else"

HELD, REFUSED, IN, OUTSIDE = "held", "refused", "stored in", "stored outside"


class Mem:
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.layer = S.StructureLayer(self.m.db)

    def say(self, text, said=SAID, speaker="User"):
        self.m.open_chat(said)
        sid = self.m.add(speaker, text, date=said)
        self.m.close_chat(write_note=False)
        return sid

    def file(self, text, subject, obj, word):
        """Base 2's path: the proposal goes through StructureLayer.file."""
        sid = self.say(text)
        return sid, self.layer.file(sid, subject, obj, S.gate("User", text, SAID)[1], word=word)

    def classic(self, text, subject, obj, word):
        """The classic path: the same proposal goes through KnowledgePipeline.process."""
        sid = self.say(text)
        decision, _ = KnowledgePipeline(self.m.db).process(Candidate(subject, word, obj, (sid,), "", "test", "1"))
        return sid, decision

    def result(self, out):
        if out.verdict == ACCEPTED:
            return "stored " + self.kb.get(out.fact_id).fact.metadata["vocabulary"]
        return {UNCERTAIN: HELD, REJECTED: REFUSED}[out.verdict]

    def facts(self):
        return self.m.db.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0]

    def sentence(self, sid):
        return self.m.db.execute("SELECT text FROM sentences WHERE sid=?", (sid,)).fetchone()[0]


@pytest.fixture
def mem(tmp_path):
    m = Mem(tmp_path)
    yield m
    m.m.close()


# ------------------------------------------------------------------ 9.1: the 22 cases each rule must change
# id, sentence, subject, object, word, wanted, the reason a held or refused item must carry
CHANGE = [
    ("S3-1", "If I get the job, I will move to Pune.", "I", "Pune", "moved_to", HELD, CONDITION),
    ("S3-2", "I will take the flat near the lake in Pune if the bank agrees.", "I", "flat near the lake", "owns", HELD, CONDITION),
    ("S3-3", "Unless the visa is refused, I will join Apollo in March.", "I", "Apollo", "works_at", HELD, CONDITION),
    ("S3-4", "I plan to move to Pune if I get the job.", "I", "Pune", "plans", HELD, CONDITION),
    ("S3-5", "In case the offer comes through, I will work at Fortis.", "I", "Fortis", "works_at", HELD, CONDITION),
    ("S4-1", "I almost bought a house in Goa.", "I", "a house in Goa", "owns", HELD, NEAR_MISS),
    ("S4-2", "I nearly joined Apollo last year.", "I", "Apollo", "joined", HELD, NEAR_MISS),
    ("S4-3", "I came close to adopting a dog.", "I", "a dog", "adopted", HELD, NEAR_MISS),
    ("S4-4", "I was on the verge of selling my car.", "I", "car", "sold", HELD, NEAR_MISS),
    ("S5-4", "I am working from the Whitefield office at the moment.", "I", "Whitefield office", "works_at", HELD, PASSING),
    ("S5-5", "I feel like Thai food tonight.", "I", "Thai food", "likes", HELD, PASSING),
    ("S5-6", "I am sick of playing tennis.", "I", "tennis", "hobby", HELD, PASSING),
    ("S5-7", "I am in the mood for jazz, which I love.", "I", "jazz", "likes", HELD, PASSING),
    ("S6-1", "I like running, reading and playing my violin.", "I", "running, reading and playing my violin", "likes", REFUSED, LIST),
    ("S6-2", "I have a dog, a cat and two rabbits.", "I", "a dog, a cat and two rabbits", "owns", REFUSED, LIST),
    ("S6-3", "I'm a fan of Bach and Mozart.", "I", "Bach and Mozart", "likes", HELD, PAIR),
    ("S6-4", "I enjoy tea or coffee in the morning.", "I", "tea or coffee", "likes", HELD, PAIR),
    ("S6-5", "I shop at Marks and Spencer.", "I", "Marks and Spencer", "other", HELD, PAIR),
    ("S7-1", "I think the new metro line is badly planned.", "the new metro line", "badly planned", "other", HELD, OPINION),
    ("S7-2", "In my opinion Bengaluru traffic is the worst in India.", "Bengaluru traffic", "the worst in India", "other", HELD, OPINION),
    ("E-1", "I am excited to start this new chapter of my life.", "I", "new chapter", "started_job", OUTSIDE, None),
    ("E-2", "I started at Manipal in 2020.", "I", "Manipal", "started_job", OUTSIDE, None),
]
STOPPED = [c for c in CHANGE if c[5] in (HELD, REFUSED)]


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted,reason", CHANGE, ids=[c[0] for c in CHANGE])
def test_change_the_rule_gives_the_wanted_result(mem, cid, text, subject, obj, word, wanted, reason):
    _, out = mem.file(text, subject, obj, word)
    assert mem.result(out) == wanted


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted,reason", STOPPED, ids=[c[0] for c in STOPPED])
def test_reason_a_stopped_proposal_says_why_in_the_fixed_words(mem, cid, text, subject, obj, word, wanted, reason):
    _, out = mem.file(text, subject, obj, word)
    assert reason in out.reasons


@pytest.mark.parametrize("cid", ["E-1", "E-2"])
def test_change_an_unsupported_started_job_is_filed_by_its_wording_and_keeps_the_fact(mem, cid):
    """4.6: the word is held back, the fact is not lost, and the predicate is not the vocabulary word."""
    _, text, subject, obj, word, _, _ = next(c for c in CHANGE if c[0] == cid)
    _, out = mem.file(text, subject, obj, word)
    assert out.verdict == ACCEPTED
    fact = mem.kb.get(out.fact_id).fact
    assert fact.metadata["vocabulary"] == "outside" and fact.predicate != "started_job" and fact.object_value == obj


# ------------------------------------------------------------------ 9.2: the 27 controls
# id, sentence, subject, object, word, today's result (which must not change)
CONTROL = [
    ("S3-c1", "I moved to Pune in March 2023.", "I", "Pune", "moved_to", IN),
    ("S3-c2", "I work at Fortis Life Sciences.", "I", "Fortis Life Sciences", "works_at", IN),
    ("S4-c1", "I have worked at Manipal for almost ten years.", "I", "Manipal", "works_at", IN),
    ("S4-c2", "I own nearly 200 books.", "I", "200 books", "owns", IN),
    ("S4-c3", "I almost always play tennis on Sundays.", "I", "tennis", "hobby", IN),
    ("S4-c4", "I work at Manipal, and the new wing is almost there.", "I", "Manipal", "works_at", IN),
    ("S4-c5", "I live in Pune, which is almost like home.", "I", "Pune", "lives_in", IN),
    ("S4-c6", "I own a flat that is almost as old as I am.", "I", "a flat", "owns", IN),
    ("S5-1", "I am in Mumbai today.", "I", "Mumbai", "lives_in", OUTSIDE),
    ("S5-2", "I am so tired of this traffic today.", "I", "traffic", "dislikes", OUTSIDE),
    ("S5-3", "I'm sick of pizza.", "I", "pizza", "dislikes", OUTSIDE),
    ("S5-8", "I am fed up with my job at Infosys.", "I", "Infosys", "works_at", IN),
    ("S5-c1", "I work at Manipal now.", "I", "Manipal", "works_at", IN),
    ("S5-c2", "I bought a car today.", "I", "a car", "bought", IN),
    ("S5-c3", "I joined Apollo today.", "I", "Apollo", "joined", IN),
    ("S5-c4", "I live in Pune.", "I", "Pune", "lives_in", IN),
    ("S5-c5", "I feel like a different person since I took up hiking, which I love.", "I", "hiking", "likes", IN),
    ("S6-c1", "I like running, reading and playing my violin.", "I", "running", "likes", IN),
    ("S6-c2", "I live in Austin, Texas.", "I", "Austin, Texas", "lives_in", IN),
    ("S6-c3", "I own 1,200 books.", "I", "1,200 books", "owns", IN),
    ("S7-c1", "My sister lives in Paris.", "my sister", "Paris", "lives_in", IN),
    ("S7-c2", "I think I like jazz.", "I", "jazz", "likes", IN),
    ("S7-c3", "I believe in my sister, who lives in Paris.", "my sister", "Paris", "lives_in", IN),
    ("S7-c4", "I often think about my daughter, who works at Infosys.", "my daughter", "Infosys", "works_at", IN),
    ("S7-c5", "Yoga is my hobby and I find it relaxing.", "I", "Yoga", "hobby", IN),
    # BF-3: S7-c4 has "often" between "I" and "think", so it holds no marker either way; S7-c6 has the excluded phrase itself.
    ("S7-c6", "I think about my daughter, who works at Infosys.", "my daughter", "Infosys", "works_at", IN),
    ("E-c1", "I started a job at Apollo in June 2023.", "I", "Apollo", "started_job", IN),
    ("E-c2", "I was hired by Fortis in 2021.", "I", "Fortis", "started_job", IN),
]


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted", CONTROL, ids=[c[0] for c in CONTROL])
def test_control_stays_as_it_is(mem, cid, text, subject, obj, word, wanted):
    _, out = mem.file(text, subject, obj, word)
    assert mem.result(out) == wanted


# ------------------------------------------------------------------ 9.3: the known miss
def test_known_miss_a_specific_word_anywhere_in_the_sentence_still_supports_started_job(mem):
    """E-k1 (4.6; the count's CF-10). The result asserted here is WRONG, and it is asserted on purpose: the narrow rule is
    satisfied by "job" anywhere in the sentence, so starting a bakery is still filed as starting a job. The fuller check
    (the object of started_job must be an institution or a role) waits for entity kinds, Increment 5. This test is expected
    to pass before and after Increment 1; when the fuller check is built it must be turned, on Manj's word."""
    _, out = mem.file("Losing my job pushed me to start a bakery.", "I", "a bakery", "started_job")
    assert mem.result(out) == IN


# ------------------------------------------------------------------ G1: every rule is on the classic path too
# The classic path files only vocabulary words under the speaker, so the three "other" rows (S6-5, S7-1, S7-2) are base 2's.
CLASSIC = [c for c in STOPPED if c[4] != "other"]


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted,reason", CLASSIC, ids=[c[0] for c in CLASSIC])
def test_classic_the_same_rule_stops_the_same_proposal(mem, cid, text, subject, obj, word, wanted, reason):
    _, decision = mem.classic(text, subject, obj, word)
    assert decision.verdict == {HELD: UNCERTAIN, REFUSED: REJECTED}[wanted] and reason in decision.reasons


@pytest.mark.parametrize("cid", ["E-1", "E-2"])
def test_classic_a_general_cue_alone_does_not_support_started_job(mem, cid):
    """On the classic path an unsupported word is held for review (its existing behaviour), not accepted."""
    _, text, subject, obj, word, _, _ = next(c for c in CHANGE if c[0] == cid)
    _, decision = mem.classic(text, subject, obj, word)
    assert decision.verdict == UNCERTAIN and "nothing in the source says started_job" in decision.reasons


def test_classic_control_a_plain_fact_is_still_accepted(mem):
    _, decision = mem.classic("I work at Manipal now.", "I", "Manipal", "works_at")
    assert decision.verdict == ACCEPTED


def test_classic_an_opinion_about_someone_else_carries_the_opinion_reason(mem):
    """BF-2b (G1): the opinion rows of 9.1 use the word "other", which the classic path does not file, so the opinion rule
    has its own classic-path test."""
    _, decision = mem.classic("I think my sister lives in Paris.", "my sister", "Paris", "lives_in")
    assert decision.verdict == UNCERTAIN and OPINION in decision.reasons


# ------------------------------------------------------------------ G2, G3: nothing stored; the queue says why; the sentence is untouched
HELD_ROWS = [c for c in CHANGE if c[5] == HELD]
REFUSED_ROWS = [c for c in CHANGE if c[5] == REFUSED]


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted,reason", HELD_ROWS, ids=[c[0] for c in HELD_ROWS])
def test_held_stores_no_fact_and_queues_one_item_with_the_reason(mem, cid, text, subject, obj, word, wanted, reason):
    sid, out = mem.file(text, subject, obj, word)
    assert out.verdict == UNCERTAIN and out.fact_id is None
    assert mem.facts() == 0
    queued = mem.kb.reviews()
    assert len(queued) == 1 and reason in queued[0]["reasons"]
    assert mem.sentence(sid) == text


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted,reason", REFUSED_ROWS, ids=[c[0] for c in REFUSED_ROWS])
def test_refused_stores_no_fact_and_queues_nothing(mem, cid, text, subject, obj, word, wanted, reason):
    sid, out = mem.file(text, subject, obj, word)
    assert out.verdict == REJECTED and out.fact_id is None
    assert mem.facts() == 0 and mem.kb.reviews() == []
    assert mem.sentence(sid) == text


# ------------------------------------------------------------------ G9: where the passing-state rule reaches
STATE_DAY = [   # each of the 13 vocabulary state words, supported by its sentence, with a day marker
    ("owns", "I own a red scooter at the moment.", "a red scooter"),
    ("lives_in", "I live in Pune at the moment.", "Pune"),
    ("works_at", "I work at Manipal for the time being.", "Manipal"),
    ("married_to", "I am married to Asha right now.", "Asha"),
    ("parent_of", "I am the parent of Arjun today.", "Arjun"),
    ("friend_of", "I am a friend of Ravi at the moment.", "Ravi"),
    ("member_of", "I am a member of the Rotary Club for now.", "Rotary Club"),
    ("job_title", "I work as a surgeon at the moment.", "surgeon"),
    ("status", "I am single right now.", "single"),
    ("likes", "I like jazz today.", "jazz"),
    ("dislikes", "I hate traffic today.", "traffic"),
    ("hobby", "I play chess this evening.", "chess"),
    ("number", "I have three cats at the moment.", "three cats"),
]
EVENT_DAY = [   # each of the 17 event words, and plans, with a day marker: the day is the event's date, not a doubt
    ("adopted", "I adopted a dog today.", "a dog"),
    ("bought", "I bought a car today.", "a car"),
    ("sold", "I sold my car today.", "car"),
    ("lost", "I lost my wallet today.", "wallet"),
    ("gave_away", "I gave my bike away today.", "bike"),
    ("moved_to", "I moved to Pune today.", "Pune"),
    ("started_job", "I started a job at Apollo today.", "Apollo"),
    ("left_job", "I left my job at Apollo today.", "Apollo"),
    ("got_married", "I got married to Asha today.", "Asha"),
    ("divorced", "I divorced Ravi today.", "Ravi"),
    ("joined", "I joined Apollo today.", "Apollo"),
    ("left_group", "I left the Rotary Club today.", "Rotary Club"),
    ("started_hobby", "I started learning chess today.", "chess"),
    ("stopped_hobby", "I stopped playing chess today.", "chess"),
    ("attended", "I attended the Pune meetup today.", "Pune meetup"),
    ("visited", "I visited Mysore today.", "Mysore"),
    ("completed", "I completed the marathon today.", "marathon"),
    ("plans", "I plan to visit Mysore tonight.", "Mysore"),
]
MOOD_ON = [     # likes, dislikes and hobby, supported by the sentence, with a mood phrase
    ("likes", "I am in the mood for jazz, which I love.", "jazz"),
    ("dislikes", "I hate traffic and I am sick of it.", "traffic"),
    ("hobby", "I am tired of playing chess.", "chess"),
]
MOOD_OFF = [    # the other ten state words with a mood phrase (D2-1, 7A3)
    ("owns", "I own a red scooter and I am sick of the noise.", "a red scooter"),
    ("lives_in", "I live in Pune and I am fed up with the heat.", "Pune"),
    ("works_at", "I am fed up with my job at Infosys.", "Infosys"),
    ("married_to", "I am married to Asha and I am tired of the commute.", "Asha"),
    ("parent_of", "I am the parent of Arjun and I am tired of the school run.", "Arjun"),
    ("friend_of", "I am a friend of Ravi and I am sick of the gossip.", "Ravi"),
    ("member_of", "I am a member of the Rotary Club and I am tired of the meetings.", "Rotary Club"),
    ("job_title", "I work as a surgeon and I am tired of the night shifts.", "surgeon"),
    ("status", "I am single and I am sick of the questions.", "single"),
    ("number", "I have three cats and I am fed up with the fur.", "three cats"),
]


def test_the_reach_tables_cover_the_vocabulary_exactly():
    """13 state words, 17 event words and plans: the 31 words, each once."""
    from engram_knowledge.normalizer import PREDICATE_TYPES
    events = {w for w, kind in PREDICATE_TYPES.items() if kind == "event"}
    states = set(PREDICATE_TYPES) - events - {"plans"}
    assert len(PREDICATE_TYPES) == 31 and len(events) == 17 and len(states) == 13
    assert {r[0] for r in STATE_DAY} == states and {r[0] for r in EVENT_DAY} == events | {"plans"}
    assert {r[0] for r in MOOD_ON} == {"likes", "dislikes", "hobby"} and {r[0] for r in MOOD_OFF} == states - {"likes", "dislikes", "hobby"}


@pytest.mark.parametrize("word,text,obj", STATE_DAY, ids=[r[0] for r in STATE_DAY])
def test_reach_held_a_day_marker_holds_every_state_word(mem, word, text, obj):
    _, out = mem.file(text, "I", obj, word)
    assert mem.result(out) == HELD and PASSING in out.reasons


@pytest.mark.parametrize("word,text,obj", EVENT_DAY, ids=[r[0] for r in EVENT_DAY])
def test_reach_control_a_day_marker_never_holds_an_event_word_or_a_plan(mem, word, text, obj):
    _, out = mem.file(text, "I", obj, word)
    assert mem.result(out) == IN


@pytest.mark.parametrize("word,text,obj", MOOD_ON, ids=[r[0] for r in MOOD_ON])
def test_reach_held_a_mood_phrase_holds_likes_dislikes_and_hobby(mem, word, text, obj):
    _, out = mem.file(text, "I", obj, word)
    assert mem.result(out) == HELD and PASSING in out.reasons


@pytest.mark.parametrize("word,text,obj", MOOD_OFF, ids=[r[0] for r in MOOD_OFF])
def test_reach_control_a_mood_phrase_never_holds_another_state_word(mem, word, text, obj):
    _, out = mem.file(text, "I", obj, word)
    assert mem.result(out) == IN


def test_reach_control_a_day_marker_never_holds_a_fact_outside_the_vocabulary(mem):
    """I1-5: "I ran 5 km today", filed by its wording, is stored as today."""
    _, out = mem.file("I ran 5 km today.", "I", "5 km", "other")
    assert mem.result(out) == OUTSIDE


# ------------------------------------------------------------------ marker forms
FORMS = [   # rule's reason, sentence, subject, object, word
    (CONDITION, "IF I get the job, I will move to Pune.", "I", "Pune", "moved_to"),
    (CONDITION, "I will move to Pune, if I get the job.", "I", "Pune", "moved_to"),
    (CONDITION, "I will move to Pune if, as planned, I get the job.", "I", "Pune", "moved_to"),
    (CONDITION, "I will move to Pune as long as the offer stands.", "I", "Pune", "moved_to"),
    (CONDITION, "Provided that the visa comes, I will move to Pune.", "I", "Pune", "moved_to"),
    (CONDITION, "Assuming the visa comes, I will move to Pune.", "I", "Pune", "moved_to"),
    (CONDITION, "Suppose the visa comes, then I will move to Pune.", "I", "Pune", "moved_to"),
    (NEAR_MISS, "Almost bought a house in Goa, I did.", "I", "a house in Goa", "owns"),
    (NEAR_MISS, "I bought a house in Goa, almost.", "I", "a house in Goa", "owns"),
    (NEAR_MISS, "I NEARLY bought a house in Goa.", "I", "a house in Goa", "owns"),
    (PASSING, "Today I work at the Whitefield office.", "I", "Whitefield office", "works_at"),
    (PASSING, "I work at the Whitefield office This Morning.", "I", "Whitefield office", "works_at"),
    (PASSING, "I work at the Whitefield office tonight, sadly.", "I", "Whitefield office", "works_at"),
    (OPINION, "IN MY VIEW the new metro line is badly planned.", "the new metro line", "badly planned", "other"),
    (OPINION, "The new metro line is badly planned, I believe.", "the new metro line", "badly planned", "other"),
    (OPINION, "It seems the new metro line is badly planned.", "the new metro line", "badly planned", "other"),
]


@pytest.mark.parametrize("reason,text,subject,obj,word", FORMS, ids=[f"{i:02d}" for i in range(len(FORMS))])
def test_forms_a_marker_is_found_in_capitals_and_anywhere_in_the_sentence(mem, reason, text, subject, obj, word):
    _, out = mem.file(text, subject, obj, word)
    assert mem.result(out) == HELD and reason in out.reasons


# ------------------------------------------------------------------ two rules at once
def test_two_rules_a_conditional_near_miss_carries_both_reasons(mem):
    _, out = mem.file("If the price drops, I almost bought a house in Goa.", "I", "a house in Goa", "owns")
    assert mem.result(out) == HELD and CONDITION in out.reasons and NEAR_MISS in out.reasons


def test_two_rules_a_negated_conditional_keeps_the_old_reason_and_gains_the_new_one(mem):
    """No existing check is removed or weakened (section 3)."""
    _, out = mem.file("If I do not get the job, I will not move to Pune.", "I", "Pune", "moved_to")
    assert mem.result(out) == HELD and "the source may negate this" in out.reasons and CONDITION in out.reasons


# ------------------------------------------------------------------ S6: counting separators
SEPARATORS = [  # sentence, object, word, wanted
    ("I like tea & coffee.", "tea & coffee", "likes", HELD),
    ("I like tea plus coffee.", "tea plus coffee", "likes", HELD),
    ("I like tea as well as coffee.", "tea as well as coffee", "likes", HELD),
    ("I like tea; coffee.", "tea; coffee", "likes", HELD),                 # Amendment 1 to the Increment 1 text (TF-1)
    ("I own 1,200 books and a piano.", "1,200 books and a piano", "owns", HELD),   # BF-2a: the comma between digits is not counted
    ("I like tea; coffee; juice.", "tea; coffee; juice", "likes", REFUSED),
    ("I like tea, coffee and juice.", "tea, coffee and juice", "likes", REFUSED),
    ("I like tea and coffee or juice.", "tea and coffee or juice", "likes", REFUSED),
]
NOT_SEPARATORS = [  # sentence, object, word: one thing, stored as today
    ("I like tea, coffee.", "tea, coffee", "likes"),            # a single comma is one thing (7A2)
    ("I live in Anderson.", "Anderson", "lives_in"),            # "and" inside a word
    ("I like sandy beaches.", "sandy beaches", "likes"),        # "and" inside a word
    ("I like oranges.", "oranges", "likes"),                    # "or" inside a word
    ("I own 12,500 stamps.", "12,500 stamps", "owns"),          # a comma between digits
]


@pytest.mark.parametrize("text,obj,word,wanted", SEPARATORS, ids=[r[1] for r in SEPARATORS])
def test_separators_counted(mem, text, obj, word, wanted):
    _, out = mem.file(text, "I", obj, word)
    assert mem.result(out) == wanted and (PAIR if wanted == HELD else LIST) in out.reasons


@pytest.mark.parametrize("text,obj,word", NOT_SEPARATORS, ids=[r[1] for r in NOT_SEPARATORS])
def test_separators_control_one_thing_is_stored(mem, text, obj, word):
    _, out = mem.file(text, "I", obj, word)
    assert mem.result(out) == IN


# ------------------------------------------------------------------ E: each general cue alone, and with each specific word
GENERAL_ALONE = [   # sentence, object
    ("I start at Manipal on Monday.", "Manipal"),
    ("I started at Manipal in 2020.", "Manipal"),
    ("I have a new desk at Manipal.", "Manipal"),
    ("I joined Manipal in 2020.", "Manipal"),
]
WITH_SPECIFIC = [   # the specific word, sentence, object
    ("job", "I started a job at Apollo.", "Apollo"),
    ("hired", "I started at Apollo after I was hired.", "Apollo"),
    ("work", "I started work at Apollo.", "Apollo"),
    ("working", "I started working at Apollo.", "Apollo"),
    ("employed", "I started at Apollo, where I am employed.", "Apollo"),
    ("position", "I started in a position at Apollo.", "Apollo"),
    ("role", "I started in a role at Apollo.", "Apollo"),
    ("career", "I started my career at Apollo.", "Apollo"),
    ("company", "I joined the company Apollo in 2020.", "Apollo"),
]


@pytest.mark.parametrize("text,obj", GENERAL_ALONE, ids=["start", "started", "new", "joined"])
def test_general_cue_alone_does_not_support_started_job(mem, text, obj):
    _, out = mem.file(text, "I", obj, "started_job")
    assert mem.result(out) == OUTSIDE


@pytest.mark.parametrize("specific,text,obj", WITH_SPECIFIC, ids=[r[0] for r in WITH_SPECIFIC])
def test_general_cue_control_with_a_specific_word_started_job_is_kept(mem, specific, text, obj):
    _, out = mem.file(text, "I", obj, "started_job")
    assert mem.result(out) == IN


def test_general_cue_control_no_other_word_s_cue_list_changes(mem):
    """4.6: only started_job is tightened. "I started learning chess" still supports started_hobby on "started" alone."""
    _, out = mem.file("I started learning chess in 2020.", "I", "chess", "started_hobby")
    assert mem.result(out) == IN


# ------------------------------------------------------------------ G8: the writer's prompt
EXISTING = "A line may state more than one fact: give each its own entry."
SENTENCE = 'When a line lists several things, such as "tea, coffee and juice", give each thing its own entry and never put the list in one object.'
PROMPT_BEFORE = "0591e35e2af87bad8619942c140e29f56948a3dfad4c9a7b5ec78a0e65523eab"   # SHA-256 of WRITER_PROMPT at 4e8fa6e


def test_prompt_the_approved_sentence_follows_the_existing_one(mem):
    assert S.WRITER_PROMPT.count(SENTENCE) == 1
    assert EXISTING + " " + SENTENCE + " " in S.WRITER_PROMPT


def test_prompt_nothing_else_in_the_prompt_changed():
    """Taking the one sentence out again gives the prompt of 4e8fa6e, character for character."""
    assert SENTENCE in S.WRITER_PROMPT
    without = S.WRITER_PROMPT.replace(" " + SENTENCE, "", 1)
    assert hashlib.sha256(without.encode()).hexdigest() == PROMPT_BEFORE


def test_prompt_control_the_existing_sentence_is_still_there():
    assert S.WRITER_PROMPT.count(EXISTING) == 1
