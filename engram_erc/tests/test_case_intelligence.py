from datetime import datetime, timezone, timedelta
import pytest

from engram_erc.contracts import ReasoningRequest
from engram_erc.application import CaseContext, ContextFact
from engram_erc.lifecycle import KnowledgeLifecycleLedger
from engram_erc.case_intelligence import (
    ExecutionPolicy, ExecutionStatus, ExecutionStage,
    CaseIntelligenceRequest, execute_case_intelligence,
)
from engram_erc.situation_awareness import (
    ObservationEvent, TriggerRule, TriggerOperator,
)
from engram_erc.adaptation import StrategyExperienceScore, strategy_ref
from engram_erc.orchestration import StrategyCatalog, StrategyDefinition, StrategyOperation
from engram_erc.knowledge_graph import (
    KnowledgeNode, KnowledgeNodeKind, KnowledgeEdge, KnowledgeRelation,
    DomainKnowledgeGraph, CrossDomainQuery, build_knowledge_graph,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)

def base_request(**kwargs):
    ctx = CaseContext("ctx1", "surgical_review", "proc1",
                          (ContextFact("age", 60, "registry:case1", T0),), T0, "site1")
    rr = ReasoningRequest("reason1", "surgical_review", (), as_of=T0)
    values = dict(request_id="exec1", generated_at=T1, reasoning_request=rr,
                  case_context=ctx, governed_knowledge=(), lifecycle=KnowledgeLifecycleLedger())
    values.update(kwargs)
    return CaseIntelligenceRequest(**values)

