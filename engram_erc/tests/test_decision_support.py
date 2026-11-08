from dataclasses import replace
from datetime import datetime, timezone
import pytest

from engram_erc.decision_support import (
    OptionAssessmentStatus, RiskSeverity, DecisionSupportStatus,
    ReviewerDisposition, OptionEvidence, RiskSignal, EscalationTrigger,
    DecisionOption, DecisionSupportRequest, ReviewerDecision,
    ReviewerDecisionLedger, assess_option, build_decision_support,
    record_reviewer_decision,
)
from engram_erc.application import CaseContext, GovernedKnowledge
from engram_erc.consolidation import ExperienceCandidate, ExperienceCounts, ConsolidationStatus
from engram_erc.contracts import Proposition, ReasoningRequest
from engram_erc.lifecycle import KnowledgeLifecycleLedger, KnowledgeStage, LifecycleAction, LifecycleEvent
from engram_erc.task_orchestration import orchestrate_case_reasoning

NOW = datetime(2026, 11, 7, 10, tzinfo=timezone.utc)

def make_reasoning_report():
    c = ExperienceCandidate("k1", "ctx", "surgical_decision", "colectomy", "experience",
        "learning", ExperienceCounts(supported=8), ("s1", "s2"), ("colectomy",),
        ("x1",), ("o1",), ("src1",), (), (), "not_scored", ConsolidationStatus.REVIEWED, ())
    k = GovernedKnowledge(c, "anastomotic_strategy", "approach_a", (), ("src:experience",), ("ev:paper",))
    ledger = KnowledgeLifecycleLedger((
        LifecycleEvent("e1", "k1", LifecycleAction.ADVANCE, KnowledgeStage.EXPERIENCE_CANDIDATE,
            KnowledgeStage.EXPERT_REVIEWED, "reviewer", "adj1", "reviewed", NOW),
        LifecycleEvent("e2", "k1", LifecycleAction.ADVANCE, KnowledgeStage.EXPERT_REVIEWED,
            KnowledgeStage.EVIDENCE_CORROBORATED, "reviewer", "adj2", "evidence reviewed", NOW,
            evidence_refs=("ev:paper",)),
    ))
    ctx = CaseContext("case1", "surgical_decision", "colectomy", (), NOW)
    req = ReasoningRequest("r1", "surgical_decision", (Proposition("p1", "case", "procedure", "colectomy"),), as_of=NOW)
    return orchestrate_case_reasoning(req, ctx, (k,), ledger)

def test_option_evidence_support_and_qualification_are_distinct():
    option = DecisionOption("a", "Option A", "Description", ("k1",), (
        OptionEvidence("ev1", "supports", "paper1", "k1"),
        OptionEvidence("ev2", "qualifies", "paper2", "k1"),
    ))
    result = assess_option(option, ("k1",))
    assert result.status == OptionAssessmentStatus.QUALIFIED_SUPPORT
    assert result.supporting_evidence_refs == ("ev1",)
    assert result.qualifying_evidence_refs == ("ev2",)

def test_contradictory_and_supporting_evidence_conflicted():
    option = DecisionOption("a", "A", "Description", ("k1",), (
        OptionEvidence("e1", "supports", "s1", "k1"),
        OptionEvidence("e2", "contradicts", "s2", "k1"),
    ))
    assert assess_option(option, ("k1",)).status == OptionAssessmentStatus.CONFLICTED

def test_contraindication_overrides_evidence_support():
    option = DecisionOption("a", "A", "Description", evidence=(OptionEvidence("e1", "supports", "s1"),), exclusion_refs=("contra:1",))
    assert assess_option(option, ()).status == OptionAssessmentStatus.EXCLUDED

def test_unmapped_knowledge_reference_creates_missing_information():
    option = DecisionOption("a", "A", "Description", knowledge_refs=("k-missing",))
    result = assess_option(option, ())
    assert result.status == OptionAssessmentStatus.INSUFFICIENT_INFORMATION
    assert "k-missing" in result.missing_information

def test_option_without_evidence_is_described_not_supported():
    assert assess_option(DecisionOption("a", "A", "Description"), ()).status == OptionAssessmentStatus.DESCRIBED

def test_risk_and_trigger_require_clinician_review():
    rr = make_reasoning_report()
    option = DecisionOption("a", "A", "Description", ("k1",), risk_signals=(RiskSignal("risk1", "Risk signal", RiskSeverity.HIGH),))
    request = DecisionSupportRequest("ds1", rr, (option,), (EscalationTrigger("t1", "Escalate if condition met", True),))
    report = build_decision_support(request)
    assert report.status == DecisionSupportStatus.REVIEW_REQUIRED
    assert report.high_priority_risks[0].signal_id == "risk1"
    assert report.triggered_escalations[0].trigger_id == "t1"

