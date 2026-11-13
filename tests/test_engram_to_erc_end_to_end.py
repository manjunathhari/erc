"""End to end: a sentence goes into Engram, a writer files it, the ERC adapter reads it, ERC reasons on it.

Before this file no test joined the two halves. The adapter and ERC tests write their facts by hand, with the
predicate chosen by the test, so they show that ERC handles a well-formed record and not that Engram writes one.
Here every fact is filed by a writer from a sentence, and what is checked is what ERC is then told and does.

Each case states one thing ERC's temporal reasoning needs to be told. The expected answer is fixed in the case, and
every case runs on two writers:

  base2    engram_structure.StructureLayer.file   the frozen base 2 writer, the one under test
  classic  engram_knowledge KnowledgePipeline     the fixed-vocabulary writer the adapter was built against. It is
           the control: it shows that a check can pass, so a failure on base 2 is the writer's and not the test's.

The proposals are hand-written and no model is called: this tests what the writer does with a correct proposal.
Made-up people only. Cases C01 to C11 and the rule case C09 are those of the E-A2 to E-A7 audit (13 November 2026),
which found that base 2 supplies 2 of the 11 needs and the classic writer 10. C12 is new here: a plain happening with
an exact day. It fails on both writers, so it has no passing control; C01 makes the same kind of check and passes on
the classic writer.

Cases that fail today are marked xfail(strict=True) with the reason. Strict means the mark must be removed when the
writer is fixed: a marked case that starts passing fails the run until someone takes the mark off on purpose.
To see the failures themselves:  python -m pytest tests/test_engram_to_erc_end_to_end.py --runxfail

One seam: `file_with_base2` below is the only place that knows the base 2 writer's interface (a subject and an object
copied from the sentence). If a later contract changes that interface, this function changes and the cases do not.
"""
import datetime as dt

import pytest

import engram_chat as E
import engram_structure as S
from engram_erc import ConclusionTemplate, PropositionPattern, RuleDefinition, RuleSet, Variable
from engram_knowledge.fact_validator import Candidate, KnowledgePipeline
from engram_records import KnowledgeBase
from erc_overlay import Reasoner

UTC = dt.timezone.utc
BASE2, CLASSIC = "base2", "classic"


def U(y, m, d):
    return dt.datetime(y, m, d, tzinfo=UTC)


def day(moment):
    return moment.astimezone(UTC).date().isoformat() if moment else None


def file_with_base2(layer, sid, speaker, text, date, proposal):
    """Today's base 2 interface: the gate reads the sentence, then one (subject, object) proposal is filed."""
    subject, obj = proposal
    _, kind = S.gate(speaker, text, date)
    return layer.file(sid, subject, obj, kind)


def file_with_classic(pipe, sid, proposal):
    predicate, obj, when = proposal
    decision, _ = pipe.process(Candidate("I", predicate, obj, (sid,), when, "end-to-end test", "1"))
    return decision


class World:
    """One memory. Each message is stored as a sentence said by User, then filed by the chosen writer."""

    def __init__(self, tmp_path, writer, messages):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        pipe, layer = KnowledgePipeline(self.m.db), S.StructureLayer(self.m.db)
        for date, text, classic_proposals, base2_proposals in messages:
            self.m.open_chat(date)
            sid = self.m.add("User", text, date=date)
            self.m.close_chat(write_note=False)
            if writer == CLASSIC:
                for p in classic_proposals: file_with_classic(pipe, sid, p)
            else:
                for p in base2_proposals: file_with_base2(layer, sid, "User", text, date, p)

    def ask(self, as_of, ruleset=None):
        if not self.kb.resolve("User"): return None
        return Reasoner(self.kb).reason("User", as_of=as_of, ruleset=ruleset)

    def name(self, value):
        e = self.kb.entity(value) if isinstance(value, str) else None
        return e.canonical_name if e else value

    def told(self, as_of, obj=None):
        """The propositions ERC is given at as_of, optionally only those about one object."""
        r = self.ask(as_of)
        if r is None: return []
        return [p for p in r.adapted.request.propositions if obj is None or str(self.name(p.object_value)).lower() == obj.lower()]


