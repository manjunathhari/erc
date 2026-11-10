"""B1 - Temporal Contract Foundation (ERC 0.5.0).

Types and validation only. Nothing in B1 answers a temporal question (does this hold at a moment, do two times
overlap, which came first): that is B3 onward. So these tests assert what the contract can *say*, that it refuses
what it must not say, and that everything that existed before B1 behaves exactly as it did.

Specification and decisions: claude/erc-b1-spec-validation.md (D1-D12 and the two conditions of approval).
"""
import dataclasses
import datetime as dt
import itertools

import pytest

import engram_erc
from engram_erc import Evidence, Proposition, ReasoningRequest, SourceKind, TimeInterval
from engram_erc.counterfactual import RegressionCase
from engram_erc.generalization import _snapshot_fingerprint
from engram_erc.primitives.comparison import _temporal_relation

UTC = dt.timezone.utc


def at(year, month=1, day=1, hour=0):
    return dt.datetime(year, month, day, hour, tzinfo=UTC)


def contract(name):
    """The B1 names, looked up late so that each test fails on its own before B1 exists."""
    return getattr(engram_erc, name)


def status(name):
    return getattr(contract("BoundaryStatus"), name)


# --------------------------------------------------------------------------
# A. Boundaries: exact, within a window, one-sided, unknown, unbounded
# --------------------------------------------------------------------------

def test_exact_start_and_end():
    t = TimeInterval(at(2021, 3, 5), at(2023, 7, 1))
    assert t.start == at(2021, 3, 5) and t.end == at(2023, 7, 1)
    assert t.start_status is status("EXACT") and t.end_status is status("EXACT")


def test_unknown_start():
    t = TimeInterval(end=at(2023))
    assert t.start is None and t.start_latest is None and t.start_status is status("UNKNOWN")
    assert t.end_status is status("EXACT")


def test_unknown_end_keeps_its_meaning_from_before_b1():
    t = TimeInterval(at(2021))
    assert t.end is None and t.end_earliest is None and t.end_unbounded is False
    assert t.end_status is status("UNKNOWN")  # ended at a moment not known; NOT "still going"


def test_both_boundaries_unknown():
    t = TimeInterval()
    assert t.start_status is status("UNKNOWN") and t.end_status is status("UNKNOWN")


def test_unbounded_start():
    t = TimeInterval(end=at(2023), start_unbounded=True)
    assert t.start is None and t.start_status is status("UNBOUNDED") and t.end_status is status("EXACT")


def test_unbounded_end():
    t = TimeInterval(at(2021), end_unbounded=True)
    assert t.end is None and t.end_status is status("UNBOUNDED") and t.start_status is status("EXACT")


def test_unbounded_at_both_ends():
    t = TimeInterval(start_unbounded=True, end_unbounded=True)
    assert t.start_status is status("UNBOUNDED") and t.end_status is status("UNBOUNDED")


def test_unknown_does_not_become_unbounded_and_unbounded_does_not_become_unknown():
    still_going, ended_unknown_when = TimeInterval(at(2021), end_unbounded=True), TimeInterval(at(2021))
    assert still_going != ended_unknown_when and hash(still_going) != hash(ended_unknown_when)
    assert still_going.end_status is not ended_unknown_when.end_status
    assert TimeInterval() != TimeInterval(start_unbounded=True) != TimeInterval(end_unbounded=True)
    assert TimeInterval(start_unbounded=True).start_status is status("UNBOUNDED")
    assert TimeInterval().start_status is status("UNKNOWN")


def test_start_within_a_window():
    t = TimeInterval(at(2021), start_latest=at(2022))  # "from 2021": began somewhere in that year
    assert t.start == at(2021) and t.start_latest == at(2022) and t.start_status is status("WITHIN")


def test_end_within_a_window():
    t = TimeInterval(at(2019), at(2022), end_earliest=at(2021))  # "until 2021": ended somewhere in that year
    assert t.end_earliest == at(2021) and t.end == at(2022) and t.end_status is status("WITHIN")