def test_completed_reasoning_and_clear_option_ready_for_clinician_review():
    rr = make_reasoning_report()
    report = build_decision_support(DecisionSupportRequest("ds1", rr, (DecisionOption("a", "A", "Description", ("k1",), (OptionEvidence("e1", "supports", "s1", "k1"),)),)))
    assert report.status == DecisionSupportStatus.READY_FOR_REVIEW
    assert report.option_assessments[0].status == OptionAssessmentStatus.EVIDENCE_SUPPORTED

def test_blocked_reasoning_blocks_decision_support():
    rr = make_reasoning_report()
    rr = replace(rr, status=__import__('engram_erc.task_orchestration', fromlist=['CaseTaskStatus']).CaseTaskStatus.BLOCKED_CONTEXT)
    report = build_decision_support(DecisionSupportRequest("ds1", rr, ()))
    assert report.status == DecisionSupportStatus.BLOCKED

def test_required_context_reference_missing_is_insufficient_input():
    rr = make_reasoning_report()
    report = build_decision_support(DecisionSupportRequest("ds1", rr, (), required_context_refs=("registry:lab",)))
    assert report.status == DecisionSupportStatus.INSUFFICIENT_INPUT
    assert report.missing_required_context_refs == ("registry:lab",)

def test_clinician_decision_is_explicit_and_separate():
    rr = make_reasoning_report()
    report = build_decision_support(DecisionSupportRequest("ds1", rr, (DecisionOption("a", "A", "Description"),)))
    decision = ReviewerDecision("d1", "ds1", "a", ReviewerDisposition.SELECTED, "clinician:1", "adj:1", "Clinician selected after review", NOW)
    ledger = record_reviewer_decision(ReviewerDecisionLedger(), decision, report)
    assert ledger.decisions == (decision,)
    assert record_reviewer_decision(ledger, decision, report) == ledger

def test_clinician_decision_cannot_reference_unknown_option():
    rr = make_reasoning_report()
    report = build_decision_support(DecisionSupportRequest("ds1", rr, ()))
    decision = ReviewerDecision("d1", "ds1", "unknown", ReviewerDisposition.SELECTED, "clinician:1", "adj:1", "Rationale", NOW)
    with pytest.raises(ValueError):
        record_reviewer_decision(ReviewerDecisionLedger(), decision, report)

def test_decision_request_must_match_report():
    rr = make_reasoning_report()
    report = build_decision_support(DecisionSupportRequest("ds1", rr, ()))
    decision = ReviewerDecision("d1", "other", None, ReviewerDisposition.DEFERRED, "clinician:1", "adj:1", "Deferred", NOW)
    with pytest.raises(ValueError):
        record_reviewer_decision(ReviewerDecisionLedger(), decision, report)

def test_duplicate_option_ids_rejected():
    rr = make_reasoning_report()
    with pytest.raises(ValueError):
        DecisionSupportRequest("ds1", rr, (DecisionOption("a", "A", "one"), DecisionOption("a", "A2", "two")))

def test_no_options_is_insufficient_input_not_empty_success():
    rr = make_reasoning_report()
    report = build_decision_support(DecisionSupportRequest("ds1", rr, ()))
    assert report.status == DecisionSupportStatus.INSUFFICIENT_INPUT

def test_selected_high_risk_option_requires_explicit_acknowledgement():
    rr = make_reasoning_report()
    option = DecisionOption("a", "A", "Description", ("k1",),
        risk_signals=(RiskSignal("risk1", "High risk", RiskSeverity.HIGH),))
    report = build_decision_support(DecisionSupportRequest("ds1", rr, (option,)))
    decision = ReviewerDecision("d1", "ds1", "a", ReviewerDisposition.SELECTED,
        "clinician:1", "adj:1", "Selected after review", NOW)
    with pytest.raises(ValueError):
        record_reviewer_decision(ReviewerDecisionLedger(), decision, report)
    acknowledged = replace(decision, acknowledged_risk_refs=("risk1",))
    ledger = record_reviewer_decision(ReviewerDecisionLedger(), acknowledged, report)
    assert ledger.decisions == (acknowledged,)

def test_contraindicated_option_requires_explicit_override_disposition():
    rr = make_reasoning_report()
    option = DecisionOption("a", "A", "Description", exclusion_refs=("contra:1",))
    report = build_decision_support(DecisionSupportRequest("ds1", rr, (option,)))
    selected = ReviewerDecision("d1", "ds1", "a", ReviewerDisposition.SELECTED,
        "clinician:1", "adj:1", "Selected despite contraindication", NOW)
    with pytest.raises(ValueError):
        record_reviewer_decision(ReviewerDecisionLedger(), selected, report)
    override = replace(selected, disposition=ReviewerDisposition.OVERRIDDEN)
    assert record_reviewer_decision(ReviewerDecisionLedger(), override, report).decisions == (override,)
