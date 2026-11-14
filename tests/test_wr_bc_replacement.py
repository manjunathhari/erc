"""WR-BC together (Amendment 4): base 2's vocabulary facts reach the state engine, and replacement has one owner.

  4A15  Replacement ownership follows the state engine. Base 2 hands replacement to the state engine only when
        transition.slot_of(predicate) gives a slot; for every other vocabulary word and for wording-only facts, base 2
        keeps its existing same-wording versioning. Ownership is read from slot_of() itself, never from a list.
  4A6   A closing word ("I left Apollo": left_job) ends the earlier state through the state engine; it is not a second,
        unrelated fact. With the 21:09 clarification: after the departure the job is not current; before it, nothing
        that is right today becomes wrong.
  L3    The floor: a moment when the job certainly held is never answered "does not hold".
  R3    The request the adapter builds carries a stated start and end, labelled stated.

These need both halves: dates from the sentence (WR-B) and the word on the record (WR-C). Fixed proposals; no model.
"""
import datetime as dt

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge import transition
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED
from engram_knowledge.normalizer import PREDICATE_TYPES
from erc_overlay import Reasoner

UTC = dt.timezone.utc
JAN, MAR = "9:00 am on 10 January, 2025", "9:00 am on 1 March, 2025"


def U(y, m, d):
    return dt.datetime(y, m, d, 12, tzinfo=UTC)


def holds_at(t, now):
    """"holds", "not" or "unsettled" for a state's TimeInterval at a moment; the B6 Stage 1 reading, end exclusive."""
    if t.start is not None and now < t.start: return "not"
    if t.end is not None and now >= t.end: return "not"
    if t.start_unbounded: begun = True
    elif t.start_latest is not None: begun = t.start_latest <= now
    elif t.start is not None and not t.start_is_lower_bound: begun = t.start <= now
    else: begun = False
    if t.end_unbounded: lasting = True
    elif t.end_earliest is not None: lasting = now < t.end_earliest
    elif t.end is not None and not t.end_is_upper_bound: lasting = now < t.end
    else: lasting = False
    return "holds" if begun and lasting else "unsettled"


class World:
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.layer = S.StructureLayer(self.m.db)

    def file(self, said, text, obj, word, subject="I"):
        self.m.open_chat(said)
        sid = self.m.add("User", text, date=said)
        self.m.close_chat(write_note=False)
        out = self.layer.file(sid, subject, obj, S.gate("User", text, said)[1], word=word)
        assert out.verdict == ACCEPTED, out
        return out

    def fact(self, out):
        return self.kb.get(out.fact_id).fact

    def states(self, as_of, obj):
        """The states ERC is told about one object at as_of (events, such as the leaving itself, left out)."""
        ps = Reasoner(self.kb).reason("User", as_of=as_of).adapted.request.propositions
        return [p for p in ps if p.qualifiers.get("time_kind") != "event" and str(self._name(p.object_value)).lower() == obj.lower()]

    def answer(self, as_of, obj):
        """What ERC is told about the state at that moment: absent, holds, not or unsettled."""
        ps = self.states(as_of, obj)
        if not ps: return "absent"
        got = {holds_at(p.valid_time, as_of) if p.valid_time else "unsettled" for p in ps}
        return "holds" if "holds" in got else "not" if got == {"not"} else "unsettled"

    def _name(self, value):
        e = self.kb.entity(value) if isinstance(value, str) else None
        return e.canonical_name if e else value


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.m.close()


# ---------------------------------------------------------------- 4A15, test 1: a slotted word is the state engine's
def test_4a15_1_a_slotted_fact_is_not_also_superseded_by_base2(world):
    assert transition.slot_of("works_at")
    a = world.file(JAN, "I work at Apollo.", "Apollo", "works_at")
    b = world.file(MAR, "I work at Manipal.", "Manipal", "works_at")
    assert (world.fact(a).status, world.fact(b).status) == ("active", "active")   # base 2 did not supersede
    assert world.fact(a).valid_to is None                                          # and stored no end (4A4)
    assert world.answer(U(2025, 9, 1), "Manipal") == "holds"                       # the state engine replaced it
    assert world.answer(U(2025, 9, 1), "Apollo") != "holds"