def still_going(p):
    """A state sent with no end, or with no time at all: nothing tells ERC it has stopped."""
    return p.qualifiers.get("time_kind") == "state" and (p.valid_time is None or p.valid_time.end_unbounded)


# ---------------------------------------------------------------- the cases
# Each message: (date said, sentence, classic proposals [(predicate, object, when)], base 2 proposals [(subject, object)])

def c01(w):
    """An event is sent as an event, in the window it happened in."""
    ps = w.told(U(2024, 1, 1), "Chennai")
    assert len(ps) == 1
    assert ps[0].qualifiers.get("time_kind") == "event" and ps[0].occurred is not None
    assert (day(ps[0].occurred.earliest), day(ps[0].occurred.latest)) == ("2023-03-01", "2023-03-31")


def c02(w):
    """A stated start is the start, is labelled stated, and the state is still going."""
    ps = w.told(U(2024, 6, 1), "Apollo")
    assert len(ps) == 1 and ps[0].valid_time is not None
    assert day(ps[0].valid_time.start) == "2019-01-01"
    assert ps[0].qualifiers.get("start_basis") == "stated" and ps[0].valid_time.end_unbounded


def c03(w):
    """The day something was said is not its start: it is only the latest it can have started."""
    ps = w.told(U(2024, 6, 1), "Apollo")
    assert len(ps) == 1 and ps[0].valid_time is not None
    assert ps[0].valid_time.start is None
    assert day(ps[0].valid_time.start_latest) == "2024-03-05" and ps[0].qualifiers.get("start_basis") == "first_said"


def c04(w):
    """A stated end is carried and labelled stated."""
    ps = w.told(U(2020, 6, 1), "Apollo")
    assert len(ps) == 1 and ps[0].valid_time is not None
    assert day(ps[0].valid_time.end) == "2022-01-01" and ps[0].qualifiers.get("end_basis") == "stated"


def c05(w):
    """A later statement ends an earlier state."""
    assert not any(still_going(p) for p in w.told(U(2024, 3, 5), "Apollo"))


def c06a(w):
    """A replaced value: the right one at each moment."""
    now = {str(w.name(p.object_value)) for p in w.told(U(2024, 3, 5)) if still_going(p)}
    then = {str(w.name(p.object_value)) for p in w.told(U(2024, 2, 1))}
    assert (now, then) == ({"Delhi"}, {"Pune"})


def c06b(w):
    """An end nobody stated is sent as the latest possible end, never as a stated end."""
    ps = w.told(U(2024, 2, 1), "Pune")
    assert len(ps) == 1 and ps[0].valid_time is not None and ps[0].valid_time.end is not None
    assert ps[0].valid_time.end_is_upper_bound and ps[0].qualifiers.get("end_basis") != "stated"


def c07(w):
    """No date anywhere: the time is unknown, said to be unknown, and nothing is invented."""
    ps = w.told(U(2024, 3, 5), "cat")
    assert len(ps) == 1 and ps[0].valid_time is None and ps[0].occurred is None
    assert ps[0].qualifiers.get("valid_time") == "unknown"


def c08(w):
    """Two incompatible values held at once reach ERC as a contradiction."""
    r = w.ask(U(2024, 3, 6))
    assert r is not None and len(r.orchestration.contradictions) > 0


def c10(w):
    """The order of two events can be decided from what is sent."""
    a, b = w.told(U(2024, 1, 1), "Chennai"), w.told(U(2024, 1, 1), "Apollo")
    assert len(a) == 1 and len(b) == 1 and a[0].occurred is not None and b[0].occurred is not None
    assert a[0].occurred.latest < b[0].occurred.earliest


def c11(w):
    """One event told twice is one fact with two sources."""
    ps = w.told(U(2024, 1, 1), "Chennai")
    assert len(ps) == 1 and len(ps[0].source_refs) == 2


