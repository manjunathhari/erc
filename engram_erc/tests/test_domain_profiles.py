"""ERC-4.0 General Core acceptance tests: general core, domain profiles, deprecated 0.4.0 names.

The legal and engineering profiles below are test fixtures only. They exist to
show that the core works for fields other than the one shipped as a profile.
"""
from __future__ import annotations

import ast
import dataclasses
import enum
import hashlib
import importlib
import re
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import engram_erc
from engram_erc import (
    DomainProfile, GENERAL_PROFILE, get_profile, registered_profiles,
)
from engram_erc.application import CaseContext, ContextFact
from engram_erc.case_intelligence import (
    CaseIntelligenceRequest, ExecutionPolicy, ExecutionStage, ExecutionStatus,
    execute_case_intelligence,
)
from engram_erc.consolidation import (
    ConsolidationDisposition, ConsolidationPolicy, ConsolidationReview,
    ConsolidationReviewLedger, ExperienceRecord, apply_consolidation_reviews,
    consolidate_experience,
)
from engram_erc.contracts import ReasoningRequest
from engram_erc.decision_support import (
    DecisionOption, DecisionSupportRequest, DecisionSupportStatus, EscalationTrigger,
    OptionAssessmentStatus, OptionEvidence, ReviewerDecision, ReviewerDecisionLedger,
    ReviewerDisposition, RiskSeverity, RiskSignal, build_decision_support,
    record_reviewer_decision,
)
from engram_erc.experience_reasoning import HistoricalAction, HistoricalExperienceDetail
from engram_erc.feedback import FeedbackLedger, OutcomeEvent, OutcomeLabel
from engram_erc.knowledge_graph import (
    CrossDomainQuery, KnowledgeEdge, KnowledgeNode, KnowledgeNodeKind,
    KnowledgeRelation, build_knowledge_graph,
)
from engram_erc.knowledge_synthesis import (
    ExternalEvidence, LocalPracticeClaim, LocalSignal, PopulationApplicability,
    synthesize_practice_intelligence,
)
from engram_erc.lifecycle import (
    EvidenceClass, EvidenceLinkRecord, EvidenceRelation, KnowledgeLifecycleLedger,
    KnowledgeStage, LifecycleAction, assess_promotion, build_lifecycle_event,
)
from engram_erc.longitudinal_learning import (
    LongitudinalObservation, LongitudinalPolicy, analyze_longitudinal_learning,
)
from engram_erc.prospective_learning import (
    ProspectiveCase, ProspectiveEvent, ProspectiveEventKind as K, ProspectiveLearningLedger,
)
from engram_erc.situation_awareness import (
    ObservationEvent, TriggerOperator, TriggerRule, evaluate_situation,
)
from engram_erc.task_orchestration import CaseReasoningPolicy, orchestrate_case_reasoning
from engram_erc.temporal_patterns import (
    CaseTrajectory, EpisodeOutcome, HistoricalEpisode, TrajectoryEvent,
    match_temporal_experience,
)

PKG = Path(engram_erc.__file__).parent
T0 = datetime(2026, 3, 1, 9, tzinfo=timezone.utc)

# --------------------------------------------------------------------------
# Test-only profiles (not shipped, not registered)
# --------------------------------------------------------------------------

ENGINEERING = DomainProfile(
    profile_id="engineering-test", version="0.0.1",
    case_label="incident", activity_label="service change", practitioner_label="engineer",
    reviewer_label="incident lead", exclusion_label="not permitted",
    adverse_event_label="outage",
    evidence_classes={"postmortem": EvidenceClass.RECORDS_ANALYSIS,
                      "on_call_experience": EvidenceClass.PRACTITIONER_EXPERIENCE,
                      "vendor_advisory": EvidenceClass.STANDARD_OR_GUIDELINE},
    node_subtypes={"service": KnowledgeNodeKind.ENTITY, "runbook_step": KnowledgeNodeKind.ACTIVITY},
    value_labels={"excluded": "not permitted", "adverse_event": "outage"},
)

LEGAL = DomainProfile(
    profile_id="legal-test", version="0.0.1",
    case_label="matter", activity_label="filing", practitioner_label="advocate",
    reviewer_label="partner", exclusion_label="not permitted",
    adverse_event_label="adverse ruling",
    evidence_classes={"appellate_judgment": EvidenceClass.PUBLISHED_STUDY,
                      "statute": EvidenceClass.STANDARD_OR_GUIDELINE,
                      "chambers_experience": EvidenceClass.PRACTITIONER_EXPERIENCE},
    value_labels={"excluded": "not permitted", "ready_for_review": "ready for partner review"},
)

SURGICAL = get_profile("surgical")
PROFILES_UNDER_TEST = (GENERAL_PROFILE, SURGICAL)

LABEL_ONLY_FIELDS = {"profile_id", "profile_version", "replay_fingerprint", "evidence_label", "subtype"}


_RANDOM_ID = re.compile(r"\b([a-z]+)_[0-9a-f]{32}\b")
_WALL_CLOCK = {"created_at"}  # ERC 1.x results are stamped with the time they were built


def strip_labels(obj):
    """Plain structure of a result with profile-dependent labels removed.

    Random graph node/edge ids and wall-clock stamps from the ERC 1.x engine are
    masked too: they differ between any two runs and carry no decision.
    """
    if isinstance(obj, str):
        return _RANDOM_ID.sub(r"\1_<id>", obj)
    if isinstance(obj, enum.Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: strip_labels(getattr(obj, f.name)) for f in dataclasses.fields(obj)
                if f.name not in LABEL_ONLY_FIELDS | _WALL_CLOCK}
    if isinstance(obj, (tuple, list)):
        return [strip_labels(x) for x in obj]
    if isinstance(obj, dict):
        return {strip_labels(k): strip_labels(v) for k, v in obj.items()}
    return obj


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------

def test_two_profiles_ship_and_general_is_default():
    assert registered_profiles() == ("general", "surgical")
    assert CaseIntelligenceRequest.__dataclass_fields__["profile_id"].default == "general"
    assert GENERAL_PROFILE.case_label == "case" and GENERAL_PROFILE.reviewer_label == "reviewer"


