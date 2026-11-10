"""B3 - Temporal comparison and compatibility (ERC 0.6.0).

The comparison reads the B1 contract: two periods certainly overlap only if the part of each that is certain shares some
time. The certain part of a period runs from the latest it could have begun to the earliest it could have ended.
"Certainly not overlapping" is untouched, and so is every answer for an interval that uses none of the six B1 fields.
Two events (`occurred`) are compared as events, by their occurrence windows, and never as periods.

Specification: claude/erc-b3-spec.md, frozen 10 Nov 2026, SHA-256 a94eb532e5d8bcfb4fb220bdac72a6875bd1515897656ddb56470aa2339e4c86.
Test numbers (R1.., E1.., V1) are that document's section 7; row numbers are its section 3.2; E-rows its section 3.4.

A test that only says "this stays as it is" passes before B3 exists. Each such test therefore first calls
`the_new_reading_is_in()`, so that every test in this file fails until B3 is implemented.
"""
import datetime as dt
import hashlib
import itertools
import json
from pathlib import Path

import engram_erc
import engram_erc.primitives
from engram_erc import Occurrence, Proposition, TimeInterval as TI, compare_propositions, find_contradictions
from engram_erc.counterfactual import RegressionCase
from engram_erc.generalization import _snapshot_fingerprint
from engram_erc.primitives.comparison import TemporalRelation, _temporal_relation
from engram_erc.primitives.contradiction import ContradictionCertainty
from engram_erc.tests import test_domain_profiles as pins
from engram_erc.tests.test_temporal_contracts import RELATION_AT_F175F03, SHAPES

UTC = dt.timezone.utc
PKG = Path(engram_erc.__file__).parent
OVERLAP, DISJOINT, UNKNOWN = "overlap", "disjoint", "unknown"
DEFINITE, POTENTIAL = ContradictionCertainty.DEFINITE, ContradictionCertainty.POTENTIAL


def at(year, month=1, day=1, hour=0):
    return dt.datetime(year, month, day, hour, tzinfo=UTC)


def end_of(year, month=12, day=31):
    """A period's last instant: bounds are inclusive (B1)."""
    return dt.datetime(year, month, day, 23, 59, 59, 999999, tzinfo=UTC)


def rel(left, right):
    return _temporal_relation(left, right).value


def both_ways(left, right):
    a, b = rel(left, right), rel(right, left)
    assert a == b, f"the comparison is not symmetric: {a} one way, {b} the other"
    return a


def the_new_reading_is_in():
    """Row 1: a state still going from 2019 certainly overlaps one that held from 2020 to 2022. Before B3: unknown."""
    assert rel(TI(at(2019), end_unbounded=True), TI(at(2020), at(2022))) == OVERLAP


def state(pid, obj, interval, polarity=True, predicate="lives_in"):
    return Proposition(pid, "asha", predicate, obj, polarity=polarity, valid_time=interval)


def contradictions(left, right, predicate="lives_in"):
    return [c.certainty for c in find_contradictions([left, right], functional_predicates=frozenset([predicate]))]


# The stand-in end the adapter still sends for an open state: "from 2026", asked 1 March 2026 (B2a, decision OP-9).
STAND_IN = TI(at(2026), at(2026, 3, 2), start_latest=end_of(2026))

