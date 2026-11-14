"""Step 3a (writing layer contract v1, section 6 step 4a; Amendment 2 R1, guarantees C11 and C14; Amendment 4, 4A5 and 4A18).

Part A, the event list. The adapter counts every vocabulary word typed as an event: the 14 that open or close a slot, and
the three that have no slot (attended, visited, completed). A fact under one of the three is sent as an occurrence, never
as a state that is still going (the end-to-end test's C12).
  - A stated date is the window it happened in.
  - A fact that was only said happened no later than the day it was told. The said day is never its start, and it is
    never given an earlier date than Engram holds (frozen B2b specification, section 6: an upper bound only).
  - The exact set is pinned: a word cannot join it, or leave it, without a decision.

Part B, the outside-vocabulary marker. A record the writer marked `metadata.vocabulary = outside` is stored and is not
played in any slot and not sent to ERC. It is told by the marker alone, never by reading the predicate's text: a wording can
equal a vocabulary word ("likes"), and such a record must not enter that word's slot. A record with no marker (the classic
path, and base 2 records written before WR-BC) behaves as before.

Both writers are run from the sentence where a writer is involved:
  base2    engram_structure.StructureLayer.file    the writer under test
  classic  engram_knowledge KnowledgePipeline      the control; it writes no marker
Made-up people only. No model is called: the proposals are hand-written.
"""
import datetime as dt

import pytest

import engram_chat as E
import engram_structure as S
import erc_overlay.knowledge as overlay_knowledge
from engram_erc import Occurrence
from engram_knowledge import StateEngine
from engram_knowledge.fact_validator import Candidate, KnowledgePipeline
from engram_knowledge.normalizer import PREDICATE_TYPES
from engram_knowledge.transition import CLOSES, OPENS, slot_of
from engram_records import Entity, FactEvidence, FactWithEvidence, KnowledgeBase, KnowledgeFact
from erc_overlay import KnowledgeAdapter, Reasoner

UTC = dt.timezone.utc
DAY = "1:00 pm on 5 March, 2024"                       # every hand-filed sentence is said on 5 March 2024
SAID_FIRST = dt.datetime(2024, 3, 5, tzinfo=UTC)
SAID_END = dt.datetime(2024, 3, 5, 23, 59, 59, 999999, tzinfo=UTC)
AS_OF = dt.datetime(2024, 6, 1, tzinfo=UTC)
NEW = ("attended", "visited", "completed")             # the three event words with no slot
SLOT_EVENTS = ("started_job", "moved_to", "got_married", "bought", "adopted", "started_hobby", "joined",
               "left_job", "divorced", "sold", "lost", "gave_away", "stopped_hobby", "left_group")
OUTSIDE = "outside the vocabulary"
BASE2, CLASSIC = "base2", "classic"


def U(*parts):
    return dt.datetime(*parts, tzinfo=UTC)


