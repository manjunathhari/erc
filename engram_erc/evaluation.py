"""Evidence-aware conclusion evaluation and explicit reporting decisions."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .contracts import (
    Evidence, EvidenceLink, EvidenceRelation, Proposition, PropositionKind,
    ReasoningResult, UncertaintyKind,
)
from .graph import ReasoningGraphBuilder, ReasoningGraphView
from .primitives.evidence_assessment import (
    EvidenceAssessment, EvidenceAssessmentStatus, assess_evidence,
)
from .primitives.contradiction import ContradictionCertainty, find_contradictions


class ConclusionDecision(str, Enum):
    ACCEPTED = "accepted"
    PROVISIONAL = "provisional"
    WITHHELD = "withheld"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"


class EscalationLevel(str, Enum):
    NONE = "none"
    REVIEW = "review"
    EXPERT_ADJUDICATION = "expert_adjudication"
    SOURCE_RETRIEVAL = "source_retrieval"


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """Transparent thresholds; intentionally no hidden evidence weighting."""
    min_supporting_sources_per_leaf: int = 1
    require_support_for_every_leaf: bool = True
    require_no_contradicting_evidence: bool = True
    allow_qualifying_evidence_for_acceptance: bool = False
    require_complete_premise_lineage: bool = True
    functional_predicates: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.min_supporting_sources_per_leaf < 0:
            raise ValueError("min_supporting_sources_per_leaf cannot be negative")


@dataclass(frozen=True, slots=True)
class PremiseCoverage:
    conclusion_id: str
    leaf_premise_ids: tuple[str, ...]
    covered_leaf_ids: tuple[str, ...]
    uncovered_leaf_ids: tuple[str, ...]
    unresolved_refs: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class ConclusionEvaluation:
    conclusion_id: str
    decision: ConclusionDecision
    escalation: EscalationLevel
    premise_coverage: PremiseCoverage
    evidence_assessments: tuple[EvidenceAssessment, ...]
    supporting_source_count: int
    contradicting_source_count: int
    qualifying_source_count: int
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    request_id: str
    policy: DecisionPolicy
    evaluations: tuple[ConclusionEvaluation, ...]
    accepted_refs: tuple[str, ...]
    provisional_refs: tuple[str, ...]
    withheld_refs: tuple[str, ...]
    conflicted_refs: tuple[str, ...]
    rejected_refs: tuple[str, ...]
    overall_decision: ConclusionDecision
    escalation: EscalationLevel


def _make_view(result: ReasoningResult, evidence, evidence_links) -> ReasoningGraphView:
    builder = ReasoningGraphBuilder()
    for proposition in result.propositions:
        builder.add_proposition(proposition)
    for item in evidence:
        builder.add_evidence(item)
    for link in evidence_links:
        builder.link_evidence(link)
    for step in result.inference_steps:
        builder.add_inference(step)
        builder.connect_inference(
            step.id,
            premise_proposition_ids=step.input_refs,
            output_proposition_ids=step.output_proposition_refs,
        )
    graph = builder.build()
    return ReasoningGraphView(graph, result.propositions, evidence, result.inference_steps)


def _premise_lineage(conclusion_id: str, result: ReasoningResult):
    """Return assertion/hypothesis leaves and unresolved references.

    A derived proposition is expanded through every inference step that creates
    it. Missing producers are reported rather than treated as source facts.
    """
    propositions = {p.id: p for p in result.propositions}
    producers: dict[str, list[tuple[str, ...]]] = {}
    for step in result.inference_steps:
        for output_id in step.output_proposition_refs:
            producers.setdefault(output_id, []).append(step.input_refs)

    leaves: set[str] = set()
    unresolved: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(ref: str):
        if ref in visiting:
            unresolved.add(ref)
            return
        if ref in visited:
            return
        proposition = propositions.get(ref)
        if proposition is None:
            unresolved.add(ref)
            return
        visiting.add(ref)
        branches = producers.get(ref, [])
        if proposition.kind == PropositionKind.INFERENCE and not branches:
            unresolved.add(ref)
        elif proposition.kind != PropositionKind.INFERENCE:
            leaves.add(ref)
        else:
            # Multiple producers mean alternative derivations. Conservatively
            # require every recorded derivation's premises for complete lineage.
            for branch in branches:
                for premise in branch:
                    walk(premise)
        visiting.remove(ref)
        visited.add(ref)

    walk(conclusion_id)
    return tuple(sorted(leaves)), tuple(sorted(unresolved))


def evaluate_conclusions(
    result: ReasoningResult,
    *,
    evidence: tuple[Evidence, ...] = (),
    evidence_links: tuple[EvidenceLink, ...] = (),
    policy: DecisionPolicy = DecisionPolicy(),
) -> EvaluationReport:
    """Evaluate whether each conclusion is justified for reporting.

    This is a deterministic gate, not truth adjudication. Evidence counts are
    counts of distinct linked evidence records, not independent studies or
    statistical weight. REJECTED is reserved for explicit, complete contrary
    evidence under the configured policy; ambiguous or missing evidence is
    WITHHELD instead.
    """
    view = _make_view(result, evidence, evidence_links)
    proposition_map = {p.id: p for p in result.propositions}
    contradictions = find_contradictions(
        result.propositions, functional_predicates=policy.functional_predicates
    )
    evaluations = []

    for conclusion_id in result.conclusion_refs:
        leaves, unresolved = _premise_lineage(conclusion_id, result)
        assessments = tuple(assess_evidence(view, ref) for ref in leaves)
        by_id = {a.proposition_id: a for a in assessments}
        covered = tuple(sorted(
            ref for ref, assessment in by_id.items()
            if len(assessment.supporting_evidence_ids) >= policy.min_supporting_sources_per_leaf
        ))
        uncovered = tuple(sorted(set(leaves) - set(covered)))
        supporting = sum(len(a.supporting_evidence_ids) for a in assessments)
        contradicting = sum(len(a.contradicting_evidence_ids) for a in assessments)
        qualifying = sum(len(a.qualifying_evidence_ids) for a in assessments)
        definite_conflicts = tuple(
            c for c in contradictions
            if c.certainty == ContradictionCertainty.DEFINITE
            and (c.left_id == conclusion_id or c.right_id == conclusion_id
                 or c.left_id in leaves or c.right_id in leaves)
        )
        potential_conflicts = tuple(
            c for c in contradictions
            if c.certainty == ContradictionCertainty.POTENTIAL
            and (c.left_id == conclusion_id or c.right_id == conclusion_id
                 or c.left_id in leaves or c.right_id in leaves)
        )

        complete = not unresolved and (not policy.require_complete_premise_lineage or bool(leaves))
        coverage = PremiseCoverage(
            conclusion_id=conclusion_id,
            leaf_premise_ids=leaves,
            covered_leaf_ids=covered,
            uncovered_leaf_ids=uncovered,
            unresolved_refs=unresolved,
            complete=complete,
        )
        reasons: list[str] = []
        limitations: list[str] = []
        all_leaves_contradicted = bool(leaves) and all(
            by_id[ref].contradicting_evidence_ids
            and not by_id[ref].supporting_evidence_ids
            for ref in leaves
        )
        mixed_support_and_contradiction = any(
            a.supporting_evidence_ids and a.contradicting_evidence_ids
            for a in assessments
        )
        if definite_conflicts or (mixed_support_and_contradiction and policy.require_no_contradicting_evidence):
            decision = ConclusionDecision.CONFLICTED
            escalation = EscalationLevel.EXPERT_ADJUDICATION
            reasons.append("CONTRADICTORY_CLAIM_OR_MIXED_EVIDENCE_REQUIRES_ADJUDICATION")
        elif all_leaves_contradicted and policy.require_no_contradicting_evidence:
            decision = ConclusionDecision.REJECTED
            escalation = EscalationLevel.EXPERT_ADJUDICATION
            reasons.append("ALL_ROOT_PREMISES_HAVE_EXPLICIT_CONTRARY_EVIDENCE")
        elif contradicting and policy.require_no_contradicting_evidence:
            decision = ConclusionDecision.CONFLICTED
            escalation = EscalationLevel.EXPERT_ADJUDICATION
            reasons.append("CONTRADICTING_EVIDENCE_REQUIRES_ADJUDICATION")
        elif not complete:
            decision = ConclusionDecision.WITHHELD
            escalation = EscalationLevel.REVIEW
            reasons.append("PREMISE_LINEAGE_INCOMPLETE")
        elif uncovered and policy.require_support_for_every_leaf:
            decision = ConclusionDecision.WITHHELD
            escalation = EscalationLevel.SOURCE_RETRIEVAL
            reasons.append("ONE_OR_MORE_ROOT_PREMISES_LACK_REQUIRED_SUPPORT")
        elif contradicting and not policy.require_no_contradicting_evidence:
            decision = ConclusionDecision.PROVISIONAL
            escalation = EscalationLevel.REVIEW
            reasons.append("CONTRADICTING_EVIDENCE_PRESENT_BUT_POLICY_ALLOWS_PROVISIONAL_REVIEW")
        elif qualifying and not policy.allow_qualifying_evidence_for_acceptance:
            decision = ConclusionDecision.PROVISIONAL
            escalation = EscalationLevel.REVIEW
            reasons.append("QUALIFYING_EVIDENCE_REQUIRES_INTERPRETATION")
        elif potential_conflicts:
            decision = ConclusionDecision.PROVISIONAL
            escalation = EscalationLevel.REVIEW
            reasons.append("POTENTIAL_CONTRADICTION_REQUIRES_SCOPE_REVIEW")
        elif policy.require_support_for_every_leaf and supporting < policy.min_supporting_sources_per_leaf * len(leaves):
            decision = ConclusionDecision.WITHHELD
            escalation = EscalationLevel.SOURCE_RETRIEVAL
            reasons.append("MINIMUM_SUPPORT_THRESHOLD_NOT_MET")
        else:
            decision = ConclusionDecision.ACCEPTED
            escalation = EscalationLevel.NONE
            reasons.append("PREMISE_LINEAGE_COMPLETE_AND_SUPPORT_THRESHOLD_MET")

        if any(a.status == EvidenceAssessmentStatus.CONFLICT for a in assessments):
            limitations.append("CONFLICTING_EVIDENCE_RETAINED_NOT_WEIGHTED")
        if any(a.status == EvidenceAssessmentStatus.NO_LINKED_EVIDENCE for a in assessments):
            limitations.append("NO_LINKED_EVIDENCE_IS_NOT_EVIDENCE_OF_FALSEHOOD")
        if qualifying:
            limitations.append("QUALIFYING_EVIDENCE_NOT_AUTOMATICALLY_RESOLVED")
        if any(
            item.reliability_score is None
            for a in assessments
            for item in evidence
            if item.id in (
                a.supporting_evidence_ids + a.contradicting_evidence_ids
                + a.qualifying_evidence_ids
            )
        ):
            limitations.append("RELIABILITY_NOT_ASSESSED_FOR_ALL_LINKED_SOURCES")
        evaluations.append(ConclusionEvaluation(
            conclusion_id=conclusion_id,
            decision=decision,
            escalation=escalation,
            premise_coverage=coverage,
            evidence_assessments=assessments,
            supporting_source_count=supporting,
            contradicting_source_count=contradicting,
            qualifying_source_count=qualifying,
            reasons=tuple(reasons),
            limitations=tuple(dict.fromkeys(limitations)),
        ))

    decisions = [item.decision for item in evaluations]
    if not decisions:
        overall = ConclusionDecision.WITHHELD
        escalation = EscalationLevel.REVIEW
    elif ConclusionDecision.CONFLICTED in decisions:
        overall = ConclusionDecision.CONFLICTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    elif all(d == ConclusionDecision.ACCEPTED for d in decisions):
        overall = ConclusionDecision.ACCEPTED
        escalation = EscalationLevel.NONE
    elif all(d == ConclusionDecision.REJECTED for d in decisions):
        overall = ConclusionDecision.REJECTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    elif ConclusionDecision.REJECTED in decisions and ConclusionDecision.ACCEPTED in decisions:
        overall = ConclusionDecision.CONFLICTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    elif ConclusionDecision.PROVISIONAL in decisions:
        overall = ConclusionDecision.PROVISIONAL
        escalation = EscalationLevel.REVIEW
    elif ConclusionDecision.REJECTED in decisions:
        overall = ConclusionDecision.REJECTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    else:
        overall = ConclusionDecision.WITHHELD
        escalation = EscalationLevel.SOURCE_RETRIEVAL

    def refs(decision):
        return tuple(item.conclusion_id for item in evaluations if item.decision == decision)

    return EvaluationReport(
        request_id=result.request_id,
        policy=policy,
        evaluations=tuple(evaluations),
        accepted_refs=refs(ConclusionDecision.ACCEPTED),
        provisional_refs=refs(ConclusionDecision.PROVISIONAL),
        withheld_refs=refs(ConclusionDecision.WITHHELD),
        conflicted_refs=refs(ConclusionDecision.CONFLICTED),
        rejected_refs=refs(ConclusionDecision.REJECTED),
        overall_decision=overall,
        escalation=escalation,
    )