def test_surgical_profile_reproduces_0_4_0_words():
    assert SURGICAL.label(OptionAssessmentStatus.EXCLUDED) == "contraindicated"
    assert SURGICAL.label(DecisionSupportStatus.READY_FOR_REVIEW) == "ready_for_clinician_review"
    assert SURGICAL.label(EpisodeOutcome.ADVERSE_EVENT) == "complication"
    assert SURGICAL.label(EvidenceClass.PRACTITIONER_EXPERIENCE) == "surgical_experience"
    assert SURGICAL.label(EvidenceClass.RECORDS_ANALYSIS) == "registry_analysis"
    assert SURGICAL.label(KnowledgeNodeKind.ENTITY) == "anatomy"
    assert SURGICAL.label(KnowledgeNodeKind.ACTIVITY) == "procedure"
    assert (SURGICAL.activity_label, SURGICAL.practitioner_label, SURGICAL.reviewer_label) == \
        ("procedure", "surgeon", "clinician")


def test_profile_maps_its_evidence_types_and_node_subtypes_onto_core_values():
    assert SURGICAL.evidence_class("randomized_trial") is EvidenceClass.PUBLISHED_STUDY
    assert SURGICAL.evidence_class("observational_study") is EvidenceClass.PUBLISHED_STUDY
    assert SURGICAL.evidence_class("guideline") is EvidenceClass.STANDARD_OR_GUIDELINE
    assert SURGICAL.node_kind("anatomy") is KnowledgeNodeKind.ENTITY
    assert LEGAL.evidence_class("statute") is EvidenceClass.STANDARD_OR_GUIDELINE
    with pytest.raises(ValueError):
        LEGAL.evidence_class("randomized_trial")


def test_profile_is_immutable_and_validated():
    with pytest.raises(dataclasses.FrozenInstanceError):
        GENERAL_PROFILE.case_label = "x"
    with pytest.raises(TypeError):
        SURGICAL.value_labels["excluded"] = "x"
    with pytest.raises(ValueError):
        DomainProfile("p", "1", "", "a", "p", "r", "e", "ae")
    with pytest.raises(ValueError):
        DomainProfile("p", "1", "c", "a", "p", "r", "e", "ae", evidence_classes={"x": "not-a-class"})


def test_general_label_falls_back_to_readable_core_value():
    assert GENERAL_PROFILE.label(OptionAssessmentStatus.INSUFFICIENT_INFORMATION) == "insufficient information"


# --------------------------------------------------------------------------
# Scenario builders (one fixed input, labels supplied by the profile)
# --------------------------------------------------------------------------

def incident_request(profile: DomainProfile, *, error_rate: float = 4.2, critical_rule: bool = False):
    """An IT incident: error-rate observations, past incidents and remediation options."""
    ctx = CaseContext("incident:2026-031", "incident_response", "service:payments-api",
                      (ContextFact("deploy_version", "v41.3", "ticket:INC-31", T0),), T0, "region:eu-west")
    rr = ReasoningRequest("reason:INC-31", "incident_response", (), as_of=T0)
    rules = (
        TriggerRule("rule:error-rate-critical", "Error rate above 10%", "error_rate_pct",
                    TriggerOperator.GT, 10.0, "critical", "runbook:sre-1", "%"),
        TriggerRule("rule:error-rate-high", "Error rate above 2%", "error_rate_pct",
                    TriggerOperator.GT, 2.0, "high", "runbook:sre-1", "%"),
    )
    obs = (ObservationEvent("obs:1", "incident:2026-031", "service:payments-api", "error_rate_pct",
                            15.0 if critical_rule else error_rate, "%", T0 + timedelta(minutes=5),
                            "metrics:prom-1"),)
    node_kind = profile.node_kind if profile in (ENGINEERING,) else None
    nodes = (
        KnowledgeNode("svc:payments", node_kind("service") if node_kind else KnowledgeNodeKind.ENTITY,
                      "Payments API", "payments", ("cmdb:1",), "prov:cmdb"),
        KnowledgeNode("mech:pool", KnowledgeNodeKind.MECHANISM, "Connection pool exhaustion",
                      "shared", ("pm:12",), "prov:pm"),
        KnowledgeNode("svc:ledger", node_kind("service") if node_kind else KnowledgeNodeKind.ENTITY,
                      "Ledger service", "ledger", ("cmdb:2",), "prov:cmdb"),
    )
    edges = (
        KnowledgeEdge("e1", "svc:payments", "mech:pool", KnowledgeRelation.HAS_MECHANISM,
                      ("pm:12",), "prov:pm", ("postmortem:12",)),
        KnowledgeEdge("e2", "svc:ledger", "mech:pool", KnowledgeRelation.HAS_MECHANISM,
                      ("pm:19",), "prov:pm", ("postmortem:19",)),
    )
    graph = build_knowledge_graph(nodes, edges)
    events_now = (TrajectoryEvent("n1", "error_spike", T0, ("metrics:1",)),
                  TrajectoryEvent("n2", "pool_saturation", T0 + timedelta(minutes=4), ("metrics:2",)))
    current = CaseTrajectory("traj:INC-31", "incident:2026-031", "service:payments-api",
                             "ctx:peak-traffic", "region:eu-west", events_now,
                             T0 + timedelta(minutes=10), ("ticket:INC-31",))
    past_events = (TrajectoryEvent("p1", "error_spike", T0 - timedelta(days=30), ("metrics:p1",)),
                   TrajectoryEvent("p2", "pool_saturation", T0 - timedelta(days=30) + timedelta(minutes=4),
                                   ("metrics:p2",)))
    past = CaseTrajectory("traj:INC-12", "incident:2026-012", "service:payments-api",
                          "ctx:peak-traffic", "region:eu-west", past_events,
                          T0 - timedelta(days=29), ("ticket:INC-12",))
    episode = HistoricalEpisode("episode:INC-12", past, EpisodeOutcome.IMPROVED,
                                "postmortem:12", ("action:INC-12",), ("experience:INC-12",))
    detail = HistoricalExperienceDetail(
        "episode:INC-12", (HistoricalAction("act:1", "raise_pool_limit", 0, ("change:CHG-88",)),),
        EpisodeOutcome.IMPROVED, "postmortem:12", ("postmortem:12:outcome",), 7, (), ("experience:INC-12",))
    options = (
        DecisionOption("opt:rollback", "Roll back v41.3", "Revert the latest deploy",
                       evidence=(OptionEvidence("ev:pm12", "supports", "postmortem:12"),),
                       risk_signals=(RiskSignal("risk:data", "In-flight payments may retry",
                                                RiskSeverity.MODERATE, ("pm:12",)),)),
        DecisionOption("opt:pool", "Raise pool limit", "Increase the DB connection pool",
                       evidence=(OptionEvidence("ev:pm19", "supports", "postmortem:19"),)),
        DecisionOption("opt:failover", "Fail over to secondary region", "Promote us-east",
                       exclusion_refs=("policy:change-freeze",)),
    )
    triggers = (EscalationTrigger("esc:sev1", "Customer-facing impact above 5 minutes", False),)
    return CaseIntelligenceRequest(
        request_id="exec:INC-31", generated_at=T0 + timedelta(minutes=10), reasoning_request=rr,
        case_context=ctx, governed_knowledge=(), lifecycle=KnowledgeLifecycleLedger(),
        situation_rules=rules, observations=obs, knowledge_graph=graph,
        cross_domain_queries=(CrossDomainQuery("q:pool", "svc:payments", "svc:ledger",
                                               "Does the ledger share the pool failure?"),),
        current_trajectory=current, historical_episodes=(episode,), experience_details=(detail,),
        decision_options=options, escalation_triggers=triggers,
        profile_id=profile.profile_id, profile_version=profile.version,
    )


