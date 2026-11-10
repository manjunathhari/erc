"""Conservative proposition comparison; no probabilistic scoring.

ERC 0.6.0 (increment B3): the temporal relation reads the whole temporal contract. Two states certainly overlap only if
the part of each that is certain shares some time; two events are compared as events, by their occurrence windows.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..contracts import Occurrence, Proposition, TimeInterval


class ComparisonKind(str, Enum):
    SAME_CLAIM = "same_claim"
    OPPOSITE_POLARITY = "opposite_polarity"
    DIFFERENT_OBJECT = "different_object"
    DIFFERENT_SUBJECT = "different_subject"
    DIFFERENT_PREDICATE = "different_predicate"


class TemporalRelation(str, Enum):
    OVERLAP = "overlap"
    DISJOINT = "disjoint"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    left_id: str
    right_id: str
    kind: ComparisonKind
    temporal_relation: TemporalRelation
    same_subject: bool
    same_predicate: bool
    same_object: bool
    same_polarity: bool
    functional_predicate: bool = False


_ALWAYS = object()  # an unbounded start: the state has no beginning as far as is stated
_NEVER = object()   # an unbounded end: the state is still going


def _latest_possible_start(interval: TimeInterval) -> Any:
    """The latest instant at which the state could have begun, or None when nothing guarantees it had begun."""
    if interval.start_unbounded:
        return _ALWAYS
    if interval.start_latest is not None:
        return interval.start_latest  # within a window, or "no later than"
    if interval.start is not None and not interval.start_is_lower_bound:
        return interval.start  # exact
    return None  # a start not known, or a lower bound only


def _earliest_possible_end(interval: TimeInterval) -> Any:
    """The earliest instant at which the state could have ended, or None when nothing guarantees it lasted."""
    if interval.end_unbounded:
        return _NEVER
    if interval.end_earliest is not None:
        return interval.end_earliest  # within a window, or "no earlier than"
    if interval.end is not None and not interval.end_is_upper_bound:
        return interval.end  # exact
    return None  # an end not known, or an upper bound only


def _temporal_relation(left: TimeInterval | None, right: TimeInterval | None) -> TemporalRelation:
    """How two states' validity intervals stand to each other.

    DISJOINT: one could not have begun before the other had certainly ended. `start` is the earliest a state could have
    begun and `end` the latest it could have ended (the 0.5.0 contract), so this test is the one it always was.
    OVERLAP: the certain part of each (from its latest possible start to its earliest possible end) shares time with
    the other's. For two intervals with exact starts and ends this is the answer it always was.
    UNKNOWN: anything else. A boundary that is not known is never read as overlap or as disjoint, and an end that is
    not known is not an end that has not come: only `end_unbounded` says a state is still going.
    """
    if left is None or right is None:
        return TemporalRelation.UNKNOWN
    if left.start is not None and right.end is not None and left.start >= right.end:
        return TemporalRelation.DISJOINT
    if right.start is not None and left.end is not None and right.start >= left.end:
        return TemporalRelation.DISJOINT
    begins = [_latest_possible_start(left), _latest_possible_start(right)]
    ends = [_earliest_possible_end(left), _earliest_possible_end(right)]
    if None in begins or None in ends:
        return TemporalRelation.UNKNOWN  # one of the two has no certain part
    begins = [instant for instant in begins if instant is not _ALWAYS]
    ends = [instant for instant in ends if instant is not _NEVER]
    # An interval whose latest possible start is not before its earliest possible end has an empty certain part and
    # can never satisfy this: the later of the two starts is then at or after the earlier of the two ends.
    if not begins or not ends or max(begins) < min(ends):
        return TemporalRelation.OVERLAP
    return TemporalRelation.UNKNOWN


def _occurrence_relation(left: Occurrence, right: Occurrence) -> TemporalRelation:
    """How two events' occurrence windows stand to each other. Both bounds of a window belong to it.

    DISJOINT: the windows cannot meet. OVERLAP: both are exact and, not being disjoint, are one and the same instant.
    UNKNOWN: the windows may meet, or a bound is not known. An occurrence is a moment, never a period.
    """
    if left.latest is not None and right.earliest is not None and left.latest < right.earliest:
        return TemporalRelation.DISJOINT
    if right.latest is not None and left.earliest is not None and right.latest < left.earliest:
        return TemporalRelation.DISJOINT
    if _is_exact(left) and _is_exact(right):
        return TemporalRelation.OVERLAP
    return TemporalRelation.UNKNOWN


def _is_exact(occurrence: Occurrence) -> bool:
    return occurrence.earliest is not None and occurrence.earliest == occurrence.latest


def compare_propositions(
    left: Proposition,
    right: Proposition,
    *,
    functional_predicates: frozenset[str] = frozenset(),
) -> ComparisonResult:
    """Compare proposition structure and temporal scope.

    A different object is not automatically contradictory. The caller must
    explicitly declare a predicate functional before exclusivity can be inferred.

    Temporal scope: two events (`occurred`) are compared by their occurrence windows, two states by their validity
    intervals. An event and a state are different kinds of time and are never compared as if both were periods.
    No qualifier is read.
    """
    same_subject = left.subject == right.subject
    same_predicate = left.predicate == right.predicate
    same_object = left.object_value == right.object_value
    same_polarity = left.polarity == right.polarity
    functional = left.predicate in functional_predicates and same_predicate

    if left.occurred is not None and right.occurred is not None:
        temporal_relation = _occurrence_relation(left.occurred, right.occurred)
    elif left.occurred is not None or right.occurred is not None:
        temporal_relation = TemporalRelation.UNKNOWN
    else:
        temporal_relation = _temporal_relation(left.valid_time, right.valid_time)

    if not same_subject:
        kind = ComparisonKind.DIFFERENT_SUBJECT
    elif not same_predicate:
        kind = ComparisonKind.DIFFERENT_PREDICATE
    elif not same_object:
        kind = ComparisonKind.DIFFERENT_OBJECT
    elif not same_polarity:
        kind = ComparisonKind.OPPOSITE_POLARITY
    else:
        kind = ComparisonKind.SAME_CLAIM

    return ComparisonResult(
        left_id=left.id,
        right_id=right.id,
        kind=kind,
        temporal_relation=temporal_relation,
        same_subject=same_subject,
        same_predicate=same_predicate,
        same_object=same_object,
        same_polarity=same_polarity,
        functional_predicate=functional,
    )