# Section 3.2: (row, left, right, the answer at 103d2fd, the answer B3 gives).
ROWS = [
    (1, TI(at(2019), end_unbounded=True), TI(at(2020), at(2022)), UNKNOWN, OVERLAP),
    (2, TI(at(2019), end_unbounded=True), TI(at(2021), end_unbounded=True), UNKNOWN, OVERLAP),
    (3, TI(at(2023), end_unbounded=True), TI(at(2020), at(2022)), DISJOINT, DISJOINT),
    (4, TI(start_unbounded=True, end_unbounded=True), TI(at(2020), at(2022)), UNKNOWN, OVERLAP),
    (5, TI(start_unbounded=True, end_unbounded=True), TI(), UNKNOWN, UNKNOWN),
    (6, TI(at(2021), start_latest=end_of(2021), end_unbounded=True), TI(at(2021), start_latest=end_of(2021), end_unbounded=True),
     UNKNOWN, OVERLAP),
    (7, TI(at(2019), at(2022), end_earliest=at(2021, 1, 2)), TI(at(2021), start_latest=end_of(2021), end_unbounded=True),
     UNKNOWN, UNKNOWN),
    (8, TI(at(2019), at(2022), end_earliest=at(2021, 1, 2)), TI(at(2020), at(2023)), OVERLAP, OVERLAP),
    (9, TI(at(2019), at(2022), end_earliest=at(2021, 1, 2)), TI(at(2021, 2, 10), at(2023)), OVERLAP, UNKNOWN),
    (10, TI(None, at(2022), start_latest=at(2020)), TI(at(2021), at(2023)), UNKNOWN, OVERLAP),
    (11, TI(None, at(2022), start_latest=at(2020)), TI(at(2019), at(2020)), UNKNOWN, UNKNOWN),
    (12, TI(at(2019), end_earliest=at(2021)), TI(at(2020), at(2022)), UNKNOWN, OVERLAP),
    (13, TI(at(2019), at(2022), start_is_lower_bound=True), TI(at(2020), at(2021)), OVERLAP, UNKNOWN),
    (14, TI(at(2019), at(2022), end_is_upper_bound=True), TI(at(2020), at(2021)), OVERLAP, UNKNOWN),
    (15, TI(None, at(2022), end_earliest=at(2021, 1, 2)), TI(at(2019), at(2020)), UNKNOWN, UNKNOWN),
    (16, TI(None, at(2022), end_earliest=at(2021, 1, 2)), TI(at(2022), at(2023)), DISJOINT, DISJOINT),
    (17, STAND_IN, TI(at(2025), at(2027)), OVERLAP, UNKNOWN),
    (18, TI(at(2019)), TI(at(2019)), UNKNOWN, UNKNOWN),
    (19, TI(at(2019), at(2023), start_latest=at(2020), end_earliest=at(2022)),
     TI(at(2021), at(2024), start_latest=at(2022), end_earliest=at(2022, 1, 2)), OVERLAP, UNKNOWN),
]


# --------------------------------------------------------------------------
# R. Two periods
# --------------------------------------------------------------------------

def test_r1_every_shape_of_the_specification_gives_its_stated_answer_both_ways_round():
    observed = {row: both_ways(left, right) for row, left, right, _, _ in ROWS}
    assert observed == {row: after for row, _, _, _, after in ROWS}


def test_r2_two_states_still_going_certainly_overlap_and_are_a_definite_contradiction():
    for row in (1, 2, 6):
        _, left, right, before, after = ROWS[row - 1]
        assert (before, after) == (UNKNOWN, OVERLAP) and both_ways(left, right) == OVERLAP
        assert contradictions(state("a", "Pune", left), state("b", "Delhi", right)) == [DEFINITE]


def test_r3_ended_at_an_unknown_moment_is_not_still_going():
    the_new_reading_is_in()                                                    # still going from 2019: overlap
    assert both_ways(TI(at(2019)), TI(at(2020), at(2022))) == UNKNOWN          # ended, no one knows when: unknown
    assert contradictions(state("a", "Pune", TI(at(2019))), state("b", "Delhi", TI(at(2020), at(2022)))) == [POTENTIAL]


def test_r4_a_window_lowers_certainty_only_when_the_certain_parts_stop_meeting():
    pune = TI(at(2019), at(2022), end_earliest=at(2021, 1, 2))                 # 2019 to some time in 2021
    assert both_ways(pune, TI(at(2020), at(2023))) == OVERLAP                  # row 8: certain through 2020
    assert both_ways(pune, TI(at(2021, 2, 10), at(2023))) == UNKNOWN           # row 9: Pune may have ended by then
    assert contradictions(state("a", "Pune", pune), state("b", "Delhi", TI(at(2020), at(2023)))) == [DEFINITE]
    assert contradictions(state("a", "Pune", pune), state("b", "Delhi", TI(at(2021, 2, 10), at(2023)))) == [POTENTIAL]


def test_r5_one_sided_bounds_are_read():
    observed = {row: both_ways(ROWS[row - 1][1], ROWS[row - 1][2]) for row in (10, 11, 12, 13, 14)}
    assert observed == {10: OVERLAP, 11: UNKNOWN, 12: OVERLAP, 13: UNKNOWN, 14: UNKNOWN}


def test_r6_an_end_with_no_start_gives_no_certain_part_with_or_without_its_end_window():
    for pune in (TI(None, at(2022), end_earliest=at(2021, 1, 2)), TI(None, at(2022))):
        assert both_ways(pune, TI(at(2019), at(2020))) == UNKNOWN              # row 15
        assert both_ways(pune, TI(at(2022), at(2023))) == DISJOINT             # row 16
    # the same end, once a latest start is known, has a certain part (began by 2020, held to 2 Jan 2021 at least)
    assert both_ways(TI(None, at(2022), start_latest=at(2020), end_earliest=at(2021, 1, 2)), TI(at(2020), at(2021))) == OVERLAP


