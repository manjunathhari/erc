from datetime import datetime, timezone, timedelta
import pytest

from engram_erc.application import *
from engram_erc.lifecycle import KnowledgeLifecycleLedger, LifecycleEvent, LifecycleAction, KnowledgeStage
from engram_erc.consolidation import ExperienceCandidate, ExperienceCounts, ConsolidationStatus

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)

def candidate(cid="c1", task="surgical_decision", procedure="colectomy"):
    return ExperienceCandidate(cid, "ctx", task, procedure, "technical_learning", "learning",
        ExperienceCounts(supported=8), ("site1", "site2"), (procedure,), ("x1",), ("o1",),
        ("src1",), (), (), "not_scored", ConsolidationStatus.REVIEWED, ())

def governed(cid="c1", conditions=(), **kwargs):
    return GovernedKnowledge(candidate(cid), "anastomotic_strategy", "prefer_strategy_a",
        tuple(conditions), ("src1",), ("ev1",), **kwargs)

def context(facts=(), **kwargs):
    return CaseContext("case-1", "surgical_decision", "colectomy", tuple(facts), NOW, **kwargs)

def promoted(cid="c1", stage=KnowledgeStage.EVIDENCE_CORROBORATED):
    events = []
    stages = [KnowledgeStage.EXPERIENCE_CANDIDATE, KnowledgeStage.EXPERT_REVIEWED,
              KnowledgeStage.EVIDENCE_CORROBORATED, KnowledgeStage.EXTERNALLY_VALIDATED,
              KnowledgeStage.PRACTICE_ELIGIBLE]
    for i in range(stages.index(stage)):
        events.append(LifecycleEvent(f"e{i}", cid, LifecycleAction.ADVANCE, stages[i], stages[i+1],
            "reviewer", "adj", "reviewed", NOW, evidence_refs=("ev1",) if stages[i+1] == KnowledgeStage.EVIDENCE_CORROBORATED else (),
            validation_refs=("val1",) if stages[i+1] in {KnowledgeStage.EXTERNALLY_VALIDATED, KnowledgeStage.PRACTICE_ELIGIBLE} else ()))
    return KnowledgeLifecycleLedger(tuple(events))

def test_exact_match_and_conditions_applicable():
    item = governed(conditions=(ApplicabilityCondition("a", "age", ConditionOperator.MINIMUM, value=18),))
    result = assess_knowledge_application(item, context((ContextFact("age", 42, "registry:age"),)), promoted())
    assert result.status == ApplicabilityStatus.APPLICABLE
    assert result.matched_conditions == ("a",)
    assert result.condition_results[0].context_source_ref == "registry:age"

def test_missing_required_fact_is_unknown_not_false():
    item = governed(conditions=(ApplicabilityCondition("a", "asa", ConditionOperator.ONE_OF, value=(1, 2)),))
    result = assess_knowledge_application(item, context(), promoted())
    assert result.status == ApplicabilityStatus.INSUFFICIENT_CONTEXT
    assert result.unknown_conditions == ("a",)

def test_failed_required_condition_not_applicable():
    item = governed(conditions=(ApplicabilityCondition("a", "age", ConditionOperator.MINIMUM, value=18),))
    result = assess_knowledge_application(item, context((ContextFact("age", 12, "registry:age"),)), promoted())
    assert result.status == ApplicabilityStatus.NOT_APPLICABLE

def test_exclusion_condition_blocks():
    item = governed(conditions=(ApplicabilityCondition("x", "pregnancy", ConditionOperator.EQUALS,
        ConditionPolarity.EXCLUSION, True),))
    result = assess_knowledge_application(item, context((ContextFact("pregnancy", True, "record"),)), promoted())
    assert result.status == ApplicabilityStatus.NOT_APPLICABLE

def test_task_or_procedure_mismatch_blocks():
    result = assess_knowledge_application(governed(), context(), KnowledgeLifecycleLedger())
    assert result.status == ApplicabilityStatus.NOT_GOVERNED
    result = assess_knowledge_application(governed(), CaseContext("x", "surgical_decision", "gastrectomy", (), NOW), promoted())
    assert result.status == ApplicabilityStatus.NOT_APPLICABLE

