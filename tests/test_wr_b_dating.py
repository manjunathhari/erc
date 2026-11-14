"""WR-B (writing layer contract v1, section 3, with Amendment 4): base 2 dates a fact only from what its sentence states.

Rules TD1 to TD10, with Amendment 4's settled points:
  4A4   TD7 in full: the day a sentence was said is never stored as a start or an end.
  4A10  AM4-3: a month or day with no year gives no stored date; no year is guessed from the conversation.
  4A11  AM4-4: a stated year or season keeps its year ("early 2021" -> 2021; "last summer", said in 2025 -> 2024).
  A2/R3 one fact may carry a start and an end; checked in the stored record itself.

These tests touch dates only. No vocabulary word is passed, so they hold whether or not WR-C is present: that keeps
WR-B assessable on its own (4A1). Fixed sentences and fixed proposals only; no model is called.

Interface proposed in the tests-first package (claude/engram-wr-bc-tests-first.md, section 2):
  engram_structure.stated_dates(text, date_said) -> tuple of (value, role), role in {"start", "end", "event"}
  fact_validator.Candidate(..., end="")  the classic back end carries a stated end (A2)
"""
import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, UNCERTAIN, Candidate, KnowledgePipeline

SAID = "2:15 pm on 12 June, 2025"        # a Thursday, as in the audit's part T and in ETA-1
SAID_NEXT_DAY = "2:15 pm on 13 June, 2025"


def ev(value):
    return ((value, "event"),)


class Mem:
    """One memory; each sentence is said by User in its own chat, then filed by base 2 with a fixed proposal."""

    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.layer = S.StructureLayer(self.m.db)

    def say(self, text, said=SAID, speaker="User"):
        self.m.open_chat(said)
        sid = self.m.add(speaker, text, date=said)
        self.m.close_chat(write_note=False)
        return sid

    def file(self, text, subject, obj, said=SAID):
        sid = self.say(text, said)
        return self.layer.file(sid, subject, obj, S.gate("User", text, said)[1])

    def fact(self, out):
        assert out.verdict == ACCEPTED and out.fact_id, out
        return self.kb.get(out.fact_id).fact


@pytest.fixture
def mem(tmp_path):
    w = Mem(tmp_path)
    yield w
    w.m.close()


# ---------------------------------------------------------------- TD4: the audit's 20 expressions, corrected by AM4-3
# (expression, the dates and roles a correct reading gives). Truth fixed before any run. Two answers differ from the
# audit's part T, by Amendment 4 (4A10): "in March" and "on the 3rd" name no year, so they give no date.
TD4 = [
    ("yesterday", ev("2025-06-11")), ("last Friday", ev("2025-06-06")), ("three days ago", ev("2025-06-09")),
    ("last month", ev("2025-05")), ("last year", ev("2024")), ("next month", ev("2025-07")),
    ("in March 2025", ev("2025-03")), ("on 4 May 2025", ev("2025-05-04")), ("since 2021", (("2021", "start"),)),
    ("from 2018 to 2021", (("2018", "start"), ("2021", "end"))), ("until December 2025", (("2025-12", "end"),)),
    ("in Mar 2021", ev("2021-03")), ("early 2021", ev("2021")), ("in March", ()), ("two weeks ago", ev("2025-05-29")),
    ("last summer", ev("2024")), ("on the 3rd", ()), ("the day before yesterday", ev("2025-06-10")),
    ("tomorrow", ev("2025-06-13")), ("a few weeks ago", ()),
]


@pytest.mark.parametrize("expr,want", TD4, ids=[e for e, _ in TD4])
def test_td4_each_expression_gives_its_fixed_dates_and_roles(expr, want):
    assert S.stated_dates(f"I visited Goa {expr}.", SAID) == want


@pytest.mark.parametrize("expr,want", [("yesterday", "2025-06-12"), ("three days ago", "2025-06-10"), ("tomorrow", "2025-06-14"),
                                       ("last Friday", "2025-06-06")])
def test_td1_a_relative_date_is_read_from_the_said_day(expr, want):
    """The said day moved by one day moves the answer, except "last Friday" (the Friday before 13 June is still 6 June)."""
    assert S.stated_dates(f"I visited Goa {expr}.", SAID_NEXT_DAY) == ev(want)


