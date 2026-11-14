"""Step 3a, the habitual-sentence problem: attended, visited and completed are sent to ERC as completed happenings, so the
shared checker lets a sentence support one of them only when the sentence states a completed happening.

The rule (fixed lists, written out in full; no model judges):
  - the sentence that holds the object uses a completed form of the word
        attended   attended, went, or the phrase "was there for"      visited   visited, went, travelled, traveled
        completed  completed, finished, graduated, done
    "was" alone is not a completed form: "I was sick" and "I was at home" say nothing of attendance.
  - and it has no word that makes it a habit (every, each, weekly, usually, often, on "Sundays" ...)
  - and no word that puts it still to come (will, gonna, tomorrow, next, upcoming, plan, planning, intend, "going to").
A sentence that fails it is a doubt, with the reason "the source does not state a completed happening":
  classic  the candidate goes to review; nothing is stored
  base 2   the word is held (RM-a): the fact is stored by its wording, outside the vocabulary (WP-1)
Only these three words are checked. The other 14 event words, and every state word, are read exactly as before.

Made-up people only. No model is called.
"""
import json

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge import fact_validator as V
from engram_knowledge.fact_validator import ACCEPTED, UNCERTAIN, Candidate, KnowledgePipeline
from engram_knowledge.normalizer import PREDICATE_TYPES
from engram_knowledge.transition import slot_of
from engram_records import KnowledgeBase

SAID = "2:15 pm on 12 June, 2025"
REASON = "the source does not state a completed happening"
NEW = ("attended", "visited", "completed")


class Mem:
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.layer = S.StructureLayer(self.m.db)
        self.pipe = KnowledgePipeline(self.m.db)

    def say(self, text, speaker="User"):
        self.m.open_chat(SAID)
        sid = self.m.add(speaker, text, date=SAID)
        self.m.close_chat(write_note=False)
        return sid

    def classic(self, text, word, obj, when=""):
        return self.pipe.process(Candidate("I", word, obj, (self.say(text),), when, "step 3a test", "1"))[0]

    def base2(self, text, word, obj):
        picked, kind = S.gate("User", text, SAID)
        assert picked, f"the gate stopped {text!r}"
        return self.layer.file(self.say(text), "I", obj, kind, word=word)

    def records(self):
        return [(p, json.loads(meta or "{}")) for p, meta in self.m.db.execute("SELECT predicate, metadata FROM knowledge_records ORDER BY recorded_at, fact_id")]

    def reviews(self):
        return self.m.db.execute("SELECT count(*) FROM review_queue").fetchone()[0]


@pytest.fixture
def mem(tmp_path):
    w = Mem(tmp_path)
    yield w
    w.m.close()


