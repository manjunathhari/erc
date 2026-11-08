"""Synthetic ERC-4.0 General Core example in a non-medical field: an IT incident.

Run: python -m engram_erc.examples.general_incident

The core decides from core values only. The profile below supplies the words a
site reliability team would use, and is applied only when printing.
"""
from datetime import datetime, timedelta, timezone

from engram_erc import (
    CaseContext, CaseIntelligenceRequest, CaseReasoningPolicy, ContextFact, DecisionOption,
    DomainProfile, EscalationTrigger, KnowledgeLifecycleLedger, ObservationEvent, OptionEvidence,
    ReasoningRequest, TriggerOperator, TriggerRule, execute_case_intelligence,
)

T0 = datetime(2026, 3, 1, 9, tzinfo=timezone.utc)

SRE = DomainProfile(
    profile_id="sre-example", version="0.1.0", case_label="incident", activity_label="service change",
    practitioner_label="engineer", reviewer_label="incident lead", exclusion_label="not permitted",
    adverse_event_label="outage",
    value_labels={"excluded": "not permitted", "review_required": "needs incident-lead review"},
)

request = CaseIntelligenceRequest(
    request_id="exec:INC-31",
    generated_at=T0 + timedelta(minutes=10),
    reasoning_request=ReasoningRequest("reason:INC-31", "incident_response", (), as_of=T0),
    case_context=CaseContext("incident:INC-31", "incident_response", "service:payments-api",
                             (ContextFact("deploy_version", "v41.3", "ticket:INC-31", T0),), T0),
    governed_knowledge=(),
    lifecycle=KnowledgeLifecycleLedger(),
    situation_rules=(TriggerRule("rule:error-rate", "Error rate above 2%", "error_rate_pct",
                                 TriggerOperator.GT, 2.0, "high", "runbook:sre-1", "%"),),
    observations=(ObservationEvent("obs:1", "incident:INC-31", "service:payments-api", "error_rate_pct",
                                   4.2, "%", T0 + timedelta(minutes=5), "metrics:prom-1"),),
    decision_options=(
        DecisionOption("opt:rollback", "Roll back v41.3", "Revert the latest deploy",
                       evidence=(OptionEvidence("ev:pm12", "supports", "postmortem:12"),)),
        DecisionOption("opt:failover", "Fail over region", "Promote the secondary region",
                       exclusion_refs=("policy:change-freeze",)),
    ),
    escalation_triggers=(EscalationTrigger("esc:sev1", "Customer impact above 5 minutes", False),),
    profile_id=SRE.profile_id,
    profile_version=SRE.version,
)

report = execute_case_intelligence(
    request, reasoning_policy=CaseReasoningPolicy(require_at_least_one_applicable_item=False))

if __name__ == "__main__":
    print(f"{SRE.case_label} {report.request_id}: {SRE.label(report.status)}")
    for stage in report.stages:
        print(f"  {stage.stage.value}: {stage.status}")
    for a in report.decision_support.option_assessments:
        print(f"  option {a.option_id}: {SRE.label(a.status)}")
    print(f"  replay fingerprint: {report.replay_fingerprint}")