def test_start_known_only_to_be_no_later_than_a_moment():
    """'Works at Manipal', said on 5 March 2024: it had begun by then; when it began is not known."""
    t = TimeInterval(start_latest=at(2024, 3, 5))
    assert t.start is None  # no start date is invented
    assert t.start_latest == at(2024, 3, 5) and t.start_status is status("NO_LATER_THAN")


def test_start_known_only_to_be_no_earlier_than_a_moment():
    t = TimeInterval(at(2024, 3, 5), start_is_lower_bound=True)
    assert t.start == at(2024, 3, 5) and t.start_latest is None and t.start_status is status("NO_EARLIER_THAN")
    assert t != TimeInterval(at(2024, 3, 5))  # not the same statement as "began exactly then"


def test_end_known_only_to_be_no_earlier_than_a_moment():
    """It had not ended before 5 March 2024; whether or when it ended later is not known."""
    t = TimeInterval(at(2019), end_earliest=at(2024, 3, 5))
    assert t.end is None and t.end_earliest == at(2024, 3, 5) and t.end_status is status("NO_EARLIER_THAN")


def test_end_known_only_to_be_no_later_than_a_moment():
    """It had ended by 1 June 2024; when it ended is not known."""
    t = TimeInterval(at(2019), at(2024, 6, 1), end_is_upper_bound=True)
    assert t.end == at(2024, 6, 1) and t.end_earliest is None and t.end_status is status("NO_LATER_THAN")
    assert t != TimeInterval(at(2019), at(2024, 6, 1))


def test_attested_on_a_day_start_unknown_before_it_end_unknown_after_it():
    t = TimeInterval(start_latest=at(2024, 3, 5), end_earliest=at(2024, 3, 5))
    assert (t.start, t.end) == (None, None)
    assert t.start_status is status("NO_LATER_THAN") and t.end_status is status("NO_EARLIER_THAN")


def test_the_five_boundary_cases_are_five_different_values():
    exact = TimeInterval(at(2021))
    window = TimeInterval(at(2021), start_latest=at(2022))
    one_sided = TimeInterval(start_latest=at(2022))
    unknown = TimeInterval()
    unbounded = TimeInterval(start_unbounded=True)
    assert len({exact, window, one_sided, unknown, unbounded}) == 5
    assert [t.start_status for t in (exact, window, one_sided, unknown, unbounded)] == [
        status("EXACT"), status("WITHIN"), status("NO_LATER_THAN"), status("UNKNOWN"), status("UNBOUNDED")]


def test_boundary_status_has_exactly_the_approved_members():
    assert {m.name for m in contract("BoundaryStatus")} == {
        "EXACT", "WITHIN", "NO_LATER_THAN", "NO_EARLIER_THAN", "UNKNOWN", "UNBOUNDED"}


INVALID = [
    ("an unbounded start with a start date", dict(start=at(2021), start_unbounded=True)),
    ("an unbounded start with a latest start", dict(start_latest=at(2021), start_unbounded=True)),
    ("an unbounded start that is also a lower bound", dict(start_unbounded=True, start_is_lower_bound=True)),
    ("an unbounded end with an end date", dict(end=at(2021), end_unbounded=True)),
    ("an unbounded end with an earliest end", dict(end_earliest=at(2021), end_unbounded=True)),
    ("an unbounded end that is also an upper bound", dict(end_unbounded=True, end_is_upper_bound=True)),
    ("latest start before the start", dict(start=at(2022), start_latest=at(2021))),
    ("latest start equal to the start (say it as exact)", dict(start=at(2021), start_latest=at(2021))),
    ("earliest end after the end", dict(end=at(2021), end_earliest=at(2022))),
    ("earliest end equal to the end (say it as exact)", dict(end=at(2021), end_earliest=at(2021))),
    ("a lower-bound start with no start", dict(start_is_lower_bound=True)),
    ("a lower-bound start that also has a latest start", dict(start=at(2021), start_latest=at(2022), start_is_lower_bound=True)),
    ("an upper-bound end with no end", dict(end_is_upper_bound=True)),
    ("an upper-bound end that also has an earliest end", dict(start=at(2019), end=at(2022), end_earliest=at(2021), end_is_upper_bound=True)),
    ("a flag that is not a boolean", dict(start=at(2021), end_unbounded="yes")),
]


