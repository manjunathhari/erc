"""Conservative proposition comparison; no probabilistic scoring."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..contracts import Proposition, TimeInterval


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


def _temporal_relation(left: TimeInterval | None, right: TimeInterval | None) -> TemporalRelation:
    # Unknown boundaries are not silently interpreted as overlap or disjoint.
    if left is None or right is None:
        return TemporalRelation.UNKNOWN
    if left.start is not None and right.end is not None and left.start >= right.end:
        return TemporalRelation.DISJOINT
    if right.start is not None and left.end is not None and right.start >= left.end:
        return TemporalRelation.DISJOINT
    # An overlap is certain only if both intervals have bounded start/end
    # values sufficient to establish intersection.
    if (left.start is not None and left.end is not None
            and right.start is not None and right.end is not None):
        return TemporalRelation.OVERLAP
    return TemporalRelation.UNKNOWN


def compare_propositions(
    left: Proposition,
    right: Proposition,
    *,
    functional_predicates: frozenset[str] = frozenset(),
) -> ComparisonResult:
    """Compare proposition structure and temporal scope.

    A different object is not automatically contradictory. The caller must
    explicitly declare a predicate functional before exclusivity can be inferred.
    """
    same_subject = left.subject == right.subject
    same_predicate = left.predicate == right.predicate
    same_object = left.object_value == right.object_value
    same_polarity = left.polarity == right.polarity
    functional = left.predicate in functional_predicates and same_predicate

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
        temporal_relation=_temporal_relation(left.valid_time, right.valid_time),
        same_subject=same_subject,
        same_predicate=same_predicate,
        same_object=same_object,
        same_polarity=same_polarity,
        functional_predicate=functional,
    )