REASONING_POLICY = CaseReasoningPolicy(require_at_least_one_applicable_item=False)


def promotion_ladder(profile: DomainProfile, evidence_label: str, experience_label: str):
    """Consolidate two offices' experience, review it, assess promotion, record the ladder."""
    events = tuple(OutcomeEvent(f"e{i}", f"r{i}", "c1", OutcomeLabel.VERIFIED_SUPPORTED, T0,
                                f"adj:{i}", "matter_strategy") for i in range(2))
    records = tuple(ExperienceRecord(
        f"x{i}", f"r{i}", "c1", f"e{i}", "ctx:commercial-dispute", "matter_strategy",
        f"office-{i}", "filing:early-mediation", "strategy_observation",
        "Propose mediation before filing a defence", (f"matter-file:{i}",), T0) for i in range(2))
    report = consolidate_experience(records, FeedbackLedger(events),
                                    policy=ConsolidationPolicy(min_adjudicated_cases=2, min_distinct_sites=2))
    c = report.candidates[0]
    review = ConsolidationReview(c.candidate_id, ConsolidationDisposition.ACCEPT_FOR_KNOWLEDGE_REVIEW,
                                 "partner:senior", "adj:review-1", T0, "Accepted for knowledge review")
    c = apply_consolidation_reviews(report, ConsolidationReviewLedger((review,))).candidates[0]
    evidence = (
        EvidenceLinkRecord("ev:judgment", EvidenceRelation.SUPPORTS, profile.evidence_class(evidence_label),
                           "source:judgment", c.candidate_id, c.context_key, T0, True, (),
                           evidence_label=evidence_label),
        EvidenceLinkRecord("ev:own", EvidenceRelation.SUPPORTS, profile.evidence_class(experience_label),
                           "source:own", c.candidate_id, c.context_key, T0, False, (),
                           evidence_label=experience_label),
    )
    assessment = assess_promotion(c, evidence=evidence)
    ledger = KnowledgeLifecycleLedger().append(build_lifecycle_event(
        event_id="l1", candidate_id=c.candidate_id, action=LifecycleAction.ADVANCE,
        current_stage=KnowledgeStage.EXPERIENCE_CANDIDATE, reviewer_ref="partner:1",
        adjudication_ref="adj:l1", rationale="Expert review complete", occurred_at=T0))
    ledger = ledger.append(build_lifecycle_event(
        event_id="l2", candidate_id=c.candidate_id, action=LifecycleAction.ADVANCE,
        current_stage=KnowledgeStage.EXPERT_REVIEWED, reviewer_ref="partner:1",
        adjudication_ref="adj:l2", rationale="Evidence gate reviewed", occurred_at=T0,
        assessment=assessment))
    return c, assessment, ledger


# --------------------------------------------------------------------------
# Acceptance 2: same decisions under any profile
# --------------------------------------------------------------------------

def _run_under(profile):
    return execute_case_intelligence(incident_request(profile), reasoning_policy=REASONING_POLICY)


def test_execute_case_intelligence_same_decisions_under_general_and_surgical():
    general, surgical = (_run_under(p) for p in PROFILES_UNDER_TEST)
    assert strip_labels(general) == strip_labels(surgical)
    assert [s.stage for s in general.stages] == [s.stage for s in surgical.stages]
    assert general.limitations == surgical.limitations
    assert (general.profile_id, surgical.profile_id) == ("general", "surgical")
    assert general.replay_fingerprint != surgical.replay_fingerprint  # the profile is part of the replay identity


def test_orchestrate_case_reasoning_same_under_both_profiles():
    results = []
    for profile in PROFILES_UNDER_TEST:
        req = incident_request(profile)
        results.append(orchestrate_case_reasoning(req.reasoning_request, req.case_context, (),
                                                  req.lifecycle, policy=REASONING_POLICY))
    assert strip_labels(results[0]) == strip_labels(results[1])
    assert results[0].status == results[1].status


def test_decision_support_same_under_both_profiles():
    reports = []
    for profile in PROFILES_UNDER_TEST:
        reports.append(_run_under(profile).decision_support)
    assert strip_labels(reports[0]) == strip_labels(reports[1])
    statuses = {a.option_id: a.status for a in reports[0].option_assessments}
    assert statuses["opt:failover"] == OptionAssessmentStatus.EXCLUDED


def test_situation_awareness_same_under_both_profiles():
    out = []
    for profile in PROFILES_UNDER_TEST:
        req = incident_request(profile)
        out.append(evaluate_situation(req.situation_rules, req.observations, as_of=req.generated_at))
    assert strip_labels(out[0]) == strip_labels(out[1])


def test_pattern_matching_same_under_both_profiles():
    out = []
    for profile in PROFILES_UNDER_TEST:
        req = incident_request(profile)
        out.append(match_temporal_experience(req.current_trajectory, req.historical_episodes,
                                             generated_at=req.generated_at))
    assert strip_labels(out[0]) == strip_labels(out[1])
    assert out[0].matches