@pytest.mark.parametrize("why,kwargs", INVALID, ids=[w for w, _ in INVALID])
def test_contradictory_boundary_combinations_are_refused(why, kwargs):
    with pytest.raises(ValueError):
        TimeInterval(**kwargs)


# --------------------------------------------------------------------------
# B. Precision: two bounding instants, kept exactly as given; ERC parses no dates
# --------------------------------------------------------------------------

def test_year_precision_is_kept_as_the_two_bounds_it_was_given():
    t = TimeInterval(at(2021), at(2024), start_latest=at(2022), end_earliest=at(2023))  # "from 2021 to 2023"
    assert (t.start, t.start_latest, t.end_earliest, t.end) == (at(2021), at(2022), at(2023), at(2024))


def test_month_precision():
    t = TimeInterval(at(2021, 3), start_latest=at(2021, 4), end_unbounded=True)
    assert (t.start, t.start_latest) == (at(2021, 3, 1), at(2021, 4, 1)) and t.start_status is status("WITHIN")


def test_day_precision():
    t = TimeInterval(at(2021, 3, 5), start_latest=at(2021, 3, 6), end_unbounded=True)
    assert (t.start, t.start_latest) == (at(2021, 3, 5), at(2021, 3, 6)) and t.start_status is status("WITHIN")


def test_instant_precision():
    t = TimeInterval(at(2021, 3, 5, 13), at(2021, 3, 5, 14))
    assert t.start_latest is None and t.end_earliest is None
    assert t.start_status is status("EXACT") and t.end_status is status("EXACT")


def test_the_interval_holds_no_original_text_and_no_precision_label():
    """Decision D2: Engram keeps the stated date and its precision; ERC receives only the bounds."""
    assert [f.name for f in dataclasses.fields(TimeInterval)] == [
        "start", "end", "start_latest", "end_earliest", "start_unbounded", "end_unbounded",
        "start_is_lower_bound", "end_is_upper_bound"]
    assert [f.name for f in dataclasses.fields(contract("Occurrence"))] == ["earliest", "latest"]


NOT_A_DATETIME = [dt.date(2021, 1, 1), "2021", 2021]


@pytest.mark.parametrize("field", ["start", "end", "start_latest", "end_earliest"])
@pytest.mark.parametrize("value", NOT_A_DATETIME, ids=["a date", "a string", "a number"])
def test_a_value_that_is_not_a_datetime_is_refused_with_a_clear_error(field, value):
    """Replaces the draft's 'invalid dates are rejected': reading dates is Engram's job, so ERC only refuses non-datetimes."""
    with pytest.raises(ValueError, match=f"TimeInterval.{field} must be a datetime"):
        TimeInterval(**{field: value})


@pytest.mark.parametrize("field", ["start", "end", "start_latest", "end_earliest"])
def test_naive_datetimes_are_refused_in_every_field(field):
    with pytest.raises(ValueError, match="timezone-aware"):
        TimeInterval(**{field: dt.datetime(2021, 1, 1)})


# --------------------------------------------------------------------------
# C. Interval rules kept from before B1
# --------------------------------------------------------------------------

def test_start_must_precede_end_when_both_are_given():
    with pytest.raises(ValueError, match="TimeInterval.start must be earlier than end"):
        TimeInterval(at(2022), at(2021))


def test_an_interval_still_cannot_be_a_single_moment():
    with pytest.raises(ValueError, match="TimeInterval.start must be earlier than end"):
        TimeInterval(at(2021), at(2021))


def test_partial_intervals_remain_representable():
    assert TimeInterval(at(2021)).end is None and TimeInterval(None, at(2021)).start is None