# ---------------------------------------------------------------- 4A15, tests 2 and 3: unslotted words stay with base 2
UNSLOTTED = {  # word: (first sentence, its object, second sentence, its object); one wording, two values
    "number": ("I have 3 bikes.", "3 bikes", "I have 4 bikes.", "4 bikes"),
    "plans": ("I plan to visit Goa.", "Goa", "I plan to visit Kerala.", "Kerala"),
    "attended": ("I attended the Bengaluru meetup.", "Bengaluru meetup", "I attended the Pune meetup.", "Pune meetup"),
    "visited": ("I visited Goa.", "Goa", "I visited Kerala.", "Kerala"),
    "completed": ("I completed the Pune marathon.", "Pune marathon", "I completed the Mumbai marathon.", "Mumbai marathon"),
}


def test_4a15_the_unslotted_cases_cover_every_word_slot_of_leaves_out():
    """If transition.py gains or loses a slot, this test names the word whose owner changed."""
    assert set(UNSLOTTED) == {w for w in PREDICATE_TYPES if transition.slot_of(w) is None}


@pytest.mark.parametrize("word", sorted(UNSLOTTED))
def test_4a15_2_and_3_an_unslotted_word_keeps_base2s_versioning(world, word):
    t1, o1, t2, o2 = UNSLOTTED[word]
    old, new = world.file(JAN, t1, o1, word), world.file(MAR, t2, o2, word)
    o, n = world.fact(old), world.fact(new)
    assert (o.predicate, n.predicate) == (word, word)
    assert (o.status, n.status) == ("superseded", "active")
    assert (o.valid_from, o.valid_to, n.valid_from) == (None, None, None)          # 4A15 test 4: no said day stored


def test_4a15_wording_only_facts_keep_base2s_versioning(world):
    old = world.file(JAN, "I speak Kannada.", "Kannada", "other")
    new = world.file(MAR, "I speak Tamil.", "Tamil", "other")
    assert (world.fact(old).status, world.fact(new).status) == ("superseded", "active")
    assert world.fact(old).valid_to is None


def test_4a15_ownership_is_read_from_slot_of_not_from_a_list(world, monkeypatch):
    """Give number a slot in the transition table for this test only: base 2 must then leave the replacement alone."""
    monkeypatch.setitem(transition.OPENS, "number", "number")
    old = world.file(JAN, "I have 3 bikes.", "3 bikes", "number")
    world.file(MAR, "I have 4 bikes.", "4 bikes", "number")
    assert world.fact(old).status == "active"


# ---------------------------------------------------------------- 4A15, test 5: graph order and evidence
def test_4a15_5_the_graph_keeps_every_version_oldest_first_with_its_sentence(world):
    old = world.file(JAN, "I have 3 bikes.", "3 bikes", "number")
    new = world.file(MAR, "I have 4 bikes.", "4 bikes", "number")
    g = world.layer.graph()
    assert [g.facts[f]["object"] for f in g.by_subject["user"]] == ["3 bikes", "4 bikes"]
    for out in (old, new):
        assert len(world.kb.get(out.fact_id).evidence) == 1


# ---------------------------------------------------------------- 4A6 and the 21:09 clarification: E11, both sides
E11A = [("10:00 am on 10 January, 2025", "I have worked at Apollo since 2019.", "works_at"), ("9:00 am on 20 August, 2025", "I left Apollo.", "left_job")]
E11B = [("10:00 am on 10 January, 2025", "I work at Apollo.", "works_at"), ("9:00 am on 20 August, 2025", "I left Apollo in July 2025.", "left_job")]