# ---------------------------------------------------------------- TD2: roles
@pytest.mark.parametrize("text,want", [
    ("I have worked at Apollo since 2019.", (("2019", "start"),)),
    ("I have lived in Pune since last month.", (("2025-05", "start"),)),
    ("I have lived in Pune from 2021.", (("2021", "start"),)),
    ("I lived in Pune until 2020.", (("2020", "end"),)),
    ("I lived in Pune till 2020.", (("2020", "end"),)),
    ("I worked at Manipal from January 2020 to March 2024.", (("2020-01", "start"), ("2024-03", "end"))),
    ("I lived in Goa from 3 March 2020 to 9 May 2022.", (("2020-03-03", "start"), ("2022-05-09", "end"))),
    ("I am living in Delhi until December 2025.", (("2025-12", "end"),)),
])
def test_td2_since_from_until_and_from_to_give_their_roles(text, want):
    assert S.stated_dates(text, SAID) == want


# ---------------------------------------------------------------- TD3: a date on an event word
@pytest.mark.parametrize("text,want", [
    ("I got married on 14 February 2020.", ev("2020-02-14")),
    ("I moved to Chennai in March 2023.", ev("2023-03")),
    ("I left Apollo in July 2025.", ev("2025-07")),
    ("I moved to Pune yesterday.", ev("2025-06-11")),
])
def test_td3_a_date_on_an_event_is_the_event_date(text, want):
    assert S.stated_dates(text, SAID) == want


# ---------------------------------------------------------------- TD5, TD6: when no date is given
@pytest.mark.parametrize("text", ["I visited Goa in 2019 and in 2021.", "I lived in Goa in 2019, 2020 and 2022."])
def test_td5_several_dates_whose_roles_do_not_settle_give_none(text):
    assert S.stated_dates(text, SAID) == ()


@pytest.mark.parametrize("text", ["I visited Goa a few weeks ago.", "I joined the club a few weeks before the wedding.",
                                  "I moved to Pune a while back.", "I visited Goa recently."])
def test_td6_a_vague_expression_gives_none(text):
    assert S.stated_dates(text, SAID) == ()


# ---------------------------------------------------------------- TD7 (4A4): never the said day
@pytest.mark.parametrize("text", ["I work at Manipal.", "I have 3 bikes.", "I live in Bengaluru.", "My sister lives in Paris."])
def test_td7_a_sentence_with_no_date_gives_none(text):
    assert S.stated_dates(text, SAID) == ()


def test_td7_the_said_day_is_returned_only_when_the_sentence_states_it():
    assert S.stated_dates("I moved to Pune on 12 June 2025.", SAID) == ev("2025-06-12")
    assert S.stated_dates("I moved to Pune.", SAID) == ()


@pytest.mark.parametrize("text,subject,obj", [("I work at Manipal.", "I", "Manipal"), ("I have 3 bikes.", "I", "3 bikes"),
                                              ("My sister lives in Paris.", "my sister", "Paris")])
def test_td7_no_date_in_the_sentence_stores_no_start_and_no_end(mem, text, subject, obj):
    f = mem.fact(mem.file(text, subject, obj))
    assert (f.valid_from, f.valid_to) == (None, None)
    assert f.metadata["said_on"] == SAID          # the said day stays in metadata and on the sentence (WP-7)


# ---------------------------------------------------------------- TD8: short month names
@pytest.mark.parametrize("text,want", [("I moved to Goa in Mar 2021.", ev("2021-03")), ("I moved to Goa in Sept 2019.", ev("2019-09")),
                                       ("I moved to Goa in Dec. 2018.", ev("2018-12"))])
def test_td8_short_month_names_are_read(text, want):
    assert S.stated_dates(text, SAID) == want


# ---------------------------------------------------------------- TD9 (4A10, AM4-3): no year, no date
@pytest.mark.parametrize("text", ["I moved to Pune in March.", "I moved to Pune on the 3rd.", "I visited Mysore in March.",
                                  "I bought the console on 17 August.", "I have lived in Pune since June."])
def test_td9_a_month_or_day_with_no_year_gives_none(text):
    assert S.stated_dates(text, SAID) == ()


@pytest.mark.parametrize("text,obj", [("I moved to Pune in March.", "Pune"), ("I moved to Pune on the 3rd.", "Pune"),
                                      ("I visited Mysore in March.", "Mysore")])
def test_td9_the_fact_is_still_filed_with_its_wording_and_no_date(mem, text, obj):
    out = mem.file(text, "I", obj)
    f = mem.fact(out)
    assert (f.valid_from, f.valid_to) == (None, None)
    assert f.predicate == S.version_key(text, obj)   # its wording is kept; only the date is absent
    assert [e.source_id for e in mem.kb.get(out.fact_id).evidence]


