"""Structured decision-support assessments (ERC-3.2).

This module organizes caller-supplied options, evidence pointers, risks,
exclusions, missing information and escalation triggers. It does not
select a course of action, rank options, diagnose, or execute actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .contracts import require_aware_datetime, require_nonempty
from .task_orchestration import CaseReasoningReport, CaseTaskStatus


class OptionAssessmentStatus(str, Enum):
    DESCRIBED = "described"
    EVIDENCE_SUPPORTED = "evidence_supported"
    QUALIFIED_SUPPORT = "qualified_support"
    CONFLICTED = "conflicted"
    NOT_SUPPORTED = "not_supported"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    EXCLUDED = "excluded"
    NOT_APPLICABLE = "not_applicable"


class RiskSeverity(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class DecisionSupportStatus(str, Enum):
    READY_FOR_REVIEW = "ready_for_review"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    INSUFFICIENT_INPUT = "insufficient_input"


class ReviewerDisposition(str, Enum):
    SELECTED = "selected"
    NOT_SELECTED = "not_selected"
    DEFERRED = "deferred"
    OVERRIDDEN = "overridden"


@dataclass(frozen=True, slots=True)
class OptionEvidence:
    evidence_ref: str
    relation: str  # supports | contradicts | qualifies
    source_ref: str
    knowledge_ref: str | None = None
    rationale: str = ""

    def __post_init__(self) -> None:
        for name in ("evidence_ref", "relation", "source_ref"):
            require_nonempty(getattr(self, name), name)
        if self.relation not in {"supports", "contradicts", "qualifies"}:
            raise ValueError("relation must be supports, contradicts, or qualifies")


@dataclass(frozen=True, slots=True)
class RiskSignal:
    signal_id: str
    description: str
    severity: RiskSeverity
    evidence_refs: tuple[str, ...] = ()
    context_refs: tuple[str, ...] = ()
    active: bool = True

    def __post_init__(self) -> None:
        require_nonempty(self.signal_id, "signal_id")
        require_nonempty(self.description, "description")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("risk evidence_refs must be unique")


@dataclass(frozen=True, slots=True)
class EscalationTrigger:
    trigger_id: str
    description: str
    triggered: bool
    evidence_refs: tuple[str, ...] = ()
    required_action_ref: str | None = None

    def __post_init__(self) -> None:
        require_nonempty(self.trigger_id, "trigger_id")
        require_nonempty(self.description, "description")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("trigger evidence_refs must be unique")


@dataclass(frozen=True, slots=True)
class DecisionOption:
    option_id: str
    label: str
    description: str
    knowledge_refs: tuple[str, ...] = ()
    evidence: tuple[OptionEvidence, ...] = ()
    risk_signals: tuple[RiskSignal, ...] = ()
    exclusion_refs: tuple[str, ...] = ()
    missing_information: tuple[str, ...] = ()
    applicability_confirmed: bool = True

    def __post_init__(self) -> None:
        for name in ("option_id", "label", "description"):
            require_nonempty(getattr(self, name), name)
        for name in ("knowledge_refs", "exclusion_refs", "missing_information"):
            values = getattr(self, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class OptionAssessment:
    option_id: str
    status: OptionAssessmentStatus
    supporting_evidence_refs: tuple[str, ...]
    contradicting_evidence_refs: tuple[str, ...]
    qualifying_evidence_refs: tuple[str, ...]
    active_risks: tuple[RiskSignal, ...]
    exclusion_refs: tuple[str, ...]
    missing_information: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionSupportRequest:
    request_id: str
    reasoning_report: CaseReasoningReport
    options: tuple[DecisionOption, ...]
    escalation_triggers: tuple[EscalationTrigger, ...] = ()
    required_context_refs: tuple[str, ...] = ()
    generated_at: datetime | None = None

    def __post_init__(self) -> None:
        require_nonempty(self.request_id, "request_id")
        require_aware_datetime(self.generated_at, "generated_at")
        ids = [o.option_id for o in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError("option_id values must be unique")
        tids = [t.trigger_id for t in self.escalation_triggers]
        if len(tids) != len(set(tids)):
            raise ValueError("trigger_id values must be unique")
        if len(set(self.required_context_refs)) != len(self.required_context_refs):
            raise ValueError("required_context_refs must be unique")


@dataclass(frozen=True, slots=True)
class ReviewerDecision:
    decision_id: str
    request_id: str
    option_id: str | None
    disposition: ReviewerDisposition
    reviewer_ref: str
    adjudication_ref: str
    rationale: str
    decided_at: datetime
    acknowledged_risk_refs: tuple[str, ...] = ()
    acknowledged_uncertainty_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("decision_id", "request_id", "reviewer_ref", "adjudication_ref", "rationale"):
            require_nonempty(getattr(self, name), name)
        require_aware_datetime(self.decided_at, "decided_at")
        if self.disposition in {ReviewerDisposition.SELECTED, ReviewerDisposition.NOT_SELECTED} and not self.option_id:
            raise ValueError("selected/not-selected disposition requires option_id")
        if len(set(self.acknowledged_risk_refs)) != len(self.acknowledged_risk_refs):
            raise ValueError("acknowledged_risk_refs must be unique")


@dataclass(frozen=True, slots=True)
class ReviewerDecisionLedger:
    decisions: tuple[ReviewerDecision, ...] = ()

    def __post_init__(self) -> None:
        ids = [d.decision_id for d in self.decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate decision_id")
        for d in self.decisions:
            if d.disposition == ReviewerDisposition.SELECTED:
                prior = [x for x in self.decisions if x.request_id == d.request_id and x.decided_at <= d.decided_at and x.decision_id != d.decision_id and x.disposition == ReviewerDisposition.SELECTED]
                if prior:
                    raise ValueError("multiple selected dispositions for a request; use a new decision event with explicit override/defer workflow")

    def append(self, decision: ReviewerDecision) -> "ReviewerDecisionLedger":
        for existing in self.decisions:
            if existing.decision_id == decision.decision_id:
                if existing == decision:
                    return self
                raise ValueError("decision_id collision")
        return ReviewerDecisionLedger(self.decisions + (decision,))


def assess_option(option: DecisionOption, applied_knowledge_refs: Iterable[str]) -> OptionAssessment:
    allowed = set(applied_knowledge_refs)
    unknown_knowledge = tuple(sorted(set(option.knowledge_refs) - allowed))
    evidence = tuple(e for e in option.evidence if e.knowledge_ref is None or e.knowledge_ref in allowed)
    supporting = tuple(sorted({e.evidence_ref for e in evidence if e.relation == "supports"}))
    contradicting = tuple(sorted({e.evidence_ref for e in evidence if e.relation == "contradicts"}))
    qualifying = tuple(sorted({e.evidence_ref for e in evidence if e.relation == "qualifies"}))
    risks = tuple(r for r in option.risk_signals if r.active)
    exclusions = tuple(sorted(set(option.exclusion_refs)))
    missing = tuple(sorted(set(option.missing_information) | set(unknown_knowledge)))
    if not option.applicability_confirmed:
        status = OptionAssessmentStatus.NOT_APPLICABLE
    elif exclusions:
        status = OptionAssessmentStatus.EXCLUDED
    elif missing:
        status = OptionAssessmentStatus.INSUFFICIENT_INFORMATION
    elif contradicting and supporting:
        status = OptionAssessmentStatus.CONFLICTED
    elif contradicting:
        status = OptionAssessmentStatus.NOT_SUPPORTED
    elif supporting and qualifying:
        status = OptionAssessmentStatus.QUALIFIED_SUPPORT
    elif supporting:
        status = OptionAssessmentStatus.EVIDENCE_SUPPORTED
    else:
        status = OptionAssessmentStatus.DESCRIBED
    limitations = (
        "Evidence relations and applicability are caller-supplied; ERC does not independently verify source content or study quality.",
        "Risk signals and exclusion references are not generated from raw source data by this module.",
        "An evidence-supported option is not a case-specific recommendation or proof of superiority.",
    )
    return OptionAssessment(option.option_id, status, supporting, contradicting, qualifying,
                            risks, exclusions, missing, limitations)


def build_decision_support(request: DecisionSupportRequest) -> "DecisionSupportReport":
    report = request.reasoning_report
    applied = set(report.applied_knowledge_refs)
    assessments = tuple(assess_option(o, applied) for o in request.options)
    triggered = tuple(t for t in request.escalation_triggers if t.triggered)
    high_risk = tuple(r for a in assessments for r in a.active_risks
                      if r.severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL, RiskSeverity.UNKNOWN})
    unknown_context = set(request.required_context_refs) - set(report.context_source_refs)
    blocking_task = report.status in {CaseTaskStatus.BLOCKED_CONTEXT, CaseTaskStatus.BLOCKED_KNOWLEDGE,
                                      CaseTaskStatus.CONFLICTED}
    if blocking_task:
        status = DecisionSupportStatus.BLOCKED
    elif not assessments or unknown_context or any(a.status in {OptionAssessmentStatus.INSUFFICIENT_INFORMATION,
                                             OptionAssessmentStatus.CONFLICTED} for a in assessments):
        status = DecisionSupportStatus.INSUFFICIENT_INPUT
    elif triggered or high_risk or report.review_requirements or report.status != CaseTaskStatus.COMPLETED:
        status = DecisionSupportStatus.REVIEW_REQUIRED
    else:
        status = DecisionSupportStatus.READY_FOR_REVIEW
    overall_limitations = (
        "ERC-3.2 structures decision-relevant information; it does not rank options or select a treatment.",
        "No option is called recommended. Selection remains an explicit, separately recorded reviewer decision.",
        "A triggered escalation item is surfaced for reviewer assessment; no emergency workflow or alert delivery is executed.",
    )
    return DecisionSupportReport(request.request_id, status, assessments, triggered, high_risk,
                                 tuple(sorted(unknown_context)), overall_limitations)


@dataclass(frozen=True, slots=True)
class DecisionSupportReport:
    request_id: str
    status: DecisionSupportStatus
    option_assessments: tuple[OptionAssessment, ...]
    triggered_escalations: tuple[EscalationTrigger, ...]
    high_priority_risks: tuple[RiskSignal, ...]
    missing_required_context_refs: tuple[str, ...]
    limitations: tuple[str, ...]


def record_reviewer_decision(
    ledger: ReviewerDecisionLedger,
    decision: ReviewerDecision,
    report: DecisionSupportReport,
) -> ReviewerDecisionLedger:
    if decision.request_id != report.request_id:
        raise ValueError("decision request_id does not match report")
    known_options = {a.option_id for a in report.option_assessments}
    if decision.option_id is not None and decision.option_id not in known_options:
        raise ValueError("decision references an option not present in the report")
    risk_ids = {r.signal_id for a in report.option_assessments for r in a.active_risks}
    if not set(decision.acknowledged_risk_refs).issubset(risk_ids):
        raise ValueError("decision acknowledges an unknown risk signal")
    if decision.option_id is not None:
        assessment = next(a for a in report.option_assessments if a.option_id == decision.option_id)
        if assessment.status in {OptionAssessmentStatus.EXCLUDED,
                                 OptionAssessmentStatus.CONFLICTED,
                                 OptionAssessmentStatus.INSUFFICIENT_INFORMATION}:
            if decision.disposition != ReviewerDisposition.OVERRIDDEN:
                raise ValueError("excluded, conflicted or insufficient options require explicit OVERRIDDEN disposition")
        if decision.disposition == ReviewerDisposition.SELECTED:
            high_risk_ids = {r.signal_id for r in assessment.active_risks
                             if r.severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL, RiskSeverity.UNKNOWN}}
            if not high_risk_ids.issubset(set(decision.acknowledged_risk_refs)):
                raise ValueError("selected option requires explicit acknowledgement of high/critical/unknown risks")
    return ledger.append(decision)