def c12(w):
    """An event with an exact day is sent as an event on that day."""
    ps = w.told(U(2024, 1, 1), "half marathon")
    assert len(ps) == 1 and ps[0].qualifiers.get("time_kind") == "event" and ps[0].occurred is not None
    assert (day(ps[0].occurred.earliest), day(ps[0].occurred.latest)) == ("2023-02-25", "2023-02-25")


MARCH5 = "1:00 pm on 5 March, 2024"
CASES = {
    "C01": (c01, [("10:00 am on 10 April, 2023", "I moved to Chennai in March 2023.", [("moved_to", "Chennai", "March 2023")], [("I", "Chennai")])]),
    "C02": (c02, [(MARCH5, "I have worked at Apollo since 2019.", [("works_at", "Apollo", "2019")], [("I", "Apollo")])]),
    "C03": (c03, [(MARCH5, "I work at Apollo.", [("works_at", "Apollo", "")], [("I", "Apollo")])]),
    "C04": (c04, [(MARCH5, "I worked at Apollo from 2018 to 2021.", [("works_at", "Apollo", "2018")], [("I", "Apollo")])]),
    "C05": (c05, [("9:00 am on 1 January, 2024", "I work at Apollo.", [("works_at", "Apollo", "")], [("I", "Apollo")]),
                  ("9:00 am on 1 March, 2024", "I left Apollo.", [("left_job", "Apollo", "")], [("I", "Apollo")])]),
    "C06a": (c06a, [("9:00 am on 1 January, 2024", "I live in Pune.", [("lives_in", "Pune", "")], [("I", "Pune")]),
                    ("9:00 am on 1 March, 2024", "I live in Delhi.", [("lives_in", "Delhi", "")], [("I", "Delhi")])]),
    "C06b": (c06b, [("9:00 am on 1 January, 2024", "I live in Pune.", [("lives_in", "Pune", "")], [("I", "Pune")]),
                    ("9:00 am on 1 March, 2024", "I live in Delhi.", [("lives_in", "Delhi", "")], [("I", "Delhi")])]),
    "C07": (c07, [("", "I own a cat.", [("owns", "cat", "")], [("I", "cat")])]),
    "C08": (c08, [(MARCH5, "I have lived in Pune since 2022.", [("lives_in", "Pune", "2022")], [("I", "Pune")]),
                  ("2:00 pm on 5 March, 2024", "My home has been in Mysore since 2022.", [("lives_in", "Mysore", "2022")], [("My home", "Mysore")])]),
    "C10": (c10, [("9:00 am on 1 July, 2023", "I moved to Chennai in March 2023.", [("moved_to", "Chennai", "March 2023")], [("I", "Chennai")]),
                  ("9:05 am on 1 July, 2023", "I started a job at Apollo in June 2023.", [("started_job", "Apollo", "June 2023")], [("I", "Apollo")])]),
    "C11": (c11, [("9:00 am on 1 July, 2023", "I moved to Chennai in March 2023.", [("moved_to", "Chennai", "March 2023")], [("I", "Chennai")]),
                  ("9:00 am on 1 August, 2023", "My move to Chennai was in March 2023.", [("moved_to", "Chennai", "March 2023")], [("My move", "Chennai")])]),
    "C12": (c12, [("2:15 pm on 3 March, 2023", "I attended a half marathon on 25 February 2023.",
                   [("attended", "half marathon", "25 February 2023")], [("I", "half marathon")])]),
}