def test_intervals_are_immutable():
    t = TimeInterval(at(2021), end_unbounded=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.end_unbounded = False


# --------------------------------------------------------------------------
# D. Compatibility: everything that existed before B1
# --------------------------------------------------------------------------

def test_existing_positional_constructor_and_attributes():
    t = TimeInterval(at(2019), at(2021))
    assert (t.start, t.end) == (at(2019), at(2021))
    assert TimeInterval().start is None and TimeInterval().end is None


def test_keyword_start_as_the_frozen_bridge_calls_it():
    t = TimeInterval(start=at(2021))  # engram_erc_bridge.py: TimeInterval(start=when)
    assert t.start == at(2021) and t.end is None and t.end_status is status("UNKNOWN")


def test_new_fields_are_keyword_only():
    with pytest.raises(TypeError):
        TimeInterval(at(2019), at(2021), at(2020))
    for f in dataclasses.fields(TimeInterval):
        assert f.kw_only is (f.name not in ("start", "end")), f.name
    assert {f.name for f in dataclasses.fields(Proposition) if f.kw_only} == {"occurred"}


def test_existing_values_keep_their_equality_and_hash():
    a, b = TimeInterval(at(2019), at(2021)), TimeInterval(at(2019), at(2021))
    assert a == b and hash(a) == hash(b) and len({a, b}) == 1
    assert TimeInterval() == TimeInterval() and TimeInterval(at(2019)) != TimeInterval(at(2019), at(2021))
    spelled_out = TimeInterval(at(2019), at(2021), start_latest=None, end_earliest=None, start_unbounded=False,
                               end_unbounded=False, start_is_lower_bound=False, end_is_upper_bound=False)
    assert a == spelled_out and hash(a) == hash(spelled_out)
    assert TimeInterval() != None  # noqa: E711 - the two stay different values, as before B1


def test_existing_proposition_and_evidence_consumers():
    p = Proposition("p1", "asha", "works_at", "manipal", True, engram_erc.PropositionKind.ASSERTION, ("s1",),
                    TimeInterval(at(2019), at(2021)), {"k": "v"})
    assert p.valid_time.start == at(2019) and p.valid_time.end == at(2021) and p.qualifiers == {"k": "v"}
    e = Evidence("e1", "s1", SourceKind.ENGRAM_MEMORY, valid_time=TimeInterval(at(2019), at(2021)))
    assert e.valid_time.end == at(2021)
    assert dataclasses.replace(p, valid_time=None).valid_time is None


def test_a_proposition_with_no_temporal_statement_is_unchanged():
    p = Proposition("p1", "manipal", "located_in", "bengaluru")
    assert p.valid_time is None and p.occurred is None
    request = ReasoningRequest("r1", "question", (p,))
    assert request.propositions[0] is p and request.as_of is None


def test_no_temporal_statement_and_unknown_time_are_different_representations():
    silent = Proposition("p1", "asha", "admires", "kalam")
    unknown = Proposition("p1", "asha", "admires", "kalam", valid_time=TimeInterval())
    assert silent.valid_time is None and unknown.valid_time is not None
    assert silent != unknown
    assert unknown.valid_time.start_status is status("UNKNOWN") and unknown.valid_time.end_status is status("UNKNOWN")


SHAPES = {"none": None, "empty": TimeInterval(), "19-21": TimeInterval(at(2019), at(2021)),
          "20-22": TimeInterval(at(2020), at(2022)), "21-23": TimeInterval(at(2021), at(2023)),
          "19-": TimeInterval(at(2019)), "22-": TimeInterval(at(2022)), "-20": TimeInterval(None, at(2020))}
# Recorded at the signed-off baseline f175f03, before any B1 change.
RELATION_AT_F175F03 = {
    "none|none": "unknown", "none|empty": "unknown", "none|19-21": "unknown", "none|20-22": "unknown",
    "none|21-23": "unknown", "none|19-": "unknown", "none|22-": "unknown", "none|-20": "unknown",
    "empty|empty": "unknown", "empty|19-21": "unknown", "empty|20-22": "unknown", "empty|21-23": "unknown",
    "empty|19-": "unknown", "empty|22-": "unknown", "empty|-20": "unknown", "19-21|19-21": "overlap",
    "19-21|20-22": "overlap", "19-21|21-23": "disjoint", "19-21|19-": "unknown", "19-21|22-": "disjoint",
    "19-21|-20": "unknown", "20-22|20-22": "overlap", "20-22|21-23": "overlap", "20-22|19-": "unknown",
    "20-22|22-": "disjoint", "20-22|-20": "disjoint", "21-23|21-23": "overlap", "21-23|19-": "unknown",
    "21-23|22-": "unknown", "21-23|-20": "disjoint", "19-|19-": "unknown", "19-|22-": "unknown",
    "19-|-20": "unknown", "22-|22-": "unknown", "22-|-20": "disjoint", "-20|-20": "unknown"}


def test_comparison_of_every_existing_interval_shape_is_unchanged():
    observed = {f"{a}|{b}": _temporal_relation(SHAPES[a], SHAPES[b]).value
                for a, b in itertools.combinations_with_replacement(SHAPES, 2)}
    assert observed == RELATION_AT_F175F03


def test_comparison_does_not_read_the_new_fields_in_b1():
    """Deliberately temporary: B3 teaches comparison the new contract and revises this test with a recorded reason."""
    plain = TimeInterval(at(2019), at(2021))
    enriched = TimeInterval(at(2019), at(2021), start_latest=at(2020), end_earliest=at(2020, 6))
    for other in SHAPES.values():
        assert _temporal_relation(enriched, other) is _temporal_relation(plain, other)
    assert _temporal_relation(TimeInterval(at(2019), end_unbounded=True), TimeInterval(at(2019), end_unbounded=True)) \
        is _temporal_relation(TimeInterval(at(2019)), TimeInterval(at(2019)))


# --------------------------------------------------------------------------
# E. Meaning: an event's occurrence is not a state's validity; observation is not validity
# --------------------------------------------------------------------------

def test_an_event_can_be_an_exact_moment():
    o = contract("Occurrence")(at(2021, 3, 5, 13), at(2021, 3, 5, 13))
    assert o.earliest == o.latest == at(2021, 3, 5, 13) and o.status is status("EXACT")


def test_an_event_within_a_window():
    o = contract("Occurrence")(at(2021), at(2022))  # "left in 2021"
    assert (o.earliest, o.latest) == (at(2021), at(2022)) and o.status is status("WITHIN")


def test_an_event_bounded_on_one_side_or_not_at_all():
    Occurrence = contract("Occurrence")
    assert Occurrence(latest=at(2024, 3, 5)).status is status("NO_LATER_THAN")
    assert Occurrence(earliest=at(2024, 3, 5)).status is status("NO_EARLIER_THAN")
    assert Occurrence().status is status("UNKNOWN")
    assert Occurrence(latest=at(2024, 3, 5)).earliest is None  # nothing invented


def test_invalid_occurrences_are_refused():
    Occurrence = contract("Occurrence")
    with pytest.raises(ValueError, match="earliest must not be later than latest"):
        Occurrence(at(2022), at(2021))
    with pytest.raises(ValueError, match="timezone-aware"):
        Occurrence(dt.datetime(2021, 1, 1))
    for value in NOT_A_DATETIME:
        with pytest.raises(ValueError, match="Occurrence.latest must be a datetime"):
            Occurrence(latest=value)
    with pytest.raises(dataclasses.FrozenInstanceError):
        Occurrence(at(2021), at(2021)).latest = at(2022)


def test_an_event_proposition_carries_an_occurrence_and_no_validity_interval():
    left = Proposition("p1", "asha", "left_job", "manipal", occurred=contract("Occurrence")(at(2021), at(2022)))
    assert left.valid_time is None  # the event is not turned into a continuing state
    assert left.occurred.earliest == at(2021) and left.occurred.latest == at(2022)


def test_a_proposition_cannot_be_both_a_state_and_an_event():
    with pytest.raises(ValueError, match="either valid_time .* or occurred"):
        Proposition("p1", "asha", "left_job", "manipal", valid_time=TimeInterval(at(2021)),
                    occurred=contract("Occurrence")(at(2021), at(2021)))


def test_occurred_must_be_an_occurrence():
    with pytest.raises(ValueError, match="occurred must be an Occurrence"):
        Proposition("p1", "asha", "left_job", "manipal", occurred=TimeInterval(at(2021)))
    with pytest.raises(TypeError):  # keyword-only: it cannot arrive as a tenth positional argument
        Proposition("p1", "asha", "left_job", "manipal", True, engram_erc.PropositionKind.ASSERTION, (), None, {},
                    contract("Occurrence")())


def test_observation_time_stays_separate_from_validity_time():
    seen = Evidence("e1", "s1", SourceKind.ENGRAM_MEMORY, observed_at=at(2024, 3, 5))
    assert seen.observed_at == at(2024, 3, 5) and seen.valid_time is None  # seeing it then says nothing of when it held
    held = Evidence("e2", "s2", SourceKind.ENGRAM_MEMORY, valid_time=TimeInterval(at(2019), at(2021)))
    assert held.observed_at is None and held.valid_time.start == at(2019)
    assert [f.name for f in dataclasses.fields(Evidence)] == [  # Evidence is unchanged in B1 (decision D8)
        "id", "source_ref", "source_kind", "evidence_kind", "observed_at", "valid_time", "reliability_score",
        "reliability_method", "metadata"]


# --------------------------------------------------------------------------
# Snapshot fingerprint (engram_erc/generalization.py)
# --------------------------------------------------------------------------

def _case(*propositions):
    return RegressionCase("c1", tuple(propositions), ())


WORKS = dict(id="p1", subject="asha", predicate="works_at", object_value="manipal")
# Recorded at the signed-off baseline f175f03, before any B1 change.
FINGERPRINT_AT_F175F03 = "3e36f30f8303d673fd2285efce23cd65dd38a4aa72ceb9e4c07d6b4d9d1c7d54"


def test_snapshot_fingerprint_of_existing_propositions_is_unchanged():
    case = _case(Proposition(**WORKS, valid_time=TimeInterval(at(2019), at(2021))),
                 Proposition("p2", "manipal", "located_in", "bengaluru"),
                 Proposition("p3", "asha", "lives_in", "pune", valid_time=TimeInterval(at(2020))))
    assert _snapshot_fingerprint(case) == FINGERPRINT_AT_F175F03


NEW_FIELD_VARIANTS = [  # (field, start, end, the new field's value); built inside the test, not at import
    ("start_latest", at(2019), at(2021), dict(start_latest=at(2020))),
    ("end_earliest", at(2019), at(2021), dict(end_earliest=at(2020))),
    ("start_is_lower_bound", at(2019), at(2021), dict(start_is_lower_bound=True)),
    ("end_is_upper_bound", at(2019), at(2021), dict(end_is_upper_bound=True)),
    ("start_unbounded", None, at(2021), dict(start_unbounded=True)),
    ("end_unbounded", at(2019), None, dict(end_unbounded=True)),
]


@pytest.mark.parametrize("name,start,end,extra", NEW_FIELD_VARIANTS, ids=[v[0] for v in NEW_FIELD_VARIANTS])
def test_snapshot_fingerprint_sees_every_new_interval_field(name, start, end, extra):
    assert list(extra) == [name]
    enriched, legacy = TimeInterval(start, end, **extra), TimeInterval(start, end)
    assert _snapshot_fingerprint(_case(Proposition(**WORKS, valid_time=enriched))) \
        != _snapshot_fingerprint(_case(Proposition(**WORKS, valid_time=legacy)))


def test_snapshot_fingerprint_sees_an_occurrence():
    Occurrence = contract("Occurrence")
    silent = _snapshot_fingerprint(_case(Proposition(**WORKS)))
    year = _snapshot_fingerprint(_case(Proposition(**WORKS, occurred=Occurrence(at(2021), at(2022)))))
    moment = _snapshot_fingerprint(_case(Proposition(**WORKS, occurred=Occurrence(at(2021), at(2021)))))
    unknown = _snapshot_fingerprint(_case(Proposition(**WORKS, occurred=Occurrence())))
    assert len({silent, year, moment, unknown}) == 4


# --------------------------------------------------------------------------
# Release
# --------------------------------------------------------------------------

def test_the_new_contract_names_are_public():
    for name in ("BoundaryStatus", "Occurrence"):
        assert name in engram_erc.__all__ and getattr(engram_erc, name) is getattr(engram_erc.contracts, name)
