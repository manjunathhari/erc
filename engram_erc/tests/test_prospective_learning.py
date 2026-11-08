from datetime import datetime, timedelta, timezone
import pytest
from engram_erc.prospective_learning import (
    ProspectiveCase, ProspectiveEvent, ProspectiveEventKind as K,
    ProspectiveCaseStatus, ProspectiveLearningLedger, inspect_prospective_case,
    to_feedback_event, append_feedback, to_experience_record,
)
from engram_erc.temporal_patterns import EpisodeOutcome
from engram_erc.feedback import FeedbackLedger, OutcomeLabel

T = datetime(2026, 1, 1, tzinfo=timezone.utc)

def case():
    return ProspectiveCase("case-1", "result-1", "procedure:colectomy", "context:A", "postop_review", "site:1", T, ("registry:case",))

def event(eid, kind, mins, **kw):
    return ProspectiveEvent(eid, "case-1", kind, T + timedelta(minutes=mins), "actor:surgeon", (f"source:{eid}",), **kw)

def full_ledger(feedback=OutcomeLabel.VERIFIED_SUPPORTED):
    ledger = ProspectiveLearningLedger().open_case(case())
    ledger = ledger.append(event("d1", K.DECISION_RECORDED, 1, related_refs=("decision:1",)))
    ledger = ledger.append(event("a1", K.ACTION_RECORDED, 2, related_refs=("action:1",)))
    ledger = ledger.append(event("f1", K.FOLLOW_UP_RECORDED, 60, related_refs=("followup:1",)))
    ledger = ledger.append(event("o1", K.OUTCOME_ADJUDICATED, 1440,
        adjudication_ref="adjudication:1", case_outcome=EpisodeOutcome.IMPROVED,
        feedback_outcome=feedback, conclusion_ref="conclusion:1",
        learning_statement="Early review followed by documented reassessment.",
        experience_kind="postoperative_response"))
    return ledger

def test_case_open_is_idempotent_and_collision_rejected():
    x = ProspectiveLearningLedger().open_case(case())
    assert x.open_case(case()) == x
    with pytest.raises(ValueError): x.open_case(ProspectiveCase("case-1", "other", "p", "c", "t", "s", T, ("src",)))

def test_events_must_follow_decision_action_followup_adjudication_order():
    ledger = ProspectiveLearningLedger().open_case(case())
    with pytest.raises(ValueError): ledger.append(event("a", K.ACTION_RECORDED, 1, related_refs=("act",)))
    with pytest.raises(ValueError): ledger.append(event("f", K.FOLLOW_UP_RECORDED, 1, related_refs=("fu",)))

def test_full_prospective_sequence_and_status():
    x = full_ledger()
    status = inspect_prospective_case(x, "case-1")
    assert status.status == ProspectiveCaseStatus.ADJUDICATED
    assert status.learning_candidate_ready
    assert status.action_refs == ("action:1",)

def test_duplicate_event_is_idempotent_and_collision_rejected():
    x = ProspectiveLearningLedger().open_case(case())
    e = event("d1", K.DECISION_RECORDED, 1, related_refs=("decision:1",))
    x = x.append(e)
    assert x.append(e) == x
    with pytest.raises(ValueError): x.append(event("d1", K.DECISION_RECORDED, 1, related_refs=("different",)))

def test_event_time_cannot_precede_case_or_prior_event():
    x = ProspectiveLearningLedger().open_case(case())
    with pytest.raises(ValueError): x.append(event("d", K.DECISION_RECORDED, -1, related_refs=("d",)))
    x = x.append(event("d", K.DECISION_RECORDED, 2, related_refs=("d",)))
    with pytest.raises(ValueError): x.append(event("a", K.ACTION_RECORDED, 1, related_refs=("a",)))