def test_td9_no_year_is_taken_from_the_conversation_date():
    for said in (SAID, "9:00 am on 2 March, 2019", "9:00 am on 30 December, 2031"):
        assert S.stated_dates("I moved to Pune in March.", said) == ()


# ---------------------------------------------------------------- 4A11 (AM4-4): a stated year or season keeps its year
@pytest.mark.parametrize("text,want", [("I moved to Goa in early 2021.", ev("2021")), ("I went to Delhi in late 2022.", ev("2022")),
                                       ("I joined in mid-2020.", ev("2020")), ("I visited Goa last summer.", ev("2024"))])
def test_am4_4_a_stated_year_or_season_keeps_the_year(text, want):
    assert S.stated_dates(text, SAID) == want


# ---------------------------------------------------------------- TD10: clock time and zone are out of this work
def test_td10_a_clock_time_gives_no_date_and_stays_word_for_word_in_the_said_text(mem):
    assert S.stated_dates("I visited Goa at 3 pm.", SAID) == ()
    f = mem.fact(mem.file("I work at Manipal.", "I", "Manipal", said="2:35 pm on 12 June, 2025"))
    assert f.metadata["said_on"] == "2:35 pm on 12 June, 2025"


# ---------------------------------------------------------------- A2 and R3: dates in the stored record itself
@pytest.mark.parametrize("text,obj,want", [
    ("I worked at Manipal from January 2020 to March 2024.", "Manipal", ("2020-01", "2024-03")),
    ("I have worked at Apollo since 2019.", "Apollo", ("2019", None)),
    ("I have lived in Pune from 2021.", "Pune", ("2021", None)),
    ("I lived in Pune until 2020.", "Pune", (None, "2020")),
    ("I moved to Chennai in March 2023.", "Chennai", ("2023-03", None)),
    ("I got married on 14 February 2020.", "married", ("2020-02-14", None)),
])
def test_r3_the_stored_record_carries_the_stated_dates(mem, text, obj, want):
    out = mem.file(text, "I", obj)
    row = mem.m.db.execute("SELECT valid_from, valid_to FROM knowledge_records WHERE fact_id=?", (out.fact_id,)).fetchone()
    assert tuple(row) == want


def test_a2_one_fact_with_both_ends_is_one_record(mem):
    mem.file("I worked at Manipal from January 2020 to March 2024.", "I", "Manipal")
    assert mem.m.db.execute("SELECT count(*) FROM knowledge_records").fetchone()[0] == 1


def test_c3_no_stored_date_is_absent_from_the_sentence_and_the_said_day(mem):
    """Guarantee C3 over every sentence above: each stored date is one the sentence's own reading gives."""
    for text, obj, _ in [("I worked at Manipal from January 2020 to March 2024.", "Manipal", 0), ("I moved to Pune in March.", "Pune", 0),
                         ("I visited Goa last summer.", "Goa", 0), ("I work at Manipal.", "Manipal", 0)]:
        f = mem.fact(mem.file(text, "I", obj))
        stated = {v for v, _ in S.stated_dates(text, SAID)}
        assert {d for d in (f.valid_from, f.valid_to) if d} <= stated


# ---------------------------------------------------------------- A2: the classic back end carries a stated end
def test_a2_the_classic_back_end_stores_a_stated_end(mem):
    sid = mem.say("I worked at Apollo from 2018 to 2021.")
    d, fid = KnowledgePipeline(mem.m.db).process(Candidate("I", "works_at", "Apollo", (sid,), "2018", "test", "1", end="2021"))
    assert d.verdict == ACCEPTED
    f = mem.kb.get(fid).fact
    assert (f.valid_from, f.valid_to) == ("2018", "2021")


def test_a2_the_classic_back_end_holds_an_end_its_source_does_not_state(mem):
    sid = mem.say("I worked at Apollo from 2018 to 2021.")
    d, _ = KnowledgePipeline(mem.m.db).process(Candidate("I", "works_at", "Apollo", (sid,), "2018", "test", "1", end="2023"))
    assert d.verdict == UNCERTAIN and "end is not in the source" in d.reasons


def test_a2_a_classic_candidate_with_no_end_is_unchanged(mem):
    sid = mem.say("I have worked at Apollo since 2019.")
    d, fid = KnowledgePipeline(mem.m.db).process(Candidate("I", "works_at", "Apollo", (sid,), "2019", "test", "1"))
    f = mem.kb.get(fid).fact
    assert d.verdict == ACCEPTED and (f.valid_from, f.valid_to) == ("2019", None)