# What fails today, and why. Recorded before the writer is changed; each line comes off when its case is fixed.
B2_PREDICATE = "base 2 files the sentence's own wording as the predicate, so the adapter cannot tell an event from a state"
B2_SAID_DAY = "base 2 stores the day the sentence was said as the day the fact began"
B2_NO_END = "base 2 never closes a state: it has no closing words and no stated end"
B2_SLOT = "base 2's predicates are wordings, so two wordings of one slot are not seen as the same slot"
FAILS_TODAY = {
    (BASE2, "C01"): B2_PREDICATE, (BASE2, "C02"): B2_SAID_DAY, (BASE2, "C03"): B2_SAID_DAY, (BASE2, "C04"): B2_NO_END,
    (BASE2, "C05"): B2_NO_END, (BASE2, "C06b"): B2_SAID_DAY, (BASE2, "C08"): B2_SLOT, (BASE2, "C10"): B2_PREDICATE,
    (BASE2, "C11"): B2_SLOT, (BASE2, "C12"): B2_PREDICATE,
    (CLASSIC, "C04"): "the classic writer takes one stated time, the start; a stated end has nowhere to go",
    (CLASSIC, "C12"): "the adapter counts only words that open or close a slot (moved_to, started_job, left_job...) as events; "
                      "attended is filed correctly and then sent as a state",
}


def params():
    out = []
    for writer in (BASE2, CLASSIC):
        for cid in CASES:
            why = FAILS_TODAY.get((writer, cid))
            marks = [pytest.mark.xfail(strict=True, reason=f"{cid} on {writer}: {why}")] if why else []
            out.append(pytest.param(writer, cid, id=f"{writer}-{cid}", marks=marks))
    return out


@pytest.mark.parametrize("writer, cid", params())
def test_what_erc_is_told(tmp_path, writer, cid):
    check, messages = CASES[cid]
    w = World(tmp_path, writer, messages)
    try:
        check(w)
    finally:
        w.m.close()


# ---------------------------------------------------------------- a rule must fire whatever the wording (C09)
X, C = Variable("x"), Variable("c")
EMPLOYED = RuleSet((RuleDefinition("employed", "1", (PropositionPattern(X, "works_at", C),), ConclusionTemplate(X, "employed_by", C)),))
WORDINGS = [("I work at Manipal.", "I"), ("I am working at Manipal.", "I"), ("My job is at Manipal.", "My job")]


@pytest.mark.parametrize("writer", [
    pytest.param(BASE2, marks=pytest.mark.xfail(strict=True, reason="C09 on base2: " + B2_PREDICATE + ", so a rule written on works_at never matches")),
    CLASSIC])
def test_one_rule_fires_for_three_wordings_of_one_fact(tmp_path, writer):
    fired = 0
    for n, (text, subject) in enumerate(WORDINGS):
        (tmp_path / str(n)).mkdir()
        w = World(tmp_path / str(n), writer, [(MARCH5, text, [("works_at", "Manipal", "")], [(subject, "Manipal")])])
        try:
            r = w.ask(U(2024, 6, 1), EMPLOYED)
            fired += r is not None and len(r.result.conclusion_refs) > 0
        finally:
            w.m.close()
    assert fired == 3


# ---------------------------------------------------------------- what already holds and must keep holding
@pytest.mark.parametrize("writer", [BASE2, CLASSIC])
def test_every_sentence_sent_as_evidence_carries_the_day_it_was_said(tmp_path, writer):
    have = total = 0
    for n, (cid, (_, messages)) in enumerate(CASES.items()):
        if cid == "C07": continue  # no date by design
        (tmp_path / str(n)).mkdir()
        w = World(tmp_path / str(n), writer, messages)
        try:
            r = w.ask(U(2025, 1, 1))
            for e in (r.adapted.request.evidence if r is not None else ()):
                if e.id.startswith("sentence:"):
                    total += 1; have += e.observed_at is not None
        finally:
            w.m.close()
    assert total > 0 and have == total


@pytest.mark.parametrize("writer", [BASE2, CLASSIC])
def test_reasoning_writes_nothing_to_the_memory(tmp_path, writer):
    w = World(tmp_path, writer, CASES["C06a"][1])
    try:
        tables = [t for (t,) in w.m.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        before = {t: w.m.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        w.ask(U(2024, 3, 5), EMPLOYED)
        after = {t: w.m.db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}
        assert before == after
    finally:
        w.m.close()