def test_minimal_execution_runs_existing_contextual_reasoning():
    report = execute_case_intelligence(base_request(),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.reasoning is not None
    assert report.status in {ExecutionStatus.COMPLETED_FOR_REVIEW, ExecutionStatus.REVIEW_REQUIRED}
    assert report.stages[0].stage == ExecutionStage.SITUATION_ASSESSMENT

def test_critical_situation_signal_blocks_downstream_reasoning():
    rule = TriggerRule("r1", "critical pressure", "pressure", TriggerOperator.GT,
                      100, "critical", "rule:1", "mmHg")
    obs = ObservationEvent("o1", "case1", "patient1", "pressure", 120, "mmHg", T1,
                           "registry:obs1")
    report = execute_case_intelligence(base_request(situation_rules=(rule,), observations=(obs,)))
    assert report.status == ExecutionStatus.SAFETY_GATE_BLOCKED
    assert report.reasoning is None
    assert report.blocking_signals

def test_high_signal_is_review_not_default_hard_block():
    rule = TriggerRule("r1", "high marker", "marker", TriggerOperator.GT,
                      5, "high", "rule:1", "unit")
    obs = ObservationEvent("o1", "case1", "patient1", "marker", 6, "unit", T1,
                           "registry:obs1")
    report = execute_case_intelligence(base_request(situation_rules=(rule,), observations=(obs,)),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.reasoning is not None
    assert report.status == ExecutionStatus.REVIEW_REQUIRED

def test_cross_domain_query_requires_graph():
    with pytest.raises(ValueError):
        base_request(cross_domain_queries=(CrossDomainQuery("q1", "a", "b", "is there a shared pathway?"),))

def test_cross_domain_candidates_are_included_without_practice_promotion():
    nodes = (KnowledgeNode("a", KnowledgeNodeKind.ACTIVITY, "Colectomy", "colorectal", ("src:a",), "prov:a", subtype="procedure"),
             KnowledgeNode("b", KnowledgeNodeKind.MECHANISM, "Tissue perfusion", "general", ("src:b",), "prov:b"))
    edge = KnowledgeEdge("e1", "a", "b", KnowledgeRelation.HAS_MECHANISM,
                         ("src:e",), "prov:e", ("evidence:1",))
    graph = build_knowledge_graph(nodes, (edge,))
    query = CrossDomainQuery("q1", "a", "b", "is there a shared pathway?")
    report = execute_case_intelligence(base_request(knowledge_graph=graph,
        cross_domain_queries=(query,)),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.cross_domain is not None
    assert report.stages[1].status == "candidate_paths_returned"
    assert any("not automatically" in x for x in report.limitations)

def test_generated_at_must_not_precede_context():
    with pytest.raises(ValueError):
        base_request(generated_at=T0 - timedelta(seconds=1))

def test_options_not_required_unless_policy_says_so():
    report = execute_case_intelligence(base_request(),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.decision_support is None
    assert report.stages[-1].status == "not_requested"

def test_required_decision_stage_without_options_requires_review():
    report = execute_case_intelligence(base_request(),
        policy=ExecutionPolicy(require_decision_structuring=True),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.status == ExecutionStatus.REVIEW_REQUIRED
    assert any("Decision structuring was required" in x for x in report.review_requirements)


def test_adaptive_selection_uses_external_experience_adapter_without_rewriting_catalog():
    strategies = (
        StrategyDefinition("baseline", "1", ("surgical_review",),
            (StrategyOperation.DETECT_CONTRADICTIONS,), priority=20),
        StrategyDefinition("experienced", "1", ("surgical_review",),
            (StrategyOperation.DETECT_CONTRADICTIONS,), priority=1),
    )
    catalog = StrategyCatalog(strategies)
    score = StrategyExperienceScore(strategy_ref(strategies[1]), "surgical_review",
                                     0.92, 12, "p6-adapter:score-1", "External scorer uncertainty")
    report = execute_case_intelligence(base_request(external_strategy_scores=(score,)),
        catalog=catalog,
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.adaptation is not None
    assert report.adaptation.selected_strategy_ref == "experienced@1"
    assert report.reasoning.orchestration.selected_strategy.strategy_id == "experienced"
    assert report.adaptation.rankings[0].origin.value == "external_experience_adapter"


def test_adaptation_abstains_to_catalog_priority_when_no_adjudicated_support():
    report = execute_case_intelligence(base_request(),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.adaptation is not None
    assert report.adaptation.status.value == "insufficient_experience"
    assert report.adaptation.selected_strategy_ref == "consistency_review@1.0"
    assert report.adaptation.abstention_reason


def test_required_situation_assessment_without_inputs_is_not_silently_complete():
    report = execute_case_intelligence(base_request(),
        policy=ExecutionPolicy(require_situation_assessment=True),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.status == ExecutionStatus.REVIEW_REQUIRED
    assert report.stages[0].status == "insufficient_input"
    assert any("no rules or observations" in x for x in report.review_requirements)


def test_temporal_and_experience_stages_compose_with_exact_adjudication_refs():
    from engram_erc.temporal_patterns import (
        EpisodeOutcome, HistoricalEpisode, CaseTrajectory, TrajectoryEvent,
    )
    from engram_erc.experience_reasoning import HistoricalAction, HistoricalExperienceDetail
    current_events = (
        TrajectoryEvent("c1", "tachycardia", T0, ("obs:c1",)),
        TrajectoryEvent("c2", "review", T0 + timedelta(minutes=30), ("obs:c2",)),
    )
    hist_events = (
        TrajectoryEvent("h1", "tachycardia", T0, ("obs:h1",)),
        TrajectoryEvent("h2", "review", T0 + timedelta(minutes=30), ("obs:h2",)),
    )
    current = CaseTrajectory("traj:current", "case:new", "proc:colectomy", "ctx:standard",
        "site:1", current_events, T0 + timedelta(days=2), ("registry:current",))
    historical = CaseTrajectory("traj:old", "case:old", "proc:colectomy", "ctx:standard",
        "site:1", hist_events, T0 + timedelta(days=2), ("registry:old",))
    episode = HistoricalEpisode("episode:old", historical, EpisodeOutcome.IMPROVED,
        "adjudication:old", ("action:old",), ("experience:old",))
    detail = HistoricalExperienceDetail("episode:old",
        (HistoricalAction("action:1", "early_review", 0, ("action-source:1",)),),
        EpisodeOutcome.IMPROVED, "adjudication:old", ("outcome-source:old",),
        30, (), ("experience:old",))
    report = execute_case_intelligence(base_request(
        generated_at=T0 + timedelta(days=3), current_trajectory=current,
        historical_episodes=(episode,), experience_details=(detail,)),
        reasoning_policy=__import__('engram_erc').CaseReasoningPolicy(require_at_least_one_applicable_item=False))
    assert report.temporal is not None and report.temporal.matches
    assert report.experience is not None
    assert "adjudication:old" in report.source_refs
    assert "outcome-source:old" in report.source_refs
