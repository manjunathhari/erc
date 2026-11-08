from datetime import datetime, timedelta, timezone
import pytest
from engram_erc.prospective_learning import (
    ProspectiveCase, ProspectiveEvent, ProspectiveEventKind as K,
    ProspectiveLearningLedger,
)
from engram_erc.temporal_patterns import EpisodeOutcome
from engram_erc.longitudinal_learning import (
    LongitudinalObservation, LongitudinalPolicy, PatternMaturity,
    analyze_longitudinal_learning,
)

T = datetime(2026, 1, 1, tzinfo=timezone.utc)

def make_registry_case(ref, site, outcome=EpisodeOutcome.IMPROVED):
    case = ProspectiveCase(ref, f"result:{ref}", "procedure:colectomy", "context:postop:v1",
                           "postop_review", site, T, (f"registry:{ref}",))
    ledger = ProspectiveLearningLedger().open_case(case)
    def ev(eid, kind, minutes, **kwargs):
        return ProspectiveEvent(eid, ref, kind, T + timedelta(minutes=minutes),
                                "actor:reviewer", (f"source:{eid}",), **kwargs)
    ledger = ledger.append(ev(f"{ref}:d", K.DECISION_RECORDED, 1, related_refs=(f"decision:{ref}",)))
    ledger = ledger.append(ev(f"{ref}:a", K.ACTION_RECORDED, 2, related_refs=(f"action:{ref}",)))
    ledger = ledger.append(ev(f"{ref}:f", K.FOLLOW_UP_RECORDED, 60, related_refs=(f"followup:{ref}",)))
    ledger = ledger.append(ev(f"{ref}:o", K.OUTCOME_ADJUDICATED, 1440,
        adjudication_ref=f"adjudication:{ref}", case_outcome=outcome))
    ledger = ledger.append(ev(f"{ref}:close", K.CASE_CLOSED, 1500))
    row = LongitudinalObservation(
        ref, "procedure:colectomy", "context:postop:v1", site,
        ("early_signal", "clinical_review", "reassessment"),
        ("early_review", "repeat_assessment"), outcome, T + timedelta(minutes=1440),
        f"adjudication:{ref}", (f"source:{ref}:o",), practitioner_ref=f"surgeon:{site}",
        practitioner_perception_tags=("high_difficulty",), follow_up_days=30,
    )
    return ledger, row

def merged_cases(*pairs):
    ledger = pairs[0][0]
    for other, _ in pairs[1:]:
        ledger = type(ledger)(ledger.cases + other.cases, ledger.events + other.events)
    return ledger

def test_cross_case_pattern_detected_across_sites():
    pairs = [make_registry_case("c1", "site:1"), make_registry_case("c2", "site:2"),
             make_registry_case("c3", "site:1", EpisodeOutcome.ADVERSE_EVENT)]
    report = analyze_longitudinal_learning([p[1] for p in pairs], merged_cases(*pairs), generated_at=T + timedelta(days=40),
        policy=LongitudinalPolicy(minimum_cases_for_pattern=3, minimum_sites_for_cross_site=2,
                                  minimum_cases_for_outcome_summary=3))
    assert report.eligible_cases == 3
    assert report.patterns[0].maturity == PatternMaturity.CROSS_SITE_RECURRING
    assert report.patterns[0].outcome_distribution.improved == 2
    assert report.patterns[0].outcome_distribution.adverse_event == 1
    assert report.patterns[0].outcome_summary_available

def test_single_case_is_not_called_recurring():
    pair = make_registry_case("c1", "site:1")
    report = analyze_longitudinal_learning([pair[1]], pair[0], generated_at=T + timedelta(days=40))
    assert report.patterns[0].maturity == PatternMaturity.SINGLE_CASE
    assert not report.patterns[0].outcome_summary_available

def test_exact_procedure_context_and_event_sequence_stratification():
    pair1 = make_registry_case("c1", "site:1")
    pair2 = make_registry_case("c2", "site:2")
    row = pair1[1]
    row2 = pair2[1]
    different = LongitudinalObservation(row2.case_ref, row2.activity_ref, row2.context_key, row2.site_ref,
        ("different_event",), row2.action_pattern, row2.case_outcome, row2.adjudicated_at,
        row2.adjudication_ref, row2.source_refs)
    registry = merged_cases(pair1, pair2)
    report = analyze_longitudinal_learning([row, different], registry, generated_at=T + timedelta(days=40))
    assert len(report.patterns) == 2
    assert {x.event_pattern for x in report.patterns} == {row.event_pattern, ("different_event",)}

def test_case_must_be_closed_by_default():
    pair = make_registry_case("c1", "site:1")
    open_ledger = type(pair[0])(pair[0].cases, pair[0].events[:-1])
    with pytest.raises(ValueError, match="not closed"):
        analyze_longitudinal_learning([pair[1]], open_ledger, generated_at=T + timedelta(days=40))

def test_adjudication_mismatch_rejected():
    pair = make_registry_case("c1", "site:1")
    row = pair[1]
    wrong = LongitudinalObservation(row.case_ref, row.activity_ref, row.context_key, row.site_ref,
        row.event_pattern, row.action_pattern, EpisodeOutcome.ADVERSE_EVENT, row.adjudicated_at,
        row.adjudication_ref, row.source_refs)
    with pytest.raises(ValueError, match="outcome/timestamp mismatch"):
        analyze_longitudinal_learning([wrong], pair[0], generated_at=T + timedelta(days=40))

def test_duplicate_case_projection_rejected():
    pair = make_registry_case("c1", "site:1")
    with pytest.raises(ValueError, match="unique"):
        analyze_longitudinal_learning([pair[1], pair[1]], pair[0], generated_at=T + timedelta(days=40))

def test_future_adjudication_excluded():
    pair = make_registry_case("c1", "site:1")
    report = analyze_longitudinal_learning([pair[1]], pair[0], generated_at=T + timedelta(hours=1))
    assert report.eligible_cases == 0
    assert report.excluded_cases == ("c1",)

def test_action_outcome_summary_is_descriptive_and_thresholded():
    pairs = [make_registry_case("c1", "site:1"), make_registry_case("c2", "site:2")]
    report = analyze_longitudinal_learning([p[1] for p in pairs], merged_cases(*pairs),
        generated_at=T + timedelta(days=40), policy=LongitudinalPolicy(minimum_cases_for_pattern=2,
        minimum_sites_for_cross_site=2, minimum_cases_for_outcome_summary=3))
    assert report.action_outcome_summaries[0].descriptive_status == "insufficient_experience"
    assert any("not a treatment-effect" in x for x in report.action_outcome_summaries[0].limitations)

def test_source_provenance_must_cover_adjudication_source():
    pair = make_registry_case("c1", "site:1")
    row = pair[1]
    bad = LongitudinalObservation(row.case_ref, row.activity_ref, row.context_key, row.site_ref,
        row.event_pattern, row.action_pattern, row.case_outcome, row.adjudicated_at,
        row.adjudication_ref, ("unrelated:source",))
    with pytest.raises(ValueError, match="provenance incomplete"):
        analyze_longitudinal_learning([bad], pair[0], generated_at=T + timedelta(days=40))