def _longitudinal(ref_prefix: str):
    pairs = []
    for i in range(3):
        ref, site = f"{ref_prefix}{i}", f"site:{i % 2 + 1}"
        case = ProspectiveCase(ref, f"result:{ref}", "activity:a1", "context:c1", "review", site, T0,
                               (f"records:{ref}",))
        ledger = ProspectiveLearningLedger().open_case(case)

        def ev(suffix, kind, mins, **kw):
            return ProspectiveEvent(f"{ref}:{suffix}", ref, kind, T0 + timedelta(minutes=mins),
                                    "actor:reviewer", (f"source:{ref}:{suffix}",), **kw)
        ledger = ledger.append(ev("d", K.DECISION_RECORDED, 1, related_refs=(f"decision:{ref}",)))
        ledger = ledger.append(ev("a", K.ACTION_RECORDED, 2, related_refs=(f"action:{ref}",)))
        ledger = ledger.append(ev("f", K.FOLLOW_UP_RECORDED, 60, related_refs=(f"followup:{ref}",)))
        outcome = EpisodeOutcome.ADVERSE_EVENT if i == 2 else EpisodeOutcome.IMPROVED
        ledger = ledger.append(ev("o", K.OUTCOME_ADJUDICATED, 1440, adjudication_ref=f"adj:{ref}",
                                  case_outcome=outcome))
        ledger = ledger.append(ev("close", K.CASE_CLOSED, 1500))
        row = LongitudinalObservation(ref, "activity:a1", "context:c1", site, ("signal", "review"),
                                      ("early_review",), outcome, T0 + timedelta(minutes=1440),
                                      f"adj:{ref}", (f"source:{ref}:o",), practitioner_ref=f"p:{site}")
        pairs.append((ledger, row))
    ledger = ProspectiveLearningLedger(tuple(c for l, _ in pairs for c in l.cases),
                                       tuple(e for l, _ in pairs for e in l.events))
    return analyze_longitudinal_learning([r for _, r in pairs], ledger, generated_at=T0 + timedelta(days=40),
        policy=LongitudinalPolicy(minimum_cases_for_pattern=3, minimum_sites_for_cross_site=2,
                                  minimum_cases_for_outcome_summary=3))


def test_longitudinal_learning_same_under_both_profiles():
    # No profile input exists for this function; it is run once per profile to show that
    # nothing a profile supplies can reach it, and the adverse-event count is the core field.
    a, b = _longitudinal("c"), _longitudinal("c")
    assert strip_labels(a) == strip_labels(b)
    assert a.patterns[0].outcome_distribution.adverse_event == 1
    assert GENERAL_PROFILE.label(EpisodeOutcome.ADVERSE_EVENT) == "adverse event"
    assert SURGICAL.label(EpisodeOutcome.ADVERSE_EVENT) == "complication"


def test_promotion_same_under_both_profiles():
    _, general, g_ledger = promotion_ladder(GENERAL_PROFILE, "published_study", "practitioner_experience")
    _, surgical, s_ledger = promotion_ladder(SURGICAL, "randomized_trial", "surgical_experience")
    assert strip_labels(general) == strip_labels(surgical)
    assert strip_labels(g_ledger) == strip_labels(s_ledger)


# --------------------------------------------------------------------------
# Acceptance 3: non-medical cases end to end
# --------------------------------------------------------------------------

def test_it_incident_runs_all_seven_stages():
    report = execute_case_intelligence(incident_request(ENGINEERING), reasoning_policy=REASONING_POLICY)
    assert [s.stage for s in report.stages] == list(ExecutionStage)
    assert all(s.status not in {"not_requested", "skipped_safety_gate"} for s in report.stages)
    assert report.profile_id == "engineering-test"
    assert report.situation is not None and report.situation.active_signals  # high, not critical
    assert report.cross_domain is not None and report.temporal.matches and report.experience is not None
    statuses = {a.option_id: a.status for a in report.decision_support.option_assessments}
    assert statuses == {"opt:rollback": OptionAssessmentStatus.EVIDENCE_SUPPORTED,
                        "opt:pool": OptionAssessmentStatus.EVIDENCE_SUPPORTED,
                        "opt:failover": OptionAssessmentStatus.EXCLUDED}
    assert report.status == ExecutionStatus.REVIEW_REQUIRED
    assert ENGINEERING.label(statuses["opt:failover"]) == "not permitted"
    assert "postmortem:12" in report.source_refs


def test_it_incident_critical_error_rate_blocks_downstream_reasoning():
    report = execute_case_intelligence(incident_request(ENGINEERING, critical_rule=True),
                                       reasoning_policy=REASONING_POLICY)
    assert report.status == ExecutionStatus.SAFETY_GATE_BLOCKED
    assert report.reasoning is None and report.decision_support is None
    assert any("rule:error-rate-critical" in s for s in report.blocking_signals)


def test_it_incident_excluded_option_needs_explicit_override():
    report = execute_case_intelligence(incident_request(ENGINEERING), reasoning_policy=REASONING_POLICY)
    ds = report.decision_support
    select = ReviewerDecision("d1", ds.request_id, "opt:failover", ReviewerDisposition.SELECTED,
                              "lead:oncall", "adj:d1", "Fail over now", T0 + timedelta(minutes=12))
    with pytest.raises(ValueError, match="explicit OVERRIDDEN"):
        record_reviewer_decision(ReviewerDecisionLedger(), select, ds)
    override = dataclasses.replace(select, disposition=ReviewerDisposition.OVERRIDDEN)
    assert len(record_reviewer_decision(ReviewerDecisionLedger(), override, ds).decisions) == 1


def _legal_reasoning_report():
    ctx = CaseContext("matter:4411", "matter_strategy", "filing:defence", (), T0, "office-1")
    rr = ReasoningRequest("reason:4411", "matter_strategy", (), as_of=T0)
    return orchestrate_case_reasoning(rr, ctx, (), KnowledgeLifecycleLedger(), policy=REASONING_POLICY)


