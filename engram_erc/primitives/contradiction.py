"""Contradiction detection with explicit certainty and conservative defaults."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import Iterable

from ..contracts import Proposition
from .comparison import (
    ComparisonKind, TemporalRelation, compare_propositions,
)


class ContradictionCertainty(str, Enum):
    DEFINITE = "definite"
    POTENTIAL = "potential"


@dataclass(frozen=True, slots=True)
class Contradiction:
    left_id: str
    right_id: str
    certainty: ContradictionCertainty
    reason_code: str
    explanation: str


def compare_for_contradiction(
    left: Proposition,
    right: Proposition,
    *,
    functional_predicates: frozenset[str] = frozenset(),
) -> Contradiction | None:
    comparison = compare_propositions(
        left, right, functional_predicates=functional_predicates
    )
    if not comparison.same_subject or not comparison.same_predicate:
        return None

    opposite_same_claim = (
        comparison.kind == ComparisonKind.OPPOSITE_POLARITY
    )
    mutually_exclusive_values = (
        comparison.kind == ComparisonKind.DIFFERENT_OBJECT
        and comparison.functional_predicate
    )
    if not (opposite_same_claim or mutually_exclusive_values):
        return None

    if comparison.temporal_relation == TemporalRelation.DISJOINT:
        return None

    if comparison.temporal_relation == TemporalRelation.OVERLAP:
        certainty = ContradictionCertainty.DEFINITE
    else:
        certainty = ContradictionCertainty.POTENTIAL

    if opposite_same_claim:
        reason = "OPPOSITE_POLARITY_SAME_CLAIM"
        explanation = (
            "The propositions assert opposite polarities for the same "
            "subject, predicate and object."
        )
    else:
        reason = "MUTUALLY_EXCLUSIVE_FUNCTIONAL_VALUES"
        explanation = (
            "The propositions assign different values to a predicate "
            "explicitly declared functional by the caller."
        )

    if certainty == ContradictionCertainty.POTENTIAL:
        explanation += " Their temporal scopes are not known to overlap."
    return Contradiction(left.id, right.id, certainty, reason, explanation)


def find_contradictions(
    propositions: Iterable[Proposition],
    *,
    functional_predicates: frozenset[str] = frozenset(),
) -> tuple[Contradiction, ...]:
    """Find pairwise contradictions; does not mutate propositions or graph."""
    items = tuple(propositions)
    results = []
    for left, right in combinations(items, 2):
        result = compare_for_contradiction(
            left, right, functional_predicates=functional_predicates
        )
        if result is not None:
            results.append(result)
    return tuple(results)
