"""Prospective case learning workflow (ERC-3.6).

Captures a case's reasoning/decision, action, follow-up and adjudicated outcome
as an append-only event stream. Case outcome labels are kept separate from
reasoning-correctness labels; no causal attribution or automatic learning occurs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .contracts import require_aware_datetime, require_nonempty
from .feedback import FeedbackLedger, OutcomeEvent, OutcomeLabel
from .consolidation import ExperienceRecord
from .temporal_patterns import EpisodeOutcome


class ProspectiveEventKind(str, Enum):
    DECISION_RECORDED = "decision_recorded"
    ACTION_RECORDED = "action_recorded"
    FOLLOW_UP_RECORDED = "follow_up_recorded"
    OUTCOME_ADJUDICATED = "outcome_adjudicated"
    CASE_CLOSED = "case_closed"


class ProspectiveCaseStatus(str, Enum):
    OPEN = "open"
    DECISION_RECORDED = "decision_recorded"
    ACTION_RECORDED = "action_recorded"
    FOLLOW_UP_RECORDED = "follow_up_recorded"
    ADJUDICATED = "adjudicated"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ProspectiveCase:
    case_ref: str
    result_ref: str
    activity_ref: str
    context_key: str
    task_type: str
    site_ref: str | None
    opened_at: datetime
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("case_ref", "result_ref", "activity_ref", "context_key", "task_type"):
            require_nonempty(getattr(self, name), name)
        require_aware_datetime(self.opened_at, "opened_at")
        if not self.source_refs or any(not x.strip() for x in self.source_refs):
            raise ValueError("case source_refs are required")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("case source_refs must be unique")


@dataclass(frozen=True, slots=True)
class ProspectiveEvent:
    event_id: str
    case_ref: str
    kind: ProspectiveEventKind
    occurred_at: datetime
    actor_ref: str
    source_refs: tuple[str, ...]
    related_refs: tuple[str, ...] = ()
    adjudication_ref: str | None = None
    case_outcome: EpisodeOutcome | None = None
    feedback_outcome: OutcomeLabel | None = None
    conclusion_ref: str | None = None
    learning_statement: str | None = None
    experience_kind: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("event_id", "case_ref", "actor_ref"):
            require_nonempty(getattr(self, name), name)
        require_aware_datetime(self.occurred_at, "occurred_at")
        if not self.source_refs or any(not x.strip() for x in self.source_refs):
            raise ValueError("event source_refs are required")
        for name in ("source_refs", "related_refs", "tags"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
        if self.kind in {ProspectiveEventKind.DECISION_RECORDED, ProspectiveEventKind.ACTION_RECORDED} and not self.related_refs:
            raise ValueError(f"{self.kind.value} requires related_refs")
        if self.kind == ProspectiveEventKind.OUTCOME_ADJUDICATED:
            require_nonempty(self.adjudication_ref or "", "adjudication_ref")
            if self.case_outcome is None:
                raise ValueError("adjudicated event requires an explicit case_outcome")
            if self.learning_statement is not None and not self.learning_statement.strip():
                raise ValueError("learning_statement cannot be blank")
            if self.experience_kind is not None and not self.experience_kind.strip():
                raise ValueError("experience_kind cannot be blank")
            if self.feedback_outcome is not None:
                require_nonempty(self.conclusion_ref or "", "conclusion_ref")


@dataclass(frozen=True, slots=True)
class ProspectiveLearningLedger:
    cases: tuple[ProspectiveCase, ...] = ()
    events: tuple[ProspectiveEvent, ...] = ()

    def __post_init__(self) -> None:
        case_ids = [x.case_ref for x in self.cases]
        event_ids = [x.event_id for x in self.events]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("duplicate prospective case_ref")
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("duplicate prospective event_id")
        known = set(case_ids)
        if any(e.case_ref not in known for e in self.events):
            raise ValueError("prospective event references an unknown case")

    def open_case(self, case: ProspectiveCase) -> "ProspectiveLearningLedger":
        existing = {x.case_ref: x for x in self.cases}
        if case.case_ref in existing:
            if existing[case.case_ref] != case:
                raise ValueError("case_ref already exists with different content")
            return self
        return ProspectiveLearningLedger(self.cases + (case,), self.events)

    def append(self, event: ProspectiveEvent) -> "ProspectiveLearningLedger":
        existing = {x.event_id: x for x in self.events}
        if event.event_id in existing:
            if existing[event.event_id] != event:
                raise ValueError("event_id already exists with different content")
            return self
        case = next((x for x in self.cases if x.case_ref == event.case_ref), None)
        if case is None:
            raise ValueError("event references an unknown case")
        case_events = tuple(x for x in self.events if x.case_ref == event.case_ref)
        if event.occurred_at < case.opened_at:
            raise ValueError("event cannot precede case opening")
        if case_events and event.occurred_at < max(x.occurred_at for x in case_events):
            raise ValueError("events must be appended in non-decreasing time order")
        status = _status(case_events)
        if status == ProspectiveCaseStatus.CLOSED:
            raise ValueError("case is closed; no further events are permitted")
        if status == ProspectiveCaseStatus.ADJUDICATED and event.kind != ProspectiveEventKind.CASE_CLOSED:
            raise ValueError("only a closure event is permitted after adjudication")
        if event.kind == ProspectiveEventKind.DECISION_RECORDED and status != ProspectiveCaseStatus.OPEN:
            raise ValueError("decision must be recorded before actions or follow-up")
        if event.kind == ProspectiveEventKind.ACTION_RECORDED and status not in {
            ProspectiveCaseStatus.DECISION_RECORDED, ProspectiveCaseStatus.ACTION_RECORDED,
        }:
            raise ValueError("action requires a recorded decision")
        if event.kind == ProspectiveEventKind.FOLLOW_UP_RECORDED and status not in {
            ProspectiveCaseStatus.ACTION_RECORDED, ProspectiveCaseStatus.FOLLOW_UP_RECORDED,
        }:
            raise ValueError("follow-up requires at least one recorded action")
        if event.kind == ProspectiveEventKind.OUTCOME_ADJUDICATED and status != ProspectiveCaseStatus.FOLLOW_UP_RECORDED:
            raise ValueError("outcome adjudication requires at least one follow-up record")
        if event.kind == ProspectiveEventKind.CASE_CLOSED and status != ProspectiveCaseStatus.ADJUDICATED:
            raise ValueError("case can only close after outcome adjudication")
        return ProspectiveLearningLedger(self.cases, self.events + (event,))

    def append_many(self, events: Iterable[ProspectiveEvent]) -> "ProspectiveLearningLedger":
        ledger = self
        for event in events:
            ledger = ledger.append(event)
        return ledger


def _status(events: tuple[ProspectiveEvent, ...]) -> ProspectiveCaseStatus:
    if not events:
        return ProspectiveCaseStatus.OPEN
    kinds = {e.kind for e in events}
    if ProspectiveEventKind.CASE_CLOSED in kinds:
        return ProspectiveCaseStatus.CLOSED
    if ProspectiveEventKind.OUTCOME_ADJUDICATED in kinds:
        return ProspectiveCaseStatus.ADJUDICATED
    if ProspectiveEventKind.FOLLOW_UP_RECORDED in kinds:
        return ProspectiveCaseStatus.FOLLOW_UP_RECORDED
    if ProspectiveEventKind.ACTION_RECORDED in kinds:
        return ProspectiveCaseStatus.ACTION_RECORDED
    return ProspectiveCaseStatus.DECISION_RECORDED


@dataclass(frozen=True, slots=True)
class CaseLearningStatus:
    case_ref: str
    status: ProspectiveCaseStatus
    decision_refs: tuple[str, ...]
    action_refs: tuple[str, ...]
    follow_up_refs: tuple[str, ...]
    adjudication_ref: str | None
    learning_candidate_ready: bool
    limitations: tuple[str, ...]


def inspect_prospective_case(ledger: ProspectiveLearningLedger, case_ref: str) -> CaseLearningStatus:
    case = next((x for x in ledger.cases if x.case_ref == case_ref), None)
    if case is None:
        raise KeyError(case_ref)
    events = tuple(x for x in ledger.events if x.case_ref == case_ref)
    status = _status(events)
    decision = tuple(r for e in events if e.kind == ProspectiveEventKind.DECISION_RECORDED for r in e.related_refs)
    actions = tuple(r for e in events if e.kind == ProspectiveEventKind.ACTION_RECORDED for r in e.related_refs)
    followups = tuple(r for e in events if e.kind == ProspectiveEventKind.FOLLOW_UP_RECORDED for r in e.related_refs)
    adjudication = next((e for e in reversed(events) if e.kind == ProspectiveEventKind.OUTCOME_ADJUDICATED), None)
    ready = bool(adjudication and adjudication.learning_statement and adjudication.experience_kind
                 and adjudication.feedback_outcome and adjudication.conclusion_ref and case.site_ref)
    limitations = []
    if not decision: limitations.append("No decision reference recorded.")
    if not actions: limitations.append("No action reference recorded.")
    if not followups: limitations.append("No follow-up reference recorded.")
    if not adjudication: limitations.append("Outcome has not been adjudicated.")
    if adjudication and not ready: limitations.append("Missing explicit learning statement, experience kind, feedback adjudication, conclusion reference or site reference; not ready for consolidation.")
    limitations.append("Prospective sequence is observational; action/outcome association does not establish causality.")
    return CaseLearningStatus(case_ref, status, decision, actions, followups,
        adjudication.adjudication_ref if adjudication else None, ready, tuple(limitations))


def to_feedback_event(ledger: ProspectiveLearningLedger, case_ref: str, *, event_id: str) -> OutcomeEvent:
    """Export only explicitly adjudicated reasoning feedback; never infer it from case outcome."""
    case = next((x for x in ledger.cases if x.case_ref == case_ref), None)
    if case is None: raise KeyError(case_ref)
    adjudication = next((e for e in reversed(ledger.events)
        if e.case_ref == case_ref and e.kind == ProspectiveEventKind.OUTCOME_ADJUDICATED), None)
    if adjudication is None or adjudication.feedback_outcome is None:
        raise ValueError("explicit reasoning feedback outcome is required before FeedbackLedger export")
    return OutcomeEvent(
        event_id=event_id, result_id=case.result_ref,
        conclusion_ref=adjudication.conclusion_ref or "",
        outcome=adjudication.feedback_outcome, observed_at=adjudication.occurred_at,
        adjudication_source_ref=adjudication.adjudication_ref or "",
        task_type=case.task_type, context_tags=(case.context_key,),
        source_refs=tuple(sorted(set(case.source_refs + adjudication.source_refs))),
    )


def append_feedback(ledger: FeedbackLedger, prospective: ProspectiveLearningLedger,
                    case_ref: str, *, event_id: str) -> FeedbackLedger:
    return ledger.append(to_feedback_event(prospective, case_ref, event_id=event_id))


def to_experience_record(
    ledger: ProspectiveLearningLedger, case_ref: str, *, experience_id: str,
    outcome_event_ref: str, feedback_ledger: FeedbackLedger,
    learning_statement: str | None = None, tags: tuple[str, ...] = (),
) -> ExperienceRecord:
    """Prepare a consolidation input only when caller supplies explicit links and learning text."""
    case = next((x for x in ledger.cases if x.case_ref == case_ref), None)
    if case is None: raise KeyError(case_ref)
    adjudication = next((e for e in reversed(ledger.events)
        if e.case_ref == case_ref and e.kind == ProspectiveEventKind.OUTCOME_ADJUDICATED), None)
    if adjudication is None: raise ValueError("case requires an adjudicated outcome")
    statement = learning_statement or adjudication.learning_statement
    if not statement or not statement.strip(): raise ValueError("explicit learning_statement is required")
    if not adjudication.experience_kind: raise ValueError("experience_kind is required in adjudication")
    if not adjudication.feedback_outcome: raise ValueError("explicit reasoning feedback outcome is required")
    linked_feedback = next((e for e in feedback_ledger.events if e.event_id == outcome_event_ref), None)
    if linked_feedback is None: raise ValueError("outcome_event_ref is absent from supplied FeedbackLedger")
    if linked_feedback.result_id != case.result_ref or linked_feedback.conclusion_ref != adjudication.conclusion_ref:
        raise ValueError("feedback event does not match prospective case/result/conclusion")
    if linked_feedback.outcome != adjudication.feedback_outcome:
        raise ValueError("feedback event outcome does not match explicit adjudication")
    if linked_feedback.adjudication_source_ref != adjudication.adjudication_ref:
        raise ValueError("feedback event adjudication reference does not match prospective adjudication")
    if linked_feedback.observed_at != adjudication.occurred_at:
        raise ValueError("feedback event timestamp does not match prospective adjudication")
    if not adjudication.conclusion_ref: raise ValueError("explicit conclusion_ref is required")
    if not case.site_ref: raise ValueError("site_ref is required for consolidation input")

    return ExperienceRecord(
        experience_id=experience_id, result_id=case.result_ref,
        conclusion_ref=adjudication.conclusion_ref,
        outcome_event_ref=outcome_event_ref, context_key=case.context_key,
        task_type=case.task_type, site_ref=case.site_ref,
        activity_ref=case.activity_ref, experience_kind=adjudication.experience_kind,
        learning_statement=statement, source_refs=tuple(sorted(set(
            case.source_refs + adjudication.source_refs + adjudication.related_refs))),
        recorded_at=adjudication.occurred_at, tags=tuple(sorted(set(tags + adjudication.tags))),
    )
