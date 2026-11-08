"""Governed knowledge promotion and lifecycle records.

This module creates immutable governance records and adapter contracts only. It
never writes to an authoritative knowledge base or treats experience as proof.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable

from .contracts import require_aware_datetime
from .consolidation import ExperienceCandidate, ConsolidationStatus


class KnowledgeStage(str, Enum):
    EXPERIENCE_CANDIDATE = "experience_candidate"
    EXPERT_REVIEWED = "expert_reviewed"
    EVIDENCE_CORROBORATED = "evidence_corroborated"
    EXTERNALLY_VALIDATED = "externally_validated"
    PRACTICE_ELIGIBLE = "practice_eligible"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"


class EvidenceClass(str, Enum):
    """Domain-neutral evidence classes.

    ``PRACTITIONER_EXPERIENCE`` is local experience. It is never counted as
    independent external corroboration, by lifecycle promotion or by synthesis.
    A domain profile maps its own evidence types onto these classes and may
    keep its own wording in ``evidence_label``; rules read only the class.
    """
    PRACTITIONER_EXPERIENCE = "practitioner_experience"
    RECORDS_ANALYSIS = "records_analysis"
    PUBLISHED_STUDY = "published_study"
    SYSTEMATIC_REVIEW = "systematic_review"
    STANDARD_OR_GUIDELINE = "standard_or_guideline"
    EXPERT_OPINION = "expert_opinion"
    OTHER = "other"


class LifecycleAction(str, Enum):
    ADVANCE = "advance"
    REJECT = "reject"
    SUPERSEDE = "supersede"
    RETIRE = "retire"


@dataclass(frozen=True, slots=True)
class EvidenceLinkRecord:
    evidence_ref: str
    relation: EvidenceRelation
    evidence_class: EvidenceClass
    source_ref: str
    claim_ref: str
    context_key: str
    publication_or_observation_date: datetime | None = None
    independent_of_candidate_experience: bool = False
    limitations: tuple[str, ...] = ()
    evidence_label: str | None = None

    def __post_init__(self) -> None:
        for field in ("evidence_ref", "source_ref", "claim_ref", "context_key"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must be non-empty")
        if self.publication_or_observation_date is not None:
            require_aware_datetime(self.publication_or_observation_date, "publication_or_observation_date")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("limitations must not contain duplicates")
        if self.evidence_class == EvidenceClass.PRACTITIONER_EXPERIENCE and self.independent_of_candidate_experience:
            raise ValueError("practitioner experience cannot be declared independent literature corroboration")


@dataclass(frozen=True, slots=True)
class ExternalValidationRecord:
    validation_ref: str
    cohort_ref: str
    site_ref: str
    context_key: str
    result_ref: str
    adjudication_ref: str
    observed_at: datetime
    passed: bool
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("validation_ref", "cohort_ref", "site_ref", "context_key", "result_ref", "adjudication_ref"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must be non-empty")
        require_aware_datetime(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    require_independent_evidence: bool = True
    minimum_external_sites: int = 2
    allow_qualified_evidence_only: bool = False

    def __post_init__(self) -> None:
        if self.minimum_external_sites < 1:
            raise ValueError("minimum_external_sites must be >= 1")


@dataclass(frozen=True, slots=True)
class PromotionAssessment:
    candidate_id: str
    current_stage: KnowledgeStage
    proposed_stage: KnowledgeStage
    eligible: bool
    blockers: tuple[str, ...]
    supporting_evidence_refs: tuple[str, ...]
    contradicting_evidence_refs: tuple[str, ...]
    qualifying_evidence_refs: tuple[str, ...]
    external_validation_refs: tuple[str, ...]
    external_sites: tuple[str, ...]
    limitations: tuple[str, ...]


def assess_promotion(
    candidate: ExperienceCandidate,
    *,
    evidence: tuple[EvidenceLinkRecord, ...] = (),
    external_validations: tuple[ExternalValidationRecord, ...] = (),
    policy: PromotionPolicy = PromotionPolicy(),
) -> PromotionAssessment:
    """Assess evidence gates; does not advance state or write to a knowledge store."""
    if candidate.status != ConsolidationStatus.REVIEWED:
        blockers = ["CANDIDATE_NOT_ACCEPTED_FOR_KNOWLEDGE_REVIEW"]
    else:
        blockers = []
    matching = tuple(e for e in evidence if e.claim_ref == candidate.candidate_id)
    context_matched = tuple(e for e in matching if e.context_key == candidate.context_key)
    supporting = tuple(sorted(e.evidence_ref for e in context_matched if e.relation == EvidenceRelation.SUPPORTS))
    contradicting = tuple(sorted(e.evidence_ref for e in context_matched if e.relation == EvidenceRelation.CONTRADICTS))
    qualifying = tuple(sorted(e.evidence_ref for e in context_matched if e.relation == EvidenceRelation.QUALIFIES))
    independent_support = tuple(e for e in context_matched if e.relation == EvidenceRelation.SUPPORTS
                                and e.independent_of_candidate_experience
                                and e.evidence_class != EvidenceClass.PRACTITIONER_EXPERIENCE)
    if contradicting:
        blockers.append("CONTRADICTORY_EVIDENCE_REQUIRES_EXPERT_RESOLUTION")
    if not supporting and not (policy.allow_qualified_evidence_only and qualifying):
        blockers.append("NO_LINKED_SUPPORTING_EVIDENCE")
    if policy.require_independent_evidence and not independent_support:
        blockers.append("NO_INDEPENDENT_EVIDENCE_CORROBORATION")

    valid_external = tuple(v for v in external_validations
                           if v.context_key == candidate.context_key and v.passed)
    sites = tuple(sorted({v.site_ref for v in valid_external}))
    if any(not v.passed and v.context_key == candidate.context_key for v in external_validations):
        blockers.append("FAILED_EXTERNAL_VALIDATION_PRESENT")
    eligible = not blockers
    if not eligible:
        proposed = KnowledgeStage.EXPERT_REVIEWED
    elif len(sites) >= policy.minimum_external_sites:
        proposed = KnowledgeStage.EXTERNALLY_VALIDATED
    else:
        proposed = KnowledgeStage.EVIDENCE_CORROBORATED

    limitations = (
        "Evidence classifications, independence declarations and context matching are caller-supplied metadata; ERC does not grade study quality.",
        "A link to a publication is not proof that its findings apply to this exact case, activity or context.",
        "External validation records must refer to independently adjudicated cohorts; this module validates references and declarations, not raw cohort data.",
        "Eligibility is a governance assessment only; no guideline, standard of practice or authoritative fact is created.",
    )
    return PromotionAssessment(
        candidate.candidate_id, KnowledgeStage.EXPERIENCE_CANDIDATE,
        proposed, eligible, tuple(blockers), supporting, contradicting,
        qualifying, tuple(sorted(v.validation_ref for v in valid_external)),
        sites, limitations,
    )


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    event_id: str
    candidate_id: str
    action: LifecycleAction
    from_stage: KnowledgeStage
    to_stage: KnowledgeStage
    reviewer_ref: str
    adjudication_ref: str
    rationale: str
    occurred_at: datetime
    evidence_refs: tuple[str, ...] = ()
    validation_refs: tuple[str, ...] = ()
    supersedes_candidate_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("event_id", "candidate_id", "reviewer_ref", "adjudication_ref", "rationale"):
            if not getattr(self, field).strip():
                raise ValueError(f"{field} must be non-empty")
        require_aware_datetime(self.occurred_at, "occurred_at")
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("evidence_refs must be unique")
        if len(self.validation_refs) != len(set(self.validation_refs)):
            raise ValueError("validation_refs must be unique")
        if self.action == LifecycleAction.SUPERSEDE and not self.supersedes_candidate_id:
            raise ValueError("superseding requires supersedes_candidate_id")
        if self.supersedes_candidate_id == self.candidate_id:
            raise ValueError("a candidate cannot supersede itself")
        if self.to_stage == KnowledgeStage.EVIDENCE_CORROBORATED and not self.evidence_refs:
            raise ValueError("evidence-corroborated state requires evidence references")
        if self.to_stage in (KnowledgeStage.EXTERNALLY_VALIDATED, KnowledgeStage.PRACTICE_ELIGIBLE):
            if not self.validation_refs:
                raise ValueError("externally validated/practice-eligible state requires validation references")
            if not self.evidence_refs:
                raise ValueError("externally validated/practice-eligible state requires evidence references")


@dataclass(frozen=True, slots=True)
class KnowledgeLifecycleLedger:
    events: tuple[LifecycleEvent, ...] = ()

    def __post_init__(self) -> None:
        ids = [e.event_id for e in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate lifecycle event_id")
        state: dict[str, KnowledgeStage] = {}
        terminal = {KnowledgeStage.REJECTED, KnowledgeStage.SUPERSEDED, KnowledgeStage.RETIRED}
        for event in self.events:
            current = state.get(event.candidate_id, KnowledgeStage.EXPERIENCE_CANDIDATE)
            if event.from_stage != current:
                raise ValueError(f"lifecycle from_stage mismatch for {event.candidate_id}")
            if current in terminal:
                raise ValueError(f"terminal lifecycle state cannot advance: {event.candidate_id}")
            allowed = {
                LifecycleAction.ADVANCE: {
                    (KnowledgeStage.EXPERIENCE_CANDIDATE, KnowledgeStage.EXPERT_REVIEWED),
                    (KnowledgeStage.EXPERT_REVIEWED, KnowledgeStage.EVIDENCE_CORROBORATED),
                    (KnowledgeStage.EVIDENCE_CORROBORATED, KnowledgeStage.EXTERNALLY_VALIDATED),
                    (KnowledgeStage.EXTERNALLY_VALIDATED, KnowledgeStage.PRACTICE_ELIGIBLE),
                },
                LifecycleAction.REJECT: {(s, KnowledgeStage.REJECTED) for s in KnowledgeStage if s not in terminal},
                LifecycleAction.SUPERSEDE: {(s, KnowledgeStage.SUPERSEDED) for s in KnowledgeStage if s not in terminal},
                LifecycleAction.RETIRE: {(s, KnowledgeStage.RETIRED) for s in KnowledgeStage if s not in terminal},
            }
            if (event.from_stage, event.to_stage) not in allowed[event.action]:
                raise ValueError("invalid lifecycle transition")
            state[event.candidate_id] = event.to_stage

    def append(self, event: LifecycleEvent) -> "KnowledgeLifecycleLedger":
        existing = {e.event_id: e for e in self.events}
        if event.event_id in existing:
            if existing[event.event_id] != event:
                raise ValueError("lifecycle event ID collision")
            return self
        return KnowledgeLifecycleLedger(self.events + (event,))

    def current_stage(self, candidate_id: str) -> KnowledgeStage:
        stage = KnowledgeStage.EXPERIENCE_CANDIDATE
        for event in self.events:
            if event.candidate_id == candidate_id:
                stage = event.to_stage
        return stage


@runtime_checkable
class KnowledgeStoreAdapter(Protocol):
    """Boundary to Engram's existing stores; implement with existing DB/KB APIs.

    Implementations must not create a parallel store. Calls are deliberately
    explicit and should be made only after caller-side transaction/adjudication.
    """
    def fetch_candidate(self, candidate_id: str) -> ExperienceCandidate | None: ...
    def fetch_evidence_links(self, candidate_id: str) -> tuple[EvidenceLinkRecord, ...]: ...
    def fetch_external_validations(self, candidate_id: str) -> tuple[ExternalValidationRecord, ...]: ...
    def append_lifecycle_event(self, event: LifecycleEvent) -> None: ...


def build_lifecycle_event(
    *, event_id: str, candidate_id: str, action: LifecycleAction,
    current_stage: KnowledgeStage, reviewer_ref: str, adjudication_ref: str,
    rationale: str, occurred_at: datetime,
    assessment: PromotionAssessment | None = None,
    supersedes_candidate_id: str | None = None,
) -> LifecycleEvent:
    """Build an explicit reviewer action with guardrails around stage advancement."""
    if action == LifecycleAction.ADVANCE:
        transitions = {
            KnowledgeStage.EXPERIENCE_CANDIDATE: KnowledgeStage.EXPERT_REVIEWED,
            KnowledgeStage.EXPERT_REVIEWED: KnowledgeStage.EVIDENCE_CORROBORATED,
            KnowledgeStage.EVIDENCE_CORROBORATED: KnowledgeStage.EXTERNALLY_VALIDATED,
            KnowledgeStage.EXTERNALLY_VALIDATED: KnowledgeStage.PRACTICE_ELIGIBLE,
        }
        target = transitions.get(current_stage)
        if target is None:
            raise ValueError("no forward transition from current stage")
        if target == KnowledgeStage.EXPERT_REVIEWED:
            # The explicit reviewer/adjudication is the gate at this stage.
            evidence_refs, validation_refs = (), ()
        else:
            if assessment is None or not assessment.eligible:
                raise ValueError("later advancement requires an eligible promotion assessment")
            if assessment.candidate_id != candidate_id:
                raise ValueError("assessment candidate mismatch")
            required_stage = KnowledgeStage.EVIDENCE_CORROBORATED if target == KnowledgeStage.EVIDENCE_CORROBORATED else KnowledgeStage.EXTERNALLY_VALIDATED
            order = list(KnowledgeStage)
            if order.index(assessment.proposed_stage) < order.index(required_stage):
                raise ValueError("assessment has not met the target stage gate")
            if target == KnowledgeStage.EVIDENCE_CORROBORATED and not assessment.supporting_evidence_refs:
                raise ValueError("evidence corroboration requires supporting evidence refs")
            if target == KnowledgeStage.EXTERNALLY_VALIDATED and not assessment.external_validation_refs:
                raise ValueError("external validation requires validation refs")
            evidence_refs, validation_refs = assessment.supporting_evidence_refs, assessment.external_validation_refs
    else:
        target = {
            LifecycleAction.REJECT: KnowledgeStage.REJECTED,
            LifecycleAction.SUPERSEDE: KnowledgeStage.SUPERSEDED,
            LifecycleAction.RETIRE: KnowledgeStage.RETIRED,
        }[action]
        evidence_refs = assessment.supporting_evidence_refs if assessment else ()
        validation_refs = assessment.external_validation_refs if assessment else ()
    return LifecycleEvent(event_id, candidate_id, action, current_stage, target,
                          reviewer_ref, adjudication_ref, rationale, occurred_at,
                          evidence_refs, validation_refs, supersedes_candidate_id)