def test_legal_matter_through_decision_support():
    request = DecisionSupportRequest("ds:4411", _legal_reasoning_report(), (
        DecisionOption("opt:settle", "Settle", "Offer settlement at 60%",
                       evidence=(OptionEvidence("ev:offer", "supports", "memo:offer"),)),
        DecisionOption("opt:mediate", "Mediate", "Propose mediation",
                       evidence=(OptionEvidence("ev:med", "supports", "judgment:2024-17"),
                                 OptionEvidence("ev:cost", "qualifies", "memo:costs"))),
        DecisionOption("opt:counterclaim", "Counterclaim", "File a counterclaim",
                       exclusion_refs=("limitation:period-expired",)),
    ), generated_at=T0)
    report = build_decision_support(request)
    statuses = {a.option_id: a.status for a in report.option_assessments}
    assert statuses == {"opt:settle": OptionAssessmentStatus.EVIDENCE_SUPPORTED,
                        "opt:mediate": OptionAssessmentStatus.QUALIFIED_SUPPORT,
                        "opt:counterclaim": OptionAssessmentStatus.EXCLUDED}
    assert LEGAL.label(statuses["opt:counterclaim"]) == "not permitted"
    decision = ReviewerDecision("d1", "ds:4411", "opt:mediate", ReviewerDisposition.SELECTED,
                                "partner:1", "adj:d1", "Mediation first", T0)
    assert record_reviewer_decision(ReviewerDecisionLedger(), decision, report).decisions == (decision,)


def test_legal_matter_through_promotion_ladder():
    c, assessment, ledger = promotion_ladder(LEGAL, "appellate_judgment", "chambers_experience")
    assert assessment.eligible
    assert assessment.proposed_stage == KnowledgeStage.EVIDENCE_CORROBORATED
    assert ledger.current_stage(c.candidate_id) == KnowledgeStage.EVIDENCE_CORROBORATED
    assert c.distinct_activities == ("filing:early-mediation",)


# --------------------------------------------------------------------------
# Acceptance 5: independence rule kept, under both profiles
# --------------------------------------------------------------------------

@pytest.mark.parametrize("profile,label", [(GENERAL_PROFILE, "practitioner_experience"),
                                           (SURGICAL, "surgical_experience"),
                                           (LEGAL, "chambers_experience")])
def test_practitioner_experience_never_counts_as_independent(profile, label):
    cls = profile.evidence_class(label)
    assert cls is EvidenceClass.PRACTITIONER_EXPERIENCE
    with pytest.raises(ValueError, match="cannot be declared independent"):
        EvidenceLinkRecord("ev", EvidenceRelation.SUPPORTS, cls, "s", "c", "ctx", None, True,
                           evidence_label=label)
    with pytest.raises(ValueError, match="cannot be declared independent"):
        ExternalEvidence("ev", "claim", EvidenceRelation.SUPPORTS, cls, "s", "a", "act", "ctx",
                         ("x",), PopulationApplicability.MATCH, True, evidence_label=label)
    # Lifecycle: experience-only support never satisfies the independence gate.
    candidate, _, _ = promotion_ladder(GENERAL_PROFILE, "published_study", "practitioner_experience")
    only_experience = (EvidenceLinkRecord("ev:own", EvidenceRelation.SUPPORTS, cls, "s",
                                          candidate.candidate_id, candidate.context_key, T0, False,
                                          evidence_label=label),)
    assessment = assess_promotion(candidate, evidence=only_experience)
    assert "NO_INDEPENDENT_EVIDENCE_CORROBORATION" in assessment.blockers
    # Second guard: even if a record bypassed its constructor check (tampered or hand-deserialised
    # data) and claims independence, the class alone keeps it out of independent support.
    forged = only_experience[0]
    object.__setattr__(forged, "independent_of_candidate_experience", True)
    assert forged.independent_of_candidate_experience is True
    assert "NO_INDEPENDENT_EVIDENCE_CORROBORATION" in assess_promotion(candidate, evidence=(forged,)).blockers


def test_synthesis_excludes_practitioner_experience_under_both_profiles():
    lr = _longitudinal("s")
    p, a = lr.patterns[0], lr.action_outcome_summaries[0]
    claim = LocalPracticeClaim("claim:1", p.pattern_id, a.action_pattern, "Early review was observed.",
                               LocalSignal.SUPPORTS, p.adjudication_refs, p.source_refs, "reviewer:1",
                               p.context_key, p.activity_ref)
    for profile, label in ((GENERAL_PROFILE, "practitioner_experience"), (SURGICAL, "surgical_experience")):
        ev = ExternalEvidence("exp:1", claim.claim_ref, EvidenceRelation.SUPPORTS,
                              profile.evidence_class(label), "src:1", "app:1", claim.activity_ref,
                              claim.context_key, claim.action_pattern, PopulationApplicability.MATCH,
                              False, evidence_label=label)
        report = synthesize_practice_intelligence(lr, [claim], [ev], generated_at=T0 + timedelta(days=40))
        assert report.excluded_evidence_refs == ("exp:1",)
        object.__setattr__(ev, "independent_of_local_records", True)  # bypasses the constructor check
        report = synthesize_practice_intelligence(lr, [claim], [ev], generated_at=T0 + timedelta(days=40))
        assert report.excluded_evidence_refs == ("exp:1",)


# --------------------------------------------------------------------------
# Acceptance 4: the core names no field
# --------------------------------------------------------------------------

FORBIDDEN = ("surgical", "surgeon", "clinician", "clinical", "patient", "procedure",
             "contraindicat", "complication", "anatomy", "operative", "drain")
ERC_1X = {"contracts.py", "graph.py", "inference.py", "orchestration.py", "evaluation.py", "rules.py",
          "validation.py", "feedback.py", "adaptation.py", "trace_learning.py"}
EXEMPT = {"compat.py", "surgical_intelligence.py", "profiles/surgical.py"}


def _core_files():
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG).as_posix()
        if rel.startswith(("tests/", "examples/", "primitives/")) or rel.startswith("examples_"):
            continue
        if rel in ERC_1X or rel in EXEMPT:
            continue
        yield rel, path