def test_r7_certainly_not_overlapping_is_untouched_by_every_new_field():
    the_new_reading_is_in()
    shapes = [x for _, left, right, _, _ in ROWS for x in (left, right)]
    for a in shapes:
        for b in shapes:
            plain = rel(TI(a.start, a.end), TI(b.start, b.end))   # the same outer bounds with every B1 field dropped
            assert (rel(a, b) == DISJOINT) == (plain == DISJOINT), (a, b)


def test_r8_the_comparison_is_symmetric_for_every_pair_of_shapes():
    the_new_reading_is_in()
    shapes = [None] + [x for _, left, right, _, _ in ROWS for x in (left, right)]
    for a in shapes:
        for b in shapes:
            assert rel(a, b) == rel(b, a), (a, b)


def test_r9_a_period_with_no_certain_part_is_accepted_as_it_is_and_never_certainly_overlaps():
    """OP-9. The stand-in end with a coarse start is accepted, not repaired and not refused; it has no certain part."""
    assert (STAND_IN.start, STAND_IN.start_latest, STAND_IN.end) == (at(2026), end_of(2026), at(2026, 3, 2))
    stated_both_ends = TI(at(2021), at(2021, 4, 1), start_latest=end_of(2021), end_earliest=at(2021, 3, 2))  # from 2021 to March 2021
    for empty in (STAND_IN, stated_both_ends):
        for other in (TI(at(2020), at(2027)), TI(at(2020), end_unbounded=True), TI(start_unbounded=True, end_unbounded=True), empty):
            assert both_ways(empty, other) == UNKNOWN, (empty, other)
    assert both_ways(STAND_IN, TI(at(2026, 3, 2), at(2027))) == DISJOINT       # its end is still read as an end (section 3.3)


def test_r10_the_36_pinned_pairs_are_unchanged_and_bounds_that_do_not_move_the_certain_part_change_nothing():
    the_new_reading_is_in()
    pairs = list(itertools.combinations_with_replacement(SHAPES, 2))
    assert {f"{a}|{b}": rel(SHAPES[a], SHAPES[b]) for a, b in pairs} == RELATION_AT_F175F03
    # A start window on an interval with no end, and an end window on an interval with no start: there was no certain
    # part before the window and there is none after it, so all 36 answers stay.
    windowed = dict(SHAPES)
    windowed["19-"] = TI(at(2019), start_latest=at(2019, 6))
    windowed["22-"] = TI(at(2022), start_latest=at(2022, 6))
    windowed["-20"] = TI(None, at(2020), end_earliest=at(2019, 6))
    assert {f"{a}|{b}": rel(windowed[a], windowed[b]) for a, b in pairs} == RELATION_AT_F175F03


def test_r11_a_shared_start_with_unknown_ends_is_not_a_certain_overlap():
    """F14. Events are still sent as an interval with a start and no end; two said on one day must not become definite."""
    assert both_ways(TI(at(2019)), TI(at(2019))) == UNKNOWN
    assert contradictions(state("a", "Pune", TI(at(2019))), state("b", "Delhi", TI(at(2019)))) == [POTENTIAL]
    assert both_ways(TI(at(2019), end_unbounded=True), TI(at(2019), end_unbounded=True)) == OVERLAP  # the same starts, still going


# Recorded at the signed-off baseline 103d2fd, before any B3 change.
FINGERPRINT_AT_103D2FD = "4bbb10ef4b4a0a6bac3eb1add6214d7070ccd80088b7c53bd458b06ea56c582d"


def test_r12_the_snapshot_fingerprint_is_unchanged_while_the_comparison_of_the_same_propositions_changes():
    pune = state("p1", "Pune", TI(at(2019), at(2022), start_latest=end_of(2019), end_earliest=at(2021, 1, 2)))
    delhi = state("p2", "Delhi", TI(at(2021, 2, 10), end_unbounded=True))
    assert _snapshot_fingerprint(RegressionCase("c1", (pune, delhi), ())) == FINGERPRINT_AT_103D2FD
    assert compare_propositions(pune, delhi).temporal_relation.value == UNKNOWN   # at 103d2fd this is also unknown ...
    still = state("p3", "Mysore", TI(at(2019), end_unbounded=True))
    assert compare_propositions(still, delhi).temporal_relation.value == OVERLAP  # ... and this one changes


