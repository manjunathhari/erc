"""Deterministic, model-independent reasoning primitives."""
from .comparison import (
    ComparisonKind, ComparisonResult, TemporalRelation, compare_propositions,
)
from .contradiction import (
    Contradiction, ContradictionCertainty, find_contradictions,
)
from .evidence_assessment import (
    EvidenceAssessment, EvidenceAssessmentStatus, assess_evidence,
)

__all__ = [
    "ComparisonKind", "ComparisonResult", "TemporalRelation",
    "compare_propositions", "Contradiction", "ContradictionCertainty",
    "find_contradictions", "EvidenceAssessment",
    "EvidenceAssessmentStatus", "assess_evidence",
]
