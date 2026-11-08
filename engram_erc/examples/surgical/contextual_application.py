"""Small illustrative ERC-3.0 contextual-application example.

Run from the release root with: PYTHONPATH=. python engram_erc/examples_contextual_application.py
"""
from datetime import datetime, timezone
from engram_erc.application import (
    ApplicabilityCondition, ConditionOperator, ContextFact, GovernedKnowledge,
    CaseContext, assess_knowledge_application,
)
from engram_erc.consolidation import ExperienceCandidate, ExperienceCounts, ConsolidationStatus
from engram_erc.lifecycle import KnowledgeLifecycleLedger, LifecycleEvent, LifecycleAction, KnowledgeStage

now = datetime.now(timezone.utc)
candidate = ExperienceCandidate(
    candidate_id="candidate:anastomosis-001", context_key="colorectal-elective",
    task_type="surgical_decision", activity_ref="procedure:colorectal-anastomosis",
    experience_kind="technical_learning", learning_statement="Illustrative governed learning item",
    counts=ExperienceCounts(supported=12), distinct_sites=("site:a", "site:b"),
    distinct_activities=("procedure:colorectal-anastomosis",), experience_refs=("experience:1",),
    outcome_refs=("outcome:1",), source_refs=("registry:case-1",), failure_category_refs=(),
    trace_pattern_refs=(), confidence_label="not_scored", status=ConsolidationStatus.REVIEWED,
    limitations=("Illustrative example only",),
)
# The evidence ref is retained in the lifecycle event; this example does not
# write to a knowledge store or make a clinical recommendation.
ledger = KnowledgeLifecycleLedger((
    LifecycleEvent("review-1", candidate.candidate_id, LifecycleAction.ADVANCE,
        KnowledgeStage.EXPERIENCE_CANDIDATE, KnowledgeStage.EXPERT_REVIEWED,
        "reviewer:1", "adjudication:1", "Expert review completed", now),
    LifecycleEvent("evidence-1", candidate.candidate_id, LifecycleAction.ADVANCE,
        KnowledgeStage.EXPERT_REVIEWED, KnowledgeStage.EVIDENCE_CORROBORATED,
        "reviewer:2", "adjudication:2", "Independent evidence reviewed", now,
        evidence_refs=("publication:doi-example",)),
))
item = GovernedKnowledge(candidate, "anastomotic_strategy", "strategy-A",
    (ApplicabilityCondition("age-min", "adult", ConditionOperator.EQUALS, value=True),),
    source_refs=candidate.source_refs, evidence_refs=("publication:doi-example",))
context = CaseContext("case:current", "surgical_decision", candidate.activity_ref,
    (ContextFact("adult", True, "registry:demographics"),), now)
print(assess_knowledge_application(item, context, ledger))