def test_r13_the_honest_spelling_of_an_open_state_restores_the_definite_contradiction():
    """The named limitation of B3 and its cure. S02: two homes, both from "2024", asked 5 March 2024. With the stand-in end
    the adapter still sends, neither has a certain part; said honestly as still going, they certainly overlap.
    S16: a genuinely closed end stays uncertain however the other value's end is spelled. Not revised at B2b."""
    stand_in = TI(at(2024), at(2024, 3, 6), start_latest=end_of(2024))
    assert both_ways(stand_in, stand_in) == UNKNOWN
    assert contradictions(state("a", "Bengaluru", stand_in), state("b", "Mysore", stand_in)) == [POTENTIAL]
    honest = TI(at(2024), start_latest=end_of(2024), end_unbounded=True)
    assert both_ways(honest, honest) == OVERLAP
    assert contradictions(state("a", "Bengaluru", honest), state("b", "Mysore", honest)) == [DEFINITE]
    closed = TI(at(2024), at(2024, 3, 6), start_latest=end_of(2024))            # Apollo from "2024", left on 5 March 2024
    first_said_open = TI(at(2024, 3, 5), end_unbounded=True)                   # Manipal, first said that day, still going
    assert both_ways(closed, first_said_open) == UNKNOWN
    assert contradictions(state("a", "Apollo", closed, predicate="works_at"),
                          state("b", "Manipal", first_said_open, predicate="works_at"), "works_at") == [POTENTIAL]


def test_r14_the_comparison_reads_no_qualifier():
    """Section 3.1 and breakage 14. The adapter labels where a boundary came from (start_basis, end_basis). Those labels are
    the adapter's; the comparison decides from the bounding instants alone, so the same intervals give the same answer
    with any label, including the two a reader might be tempted to act on."""
    the_new_reading_is_in()
    said, stand_in = TI(at(2024, 3, 5), at(2024, 3, 6)), TI(at(2024), at(2024, 3, 6), start_latest=end_of(2024))
    for left, right, expected in ((said, said, OVERLAP), (stand_in, stand_in, UNKNOWN), (said, stand_in, UNKNOWN)):
        answers = set()
        for labels in ({}, {"start_basis": "first_said", "end_basis": "open"}, {"start_basis": "stated", "end_basis": "open"},
                       {"start_basis": "first_said", "end_basis": "closed"}):
            a = Proposition("a", "asha", "lives_in", "Pune", valid_time=left, qualifiers=labels)
            b = Proposition("b", "asha", "lives_in", "Delhi", valid_time=right, qualifiers=labels)
            answers.add(compare_propositions(a, b).temporal_relation.value)
        assert answers == {expected}, (left, right, answers)


# --------------------------------------------------------------------------
# E. Two events (OP-3, section 3.4)
# --------------------------------------------------------------------------

def event(pid, obj, occurred, polarity=True):
    return Proposition(pid, "asha", "moved_to", obj, polarity=polarity, occurred=occurred)


def events(left, right):
    a = compare_propositions(left, right).temporal_relation.value
    b = compare_propositions(right, left).temporal_relation.value
    assert a == b
    found = find_contradictions([left, right], functional_predicates=frozenset(["moved_to"]))
    return a, [c.certainty for c in found]


def year(y):
    return Occurrence(at(y), end_of(y))


def moment(*parts):
    return Occurrence(at(*parts), at(*parts))


def test_e1_events_whose_windows_cannot_meet_are_disjoint_and_never_contradict():
    assert events(event("a", "Pune", moment(2022)), event("b", "Delhi", moment(2023))) == (DISJOINT, [])                 # E1
    assert events(event("a", "Pune", year(2022)), event("b", "Delhi", year(2023))) == (DISJOINT, [])                     # E2a
    assert events(event("a", "Pune", Occurrence(latest=at(2021))), event("b", "Delhi", Occurrence(earliest=at(2022)))) \
        == (DISJOINT, [])                                                                                                # E4a


def test_e2_events_whose_windows_may_meet_are_unknown_and_at_most_a_potential_contradiction():
    the_new_reading_is_in()
    cases = {
        "E2b": (year(2022), year(2022)),
        "E2c": (moment(2022, 6), year(2022)),
        "E2d": (Occurrence(at(2021), at(2022)), Occurrence(at(2022), at(2023))),  # one shared instant: bounds are inclusive
        "E4b": (Occurrence(latest=at(2022)), Occurrence(earliest=at(2021))),
        "E4c": (Occurrence(), moment(2022)),
    }
    for name, (left, right) in cases.items():
        assert events(event("a", "Pune", left), event("b", "Delhi", right)) == (UNKNOWN, [POTENTIAL]), name


