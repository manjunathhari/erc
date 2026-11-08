"""Human-governed reasoning improvement proposals.

Proposals are review artifacts derived from ERC-1.9 descriptive trace metrics.
They are not executable patches and never mutate rules, strategy catalogues,
evidence, P6, registry records, or persistent stores.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Iterable

from .feedback import FeedbackLedger, OutcomeLabel
from .trace_learning import TraceLearningReport, TracePatternMetric, TraceStepMetric


class ProposalKind(str, Enum):
    REVIEW_REASONING_PATH = "review_reasoning_path"
    REVIEW_RULE_APPLICATION = "review_rule_application"
    REVIEW_PREMISE_REQUIREMENTS = "review_premise_requirements"


class ReviewDisposition(str, Enum):
    ACCEPT_FOR_MANUAL_CHANGE = "accept_for_manual_change"
    REJECT = "reject"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class ImprovementPolicy:
    min_adjudicated_events: int = 5
    min_contradicted_events: int = 1
    include_step_proposals: bool = True
    include_path_proposals: bool = True
    include_premise_proposals: bool = True

    def __post_init__(self) -> None:
        if self.min_adjudicated_events < 1:
            raise ValueError("min_adjudicated_events must be at least 1")
        if self.min_contradicted_events < 1:
            raise ValueError("min_contradicted_events must be at least 1")


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    proposal_id: str
    kind: ProposalKind
    target_refs: tuple[str, ...]
    context_key: str
    path_signature: tuple[str, ...]
    premise_signature: tuple[str, ...]
    verified_count: int
    contradicted_count: int
    inconclusive_count: int
    superseded_count: int
    event_refs: tuple[str, ...]
    adjudication_source_refs: tuple[str, ...]
    notes_refs: tuple[str, ...]
    observed_success_rate: float | None
    question_for_review: str
    suggested_review: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProposalReport:
    proposals: tuple[ImprovementProposal, ...]
    skipped_below_threshold: int
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProposalReview:
    proposal_id: str
    disposition: ReviewDisposition
    reviewer_ref: str
    reviewed_at: str
    rationale: str

    def __post_init__(self) -> None:
        for field_name in ("proposal_id", "reviewer_ref", "reviewed_at", "rationale"):
            if not getattr(self, field_name) or not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class ProposalReviewLedger:
    """Immutable review history; acceptance authorizes manual work only."""
    reviews: tuple[ProposalReview, ...] = ()

    def __post_init__(self) -> None:
        keys = [(r.proposal_id, r.reviewer_ref, r.reviewed_at) for r in self.reviews]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate proposal review record")

    def append(self, review: ProposalReview) -> "ProposalReviewLedger":
        if review in self.reviews:
            return self
        return ProposalReviewLedger(self.reviews + (review,))


def _id(kind: ProposalKind, targets: tuple[str, ...], context: str,
        path: tuple[str, ...], premises: tuple[str, ...]) -> str:
    raw = "|".join((kind.value, *targets, context, *path, *premises))
    return "erc-proposal-" + sha256(raw.encode("utf-8")).hexdigest()[:20]


def _event_refs(ledger: FeedbackLedger, refs: tuple[str, ...]):
    lookup = {e.event_id: e for e in ledger.events}
    selected = [lookup[r] for r in refs if r in lookup]
    contradicted = [e for e in selected if e.outcome == OutcomeLabel.CONTRADICTED]
    return (
        tuple(sorted(e.event_id for e in contradicted)),
        tuple(sorted({e.adjudication_source_ref for e in contradicted})),
        tuple(sorted({e.notes_ref for e in contradicted if e.notes_ref})),
    )


def _proposal(kind: ProposalKind, targets: tuple[str, ...], context: str,
              path: tuple[str, ...], premises: tuple[str, ...], counts,
              event_refs: tuple[str, ...], ledger: FeedbackLedger,
              question: str, review: str) -> ImprovementProposal:
    contradicted_refs, adjudication_refs, notes_refs = _event_refs(ledger, event_refs)
    return ImprovementProposal(
        _id(kind, targets, context, path, premises), kind, targets, context,
        path, premises, counts.verified_supported, counts.contradicted,
        counts.inconclusive, counts.superseded, event_refs,
        adjudication_refs, notes_refs, counts.observed_success_rate,
        question, review,
        ("Descriptive association only; no causal attribution is established.",
         "A contradicted conclusion does not by itself prove that the implicated rule is defective.",
         "This proposal is a review prompt, not an executable rule patch or practice recommendation."),
    )


def generate_improvement_proposals(
    trace_report: TraceLearningReport,
    ledger: FeedbackLedger,
    *,
    policy: ImprovementPolicy = ImprovementPolicy(),
) -> ProposalReport:
    """Create review prompts from eligible trace patterns and steps.

    Only explicitly linked contradicted events supply adjudication provenance.
    A proposal is emitted only when both sample and contradiction thresholds
    are met. No source or rule attribution is inferred from co-occurrence.
    """
    proposals: dict[str, ImprovementProposal] = {}
    skipped = 0
    for pattern in trace_report.patterns:
        counts = pattern.counts
        if not pattern.eligible_for_comparison or counts.adjudicated < policy.min_adjudicated_events or counts.contradicted < policy.min_contradicted_events:
            skipped += 1
            continue
        if policy.include_path_proposals:
            item = _proposal(
                ProposalKind.REVIEW_REASONING_PATH, pattern.path_signature,
                pattern.context_key, pattern.path_signature,
                pattern.root_premise_signature, counts, pattern.event_refs, ledger,
                "Which interaction or ordering within this recorded path should be examined?",
                "Review the complete inference chain, intermediate propositions, and rule interactions against the adjudication records.",
            )
            proposals[item.proposal_id] = item
        if policy.include_premise_proposals and pattern.root_premise_signature:
            item = _proposal(
                ProposalKind.REVIEW_PREMISE_REQUIREMENTS, pattern.path_signature,
                pattern.context_key, pattern.path_signature,
                pattern.root_premise_signature, counts, pattern.event_refs, ledger,
                "Were the recorded root premises sufficient, current, and correctly scoped for this conclusion?",
                "Review missing-premise possibilities, temporal scope, applicability conditions, and whether additional evidence gates are needed.",
            )
            proposals[item.proposal_id] = item

    if policy.include_step_proposals:
        for step in trace_report.steps:
            counts = step.counts
            if not step.eligible_for_comparison or counts.adjudicated < policy.min_adjudicated_events or counts.contradicted < policy.min_contradicted_events:
                skipped += 1
                continue
            item = _proposal(
                ProposalKind.REVIEW_RULE_APPLICATION, (step.rule_id,),
                step.context_key, (f"{step.operation}:{step.rule_id}",), (),
                counts, step.event_refs, ledger,
                "Under what conditions did this rule application appear in contradicted conclusion lineages?",
                "Inspect the rule's applicability conditions, input quality, temporal assumptions, and boundary cases. Do not change the rule without independent validation.",
            )
            proposals[item.proposal_id] = item

    ordered = tuple(sorted(proposals.values(), key=lambda p: (p.kind.value, p.context_key, p.target_refs, p.proposal_id)))
    return ProposalReport(ordered, skipped, (
        "Proposals are generated only from eligible ERC-1.9 metrics and explicitly linked contradicted outcomes.",
        "Adjudication source and notes references are provenance pointers, not proof of causal responsibility.",
        "Accepting a proposal authorizes consideration of a manual change; it does not apply or persist a change.",
        "No automatic rule, strategy, evidence, registry, or P6 mutation occurs.",
    ))
