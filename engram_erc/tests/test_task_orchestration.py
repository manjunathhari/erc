from dataclasses import replace
from datetime import datetime, timezone
import pytest

from engram_erc.application import (
    ApplicabilityCondition, ConditionOperator, ContextFact, GovernedKnowledge,
    CaseContext,
)
from engram_erc.consolidation import ExperienceCandidate, ExperienceCounts, ConsolidationStatus
from engram_erc.contracts import Proposition, ReasoningRequest
from engram_erc.lifecycle import KnowledgeLifecycleLedger, KnowledgeStage, LifecycleAction, LifecycleEvent
from engram_erc.task_orchestration import (
    CaseTaskStatus, CaseReasoningPolicy, orchestrate_case_reasoning,
)

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)

def candidate(cid="k1"):
    return ExperienceCandidate(cid, "ctx", "surgical_decision", "colectomy", "experience",
        "learning statement", ExperienceCounts(supported=8), ("site1", "site2"),
        ("colectomy",), ("x1",), ("o1",), ("src1",), (), (), "not_scored",
        ConsolidationStatus.REVIEWED, ())

def knowledge(cid="k1", conditions=(), stance="approach_a"):
    return GovernedKnowledge(candidate(cid), "anastomotic_strategy", stance,
        tuple(conditions), ("src:experience",), ("ev:paper",))

def context(facts=()):
    return CaseContext("case-1", "surgical_decision", "colectomy", tuple(facts), NOW)

def lifecycle(*ids):
    events=[]
    for cid in ids:
        events.extend([
            LifecycleEvent(f"{cid}-1", cid, LifecycleAction.ADVANCE, KnowledgeStage.EXPERIENCE_CANDIDATE, KnowledgeStage.EXPERT_REVIEWED, "reviewer", "adj", "reviewed", NOW),
            LifecycleEvent(f"{cid}-2", cid, LifecycleAction.ADVANCE, KnowledgeStage.EXPERT_REVIEWED, KnowledgeStage.EVIDENCE_CORROBORATED, "reviewer", "adj", "corroborated", NOW, evidence_refs=("ev:paper",)),
        ])
    return KnowledgeLifecycleLedger(tuple(events))

def request():
    return ReasoningRequest("req-1", "surgical_decision", (Proposition("p1", "case", "procedure", "colectomy"),), as_of=NOW)

def test_successful_context_gate_runs_existing_reasoner_and_carries_provenance():
    item=knowledge(conditions=(ApplicabilityCondition("age", "age", ConditionOperator.MINIMUM, value=18),))
    ctx=context((ContextFact("age", 55, "registry:age"),))
    report=orchestrate_case_reasoning(request(), ctx, (item,), lifecycle("k1"))
    assert report.status == CaseTaskStatus.COMPLETED
    assert report.orchestration is not None
    assert report.applied_knowledge_refs == ("k1",)
    assert "registry:age" in report.orchestration.result.trace[0].input_refs or "registry:age" in report.orchestration.result.trace[0].details.values() or report.context_source_refs == ("registry:age",)

def test_missing_context_blocks_inference_by_default():
    item=knowledge(conditions=(ApplicabilityCondition("age", "age", ConditionOperator.MINIMUM, value=18),))
    report=orchestrate_case_reasoning(request(), context(), (item,), lifecycle("k1"))
    assert report.status == CaseTaskStatus.BLOCKED_CONTEXT
    assert report.orchestration is None

def test_unknown_context_can_only_proceed_as_review_required_when_explicitly_allowed():
    item=knowledge(conditions=(ApplicabilityCondition("age", "age", ConditionOperator.MINIMUM, value=18),))
    report=orchestrate_case_reasoning(request(), context(), (item,), lifecycle("k1"),
        policy=CaseReasoningPolicy(allow_unknown_context_with_review=True))
    assert report.status == CaseTaskStatus.REVIEW_REQUIRED
    assert report.orchestration is not None
    assert report.review_requirements

def test_opposing_applicable_knowledge_blocks():
    items=(knowledge("k1", stance="a"), knowledge("k2", stance="b"))
    report=orchestrate_case_reasoning(request(), context(), items, lifecycle("k1", "k2"))
    assert report.status == CaseTaskStatus.CONFLICTED
    assert report.orchestration is None

def test_no_applicable_knowledge_blocks_by_default():
    item=knowledge()
    ctx=CaseContext("case-1", "surgical_decision", "gastrectomy", (), NOW)
    report=orchestrate_case_reasoning(request(), ctx, (item,), lifecycle("k1"))
    assert report.status == CaseTaskStatus.BLOCKED_KNOWLEDGE

def test_task_type_mismatch_rejected():
    bad=replace(request(), task_type="other")
    with pytest.raises(ValueError):
        orchestrate_case_reasoning(bad, context(), (knowledge(),), lifecycle("k1"))

def test_as_of_mismatch_rejected():
    bad=replace(request(), as_of=datetime(2026, 11, 6, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        orchestrate_case_reasoning(bad, context(), (knowledge(),), lifecycle("k1"))
