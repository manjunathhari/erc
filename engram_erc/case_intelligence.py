"""ERC-4.0 General Core: case intelligence execution and adaptive reasoning.

Deterministic composition of existing ERC capabilities over caller-supplied,
immutable snapshots. This is an orchestration layer, not a new knowledge store.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Iterable

from .application import GovernedKnowledge, CaseContext
from .adaptation import (AdaptationPolicy, AdaptationReport, StrategyExperienceScore, rank_catalog_strategies)
from .feedback import FeedbackLedger
from .contracts import ReasoningRequest, require_aware_datetime, require_nonempty
from .decision_support import (
    DecisionOption, DecisionSupportReport, DecisionSupportRequest,
    EscalationTrigger, build_decision_support,
)
from .experience_reasoning import (
    ExperienceComparisonPolicy, ExperienceReasoningReport,
    HistoricalExperienceDetail, compare_case_experience,
)
from .knowledge_graph import (
    CrossDomainPolicy, CrossDomainQuery, CrossDomainReasoningReport,
    DomainKnowledgeGraph, reason_across_domains,
)
from .lifecycle import KnowledgeLifecycleLedger
from .orchestration import OrchestrationLimits, StrategyCatalog, default_strategy_catalog
from .rules import RuleSet
from .situation_awareness import (
    ObservationEvent, SituationLedger, SituationPolicy, SituationReport,
    TriggerRule, evaluate_situation,
)
from .task_orchestration import (
    CaseReasoningPolicy, CaseReasoningReport,
    orchestrate_case_reasoning,
)
from .temporal_patterns import (
    HistoricalEpisode, CaseTrajectory, TemporalMatchPolicy,
    TemporalPatternReport, match_temporal_experience,
)


class ExecutionStatus(str, Enum):
    COMPLETED_FOR_REVIEW = "completed_for_review"
    REVIEW_REQUIRED = "review_required"
    SAFETY_GATE_BLOCKED = "safety_gate_blocked"
    INSUFFICIENT_INPUT = "insufficient_input"


class ExecutionStage(str, Enum):
    SITUATION_ASSESSMENT = "situation_assessment"
    KNOWLEDGE_GRAPH_RETRIEVAL = "knowledge_graph_retrieval"
    ADAPTIVE_STRATEGY_SELECTION = "adaptive_strategy_selection"
    CONTEXTUAL_REASONING = "contextual_reasoning"
    TEMPORAL_COMPARISON = "temporal_comparison"
    EXPERIENCE_COMPARISON = "experience_comparison"
    DECISION_STRUCTURING = "decision_structuring"


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    block_on_severity: tuple[str, ...] = ("critical",)
    require_situation_assessment: bool = False
    require_reasoning: bool = True
    require_temporal_comparison: bool = False
    require_decision_structuring: bool = False
    include_cross_domain_candidates: bool = True

    def __post_init__(self) -> None:
        if len(set(self.block_on_severity)) != len(self.block_on_severity):
            raise ValueError("block_on_severity must be unique")
        if any(not x.strip() for x in self.block_on_severity):
            raise ValueError("block_on_severity entries must be non-empty")


@dataclass(frozen=True, slots=True)
class CaseIntelligenceRequest:
    request_id: str
    generated_at: datetime
    reasoning_request: ReasoningRequest
    case_context: CaseContext
    governed_knowledge: tuple[GovernedKnowledge, ...]
    lifecycle: KnowledgeLifecycleLedger
    situation_rules: tuple[TriggerRule, ...] = ()
    observations: tuple[ObservationEvent, ...] = ()
    situation_ledger: SituationLedger = SituationLedger()
    knowledge_graph: DomainKnowledgeGraph | None = None
    cross_domain_queries: tuple[CrossDomainQuery, ...] = ()
    current_trajectory: CaseTrajectory | None = None
    historical_episodes: tuple[HistoricalEpisode, ...] = ()
    experience_details: tuple[HistoricalExperienceDetail, ...] = ()
    decision_options: tuple[DecisionOption, ...] = ()
    escalation_triggers: tuple[EscalationTrigger, ...] = ()
    context_tags: tuple[str, ...] = ()
    feedback_ledger: FeedbackLedger | None = None
    external_strategy_scores: tuple[StrategyExperienceScore, ...] = ()
    profile_id: str = "general"
    profile_version: str = "1.0.0"

    def __post_init__(self) -> None:
        require_nonempty(self.request_id, "request_id")
        require_nonempty(self.profile_id, "profile_id")
        require_nonempty(self.profile_version, "profile_version")
        require_aware_datetime(self.generated_at, "generated_at")
        if len(set(self.context_tags)) != len(self.context_tags):
            raise ValueError("context_tags must be unique")
        if self.generated_at < self.case_context.as_of:
            raise ValueError("generated_at cannot precede case_context.as_of")
        if self.generated_at < self.reasoning_request.as_of:
            raise ValueError("generated_at cannot precede reasoning_request.as_of")
        if self.cross_domain_queries and self.knowledge_graph is None:
            raise ValueError("cross_domain_queries require knowledge_graph")
        if self.experience_details and self.current_trajectory is None:
            raise ValueError("experience_details require current_trajectory")
        if self.historical_episodes and self.current_trajectory is None:
            raise ValueError("historical_episodes require current_trajectory")
        if self.current_trajectory and self.generated_at < self.current_trajectory.recorded_at:
            raise ValueError("generated_at cannot precede current trajectory")


@dataclass(frozen=True, slots=True)
class StageResult:
    stage: ExecutionStage
    status: str
    detail_refs: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseIntelligenceReport:
    request_id: str
    generated_at: datetime
    status: ExecutionStatus
    stages: tuple[StageResult, ...]
    situation: SituationReport | None
    cross_domain: CrossDomainReasoningReport | None
    reasoning: CaseReasoningReport | None
    temporal: TemporalPatternReport | None
    experience: ExperienceReasoningReport | None
    decision_support: DecisionSupportReport | None
    adaptation: AdaptationReport | None
    blocking_signals: tuple[str, ...]
    review_requirements: tuple[str, ...]
    source_refs: tuple[str, ...]
    limitations: tuple[str, ...]
    profile_id: str = "general"
    profile_version: str = "1.0.0"
    replay_fingerprint: str = ""


def _replay_fingerprint(report: CaseIntelligenceReport) -> str:
    """Deterministic identity of a replay: the profile plus every decision-bearing output."""
    payload = {
        "request_id": report.request_id,
        "generated_at": report.generated_at.isoformat(),
        "profile": [report.profile_id, report.profile_version],
        "status": report.status.value,
        "stages": [[s.stage.value, s.status, list(s.detail_refs), list(s.notes)] for s in report.stages],
        "reasoning_status": report.reasoning.status.value if report.reasoning else None,
        "decision_status": report.decision_support.status.value if report.decision_support else None,
        "option_statuses": [[a.option_id, a.status.value] for a in report.decision_support.option_assessments]
        if report.decision_support else [],
        "blocking_signals": list(report.blocking_signals),
        "review_requirements": list(report.review_requirements),
        "source_refs": list(report.source_refs),
        "limitations": list(report.limitations),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "erc-replay-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _finalise(report: CaseIntelligenceReport, request: CaseIntelligenceRequest) -> CaseIntelligenceReport:
    stamped = replace(report, profile_id=request.profile_id, profile_version=request.profile_version)
    return replace(stamped, replay_fingerprint=_replay_fingerprint(stamped))


def execute_case_intelligence(
    request: CaseIntelligenceRequest,
    *,
    policy: ExecutionPolicy = ExecutionPolicy(),
    reasoning_policy: CaseReasoningPolicy = CaseReasoningPolicy(),
    orchestration_limits: OrchestrationLimits = OrchestrationLimits(),
    cross_domain_policy: CrossDomainPolicy = CrossDomainPolicy(),
    temporal_policy: TemporalMatchPolicy = TemporalMatchPolicy(),
    experience_policy: ExperienceComparisonPolicy = ExperienceComparisonPolicy(),
    adaptation_policy: AdaptationPolicy = AdaptationPolicy(),
    situation_policy: SituationPolicy = SituationPolicy(),
    ruleset: RuleSet | None = None,
    catalog: StrategyCatalog | None = None,
) -> CaseIntelligenceReport:
    """Execute the available ERC pipeline over one immutable case snapshot.

    Ordering is intentional: situation gates precede inference; cross-domain
    paths remain candidates; contextual reasoning precedes historical comparison;
    decision structuring is last and never selects an option.
    """
    stages: list[StageResult] = []
    reviews: list[str] = []
    blockers: list[str] = []
    source_refs = {f.source_ref for f in request.case_context.facts}
    source_refs.update(request.reasoning_request.context_refs)
    source_refs.update(e.source_ref for e in request.reasoning_request.evidence)
    source_refs.update(r for proposition in request.reasoning_request.propositions for r in proposition.source_refs)

    situation: SituationReport | None = None
    if request.situation_rules or request.observations or policy.require_situation_assessment:
        situation = evaluate_situation(
            request.situation_rules, request.observations,
            as_of=request.generated_at, ledger=request.situation_ledger,
            policy=situation_policy,
        )
        active = situation.active_signals
        blocking = tuple(s for s in active if s.status.value == "active" and
                         any(rule.rule_id == s.rule_id and rule.severity.lower() in policy.block_on_severity
                             for rule in request.situation_rules))
        blockers.extend(f"Active safety signal: {s.rule_id} ({s.case_ref})" for s in blocking)
        reviews.extend(f"Active signal requires reviewer assessment: {s.rule_id} ({s.case_ref})"
                       for s in active if s not in blocking)
        source_refs.update(r for e in request.observations for r in (e.source_ref,))
        missing_required_inputs = policy.require_situation_assessment and not (request.situation_rules or request.observations)
        if missing_required_inputs:
            reviews.append("Situation assessment is required by policy but no rules or observations were supplied.")
        stages.append(StageResult(ExecutionStage.SITUATION_ASSESSMENT,
            "blocked" if blocking else ("insufficient_input" if missing_required_inputs else "completed"),
            tuple(s.rule_id for s in active),
            tuple(f"{s.rule_id}: {s.rationale}" for s in active)))
    else:
        stages.append(StageResult(ExecutionStage.SITUATION_ASSESSMENT,
            "insufficient_input" if policy.require_situation_assessment else "not_requested",
            notes=("No situation rules or observations supplied.",)))
        if policy.require_situation_assessment:
            reviews.append("Situation assessment is required by policy but no rules or observations were supplied.")

    cross_domain = None
    if request.knowledge_graph is not None and request.cross_domain_queries and policy.include_cross_domain_candidates:
        cross_domain = reason_across_domains(request.knowledge_graph, request.cross_domain_queries,
                                             generated_at=request.generated_at, policy=cross_domain_policy)
        graph_nodes = {n.node_ref: n for n in request.knowledge_graph.nodes}
        for query in request.cross_domain_queries:
            for node_ref in (query.source_node_ref, query.target_node_ref):
                node = graph_nodes[node_ref]
                source_refs.update(node.source_refs)
                source_refs.add(node.provenance_ref)
        stages.append(StageResult(ExecutionStage.KNOWLEDGE_GRAPH_RETRIEVAL, "candidate_paths_returned",
            tuple(q.query_ref for q in request.cross_domain_queries),
            ("Cross-domain paths are candidate relationships, not practice recommendations.",
             "Graph fingerprint: " + request.knowledge_graph.graph_fingerprint)))
        for finding in cross_domain.findings:
            for path in finding.paths:
                source_refs.update(path.source_refs)
                source_refs.update(path.evidence_refs)
    else:
        stages.append(StageResult(ExecutionStage.KNOWLEDGE_GRAPH_RETRIEVAL, "not_requested"))

    if blockers:
        stages.append(StageResult(ExecutionStage.CONTEXTUAL_REASONING, "skipped_safety_gate"))
        if policy.require_reasoning:
            reviews.append("Reasoning was not executed because a configured safety gate was active.")
        return _finalise(CaseIntelligenceReport(
            request.request_id, request.generated_at, ExecutionStatus.SAFETY_GATE_BLOCKED,
            tuple(stages), situation, cross_domain, None, None, None, None, None,
            tuple(blockers), tuple(dict.fromkeys(reviews)), tuple(sorted(source_refs)),
            ("Safety gate blocks downstream reasoning; this report does not replace professional assessment or emergency protocols.",
             "No autonomous action, treatment selection, alert delivery, or registry write is performed."),
        ), request)

    effective_catalog = catalog or default_strategy_catalog()
    adaptation = rank_catalog_strategies(
        request.reasoning_request, effective_catalog, has_rules=ruleset is not None,
        context_tags=request.context_tags, feedback=request.feedback_ledger,
        external_scores=request.external_strategy_scores, policy=adaptation_policy,
    )
    strategy_override = adaptation.selected_strategy_ref
    if adaptation.status.value == "no_eligible_strategies":
        strategy_override = None
    stages.append(StageResult(ExecutionStage.ADAPTIVE_STRATEGY_SELECTION, adaptation.status.value,
                              tuple(x.strategy_ref for x in adaptation.rankings),
                              (adaptation.abstention_reason,) if adaptation.abstention_reason else ()))
    source_refs.update(r for ranking in adaptation.rankings for r in ranking.source_refs)
    reasoning = orchestrate_case_reasoning(
        request.reasoning_request, request.case_context, request.governed_knowledge,
        request.lifecycle, ruleset=ruleset, catalog=effective_catalog,
        limits=orchestration_limits, policy=reasoning_policy,
        strategy_ref_override=strategy_override,
    )
    stages.append(StageResult(ExecutionStage.CONTEXTUAL_REASONING, reasoning.status.value,
                              reasoning.applied_knowledge_refs, reasoning.review_requirements))
    reviews.extend(reasoning.review_requirements)
    source_refs.update(reasoning.context_source_refs)

    temporal = None
    experience = None
    if request.current_trajectory is not None:
        temporal = match_temporal_experience(request.current_trajectory, request.historical_episodes,
                                             generated_at=request.generated_at, policy=temporal_policy)
        stages.append(StageResult(ExecutionStage.TEMPORAL_COMPARISON,
            "completed" if temporal.matches else "insufficient_or_no_matches",
            tuple(m.episode_id for m in temporal.matches), temporal.limitations))
        if policy.require_temporal_comparison and not temporal.matches:
            reviews.append("Required temporal comparison produced no eligible historical matches.")
        source_refs.update(request.current_trajectory.source_refs)
        source_refs.update(r for event in request.current_trajectory.events for r in event.source_refs)
        for episode in request.historical_episodes:
            source_refs.update(episode.trajectory.source_refs)
            source_refs.update(r for event in episode.trajectory.events for r in event.source_refs)
            source_refs.add(episode.adjudication_ref)
            source_refs.update(episode.practitioner_action_refs)
            source_refs.update(episode.experience_refs)
        if request.experience_details:
            for detail in request.experience_details:
                source_refs.add(detail.adjudication_ref)
                source_refs.update(detail.outcome_source_refs)
                source_refs.update(detail.experience_refs)
                source_refs.update(r for action in detail.actions for r in action.source_refs)
        if request.experience_details:
            experience = compare_case_experience(temporal, request.experience_details,
                generated_at=request.generated_at, policy=experience_policy)
            stages.append(StageResult(ExecutionStage.EXPERIENCE_COMPARISON, "completed",
                tuple(x.episode_id for x in experience.explanations), experience.limitations))
        else:
            stages.append(StageResult(ExecutionStage.EXPERIENCE_COMPARISON, "not_requested"))
    else:
        stages.append(StageResult(ExecutionStage.TEMPORAL_COMPARISON, "not_requested"))
        stages.append(StageResult(ExecutionStage.EXPERIENCE_COMPARISON, "not_requested"))

    decision = None
    if request.decision_options:
        for option in request.decision_options:
            source_refs.update(e.source_ref for e in option.evidence)
            source_refs.update(e.evidence_ref for e in option.evidence)
            source_refs.update(r for risk in option.risk_signals for r in risk.evidence_refs)
            source_refs.update(option.knowledge_refs)
        source_refs.update(r for trigger in request.escalation_triggers for r in trigger.evidence_refs)
        decision = build_decision_support(DecisionSupportRequest(
            request_id=request.request_id, reasoning_report=reasoning,
            options=request.decision_options, escalation_triggers=request.escalation_triggers,
            required_context_refs=tuple(sorted(set(request.reasoning_request.context_refs))),
            generated_at=request.generated_at,
        ))
        stages.append(StageResult(ExecutionStage.DECISION_STRUCTURING, decision.status.value,
            tuple(a.option_id for a in decision.option_assessments), decision.limitations))
        if decision.status.value != "ready_for_review":
            reviews.append("Decision-support output requires review or additional information.")
    else:
        stages.append(StageResult(ExecutionStage.DECISION_STRUCTURING, "not_requested"))

    if policy.require_decision_structuring and decision is None:
        reviews.append("Decision structuring was required by policy but no decision options were supplied.")
    if reasoning.status.value in {"blocked_context", "blocked_knowledge", "conflicted"}:
        status = ExecutionStatus.SAFETY_GATE_BLOCKED
    elif reviews or (policy.require_decision_structuring and decision is None) or (
        policy.require_temporal_comparison and (temporal is None or not temporal.matches)
    ):
        status = ExecutionStatus.REVIEW_REQUIRED
    else:
        status = ExecutionStatus.COMPLETED_FOR_REVIEW

    limitations = (
        "All inputs are caller-supplied snapshots; this execution layer does not create or own canonical registry or knowledge records.",
        "Cross-domain relationships are surfaced as candidates and are not automatically transferred into practice.",
        "Historical outcome patterns are descriptive; they do not establish causality or predict an individual case's outcome.",
        "Decision support structures options and risks but never selects an operation, treatment, or action.",
        "Human adjudication, domain governance, and the host application's persistence and audit controls remain authoritative.",
    )
    return _finalise(CaseIntelligenceReport(
        request.request_id, request.generated_at, status, tuple(stages), situation,
        cross_domain, reasoning, temporal, experience, decision, adaptation, (),
        tuple(dict.fromkeys(reviews)), tuple(sorted(source_refs)), limitations,
    ), request)