def test_e3_the_same_exact_instant_is_a_certain_coincidence():
    assert events(event("a", "Pune", moment(2022)), event("b", "Delhi", moment(2022))) == (OVERLAP, [DEFINITE])          # E3a
    affirmed, denied = event("a", "Pune", moment(2022)), event("b", "Pune", moment(2022), polarity=False)
    assert compare_propositions(affirmed, denied).temporal_relation.value == OVERLAP                                     # E3b
    assert [c.certainty for c in find_contradictions([affirmed, denied])] == [DEFINITE]   # no one-value list needed


def test_e4_an_event_is_never_compared_with_a_state_as_if_both_were_periods():
    the_new_reading_is_in()
    happened = event("a", "Pune", moment(2022))
    held = Proposition("b", "asha", "moved_to", "Delhi", valid_time=TI(at(2021), at(2023)))
    silent = Proposition("b", "asha", "moved_to", "Delhi")
    assert events(happened, held) == (UNKNOWN, [POTENTIAL])                                                              # E4d
    assert events(happened, silent) == (UNKNOWN, [POTENTIAL])                                                            # E4e
    # two states still go to the comparison of periods (row 9 through compare_propositions)
    _, left, right, _, after = ROWS[8]
    assert compare_propositions(state("a", "Pune", left), state("b", "Delhi", right)).temporal_relation.value == after == UNKNOWN


def test_e5_an_event_still_sent_as_an_interval_is_compared_as_an_interval_exactly_as_before():
    """Until B2b the adapter sends an event as TimeInterval(date, None). The dispatch reads `occurred` only."""
    the_new_reading_is_in()
    pune = Proposition("a", "asha", "moved_to", "Pune", valid_time=TI(at(2022)))
    delhi = Proposition("b", "asha", "moved_to", "Delhi", valid_time=TI(at(2023)))
    same_day = Proposition("c", "asha", "moved_to", "Delhi", valid_time=TI(at(2022)))
    assert events(pune, delhi) == (UNKNOWN, [POTENTIAL])
    assert events(pune, same_day) == (UNKNOWN, [POTENTIAL])


# --------------------------------------------------------------------------
# V. Version, pins and public names
# --------------------------------------------------------------------------

PUBLIC_NAMES_AT_103D2FD = (300, "80ce1eda47d019cdc9403366bbca2072eb3fb6768e5f12435b9be451ecbaea4b")
PRIMITIVE_NAMES_AT_103D2FD = ["ComparisonKind", "ComparisonResult", "Contradiction", "ContradictionCertainty", "EvidenceAssessment",
                              "EvidenceAssessmentStatus", "TemporalRelation", "assess_evidence", "compare_propositions",
                              "find_contradictions"]


def test_v1_version_and_release_pin():
    assert engram_erc.__version__ == (PKG / "VERSION").read_text().strip() == "0.6.0"
    digest, release, reason = pins.ERC_1X_RELEASE_PINS["primitives/comparison.py"]
    assert release == "0.6.0" and "B3" in reason
    assert digest == hashlib.sha256((PKG / "primitives/comparison.py").read_bytes()).hexdigest() != pins.ERC_1X_SHA256_AT_0_4_0["primitives/comparison.py"]
    assert pins.ERC_1X_FILES_CHANGED_SINCE_0_4_0 == {"contracts.py", "primitives/comparison.py"}
    # the contradiction layer is not touched: still its 0.4.0 bytes
    assert hashlib.sha256((PKG / "primitives/contradiction.py").read_bytes()).hexdigest() == pins.ERC_1X_SHA256_AT_0_4_0["primitives/contradiction.py"]


def test_v1_nothing_new_is_public_and_the_relation_keeps_its_three_values():
    """OP-5, OP-6, OP-7. Kept apart from the pin test above so that the deliberate-breakage suite, which must leave the
    byte pin out (every mutation changes the bytes), can still run this one."""
    the_new_reading_is_in()
    names = sorted(engram_erc.__all__)
    assert (len(names), hashlib.sha256(json.dumps(names).encode()).hexdigest()) == PUBLIC_NAMES_AT_103D2FD
    assert sorted(engram_erc.primitives.__all__) == PRIMITIVE_NAMES_AT_103D2FD
    assert [r.value for r in TemporalRelation] == [OVERLAP, DISJOINT, UNKNOWN]