def _words(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
            yield from (a.arg for a in node.args.args + node.args.kwonlyargs) if not isinstance(node, ast.ClassDef) else ()
        elif isinstance(node, ast.arg):
            yield node.arg
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.arg
        elif isinstance(node, ast.alias):
            yield node.name
            if node.asname:
                yield node.asname
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value  # docstrings, enum values, defaults, messages, limitations


def test_core_modules_name_no_field():
    offences = []
    files = list(_core_files())
    assert {"case_intelligence.py", "decision_support.py", "profiles/__init__.py", "profiles/general.py",
            "__init__.py"} <= {rel for rel, _ in files}
    for rel, path in files:
        for word in _words(ast.parse(path.read_text(encoding="utf-8"))):
            low = word.lower()
            hits = [f for f in FORBIDDEN if f in low]
            if hits:
                offences.append(f"{rel}: {hits} in {word[:80]!r}")
    assert not offences, "\n".join(offences)


def test_core_enum_values_name_no_field():
    for module_name in ("decision_support", "temporal_patterns", "knowledge_graph", "lifecycle",
                        "task_orchestration", "case_intelligence", "situation_awareness"):
        module = importlib.import_module(f"engram_erc.{module_name}")
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, enum.Enum) and obj.__module__ == module.__name__:
                for member in obj:
                    assert not any(f in str(member.value).lower() for f in FORBIDDEN), (obj, member)


# --------------------------------------------------------------------------
# Acceptance 6: ERC 1.x untouched
# --------------------------------------------------------------------------

ERC_1X_SHA256_AT_0_4_0 = {
    "contracts.py": "ee4f95d389ff79762917cb11da51a63eba2858694e3978abfef1046eec95164e",
    "graph.py": "d6206a5c5fb37b283e7f4ef2be3408f84f55e5f572ce6ffcd1dbb2a0eae9667d",
    "inference.py": "869569c2455e12c8d08ffad392620482223bf019ab9dda79bf019fbf866f4103",
    "orchestration.py": "a6821e7ef4f3bf832ac79ac84d38c657a0122d2e6a2da08c400bb3e92e6da503",
    "evaluation.py": "fe07d5ae3029116bca411101bc4beb3b8770c632984dbec7903575e2da252553",
    "rules.py": "8e82967e31e306f6d529e431f649350e52c779f1035e869257fa4dccec65284c",
    "validation.py": "2c874e1748f929129fb04692aaa578d8cb33c295fb105c39d3f06ce606eaa60c",
    "feedback.py": "6e9f81a27001202610cecbd4082d1997bb0e9e18b8971cd72ca1611256ffa58a",
    "adaptation.py": "2d605d14e134fb78d9953fdc2d2a825b7f5e9c3023501c18ecedd2a26bd43179",
    "trace_learning.py": "45ccfb16e73d47194f1eaae9c0879edddae1ad2b2d7b4b54c24f850893ca0e8f",
    "primitives/__init__.py": "358cbc64d06e96d5c3fb713612b4efec406e648edd153df938c14fb514fa6e93",
    "primitives/comparison.py": "14834621ae79e16b78c3a423bbc22ebdf3cddc28db9686a7ee87307a066d3e69",
    "primitives/contradiction.py": "c6671af581650e4d374fca69370e45a6f693f82f848bfc2e68dbbee1208ad93f",
    "primitives/evidence_assessment.py": "aa6b666a5486232dcdf767c8c68f3c749ac1d564eb13a45c9dff27e57300b95f",
}


# The table above is the historical record of the 0.4.0 release and is never edited: its own digest is pinned below.
# A file changed on purpose after 0.4.0 is listed here with the release that changed it and the reason, and is held
# to that release pin instead. Every other file stays held to its 0.4.0 bytes.
ERC_1X_HISTORICAL_TABLE_SHA256 = "1d72e781ec1dcd5fcbbf20ad1580cd28d6321047cf1498d33049fe1763e53dda"
ERC_1X_RELEASE_PINS = {
    # file: (sha256, release, increment and reason)
    "contracts.py": ("64ebe6722c734ad87f6163007b7c403b057765ba0fe1c3a6b7042a058e9fe8cd", "0.5.0",
                     "B1 temporal contract: additive keyword-only TimeInterval fields, BoundaryStatus, Occurrence, "
                     "Proposition.occurred. No existing behaviour changed."),
    "primitives/comparison.py": ("ead6a041f46db99faac626d43493350bcaaae3329316251322484a1411f20d8f", "0.6.0",
                                 "B3 temporal comparison: the temporal relation reads the 0.5.0 contract (certain overlap only "
                                 "when the certain parts of both intervals share time; disjointness unchanged), and two events "
                                 "are compared by their occurrence windows. Intervals with none of the 0.5.0 fields compare "
                                 "exactly as before."),
}
ERC_1X_FILES_CHANGED_SINCE_0_4_0 = {"contracts.py", "primitives/comparison.py"}


def test_the_0_4_0_hash_table_is_kept_as_an_unedited_historical_record():
    assert len(ERC_1X_SHA256_AT_0_4_0) == 14
    canonical = "\n".join(f"{rel} {digest}" for rel, digest in sorted(ERC_1X_SHA256_AT_0_4_0.items()))
    assert hashlib.sha256(canonical.encode()).hexdigest() == ERC_1X_HISTORICAL_TABLE_SHA256


def test_only_the_approved_erc_1x_files_have_changed_since_0_4_0():
    assert set(ERC_1X_RELEASE_PINS) == ERC_1X_FILES_CHANGED_SINCE_0_4_0
    assert set(ERC_1X_RELEASE_PINS) <= set(ERC_1X_SHA256_AT_0_4_0)
    for rel, (digest, release, reason) in ERC_1X_RELEASE_PINS.items():
        assert digest != ERC_1X_SHA256_AT_0_4_0[rel], f"{rel} is listed as changed but still has its 0.4.0 bytes"
        assert release and reason.strip(), f"{rel}: a changed file needs its release and its reason"


@pytest.mark.parametrize("rel", sorted(set(ERC_1X_SHA256_AT_0_4_0) - set(ERC_1X_RELEASE_PINS)))
def test_erc_1x_files_are_byte_identical_to_0_4_0(rel):
    assert hashlib.sha256((PKG / rel).read_bytes()).hexdigest() == ERC_1X_SHA256_AT_0_4_0[rel]


@pytest.mark.parametrize("rel", sorted(ERC_1X_RELEASE_PINS))
def test_erc_1x_files_changed_since_0_4_0_match_their_release_pin(rel):
    assert hashlib.sha256((PKG / rel).read_bytes()).hexdigest() == ERC_1X_RELEASE_PINS[rel][0]


# --------------------------------------------------------------------------
# Fingerprints and the replay identity
# --------------------------------------------------------------------------