HAPPENED = [
    ("I attended a half marathon on 25 February 2023.", "attended", "half marathon"),
    ("I attended the cardiology conference.", "attended", "cardiology conference"),
    ("I went to the cardiology conference.", "attended", "cardiology conference"),
    ("I was there for the Pune meetup.", "attended", "Pune meetup"),
    ("I have attended two workshops on suturing.", "attended", "workshops"),
    ("I visited Hampi in January 2023.", "visited", "Hampi"),
    ("I have visited Hampi with my cousin.", "visited", "Hampi"),
    ("I went to Hampi with my cousin.", "visited", "Hampi"),
    ("I travelled to Hampi with my cousin.", "visited", "Hampi"),
    ("I completed my MBA in 2019.", "completed", "MBA"),
    ("I finished the Kaveri trail.", "completed", "Kaveri trail"),
    ("I graduated from the nursing course.", "completed", "nursing course"),
    ("I am done with the nursing course.", "completed", "nursing course"),
]
HABIT = [
    ("I visit my mother every Sunday.", "visited", "mother"),
    ("I attend the cycling club every week.", "attended", "cycling club"),
    ("I go to the temple every morning.", "attended", "temple"),
    ("I usually visit Mysore in December.", "visited", "Mysore"),
    ("I have attended the cycling club every week since 2020.", "attended", "cycling club"),
    ("I often go to the gym near my house.", "attended", "gym"),
    ("I visit Mysore regularly.", "visited", "Mysore"),
    ("I attend church on Sundays.", "attended", "church"),
    ("I visit my mother weekly.", "visited", "mother"),
    ("I went to Hampi each summer as a child.", "visited", "Hampi"),
    ("I always finished the Kaveri trail first.", "completed", "Kaveri trail"),
    ("I complete a marathon every year.", "completed", "marathon"),
]
STILL_TO_COME = [
    ("I am going to attend the conference next month.", "attended", "conference"),
    ("I will visit Hampi in January 2027.", "visited", "Hampi"),
    ("I plan to visit Hampi with my cousin.", "visited", "Hampi"),
    ("I am gonna finish the Kaveri trail.", "completed", "Kaveri trail"),
    ("I attend the conference tomorrow.", "attended", "conference"),
    ("I am going to get the Kaveri trail done.", "completed", "Kaveri trail"),
    # a completed form is there, and only the word that puts it still to come holds it
    ("By next year I will have completed my MBA.", "completed", "MBA"),
    ("I will have visited Hampi by December.", "visited", "Hampi"),
]
GOING_ON = [
    ("I am attending a course at IIM.", "attended", "course"),
    ("I am visiting my mother this week.", "visited", "mother"),
    ("I am completing my MBA at IIM.", "completed", "MBA"),
    ("I visit my mother in Mysore.", "visited", "mother"),
    ("I attend St Mary's church.", "attended", "church"),
]
# "was" alone is not attendance (S3a-9, his refinement): each sentence has "was" and names an event or a place, and none says he attended
WAS_ALONE = [
    ("I was sick during the Pune meetup.", "attended", "Pune meetup"),
    ("I was at home during the cardiology conference.", "attended", "cardiology conference"),
    ("I was at home.", "attended", "home"),
    ("I was at the cardiology conference.", "attended", "cardiology conference"),
    ("I was busy on the day of the Pune meetup.", "attended", "Pune meetup"),
    ("I was the organiser of the Pune meetup.", "attended", "Pune meetup"),
    ("I was planning to attend the cardiology conference.", "attended", "cardiology conference"),
    ("I was there every week for the Pune meetup.", "attended", "Pune meetup"),
]
NOT_ONE = HABIT + STILL_TO_COME + GOING_ON + WAS_ALONE


def ids(rows):
    return [r[0] for r in rows]


# ---------------------------------------------------------------- the classic writer (the shared checker in fixed-list mode)
@pytest.mark.parametrize("text, word, obj", HAPPENED, ids=ids(HAPPENED))
def test_classic_a_completed_happening_is_accepted_under_its_word(mem, text, word, obj):
    d = mem.classic(text, word, obj)
    assert d.verdict == ACCEPTED and d.reasons == ()
    assert [p for p, _ in mem.records()] == [word]


@pytest.mark.parametrize("text, word, obj", NOT_ONE, ids=ids(NOT_ONE))
def test_classic_a_habit_a_plan_or_something_going_on_goes_to_review_and_nothing_is_stored(mem, text, word, obj):
    d = mem.classic(text, word, obj)
    assert d.verdict == UNCERTAIN and REASON in d.reasons
    assert mem.records() == [] and mem.reviews() == 1


# ---------------------------------------------------------------- base 2
@pytest.mark.parametrize("text, word, obj", HAPPENED, ids=ids(HAPPENED))
def test_base2_a_completed_happening_is_filed_under_its_word(mem, text, word, obj):
    out = mem.base2(text, word, obj)
    assert out.verdict == ACCEPTED and out.reasons == ()
    ((predicate, meta),) = mem.records()
    assert predicate == word and meta["vocabulary"] == "in"


@pytest.mark.parametrize("text, word, obj", NOT_ONE, ids=ids(NOT_ONE))
def test_base2_a_habit_a_plan_or_something_going_on_is_kept_by_its_wording_outside_the_vocabulary(mem, text, word, obj):
    """RM-a: the word is held, the fact is kept (WP-1). It is never stored under an event word."""
    out = mem.base2(text, word, obj)
    assert out.verdict == ACCEPTED and out.reasons == (f"word held: {REASON}",)
    ((predicate, meta),) = mem.records()
    assert meta["vocabulary"] == "outside" and predicate == meta["wording"] == S.version_key(text, obj)
    assert predicate not in PREDICATE_TYPES and slot_of(predicate) is None


