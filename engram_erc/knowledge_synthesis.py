"""Knowledge synthesis and practice intelligence (ERC-3.8).

Combines caller-adjudicated local longitudinal signals with explicitly linked
external evidence. This is a synthesis and review-candidate layer only: it does
not grade study quality, infer causality, create recommendations, or write to
authoritative knowledge stores.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Iterable

from .contracts import require_aware_datetime, require_nonempty
from .longitudinal_learning import (
    LongitudinalLearningReport, ActionPatternSummary, CasePatternSummary,
)
from .lifecycle import EvidenceClass, EvidenceRelation


class LocalSignal(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    INSUFFICIENT = "insufficient"


class PopulationApplicability(str, Enum):
    MATCH = "match"
    PARTIAL = "partial"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class SynthesisStatus(str, Enum):
    CONCORDANT = "concordant"
    DISCORDANT = "discordant"
    CONFLICTED = "conflicted"
    QUALIFIED = "qualified"
    LOCAL_SIGNAL_ONLY = "local_signal_only"
    EVIDENCE_ONLY = "evidence_only"
    INCOMPARABLE = "incomparable"
    INSUFFICIENT_LOCAL_EXPERIENCE = "insufficient_local_experience"


class PracticeDisposition(str, Enum):
    NO_CHANGE = "no_change"
    EXPERT_REVIEW_CANDIDATE = "expert_review_candidate"
    CONFLICT_REVIEW_REQUIRED = "conflict_review_required"
    INSUFFICIENT_BASIS = "insufficient_basis"


class ReviewDecision(str, Enum):
    ACCEPT_FOR_PRACTICE_REVIEW = "accept_for_practice_review"
    DEFER = "defer"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class LocalPracticeClaim:
    claim_ref: str
    pattern_id: str
    action_pattern: tuple[str, ...]
    learning_statement: str
    local_signal: LocalSignal
    adjudication_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    reviewer_ref: str
    context_key: str
    activity_ref: str

    def __post_init__(self) -> None:
        for name in ("claim_ref", "pattern_id", "learning_statement", "reviewer_ref", "context_key", "activity_ref"):
            require_nonempty(getattr(self, name), name)
        if not self.action_pattern or any(not x.strip() for x in self.action_pattern):
            raise ValueError("action_pattern must contain non-empty action codes")
        for name in ("adjudication_refs", "source_refs"):
            values = getattr(self, name)
            if not values or any(not x.strip() for x in values):
                raise ValueError(f"{name} are required and cannot contain blanks")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")


@dataclass(frozen=True, slots=True)
class ExternalEvidence:
    evidence_ref: str
    claim_ref: str
    relation: EvidenceRelation
    evidence_class: EvidenceClass
    source_ref: str
    appraisal_ref: str
    activity_ref: str
    context_key: str
    action_pattern: tuple[str, ...]
    population_applicability: PopulationApplicability
    independent_of_local_records: bool
    publication_date: datetime | None = None
    outcome_domain: str = ""
    limitations: tuple[str, ...] = ()
    evidence_label: str | None = None

    def __post_init__(self) -> None:
        for name in ("evidence_ref", "claim_ref", "source_ref", "appraisal_ref", "activity_ref", "context_key"):
            require_nonempty(getattr(self, name), name)
        if not self.action_pattern or any(not x.strip() for x in self.action_pattern):
            raise ValueError("action_pattern must contain non-empty action codes")
        if self.publication_date is not None:
            require_aware_datetime(self.publication_date, "publication_date")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("limitations must not contain duplicates")
        if self.evidence_class == EvidenceClass.PRACTITIONER_EXPERIENCE and self.independent_of_local_records:
            raise ValueError("practitioner experience cannot be declared independent external evidence")


@dataclass(frozen=True, slots=True)
class SynthesisPolicy:
    minimum_local_cases: int = 5
    require_independent_external_evidence: bool = True
    require_population_match_for_concordance: bool = True

    def __post_init__(self) -> None:
        if self.minimum_local_cases < 1:
            raise ValueError("minimum_local_cases must be positive")


@dataclass(frozen=True, slots=True)
class EvidenceSynthesisItem:
    evidence_ref: str
    relation: EvidenceRelation
    evidence_class: EvidenceClass
    population_applicability: PopulationApplicability
    source_ref: str
    appraisal_ref: str
    independent: bool
    limitations: tuple[str, ...]
    evidence_label: str | None = None


@dataclass(frozen=True, slots=True)
class PracticeIntelligenceItem:
    claim_ref: str
    pattern_id: str
    activity_ref: str
    context_key: str
    action_pattern: tuple[str, ...]
    learning_statement: str
    local_signal: LocalSignal
    local_case_count: int
    local_action_outcomes: tuple[tuple[str, int], ...]
    evidence_items: tuple[EvidenceSynthesisItem, ...]
    synthesis_status: SynthesisStatus
    disposition: PracticeDisposition
    source_refs: tuple[str, ...]
    adjudication_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeSynthesisReport:
    generated_at: datetime
    items: tuple[PracticeIntelligenceItem, ...]
    excluded_evidence_refs: tuple[str, ...]
    limitations: tuple[str, ...]


def _find_pattern(report: LongitudinalLearningReport, pattern_id: str) -> CasePatternSummary | None:
    return next((p for p in report.patterns if p.pattern_id == pattern_id), None)


def _find_action(report: LongitudinalLearningReport, pattern_id: str, action_pattern: tuple[str, ...]) -> ActionPatternSummary | None:
    return next((a for a in report.action_outcome_summaries
                 if a.pattern_id == pattern_id + "|actions:" + ">".join(action_pattern)), None)


def _synthesize_status(local: LocalSignal, evidence: tuple[ExternalEvidence, ...],
                       comparable: tuple[ExternalEvidence, ...], local_sufficient: bool) -> SynthesisStatus:
    if not local_sufficient:
        return SynthesisStatus.INSUFFICIENT_LOCAL_EXPERIENCE
    if evidence and not comparable:
        return SynthesisStatus.INCOMPARABLE
    if not comparable:
        return SynthesisStatus.LOCAL_SIGNAL_ONLY if local != LocalSignal.INSUFFICIENT else SynthesisStatus.INSUFFICIENT_LOCAL_EXPERIENCE
    supports = any(e.relation == EvidenceRelation.SUPPORTS for e in comparable)
    contradicts = any(e.relation == EvidenceRelation.CONTRADICTS for e in comparable)
    qualifies = any(e.relation == EvidenceRelation.QUALIFIES for e in comparable)
    if supports and contradicts:
        return SynthesisStatus.CONFLICTED
    if qualifies:
        return SynthesisStatus.QUALIFIED
    if local == LocalSignal.INSUFFICIENT:
        return SynthesisStatus.EVIDENCE_ONLY
    if (local == LocalSignal.SUPPORTS and supports) or (local == LocalSignal.CONTRADICTS and contradicts):
        return SynthesisStatus.CONCORDANT
    if (local == LocalSignal.SUPPORTS and contradicts) or (local == LocalSignal.CONTRADICTS and supports):
        return SynthesisStatus.DISCORDANT
    return SynthesisStatus.QUALIFIED


def synthesize_practice_intelligence(
    longitudinal_report: LongitudinalLearningReport,
    claims: Iterable[LocalPracticeClaim],
    external_evidence: Iterable[ExternalEvidence],
    *, generated_at: datetime,
    policy: SynthesisPolicy = SynthesisPolicy(),
) -> KnowledgeSynthesisReport:
    """Synthesize explicit local claims and evidence links for expert review.

    Local claims are caller-adjudicated interpretations; ERC does not infer a
    causal local signal from raw outcome counts. Evidence links are retained only
    when claim, activity, context and exact action sequence match. Partial or
    unknown population applicability can qualify but cannot establish
    concordance when the policy requires a population match.
    """
    require_aware_datetime(generated_at, "generated_at")
    claim_rows = tuple(claims)
    evidence_rows = tuple(external_evidence)
    if len({c.claim_ref for c in claim_rows}) != len(claim_rows):
        raise ValueError("claim_ref values must be unique")
    if len({e.evidence_ref for e in evidence_rows}) != len(evidence_rows):
        raise ValueError("evidence_ref values must be unique")
    items: list[PracticeIntelligenceItem] = []
    excluded: set[str] = set()
    for claim in claim_rows:
        pattern = _find_pattern(longitudinal_report, claim.pattern_id)
        if pattern is None:
            raise ValueError(f"unknown longitudinal pattern: {claim.pattern_id}")
        if pattern.activity_ref != claim.activity_ref or pattern.context_key != claim.context_key:
            raise ValueError(f"claim activity/context mismatch: {claim.claim_ref}")
        action = _find_action(longitudinal_report, claim.pattern_id, claim.action_pattern)
        if action is None:
            raise ValueError(f"unknown action pattern for claim: {claim.claim_ref}")
        if not set(claim.adjudication_refs).issubset(set(pattern.adjudication_refs)):
            raise ValueError(f"claim adjudication references not present in local pattern: {claim.claim_ref}")
        if not set(claim.source_refs).issubset(set(pattern.source_refs)):
            raise ValueError(f"claim source references not present in local pattern: {claim.claim_ref}")

        matching = tuple(e for e in evidence_rows if e.claim_ref == claim.claim_ref)
        comparable: list[ExternalEvidence] = []
        eligible_links: list[ExternalEvidence] = []
        rendered: list[EvidenceSynthesisItem] = []
        for e in matching:
            if e.activity_ref != claim.activity_ref or e.context_key != claim.context_key or e.action_pattern != claim.action_pattern:
                excluded.add(e.evidence_ref)
                continue
            if e.publication_date is not None and e.publication_date > generated_at:
                excluded.add(e.evidence_ref)
                continue
            if policy.require_independent_external_evidence and (not e.independent_of_local_records or e.evidence_class == EvidenceClass.PRACTITIONER_EXPERIENCE):
                excluded.add(e.evidence_ref)
                continue
            eligible_links.append(e)
            rendered.append(EvidenceSynthesisItem(
                e.evidence_ref, e.relation, e.evidence_class, e.population_applicability,
                e.source_ref, e.appraisal_ref, e.independent_of_local_records, e.limitations,
                e.evidence_label,
            ))
            if e.population_applicability == PopulationApplicability.MATCH:
                comparable.append(e)
            elif not policy.require_population_match_for_concordance and e.population_applicability == PopulationApplicability.PARTIAL:
                comparable.append(e)
        local_sufficient = action.sample_size >= policy.minimum_local_cases and action.descriptive_status == "descriptive_summary_available"
        status = _synthesize_status(claim.local_signal, tuple(eligible_links), tuple(comparable), local_sufficient)
        if status == SynthesisStatus.CONCORDANT and claim.local_signal in (LocalSignal.SUPPORTS, LocalSignal.CONTRADICTS):
            disposition = PracticeDisposition.EXPERT_REVIEW_CANDIDATE
        elif status in (SynthesisStatus.CONFLICTED, SynthesisStatus.DISCORDANT):
            disposition = PracticeDisposition.CONFLICT_REVIEW_REQUIRED
        elif status in (SynthesisStatus.INSUFFICIENT_LOCAL_EXPERIENCE, SynthesisStatus.INCOMPARABLE):
            disposition = PracticeDisposition.INSUFFICIENT_BASIS
        else:
            disposition = PracticeDisposition.NO_CHANGE
        local_counts = action.outcome_distribution
        limitations = [
            "Local signal is an explicit caller-adjudicated interpretation; ERC does not infer causality from outcome counts.",
            "External evidence relation, study classification, appraisal reference and population applicability are supplied by the caller; ERC does not independently grade the source.",
            "Concordance is a structured evidence-map result, not proof of causality, effectiveness, generalizability or standard of care.",
            "An expert-review candidate is not an approved practice change or practice recommendation.",
        ]
        if any(e.population_applicability != PopulationApplicability.MATCH for e in rendered):
            limitations.append("Some linked evidence has partial, mismatched or unknown population applicability.")
        if any(e.relation == EvidenceRelation.QUALIFIES for e in rendered):
            limitations.append("Qualifying evidence limits interpretation and should be reviewed alongside supporting and contradicting evidence.")
        items.append(PracticeIntelligenceItem(
            claim.claim_ref, claim.pattern_id, claim.activity_ref, claim.context_key,
            claim.action_pattern, claim.learning_statement, claim.local_signal,
            action.sample_size,
            tuple((name, getattr(local_counts, name)) for name in ("improved", "unchanged", "deteriorated", "adverse_event", "inconclusive", "unknown")),
            tuple(sorted(rendered, key=lambda x: x.evidence_ref)), status, disposition,
            tuple(sorted(set(claim.source_refs) | {e.source_ref for e in rendered})),
            claim.adjudication_refs,
            tuple(limitations),
        ))
    return KnowledgeSynthesisReport(
        generated_at, tuple(items), tuple(sorted(excluded)), (
            "Synthesis is bounded to exact claim, activity, context and action-pattern references; no semantic matching is inferred.",
            "Local observational experience and external published evidence remain distinct source classes.",
            "No treatment effect, causal estimate, individual case prediction, practitioner ranking or practice directive is generated.",
            "The host application remains responsible for privacy minimization, source verification, evidence appraisal and domain governance.",
        ),
    )


@dataclass(frozen=True, slots=True)
class PracticeReview:
    review_id: str
    claim_ref: str
    decision: ReviewDecision
    reviewer_ref: str
    adjudication_ref: str
    rationale: str
    reviewed_at: datetime

    def __post_init__(self) -> None:
        for name in ("review_id", "claim_ref", "reviewer_ref", "adjudication_ref", "rationale"):
            require_nonempty(getattr(self, name), name)
        require_aware_datetime(self.reviewed_at, "reviewed_at")


@dataclass(frozen=True, slots=True)
class PracticeReviewLedger:
    reviews: tuple[PracticeReview, ...] = ()

    def __post_init__(self) -> None:
        ids = [r.review_id for r in self.reviews]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate review_id")

    def append(self, review: PracticeReview) -> "PracticeReviewLedger":
        existing = next((r for r in self.reviews if r.review_id == review.review_id), None)
        if existing:
            if existing == review:
                return self
            raise ValueError("review_id collision with different content")
        if any(r.claim_ref == review.claim_ref for r in self.reviews):
            raise ValueError("a claim may have only one final review in this ledger")
        return PracticeReviewLedger(self.reviews + (review,))


def build_practice_review(
    report: KnowledgeSynthesisReport, *, review_id: str, claim_ref: str,
    decision: ReviewDecision, reviewer_ref: str, adjudication_ref: str,
    rationale: str, reviewed_at: datetime,
) -> PracticeReview:
    if not any(x.claim_ref == claim_ref for x in report.items):
        raise ValueError("unknown claim_ref in synthesis report")
    return PracticeReview(review_id, claim_ref, decision, reviewer_ref,
                          adjudication_ref, rationale, reviewed_at)