# Computed with the 0.4.0 surgical release: ANATOMY 'anat:liver', PROCEDURE 'proc:hep', MECHANISM 'mech:perf'.
GRAPH_FINGERPRINT_AT_0_4_0 = "afc1d6437a1d1bf026b2ca097f594554b7e29c69e5c75138d7a71d42f72998ca"


def _hpb_graph(kind_entity, kind_activity, subtypes=(None, None)):
    n = (KnowledgeNode("anat:liver", kind_entity, "Liver", "hpb", ("src:l",), "prov:l", subtype=subtypes[0]),
         KnowledgeNode("proc:hep", kind_activity, "Hepatectomy", "hpb", ("src:h",), "prov:h", subtype=subtypes[1]),
         KnowledgeNode("mech:perf", KnowledgeNodeKind.MECHANISM, "Perfusion", "shared", ("src:m",), "prov:m"))
    e = (KnowledgeEdge("e1", "proc:hep", "anat:liver", KnowledgeRelation.INVOLVES, ("src:e1",), "prov:e1"),
         KnowledgeEdge("e2", "proc:hep", "mech:perf", KnowledgeRelation.HAS_MECHANISM, ("src:e2",), "prov:e2",
                       ("ev:1",)))
    return build_knowledge_graph(n, e)


def test_graph_with_profile_subtypes_keeps_its_0_4_0_fingerprint():
    graph = _hpb_graph(KnowledgeNodeKind.ENTITY, KnowledgeNodeKind.ACTIVITY, ("anatomy", "procedure"))
    assert graph.graph_fingerprint == GRAPH_FINGERPRINT_AT_0_4_0


def test_graph_without_subtypes_uses_core_kind_values():
    graph = _hpb_graph(KnowledgeNodeKind.ENTITY, KnowledgeNodeKind.ACTIVITY)
    assert graph.graph_fingerprint != GRAPH_FINGERPRINT_AT_0_4_0


def test_subtype_never_changes_traversal():
    with_sub = _hpb_graph(KnowledgeNodeKind.ENTITY, KnowledgeNodeKind.ACTIVITY, ("anatomy", "procedure"))
    without = _hpb_graph(KnowledgeNodeKind.ENTITY, KnowledgeNodeKind.ACTIVITY)
    from engram_erc.knowledge_graph import reason_across_domains
    q = (CrossDomainQuery("q", "anat:liver", "mech:perf", "Is perfusion involved?"),)
    a = strip_labels(reason_across_domains(with_sub, q, generated_at=T0))
    b = strip_labels(reason_across_domains(without, q, generated_at=T0))
    a.pop("graph_fingerprint"); b.pop("graph_fingerprint")
    assert a == b


def test_replay_fingerprint_is_deterministic_and_includes_profile():
    a = _run_under(GENERAL_PROFILE)
    b = _run_under(GENERAL_PROFILE)
    assert a.replay_fingerprint == b.replay_fingerprint and a.replay_fingerprint.startswith("erc-replay-")
    bumped = execute_case_intelligence(dataclasses.replace(incident_request(GENERAL_PROFILE), profile_version="1.0.1"),
                                       reasoning_policy=REASONING_POLICY)
    assert bumped.replay_fingerprint != a.replay_fingerprint
    assert (bumped.profile_id, bumped.profile_version) == ("general", "1.0.1")


def test_request_rejects_blank_profile():
    with pytest.raises(ValueError):
        dataclasses.replace(incident_request(GENERAL_PROFILE), profile_id=" ")


# --------------------------------------------------------------------------
# Acceptance 1 (compatibility): 0.4.0 names still work, with a warning
# --------------------------------------------------------------------------

OLD_TO_NEW = engram_erc.compat.DEPRECATED_NAMES


@pytest.mark.parametrize("old", sorted(n for n in OLD_TO_NEW if not n.startswith("_")))
def test_old_name_from_package_warns_and_is_the_new_object(old):
    module_name, new = OLD_TO_NEW[old]
    with pytest.warns(DeprecationWarning, match=old):
        obj = getattr(engram_erc, old)
    assert obj is getattr(importlib.import_module(f"engram_erc.{module_name}"), new)


@pytest.mark.parametrize("old", sorted(OLD_TO_NEW))
def test_old_name_from_its_0_4_0_module_warns_and_is_the_new_object(old):
    module_name, new = OLD_TO_NEW[old]
    module = importlib.import_module(f"engram_erc.{module_name}")
    with pytest.warns(DeprecationWarning):
        assert getattr(module, old) is getattr(module, new)


def test_from_import_of_old_name_works():
    with pytest.warns(DeprecationWarning):
        from engram_erc.task_orchestration import SurgicalReasoningPolicy  # noqa: N811
    assert SurgicalReasoningPolicy is CaseReasoningPolicy


def test_old_module_name_warns_and_re_exports():
    sys.modules.pop("engram_erc.surgical_intelligence", None)
    with pytest.warns(DeprecationWarning, match="case_intelligence"):
        old = importlib.import_module("engram_erc.surgical_intelligence")
    assert old.execute_surgical_intelligence is execute_case_intelligence
    assert old.SurgicalIntelligenceRequest is CaseIntelligenceRequest


def test_unknown_attribute_still_raises():
    with pytest.raises(AttributeError):
        engram_erc.decision_support.NoSuchThing  # noqa: B018


def test_old_enum_members_and_values_resolve_to_new_members():
    assert OptionAssessmentStatus.CONTRAINDICATED is OptionAssessmentStatus.EXCLUDED
    assert KnowledgeNodeKind.PROCEDURE is KnowledgeNodeKind.ACTIVITY
    # By name, as 0.4.0 code that deserialises enum names does:
    assert KnowledgeNodeKind["ANATOMY"] is KnowledgeNodeKind.ENTITY
    assert EvidenceClass["RANDOMIZED_TRIAL"] is EvidenceClass.PUBLISHED_STUDY
    assert DecisionSupportStatus["READY_FOR_CLINICIAN_REVIEW"] is DecisionSupportStatus.READY_FOR_REVIEW
    cases = [(OptionAssessmentStatus, "contraindicated", OptionAssessmentStatus.EXCLUDED),
             (DecisionSupportStatus, "ready_for_clinician_review", DecisionSupportStatus.READY_FOR_REVIEW),
             (EpisodeOutcome, "complication", EpisodeOutcome.ADVERSE_EVENT),
             (EvidenceClass, "surgical_experience", EvidenceClass.PRACTITIONER_EXPERIENCE),
             (EvidenceClass, "registry_analysis", EvidenceClass.RECORDS_ANALYSIS),
             (EvidenceClass, "randomized_trial", EvidenceClass.PUBLISHED_STUDY),
             (KnowledgeNodeKind, "anatomy", KnowledgeNodeKind.ENTITY)]
    for cls, old_value, member in cases:
        with pytest.warns(DeprecationWarning, match=old_value):
            assert cls(old_value) is member
    assert len(list(OptionAssessmentStatus)) == 8  # aliases add no members
    assert "CONTRAINDICATED" not in [m.name for m in OptionAssessmentStatus]
    with pytest.raises(ValueError):
        OptionAssessmentStatus("no_such_value")


