"""Evidence relation accounting without fabricated confidence aggregation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..contracts import Evidence, EvidenceKind, EvidenceRelation
from ..graph import ReasoningGraphView


class EvidenceAssessmentStatus(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    CONFLICT = "conflict"
    QUALIFIED = "qualified"
    SUPPORTED_WITH_QUALIFICATIONS = "supported_with_qualifications"
    NO_LINKED_EVIDENCE = "no_linked_evidence"


@dataclass(frozen=True, slots=True)
class EvidenceAssessment:
    proposition_id: str
    status: EvidenceAssessmentStatus
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    qualifying_evidence_ids: tuple[str, ...]
    evidence_count: int
    reliability_scores_present: int
    limitations: tuple[str, ...]


def assess_evidence(
    view: ReasoningGraphView,
    proposition_id: str,
) -> EvidenceAssessment:
    """Summarise explicit evidence links.

    This is relation accounting, not a quality score or truth probability.
    Reliability values are reported only as presence/absence; no weighting or
    averaging is performed.
    """
    if proposition_id not in view.propositions:
        raise KeyError(f"unknown proposition: {proposition_id}")

    grouped = view.evidence_by_relation(proposition_id)
    supporting = grouped["supports"]
    contradicting = grouped["contradicts"]
    qualifying = grouped["qualifies"]
    all_evidence = supporting + contradicting + qualifying

    if not all_evidence:
        status = EvidenceAssessmentStatus.NO_LINKED_EVIDENCE
    elif supporting and contradicting:
        status = EvidenceAssessmentStatus.CONFLICT
    elif supporting and qualifying:
        status = EvidenceAssessmentStatus.SUPPORTED_WITH_QUALIFICATIONS
    elif supporting:
        status = EvidenceAssessmentStatus.SUPPORTED
    elif contradicting:
        status = EvidenceAssessmentStatus.CONTRADICTED
    else:
        status = EvidenceAssessmentStatus.QUALIFIED

    limitations = []
    if not all_evidence:
        limitations.append("NO_LINKED_EVIDENCE_DOES_NOT_ESTABLISH_FALSEHOOD")
    if qualifying:
        limitations.append("QUALIFYING_EVIDENCE_REQUIRES_INTERPRETATION")
    if supporting and contradicting:
        limitations.append("CONFLICT_RETAINED_NO_AUTOMATIC_ADJUDICATION")
    if any(item.reliability_score is None for item in all_evidence):
        limitations.append("SOME_EVIDENCE_HAS_NO_ASSESSED_RELIABILITY")
    if any(item.evidence_kind == EvidenceKind.OTHER for item in all_evidence):
        limitations.append("SOME_EVIDENCE_KIND_IS_UNSPECIFIED")

    return EvidenceAssessment(
        proposition_id=proposition_id,
        status=status,
        supporting_evidence_ids=tuple(item.id for item in supporting),
        contradicting_evidence_ids=tuple(item.id for item in contradicting),
        qualifying_evidence_ids=tuple(item.id for item in qualifying),
        evidence_count=len(all_evidence),
        reliability_scores_present=sum(
            item.reliability_score is not None for item in all_evidence
        ),
        limitations=tuple(limitations),
    )
