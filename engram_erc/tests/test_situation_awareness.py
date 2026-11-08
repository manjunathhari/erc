from datetime import datetime, timedelta, timezone
import pytest

from engram_erc.situation_awareness import (
    ObservationEvent, TriggerRule, TriggerOperator, SignalStatus,
    SignalTransitionKind, SituationLedger, evaluate_situation,
)

T0 = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)

def event(i, value, *, metric="drain_output", unit="ml", subject="patient:1", at=None):
    return ObservationEvent(f"ev:{i}", "case:1", subject, metric, value, unit,
                            at or T0 + timedelta(minutes=i), f"registry:{i}")

def rule(**kwargs):
    base = dict(rule_id="rule:1", description="Caller-defined monitoring rule", metric="drain_output",
                operator=TriggerOperator.GT, threshold=100, severity="high", source_ref="protocol:1",
                unit="ml", window_seconds=3600, max_age_seconds=3600)
    base.update(kwargs)
    return TriggerRule(**base)

def test_threshold_rule_triggers_and_carries_provenance():
    report = evaluate_situation((rule(),), (event(1, 120),), as_of=T0 + timedelta(minutes=2))
    result = report.evaluations[0]
    assert result.status == SignalStatus.ACTIVE
    assert result.observation_refs == ("ev:1",)
    assert result.source_refs == ("registry:1",)
    assert report.transitions[0].kind == SignalTransitionKind.OPENED

def test_consecutive_requirement_blocks_single_spike():
    r = rule(consecutive_observations=2)
    report = evaluate_situation((r,), (event(1, 120),), as_of=T0 + timedelta(minutes=2))
    assert report.evaluations[0].status == SignalStatus.INSUFFICIENT_DATA

def test_consecutive_requirement_triggers_on_two_matches():
    r = rule(consecutive_observations=2)
    report = evaluate_situation((r,), (event(1, 120), event(2, 130)), as_of=T0 + timedelta(minutes=3))
    assert report.evaluations[0].status == SignalStatus.ACTIVE
    assert len(report.evaluations[0].observation_refs) == 2

def test_resolution_transition_after_condition_clears():
    r = rule()
    first = evaluate_situation((r,), (event(1, 120),), as_of=T0 + timedelta(minutes=2))
    second = evaluate_situation((r,), (event(2, 80),), as_of=T0 + timedelta(minutes=3), ledger=first.ledger)
    assert second.evaluations[0].status == SignalStatus.NOT_TRIGGERED
    assert second.transitions[0].kind == SignalTransitionKind.RESOLVED

def test_stale_observation_is_not_active():
    r = rule(window_seconds=7200, max_age_seconds=300)
    report = evaluate_situation((r,), (event(1, 120),), as_of=T0 + timedelta(minutes=20))
    assert report.evaluations[0].status == SignalStatus.STALE

def test_changed_operator_requires_two_observations():
    r = rule(operator=TriggerOperator.CHANGED, threshold=None)
    one = evaluate_situation((r,), (event(1, 10),), as_of=T0 + timedelta(minutes=2))
    assert one.evaluations[0].status == SignalStatus.INSUFFICIENT_DATA
    two = evaluate_situation((r,), (event(2, 12),), as_of=T0 + timedelta(minutes=3), ledger=one.ledger)
    assert two.evaluations[0].status == SignalStatus.ACTIVE

def test_independent_subjects_are_evaluated_separately():
    events = (event(1, 120, subject="drain:A"), event(2, 50, subject="drain:B"))
    report = evaluate_situation((rule(),), events, as_of=T0 + timedelta(minutes=3))
    assert {x.subject_ref: x.status for x in report.evaluations} == {
        "drain:A": SignalStatus.ACTIVE, "drain:B": SignalStatus.NOT_TRIGGERED}

def test_future_observation_rejected():
    with pytest.raises(ValueError, match="future observation"):
        evaluate_situation((rule(),), (event(1, 120, at=T0 + timedelta(days=1)),), as_of=T0)

def test_event_idempotency_and_collision():
    e = event(1, 120)
    ledger = SituationLedger().append_observation(e)
    assert ledger.append_observation(e) == ledger
    with pytest.raises(ValueError, match="collision"):
        ledger.append_observation(event(1, 999))

def test_active_signal_continuation_is_audited():
    r = rule()
    first = evaluate_situation((r,), (event(1, 120),), as_of=T0 + timedelta(minutes=2))
    second = evaluate_situation((r,), (), as_of=T0 + timedelta(minutes=3), ledger=first.ledger)
    assert second.transitions[0].kind == SignalTransitionKind.CONTINUED

def test_rule_unit_mismatch_does_not_match_observation():
    report = evaluate_situation((rule(unit="L"),), (event(1, 120),), as_of=T0 + timedelta(minutes=2))
    assert report.evaluations[0].status == SignalStatus.INSUFFICIENT_DATA

def test_duplicate_rule_ids_rejected():
    with pytest.raises(ValueError, match="rule_id"):
        evaluate_situation((rule(), rule()), (), as_of=T0)