def test_requires_governed_stage():
    result = assess_knowledge_application(governed(), context(), KnowledgeLifecycleLedger())
    assert result.status == ApplicabilityStatus.NOT_GOVERNED

def test_conflict_refs_block_application():
    result = assess_knowledge_application(governed(conflict_refs=("c2",)), context(), promoted())
    assert result.status == ApplicabilityStatus.CONFLICTED

def test_validity_window():
    item = governed(valid_until=NOW - timedelta(days=1))
    result = assess_knowledge_application(item, context(), promoted())
    assert result.status == ApplicabilityStatus.EXPIRED

def test_terminal_lifecycle_not_applied():
    event = LifecycleEvent("reject", "c1", LifecycleAction.REJECT, KnowledgeStage.EXPERIENCE_CANDIDATE,
        KnowledgeStage.REJECTED, "r", "a", "no", NOW)
    result = assess_knowledge_application(governed(), context(), KnowledgeLifecycleLedger((event,)))
    assert result.status == ApplicabilityStatus.NOT_GOVERNED

def test_opposing_applicable_stances_are_conflicted():
    a = governed("c1")
    b = GovernedKnowledge(candidate("c2"), "anastomotic_strategy", "prefer_strategy_b", (),
        ("src2",), ("ev2",))
    report = apply_contextual_knowledge((a, b), context(), promoted("c1").append(
        LifecycleEvent("b1", "c2", LifecycleAction.ADVANCE, KnowledgeStage.EXPERIENCE_CANDIDATE,
            KnowledgeStage.EXPERT_REVIEWED, "r", "a", "review", NOW)).append(
        LifecycleEvent("b2", "c2", LifecycleAction.ADVANCE, KnowledgeStage.EXPERT_REVIEWED,
            KnowledgeStage.EVIDENCE_CORROBORATED, "r", "a", "review", NOW, evidence_refs=("ev2",))))
    assert report.conflicting_candidate_groups == (("c1", "c2"),)
    assert all(x.status == ApplicabilityStatus.CONFLICTED for x in report.applications)

def test_no_conditions_is_only_conditional():
    result = assess_knowledge_application(governed(), context(), promoted())
    assert result.status == ApplicabilityStatus.CONDITIONALLY_APPLICABLE

def test_context_duplicate_keys_rejected():
    with pytest.raises(ValueError):
        context((ContextFact("age", 10, "a"), ContextFact("age", 20, "b")))

def test_condition_type_is_strict():
    item = governed(conditions=(ApplicabilityCondition("a", "age", ConditionOperator.EQUALS, value=18),))
    result = assess_knowledge_application(item, context((ContextFact("age", True, "a"),)), promoted())
    assert result.status == ApplicabilityStatus.NOT_APPLICABLE

def test_stale_context_fact_becomes_unknown():
    item = governed(conditions=(ApplicabilityCondition("a", "temperature", ConditionOperator.MAXIMUM,
        value=38.0, max_age_hours=2),))
    fact = ContextFact("temperature", 37.0, "obs", NOW - timedelta(hours=3))
    result = assess_knowledge_application(item, context((fact,)), promoted())
    assert result.status == ApplicabilityStatus.INSUFFICIENT_CONTEXT
    assert result.condition_results[0].matched is None

def test_future_context_fact_becomes_unknown():
    item = governed(conditions=(ApplicabilityCondition("a", "temperature", ConditionOperator.MAXIMUM,
        value=38.0, max_age_hours=2),))
    fact = ContextFact("temperature", 37.0, "obs", NOW + timedelta(hours=1))
    result = assess_knowledge_application(item, context((fact,)), promoted())
    assert result.status == ApplicabilityStatus.INSUFFICIENT_CONTEXT

def test_freshness_requires_timestamp():
    item = governed(conditions=(ApplicabilityCondition("a", "temperature", ConditionOperator.MAXIMUM,
        value=38.0, max_age_hours=2),))
    fact = ContextFact("temperature", 37.0, "obs")
    result = assess_knowledge_application(item, context((fact,)), promoted())
    assert result.status == ApplicabilityStatus.INSUFFICIENT_CONTEXT