def build(world, msgs):
    return [world.file(said, text, "Apollo", word) for said, text, word in msgs]


def test_4a6_the_leaving_is_its_own_closing_record_not_a_second_job(world):
    job, left = build(world, E11A)
    assert (world.fact(job).predicate, world.fact(left).predicate) == ("works_at", "left_job")
    assert world.fact(job).status == "active" and world.fact(job).valid_to is None   # ended by the state engine, not stored


@pytest.mark.parametrize("msgs,moment", [(E11A, U(2025, 9, 1)), (E11B, U(2025, 9, 1))], ids=["E11a", "E11b"])
def test_e11_after_the_departure_the_job_is_not_current(world, msgs, moment):
    build(world, msgs)
    assert world.answer(moment, "Apollo") in ("not", "absent")


@pytest.mark.parametrize("msgs,moment", [(E11A, U(2018, 6, 1))], ids=["E11a-2018"])
def test_e11_before_the_job_began_it_does_not_hold(world, msgs, moment):
    build(world, msgs)
    assert world.answer(moment, "Apollo") in ("not", "absent")


def test_e11_before_the_departure_a_moment_right_today_stays_right(world):
    """E11b at 1 March 2025: said on 10 January to be current, left in July. Right today, so it must stay right."""
    build(world, E11B)
    assert world.answer(U(2025, 3, 1), "Apollo") == "holds"


@pytest.mark.parametrize("msgs,moment", [(E11A, U(2025, 3, 1)), (E11B, U(2025, 7, 15))], ids=["E11a-unknown-end", "E11b-inside-July"])
def test_e11_where_the_truth_cannot_be_known_the_answer_is_not_definite(world, msgs, moment):
    build(world, msgs)
    assert world.answer(moment, "Apollo") == "unsettled"


def test_l3_floor_a_moment_when_the_job_certainly_held_is_never_does_not_hold(world):
    """E11a at 1 January 2022: it held. "unsettled" is accepted (finding L3, the E17 floor parked with B6); "not" is wrong."""
    build(world, E11A)
    assert world.answer(U(2022, 1, 1), "Apollo") in ("holds", "unsettled")


# ---------------------------------------------------------------- R3: what the adapter is told
def test_r3_a_stated_start_and_end_reach_the_adapter_labelled_stated(world):
    world.file(JAN, "I worked at Manipal from January 2020 to March 2024.", "Manipal", "works_at")
    [p] = world.states(U(2022, 1, 1), "Manipal")
    assert p.valid_time.start.date().isoformat() == "2020-01-01" and p.qualifiers.get("start_basis") == "stated"
    assert p.valid_time.end is not None and p.qualifiers.get("end_basis") == "stated"


def test_r3_a_sentence_with_no_date_reaches_the_adapter_as_first_said_only(world):
    """C03's shape: the said day is only the latest the state can have begun, never its start (TD7)."""
    world.file(JAN, "I work at Apollo.", "Apollo", "works_at")
    [p] = world.states(U(2025, 6, 1), "Apollo")
    assert p.valid_time.start is None and p.qualifiers.get("start_basis") == "first_said"


# ---------------------------------------------------------------- 4A16 (OQ-3): a date the writer supplies cannot reach the record
def test_4a16_a_date_in_the_writers_reply_cannot_change_the_stored_record(world):
    """The reply claims 1999; the sentence says 2019. Once the reply is parsed and the proposal filed, the record carries 2019."""
    import json
    text = "I have worked at Apollo since 2019."
    reply = json.dumps({"facts": [dict(line="D1:1", subject="I", word="works_at", object="Apollo", date="1999", start="1999")]})
    [p] = S.parse_proposals(reply, {"D1:1"})
    f = world.fact(world.file(JAN, text, p["object"], p["word"], subject=p["subject"]))
    assert (f.valid_from, f.valid_to) == ("2019", None)