class World:
    """One memory with hand-filed facts: the adapter's and the state engine's side, with no writer in the way."""

    def __init__(self, path):
        self.m = E.ChatMemory(path, durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.engine = StateEngine(self.kb)

    def who(self, name):
        return self.kb.resolve(name) or self.kb.add_entity(Entity.create(name, "person")).entity_id

    def say(self, speaker, text, date=DAY):
        self.m.open_chat(DAY)
        sid = self.m.add(speaker, text, date=date)
        self.m.close_chat(write_note=False)
        return sid

    def fact(self, subject, predicate, value, valid_from=None, valid_to=None, marker=None, fact_type="attribute", date=DAY, role="supports",
             engine=True, status="active"):
        """Files one fact. `marker` is metadata.vocabulary ("in", "outside") or None for a record that has no marker at all.
        `engine=False` stores it as base 2 does, straight into the store, without the state engine's own filing."""
        sid = self.say(subject, f"{subject} {predicate} {value}.", date)
        meta = None if marker is None else dict(vocabulary=marker, wording=f"{predicate} _")
        f = KnowledgeFact.create(self.who(subject), predicate, "text", fact_type, "explicit", object_value=value, valid_from=valid_from,
                                 valid_to=valid_to, validation_status="accepted", metadata=meta)
        record = FactWithEvidence(f, (FactEvidence.create(f.fact_id, sid, role),))
        (self.engine.apply_observation if engine else self.kb.add)(record)
        if status != "active": self.kb.set_status(f.fact_id, status)
        return f.fact_id

    def sent(self, as_of=AS_OF, who="Asha", hops=1):
        a = KnowledgeAdapter(self.kb).request_for(who, as_of=as_of, hops=hops)
        return a, {p.id[5:]: p for p in a.request.propositions}


@pytest.fixture
def world(tmp_path):
    w = World(str(tmp_path / "m.db"))
    yield w
    w.m.close()


def reasons(a):
    return {l.fact_id: (l.reason, l.needs) for l in a.left_out}


# ================================================================ Part A: the event list
def test_a1_the_event_list_is_exactly_the_vocabularys_event_words_and_is_pinned():
    """Step 4a: "the adapter counts every vocabulary word typed as an event". The exact set is named here, so that a word
    cannot receive an occurrence, or the said-day bound, without a decision (the frozen B2b specification's rule, F32)."""
    assert overlay_knowledge.EVENTS == frozenset(SLOT_EVENTS + NEW)
    assert len(overlay_knowledge.EVENTS) == 17
    assert overlay_knowledge.EVENTS == frozenset(w for w, t in PREDICATE_TYPES.items() if t == "event")


def test_a2_every_word_that_opens_or_closes_another_words_slot_is_still_an_event_and_no_state_word_is():
    """Nothing is lost from B2b's 14: the words whose slot is another word. A word that names its own slot is a state."""
    moving = frozenset(p for p, s in {**OPENS, **CLOSES}.items() if p != s)
    assert moving == frozenset(SLOT_EVENTS) and moving <= overlay_knowledge.EVENTS
    assert overlay_knowledge.EVENTS - moving == frozenset(NEW)
    assert all(slot_of(w) is None for w in NEW)
    states = {p for p, s in OPENS.items() if p == s} | {"plans", "number"}
    assert not states & overlay_knowledge.EVENTS


@pytest.mark.parametrize("word", NEW)
@pytest.mark.parametrize("stated, first, last", [("2023-02-25", U(2023, 2, 25), U(2023, 2, 25, 23, 59, 59, 999999)),
                                                 ("2023-02", U(2023, 2, 1), U(2023, 2, 28, 23, 59, 59, 999999)),
                                                 ("2023", U(2023, 1, 1), U(2023, 12, 31, 23, 59, 59, 999999))])
def test_a3_a_stated_date_is_the_window_the_event_happened_in(world, word, stated, first, last):
    """C12. The whole of the stated day, month or year, labelled stated; never a period, never "still going"."""
    fid = world.fact("Asha", word, "Hampi", valid_from=stated)
    _, props = world.sent()
    p = props[fid]
    assert p.qualifiers["time_kind"] == "event" and p.valid_time is None
    assert p.occurred == Occurrence(first, last)
    assert p.qualifiers["start_basis"] == "stated" and "end_basis" not in p.qualifiers and p.qualifiers["valid_time"] == "known"


@pytest.mark.parametrize("word", NEW)
def test_a4_an_event_only_said_happened_no_later_than_the_day_it_was_told_and_gets_no_earlier_date(world, word):
    """The frozen B2b rule, now for all 17: the said day is the latest the event can have happened. It is never the day it
    happened, never a start, and no earliest date is given: an event reported later acquires no date Engram does not hold."""
    fid = world.fact("Asha", word, "Hampi")
    _, props = world.sent()
    p = props[fid]
    assert p.occurred == Occurrence(None, SAID_END)
    assert p.occurred.earliest is None and p.valid_time is None
    assert p.qualifiers["time_kind"] == "event" and p.qualifiers["start_basis"] == "first_said"


@pytest.mark.parametrize("word", NEW)
def test_a5_an_event_only_said_is_left_out_when_asked_about_a_moment_before_it_was_told(world, word):
    """The guard reads Engram's dates: the fact is known only from the day it was said."""
    fid = world.fact("Asha", word, "Hampi")
    a, props = world.sent(as_of=U(2024, 3, 4))
    assert fid not in props and reasons(a)[fid] == ("starts after as_of", "a later as_of")
    _, props = world.sent(as_of=SAID_FIRST)
    assert fid in props


@pytest.mark.parametrize("word", NEW)
def test_a6_with_no_stated_date_and_no_readable_said_day_the_time_is_unknown_and_nothing_is_invented(world, word):
    fid = world.fact("Asha", word, "Hampi", date="sometime")
    a, props = world.sent()
    p = props[fid]
    assert p.occurred is None and p.valid_time is None and p.qualifiers["valid_time"] == "unknown" and p.qualifiers["time_kind"] == "event"
    assert next(e for e in a.request.evidence if e.id == f"state:{fid}").metadata["qualified_for"] == ("valid time unknown",)


@pytest.mark.parametrize("word", NEW)
def test_a7_a_plan_is_left_out_and_a_sentence_that_only_qualifies_gives_no_bound(world, word):
    """B2b's conditions 2 and 3 hold for the three words as for the 14."""
    planned = world.fact("Asha", word, "Goa", fact_type="plan")
    qualified = world.fact("Asha", word, "Hampi", date="sometime")
    world.kb.add_evidence(FactEvidence.create(qualified, world.say("Ravi", "Asha went to Hampi, I think."), "qualifies"))
    a, props = world.sent()
    assert reasons(a)[planned] == ("plan", "none") and planned not in props
    assert props[qualified].occurred is None and props[qualified].qualifiers["valid_time"] == "unknown"


@pytest.mark.parametrize("word", NEW)
def test_a8_an_event_stays_in_at_every_later_moment_and_is_never_sent_as_a_state(world, word):
    """Nothing that is sent depends on as_of, and an occurrence has no end to fall before it."""
    fid = world.fact("Asha", word, "Hampi", valid_from="2023-02-25")
    for as_of in (U(2023, 2, 25), U(2023, 3, 1), U(2030, 1, 1)):
        a, props = world.sent(as_of=as_of)
        assert props[fid].occurred == Occurrence(U(2023, 2, 25), U(2023, 2, 25, 23, 59, 59, 999999)) and props[fid].valid_time is None
    a, props = world.sent(as_of=U(2023, 2, 24))
    assert fid not in props and reasons(a)[fid][0] == "starts after as_of"


def test_a9_the_three_words_have_no_slot_no_period_and_cannot_conflict(world):
    """They are events outside every slot: the state engine builds nothing for them, and two of them are never a conflict."""
    for word, value in (("visited", "Hampi"), ("visited", "Mysore"), ("attended", "meetup"), ("completed", "MBA")):
        world.fact("Asha", word, value, valid_from="2023")
    assert world.engine.get_current_state(world.who("Asha")) == {}
    assert not set(NEW) & overlay_knowledge.FUNCTIONAL
    r = Reasoner(world.kb).reason("Asha", as_of=AS_OF)
    assert list(r.orchestration.contradictions) == []


def test_a10_the_order_of_two_such_events_can_be_decided_from_what_is_sent(world):
    first, second = world.fact("Asha", "attended", "half marathon", valid_from="2023-02-25"), world.fact("Asha", "completed", "MBA", valid_from="2023-06")
    _, props = world.sent()
    assert props[first].occurred.latest < props[second].occurred.earliest


def test_a11_explain_reads_such_a_fact_as_an_event(world):
    world.fact("Asha", "attended", "half marathon", valid_from="2023-02-25"); world.fact("Asha", "visited", "Hampi")
    r = Reasoner(world.kb)
    lines = "\n".join(r.explain(r.reason("Asha", as_of=AS_OF)))
    assert "fact: Asha attended half marathon;" in lines and "event on 2023-02-25" in lines and "time: event stated 2023-02-25" in lines
    assert "event by 2024-03-05" in lines and "time: event not stated (first said 2024-03-05)" in lines
    assert "still going" not in lines


def test_a12_the_14_slot_events_are_sent_as_before(world):
    """The change adds three words. A slot event with a stated date, and one only said, are sent exactly as B2b sends them."""
    dated, said = world.fact("Asha", "moved_to", "Delhi", valid_from="2023-03"), world.fact("Asha", "bought", "car")
    _, props = world.sent()
    assert props[dated].occurred == Occurrence(U(2023, 3, 1), U(2023, 3, 31, 23, 59, 59, 999999))
    assert props[said].occurred == Occurrence(None, SAID_END)
    state = world.fact("Asha", "works_at", "Apollo", valid_from="2021")
    _, props = world.sent()
    assert props[state].qualifiers["time_kind"] == "state" and props[state].occurred is None and props[state].valid_time.end_unbounded


# ================================================================ Part B: the outside-vocabulary marker
def test_b1_the_adapter_leaves_out_a_record_marked_outside_and_says_why(world):
    """C11, R1. Stored, not sent: reported with its reason, its state and what it needs. Nothing about it reaches ERC."""
    inside = world.fact("Asha", "works_at", "Apollo", valid_from="2021", marker="in")
    outside = world.fact("Asha", "i ran", "half marathon", marker="outside", engine=False)
    a, props = world.sent()
    assert set(props) == {inside} and a.fact_ids == (inside,)
    assert reasons(a) == {outside: (OUTSIDE, "a vocabulary word")}
    assert next(l for l in a.left_out if l.fact_id == outside).state == dict(status="active", validation_status="accepted", source_type="explicit")
    assert not any(outside in e.id or outside in str(e.source_ref) for e in a.request.evidence)
    assert world.kb.get(outside).fact.status == "active"                      # still stored, untouched (WP-1)


@pytest.mark.parametrize("word, value", [("likes", "filter coffee"), ("owns", "red Tata Nexon"), ("hobby", "chess"), ("status", "single"),
                                         ("works_at", "Apollo"), ("bought", "car")])
def test_b2_a_wording_that_equals_a_vocabulary_word_does_not_enter_that_words_slot(world, word, value):
    """The slot-bypass case (review finding A9). The record's predicate reads as a vocabulary word; the marker says outside."""
    who = world.who("Asha")
    fid = world.fact("Asha", word, value, marker="outside", engine=False)
    slot = slot_of(word)
    assert world.engine.get_current_state(who) == {}
    assert world.engine.get_state_at(who, "2024") == {}
    history = world.engine.get_history(who, slot)
    assert history["periods"] == [] and history["conflicts"] == []
    assert [x.fact.fact_id for x in history["not_counted"]] == [fid]            # nothing is lost silently
    a, props = world.sent()
    assert props == {} and reasons(a) == {fid: (OUTSIDE, "a vocabulary word")}


@pytest.mark.parametrize("marker, plays", [("outside", False), ("in", True), (None, True)])
def test_b3_the_marker_alone_decides_and_a_record_with_no_marker_behaves_as_before(world, marker, plays):
    """S3a-6. Same subject, predicate and value three times over; only the marker differs. No marker (the classic path, and
    base 2 before WR-BC) is not "outside"."""
    who = world.who("Asha")
    fid = world.fact("Asha", "likes", "filter coffee", marker=marker, engine=False)
    held = [i for p in world.engine.get_history(who, "likes")["periods"] for i in p.fact_ids]
    a, props = world.sent()
    assert (held == [fid]) is plays and (fid in props) is plays
    assert (reasons(a).get(fid) == (OUTSIDE, "a vocabulary word")) is not plays


def test_b4_an_outside_record_does_not_touch_a_vocabulary_facts_period_or_make_a_conflict(world):
    """A single-valued slot: an outside record reading "status" beside a vocabulary status. One period, the vocabulary
    fact's own dates, no conflict in Engram and no contradiction in ERC."""
    who = world.who("Asha")
    inside = world.fact("Asha", "status", "married", valid_from="2020", marker="in")
    before = world.engine.get_history(who, "status")
    outside = world.fact("Asha", "status", "single", marker="outside", engine=False)
    after = world.engine.get_history(who, "status")
    assert [(p.value, p.start, p.end, p.end_kind, p.fact_ids) for p in after["periods"]] == [(p.value, p.start, p.end, p.end_kind, p.fact_ids) for p in before["periods"]]
    assert after["conflicts"] == [] and not world.engine.get_current_state(who)["status"].conflict
    a, props = world.sent()
    assert set(props) == {inside} and props[inside].valid_time.end_unbounded and reasons(a)[outside][0] == OUTSIDE
    assert list(Reasoner(world.kb).reason("Asha", as_of=AS_OF).orchestration.contradictions) == []


def test_b5_an_outside_record_reading_as_a_closing_word_closes_nothing(world):
    who = world.who("Asha")
    car = world.fact("Asha", "owns", "car", valid_from="2020", marker="in")
    world.fact("Asha", "sold", "car", valid_from="2023", marker="outside", engine=False)
    periods = world.engine.get_history(who, "owns")["periods"]
    assert [(p.end, p.end_kind, p.fact_ids) for p in periods] == [(None, "open", [car])]
    _, props = world.sent()
    assert set(props) == {car} and props[car].valid_time.end_unbounded


def test_b6_a_trial_conflict_is_not_run_for_an_outside_record(world):
    world.fact("Asha", "status", "married", valid_from="2020", marker="in")
    f = KnowledgeFact.create(world.who("Asha"), "status", "text", "attribute", "explicit", object_value="single", valid_from="2021",
                             validation_status="accepted", metadata=dict(vocabulary="outside"))
    g = KnowledgeFact.create(world.who("Asha"), "status", "text", "attribute", "explicit", object_value="single", valid_from="2021", validation_status="accepted")
    sid = world.say("Ravi", "Asha status single.")
    assert world.engine.detect_conflict(FactWithEvidence(f, (FactEvidence.create(f.fact_id, sid),))) == []
    assert world.engine.detect_conflict(FactWithEvidence(g, (FactEvidence.create(g.fact_id, sid),))) != []       # the control: no marker


def test_b7_an_outside_record_is_never_a_bridge_to_the_entity_it_names(world):
    """Eligibility is decided inside the walk: a fact that is left out leads nowhere."""
    world.who("Manipal")
    world.fact("Manipal", "located_in", "Bengaluru", valid_from="2010")
    link = world.fact("Asha", "works_at", "Manipal", marker="outside", engine=False)
    a, props = world.sent(hops=2)
    assert props == {} and reasons(a) == {link: (OUTSIDE, "a vocabulary word")}
    world.fact("Asha", "works_at", "Manipal", valid_from="2021", marker="in")
    _, props = world.sent(hops=2)
    assert sorted(p.predicate for p in props.values()) == ["located_in", "works_at"]


@pytest.mark.parametrize("fact_type, status", [("plan", "active"), ("observation", "superseded"), ("event", "active")])
def test_b8_the_marker_is_read_before_anything_else(world, fact_type, status):
    """Whatever else is true of it (a plan, a replaced version, an event wording), the reason given is that it is outside."""
    fid = world.fact("Asha", "visited", "Hampi", valid_from="2023", marker="outside", fact_type=fact_type, engine=False, status=status)
    a, props = world.sent()
    assert props == {} and reasons(a) == {fid: (OUTSIDE, "a vocabulary word")}


def test_b9_explain_lists_the_outside_record_as_left_out(world):
    world.fact("Asha", "works_at", "Apollo", valid_from="2021", marker="in")
    fid = world.fact("Asha", "i ran", "half marathon", marker="outside", engine=False)
    r = Reasoner(world.kb)
    lines = r.explain(r.reason("Asha", as_of=AS_OF))
    assert f"left out: fact {fid} ({OUTSIDE}; status active, validation accepted, source explicit; needs a vocabulary word)" in lines


def test_b10_only_the_exact_value_outside_marks_a_record(world):
    """Any other value of the key, or other metadata, is not the marker."""
    kept = [world.fact("Asha", "likes", v, marker=m, engine=False) for v, m in (("tea", "in"), ("coffee", "Outside"), ("milk", "out"), ("water", ""))]
    f = KnowledgeFact.create(world.who("Asha"), "likes", "text", "preference", "explicit", object_value="juice", validation_status="accepted", metadata=dict(wording="outside"))
    world.kb.add(FactWithEvidence(f, (FactEvidence.create(f.fact_id, world.say("Asha", "Asha likes juice.")),)))
    _, props = world.sent()
    assert set(props) == set(kept) | {f.fact_id}


# ================================================================ from the sentence, on both writers
class Told:
    """One memory. Each message is stored as a sentence said by User, then filed by the chosen writer."""

    def __init__(self, tmp_path, writer, messages):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.outcomes = []
        pipe, layer = KnowledgePipeline(self.m.db), S.StructureLayer(self.m.db)
        for date, text, word, obj, when in messages:
            self.m.open_chat(date)
            sid = self.m.add("User", text, date=date)
            self.m.close_chat(write_note=False)
            if writer == CLASSIC:
                decision, _ = pipe.process(Candidate("I", word, obj, (sid,), when, "step 3a test", "1"))
                self.outcomes.append((decision.verdict, decision.reasons))
            else:
                picked, kind = S.gate("User", text, date)
                assert picked, f"the gate stopped {text!r}"
                out = layer.file(sid, "I", obj, kind, word=word)
                self.outcomes.append((out.verdict, out.reasons))

    def ask(self, as_of):
        who = self.kb.resolve("User")
        return KnowledgeAdapter(self.kb).request_for(who, as_of=as_of) if who else None

    def stored(self):
        return [(p, __import__("json").loads(meta or "{}").get("vocabulary")) for p, meta in
                self.m.db.execute("SELECT predicate, metadata FROM knowledge_records ORDER BY recorded_at, fact_id")]


SAID = "2:15 pm on 3 March, 2023"
SAID_LAST = U(2023, 3, 3, 23, 59, 59, 999999)
HAPPENED = [  # sentence, word, object, classic's stated time, (earliest, latest) of the occurrence that must be sent
    ("I attended a half marathon on 25 February 2023.", "attended", "half marathon", "25 February 2023", (U(2023, 2, 25), U(2023, 2, 25, 23, 59, 59, 999999))),
    ("I attended the cardiology conference.", "attended", "cardiology conference", "", (None, SAID_LAST)),
    ("I went to the cardiology conference.", "attended", "cardiology conference", "", (None, SAID_LAST)),
    ("I visited Hampi in January 2023.", "visited", "Hampi", "January 2023", (U(2023, 1, 1), U(2023, 1, 31, 23, 59, 59, 999999))),
    ("I visited my cousin in Hampi.", "visited", "Hampi", "", (None, SAID_LAST)),
    ("I completed my MBA in 2019.", "completed", "MBA", "2019", (U(2019, 1, 1), U(2019, 12, 31, 23, 59, 59, 999999))),
    ("I finished the Kaveri trail.", "completed", "Kaveri trail", "", (None, SAID_LAST)),
]
NOT_HAPPENED = [  # sentence, word, object: a habit, something still to come, or something still going on
    ("I visit my mother every Sunday.", "visited", "mother"),
    ("I attend the cycling club every week.", "attended", "cycling club"),
    ("I go to the temple every morning.", "attended", "temple"),
    ("I usually visit Mysore in December.", "visited", "Mysore"),
    ("I have attended the cycling club every week since 2020.", "attended", "cycling club"),
    ("I attend church on Sundays.", "attended", "church"),
    ("I visit my mother weekly.", "visited", "mother"),
    ("I am going to attend the conference next month.", "attended", "conference"),
    ("I will visit Hampi in January 2027.", "visited", "Hampi"),
    ("I am attending a course at IIM.", "attended", "course"),
    ("I am visiting my mother this week.", "visited", "mother"),
]


@pytest.mark.parametrize("writer", [BASE2, CLASSIC])
@pytest.mark.parametrize("text, word, obj, when, window", HAPPENED, ids=[h[0] for h in HAPPENED])
def test_e1_a_completed_happening_is_filed_under_its_word_and_sent_as_an_event(tmp_path, writer, text, word, obj, when, window):
    w = Told(tmp_path, writer, [(SAID, text, word, obj, when)])
    try:
        assert w.outcomes == [("accepted", ())]
        assert w.stored() == [(word, "in" if writer == BASE2 else None)]
        a = w.ask(U(2024, 1, 1))
        (p,) = a.request.propositions
        assert p.predicate == word and p.qualifiers["time_kind"] == "event" and p.valid_time is None
        assert (p.occurred.earliest, p.occurred.latest) == window
        assert a.left_out == ()
    finally:
        w.m.close()


@pytest.mark.parametrize("writer", [BASE2, CLASSIC])
@pytest.mark.parametrize("text, word, obj", NOT_HAPPENED, ids=[h[0] for h in NOT_HAPPENED])
def test_e2_a_habit_a_plan_or_something_still_going_on_is_never_sent_as_a_completed_happening(tmp_path, writer, text, word, obj):
    """The habitual-sentence problem. Base 2 keeps the fact, by its wording, outside the vocabulary (WP-1), and the adapter
    leaves it out. The classic writer sends it to review and stores nothing. On neither is ERC told an event happened."""
    w = Told(tmp_path, writer, [(SAID, text, word, obj, "")])
    try:
        a = w.ask(U(2030, 1, 1))
        told = () if a is None else a.request.propositions
        assert not [p for p in told if p.occurred is not None or p.predicate in NEW]
        if writer == BASE2:
            assert w.outcomes == [("accepted", ("word held: the source does not state a completed happening",))]
            ((predicate, marker),) = w.stored()
            assert marker == "outside" and predicate not in PREDICATE_TYPES
            assert told == () and [l.reason for l in a.left_out] == [OUTSIDE]
        else:
            assert w.outcomes[0][0] == "uncertain" and "the source does not state a completed happening" in w.outcomes[0][1]
            assert w.stored() == [] and a is None
    finally:
        w.m.close()


def test_e3_an_outside_fact_written_by_base_2_is_stored_and_not_sent_and_a_classic_record_is_sent_as_before(tmp_path):
    """C14 covers records "written by the corrected writer". The classic writer writes no marker: its record is sent."""
    (tmp_path / "b").mkdir(); (tmp_path / "c").mkdir()
    b = Told(tmp_path / "b", BASE2, [(SAID, "I ran a half marathon.", "other", "half marathon", "")])
    c = Told(tmp_path / "c", CLASSIC, [(SAID, "I own a cat.", "owns", "cat", "")])
    try:
        assert b.outcomes == [("accepted", ())] and [m for _, m in b.stored()] == ["outside"]
        a = b.ask(U(2024, 1, 1))
        assert a.request.propositions == () and [l.reason for l in a.left_out] == [OUTSIDE]
        assert [m for _, m in c.stored()] == [None]
        assert [p.predicate for p in c.ask(U(2024, 1, 1)).request.propositions] == ["owns"]
    finally:
        b.m.close(); c.m.close()


def test_e4_reasoning_over_a_memory_that_holds_outside_records_writes_nothing(tmp_path):
    w = Told(tmp_path, BASE2, [(SAID, "I ran a half marathon.", "other", "half marathon", ""), (SAID, "I visited Hampi in January 2023.", "visited", "Hampi", "")])
    try:
        tables = [t for (t,) in w.m.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        before = {t: w.m.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        r = Reasoner(w.kb).reason("User", as_of=U(2024, 1, 1))
        assert [p.predicate for p in r.adapted.request.propositions] == ["visited"]
        assert before == {t: w.m.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
    finally:
        w.m.close()