def test_base2_the_held_fact_keeps_the_type_the_gate_gives_it_never_event(mem):
    """D10: a fact outside the vocabulary keeps the type base 2's gate assigns."""
    for text, word, obj in (HABIT[0], STILL_TO_COME[1], GOING_ON[0]):
        mem.base2(text, word, obj)
    types = [t for (t,) in mem.m.db.execute("SELECT fact_type FROM knowledge_records ORDER BY recorded_at, fact_id")]
    assert len(types) == 3 and "event" not in types


# ---------------------------------------------------------------- the rule's edges
def test_only_the_sentence_that_holds_the_object_is_read(mem):
    """A message can hold many sentences. A habit in another sentence does not hold the word, and a completed form in another
    sentence does not supply one."""
    assert mem.classic("I visited Hampi with my cousin. I go to the gym every day.", "visited", "Hampi").verdict == ACCEPTED
    d = mem.classic("I visit my mother in Mysore. I went to the gym.", "visited", "mother")
    assert d.verdict == UNCERTAIN and REASON in d.reasons


@pytest.mark.parametrize("text, word, obj", [
    ("I buy vegetables every Sunday.", "bought", "vegetables"), ("I will buy a car next month.", "bought", "car"),
    ("I move house every year.", "moved_to", "house"), ("I join a new gym every January.", "joined", "gym"),
    ("I work at Apollo every day.", "works_at", "Apollo"), ("I usually live in Pune.", "lives_in", "Pune"),
    ("I play chess every evening.", "hobby", "chess"), ("I will always love filter coffee.", "likes", "filter coffee")])
def test_only_the_three_words_are_checked_and_every_other_word_is_read_as_before(mem, text, word, obj):
    """Scope. The 14 slot events were fixed as completed happenings by the frozen B2b specification; that is not reopened here."""
    d = mem.classic(text, word, obj)
    assert REASON not in d.reasons and d.verdict == ACCEPTED


def test_the_other_doubts_still_apply(mem):
    """The new reason is one doubt among the others: a negated or hypothetical sentence is still a doubt, with or without it."""
    d = mem.classic("I never completed my PhD.", "completed", "PhD")
    assert d.verdict == UNCERTAIN and "the source may negate this" in d.reasons and REASON not in d.reasons
    d = mem.classic("I wish I had visited Hampi.", "visited", "Hampi")
    assert d.verdict == UNCERTAIN and "the source may be hypothetical" in d.reasons
    out = mem.base2("I never completed my PhD.", "completed", "PhD")
    assert out.verdict == UNCERTAIN and out.fact_id is None


def test_a_sentence_with_no_word_for_the_fact_gives_both_reasons_and_base_2_reports_the_first(mem):
    d = mem.classic("I ran a half marathon.", "attended", "half marathon")
    assert d.reasons == ("nothing in the source says attended", REASON)
    out = mem.base2("I ran a half marathon.", "attended", "half marathon")
    assert out.reasons == ("word held: nothing in the source says attended",) and mem.records()[-1][1]["vocabulary"] == "outside"


def test_the_open_predicate_checker_is_untouched(mem):
    """Base 2's own check (wordings, not the fixed list) never applies the rule: only its word check does."""
    sid = mem.say("I visit my mother every Sunday.")
    verdict, reasons, _ = mem.layer.check(sid, "I", "mother")
    assert verdict == ACCEPTED and reasons == ()


def test_the_lists_are_pinned():
    """Fixed lists, written out in full. A word cannot be added to or taken from them without a decision."""
    assert V.COMPLETED_FORMS == {"attended": {"attended", "went"}, "visited": {"visited", "went", "travelled", "traveled"},
                                 "completed": {"completed", "finished", "graduated", "done"}}
    assert V.COMPLETED_PHRASES == {"attended": ("was there for",)}
    assert not any("was" in forms for forms in V.COMPLETED_FORMS.values())
    assert set(V.COMPLETED_FORMS) == set(NEW) == {w for w, t in PREDICATE_TYPES.items() if t == "event" and slot_of(w) is None}
    assert V.RECURRING == set("every each daily weekly monthly yearly annually usually often regularly always sometimes generally normally "
                              "occasionally frequently routinely weekends weekdays mornings evenings nights "
                              "mondays tuesdays wednesdays thursdays fridays saturdays sundays".split())
    assert V.NOT_YET == set("will gonna tomorrow next upcoming plan planning intend".split())
    assert V.NOT_COMPLETED == REASON