def test_outcome_requires_followup_and_explicit_adjudication():
    x = ProspectiveLearningLedger().open_case(case())
    x = x.append(event("d", K.DECISION_RECORDED, 1, related_refs=("d",)))
    x = x.append(event("a", K.ACTION_RECORDED, 2, related_refs=("a",)))
    with pytest.raises(ValueError): x.append(event("o", K.OUTCOME_ADJUDICATED, 3,
        adjudication_ref="adj", case_outcome=EpisodeOutcome.IMPROVED))

def test_closure_only_after_adjudication_and_then_terminal():
    x = full_ledger()
    x = x.append(event("close", K.CASE_CLOSED, 1500))
    assert inspect_prospective_case(x, "case-1").status == ProspectiveCaseStatus.CLOSED
    with pytest.raises(ValueError): x.append(event("later", K.FOLLOW_UP_RECORDED, 1600, related_refs=("fu",)))

def test_feedback_export_requires_explicit_reasoning_outcome():
    x = full_ledger(feedback=None)
    with pytest.raises(ValueError): to_feedback_event(x, "case-1", event_id="fb1")

def test_feedback_export_keeps_clinical_outcome_separate():
    x = full_ledger(OutcomeLabel.CONTRADICTED)
    e = to_feedback_event(x, "case-1", event_id="fb1")
    assert e.outcome == OutcomeLabel.CONTRADICTED
    assert e.conclusion_ref == "conclusion:1"

def test_append_feedback_is_idempotent():
    x = full_ledger()
    fb = append_feedback(FeedbackLedger(), x, "case-1", event_id="fb1")
    assert append_feedback(fb, x, "case-1", event_id="fb1") == fb

def test_experience_record_requires_matching_feedback_event():
    x = full_ledger()
    fb = append_feedback(FeedbackLedger(), x, "case-1", event_id="fb1")
    rec = to_experience_record(x, "case-1", experience_id="exp1", outcome_event_ref="fb1", feedback_ledger=fb)
    assert rec.result_id == "result-1"
    assert rec.outcome_event_ref == "fb1"
    with pytest.raises(ValueError): to_experience_record(x, "case-1", experience_id="exp2", outcome_event_ref="missing", feedback_ledger=fb)

def test_experience_record_requires_explicit_adjudication_and_site():
    x = full_ledger()
    with pytest.raises(ValueError): to_experience_record(x, "case-1", experience_id="exp1", outcome_event_ref="fb", feedback_ledger=FeedbackLedger())
    c = ProspectiveCase("case-1", "result-1", "p", "ctx", "task", None, T, ("src",))
    y = ProspectiveLearningLedger().open_case(c)
    y = y.append(event("d", K.DECISION_RECORDED, 1, related_refs=("d",)))
    y = y.append(event("a", K.ACTION_RECORDED, 2, related_refs=("a",)))
    y = y.append(event("f", K.FOLLOW_UP_RECORDED, 3, related_refs=("f",)))
    y = y.append(event("o", K.OUTCOME_ADJUDICATED, 4, adjudication_ref="adj", case_outcome=EpisodeOutcome.IMPROVED,
        feedback_outcome=OutcomeLabel.VERIFIED_SUPPORTED, conclusion_ref="con", learning_statement="learn", experience_kind="kind"))
    fb = append_feedback(FeedbackLedger(), y, "case-1", event_id="fb")
    with pytest.raises(ValueError): to_experience_record(y, "case-1", experience_id="exp", outcome_event_ref="fb", feedback_ledger=fb)

def test_unadjudicated_case_not_ready_for_consolidation():
    x = ProspectiveLearningLedger().open_case(case())
    x = x.append(event("d", K.DECISION_RECORDED, 1, related_refs=("d",)))
    status = inspect_prospective_case(x, "case-1")
    assert not status.learning_candidate_ready
    assert any("not been adjudicated" in s for s in status.limitations)

def test_event_requires_source_refs_and_timezone():
    with pytest.raises(ValueError): ProspectiveEvent("e", "c", K.DECISION_RECORDED, T, "actor", ())
    with pytest.raises(ValueError): ProspectiveCase("c", "r", "p", "ctx", "task", "site", datetime(2026,1,1), ("src",))