def test_subtype_cannot_impersonate_another_core_kind():
    with pytest.raises(ValueError, match="different core node kind"):
        KnowledgeNode("n", KnowledgeNodeKind.ENTITY, "N", "d", ("s",), "p", subtype="event")
    KnowledgeNode("n", KnowledgeNodeKind.EVENT, "N", "d", ("s",), "p", subtype="event")  # own value is fine


def test_one_subtype_names_one_kind_within_a_graph():
    a = KnowledgeNode("a", KnowledgeNodeKind.ENTITY, "A", "d", ("s",), "p", subtype="unit")
    b = KnowledgeNode("b", KnowledgeNodeKind.ACTIVITY, "B", "d", ("s",), "p", subtype="unit")
    with pytest.raises(ValueError, match="more than one node kind"):
        build_knowledge_graph((a, b), ())


def test_legacy_kwargs_only_converts_fields_the_class_has():
    from engram_erc.profiles.surgical import legacy_kwargs
    # Unscoped (direct use): converts as documented.
    assert legacy_kwargs(kind="procedure") == {"kind": KnowledgeNodeKind.ACTIVITY, "subtype": "procedure"}
    # Scoped to a class without `subtype`: an unrelated `kind` value is left alone.
    assert legacy_kwargs(frozenset({"kind", "signal_id"}), kind="procedure") == {"kind": "procedure"}
    assert legacy_kwargs(frozenset({"evidence_class"}), evidence_class="randomized_trial") == \
        {"evidence_class": "randomized_trial"}


def test_from_legacy_accepts_0_4_0_field_names_and_values():
    with pytest.warns(DeprecationWarning):
        ctx = CaseContext.from_legacy(context_id="ctx", task_type="t", procedure_ref="proc:1", facts=(), as_of=T0)
    assert ctx.activity_ref == "proc:1"
    with pytest.warns(DeprecationWarning):
        opt = DecisionOption.from_legacy(option_id="o", label="O", description="d", contraindication_refs=("c",))
    assert opt.exclusion_refs == ("c",)
    with pytest.warns(DeprecationWarning):
        ev = EvidenceLinkRecord.from_legacy(evidence_ref="e", relation=EvidenceRelation.SUPPORTS,
                                            evidence_class="randomized_trial", source_ref="s", claim_ref="c",
                                            context_key="k")
    assert (ev.evidence_class, ev.evidence_label) == (EvidenceClass.PUBLISHED_STUDY, "randomized_trial")
    with pytest.warns(DeprecationWarning):
        with pytest.raises(TypeError, match="given twice"):
            CaseContext.from_legacy(context_id="c", task_type="t", procedure_ref="a", activity_ref="b",
                                    facts=(), as_of=T0)


def test_from_legacy_graph_reproduces_0_4_0_fingerprint():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        n = (KnowledgeNode.from_legacy(node_ref="anat:liver", kind="anatomy", label="Liver", domain="hpb",
                                       source_refs=("src:l",), provenance_ref="prov:l"),
             KnowledgeNode.from_legacy(node_ref="proc:hep", kind="procedure", label="Hepatectomy", domain="hpb",
                                       source_refs=("src:h",), provenance_ref="prov:h"),
             KnowledgeNode("mech:perf", KnowledgeNodeKind.MECHANISM, "Perfusion", "shared", ("src:m",), "prov:m"))
    e = (KnowledgeEdge("e1", "proc:hep", "anat:liver", KnowledgeRelation.INVOLVES, ("src:e1",), "prov:e1"),
         KnowledgeEdge("e2", "proc:hep", "mech:perf", KnowledgeRelation.HAS_MECHANISM, ("src:e2",), "prov:e2",
                       ("ev:1",)))
    assert build_knowledge_graph(n, e).graph_fingerprint == GRAPH_FINGERPRINT_AT_0_4_0


def test_legacy_request_runs_end_to_end_with_old_names():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        Ctx = engram_erc.SurgicalContext
        Req = engram_erc.SurgicalIntelligenceRequest
        run = engram_erc.execute_surgical_intelligence
        Policy = engram_erc.SurgicalReasoningPolicy
        ctx = Ctx.from_legacy(context_id="ctx1", task_type="surgical_review", procedure_ref="proc1",
                              facts=(ContextFact("age", 60, "registry:case1", T0),), as_of=T0, site_ref="site1")
        req = Req.from_legacy(request_id="exec1", generated_at=T0 + timedelta(hours=1),
                              reasoning_request=ReasoningRequest("r1", "surgical_review", (), as_of=T0),
                              surgical_context=ctx, governed_knowledge=(), lifecycle=KnowledgeLifecycleLedger())
        report = run(req, reasoning_policy=Policy(require_at_least_one_applicable_item=False))
    assert report.reasoning is not None and report.profile_id == "general"


def test_version_comes_from_version_file():
    assert engram_erc.__version__ == (PKG / "VERSION").read_text().strip() == "0.6.0"


@pytest.mark.parametrize("module", ["engram_erc.examples.general_incident",
                                    "engram_erc.examples.surgical.contextual_application",
                                    "engram_erc.examples.surgical.experience_reasoning",
                                    "engram_erc.examples.surgical.knowledge_graph",
                                    "engram_erc.examples.surgical.temporal_patterns",
                                    "engram_erc.examples.surgical.decision_support"])
def test_examples_import_without_deprecated_names(module):
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        importlib.import_module(module)
