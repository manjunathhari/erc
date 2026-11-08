"""Event-driven situation awareness (ERC-3.3).

Consumes provenance-bearing observations and caller-authored trigger rules.
It detects configured signals and state changes; it does not diagnose, set
domain thresholds, recommend treatment, or execute real-world actions.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from .contracts import require_aware_datetime, require_nonempty


class TriggerOperator(str, Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    CHANGED = "changed"


class SignalStatus(str, Enum):
    ACTIVE = "active"
    NOT_TRIGGERED = "not_triggered"
    INSUFFICIENT_DATA = "insufficient_data"
    STALE = "stale"


class SignalTransitionKind(str, Enum):
    OPENED = "opened"
    CONTINUED = "continued"
    RESOLVED = "resolved"
    BECAME_INDETERMINATE = "became_indeterminate"


@dataclass(frozen=True, slots=True)
class ObservationEvent:
    event_id: str
    case_ref: str
    subject_ref: str
    metric: str
    value: float | int | str | bool
    unit: str
    observed_at: datetime
    source_ref: str
    source_kind: str = "registry_observation"
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("event_id", "case_ref", "subject_ref", "metric", "unit", "source_ref", "source_kind"):
            require_nonempty(getattr(self, name), name)
        require_aware_datetime(self.observed_at, "observed_at")
        if isinstance(self.value, float) and (self.value != self.value or self.value in (float("inf"), float("-inf"))):
            raise ValueError("numeric observation must be finite")


@dataclass(frozen=True, slots=True)
class TriggerRule:
    rule_id: str
    description: str
    metric: str
    operator: TriggerOperator
    threshold: float | int | str | bool | None
    severity: str
    source_ref: str
    unit: str
    subject_ref: str | None = None
    consecutive_observations: int = 1
    window_seconds: int = 3600
    max_age_seconds: int = 3600

    def __post_init__(self) -> None:
        for name in ("rule_id", "description", "metric", "severity", "source_ref", "unit"):
            require_nonempty(getattr(self, name), name)
        if self.operator == TriggerOperator.CHANGED and self.threshold is not None:
            raise ValueError("CHANGED rule must use threshold=None")
        if self.operator != TriggerOperator.CHANGED and self.threshold is None:
            raise ValueError("threshold is required except for CHANGED")
        if self.consecutive_observations < 1 or self.window_seconds < 1 or self.max_age_seconds < 1:
            raise ValueError("consecutive_observations, window_seconds and max_age_seconds must be positive")


@dataclass(frozen=True, slots=True)
class SignalEvaluation:
    rule_id: str
    case_ref: str
    subject_ref: str
    status: SignalStatus
    observed_value: float | int | str | bool | None
    threshold: float | int | str | bool | None
    unit: str
    observation_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    evaluated_at: datetime
    rationale: str


@dataclass(frozen=True, slots=True)
class SignalTransition:
    transition_id: str
    rule_id: str
    case_ref: str
    subject_ref: str
    kind: SignalTransitionKind
    from_status: SignalStatus | None
    to_status: SignalStatus
    observed_at: datetime
    observation_refs: tuple[str, ...]
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_nonempty(self.transition_id, "transition_id")
        require_aware_datetime(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class SituationLedger:
    observations: tuple[ObservationEvent, ...] = ()
    transitions: tuple[SignalTransition, ...] = ()

    def __post_init__(self) -> None:
        ids = [x.event_id for x in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate observation event_id")
        tids = [x.transition_id for x in self.transitions]
        if len(tids) != len(set(tids)):
            raise ValueError("duplicate transition_id")

    def append_observation(self, event: ObservationEvent) -> "SituationLedger":
        for old in self.observations:
            if old.event_id == event.event_id:
                if old == event:
                    return self
                raise ValueError("observation event_id collision")
        return SituationLedger(self.observations + (event,), self.transitions)

    def append_transition(self, event: SignalTransition) -> "SituationLedger":
        for old in self.transitions:
            if old.transition_id == event.transition_id:
                if old == event:
                    return self
                raise ValueError("transition_id collision")
        return SituationLedger(self.observations, self.transitions + (event,))


@dataclass(frozen=True, slots=True)
class SituationPolicy:
    allow_out_of_order_events: bool = True
    require_source_ref: bool = True
    max_events_per_rule: int = 1000

    def __post_init__(self) -> None:
        if self.max_events_per_rule < 1:
            raise ValueError("max_events_per_rule must be positive")


@dataclass(frozen=True, slots=True)
class SituationReport:
    generated_at: datetime
    evaluations: tuple[SignalEvaluation, ...]
    transitions: tuple[SignalTransition, ...]
    active_signals: tuple[SignalEvaluation, ...]
    ledger: SituationLedger
    limitations: tuple[str, ...]


def _matches(value: Any, rule: TriggerRule) -> bool:
    op, threshold = rule.operator, rule.threshold
    if op == TriggerOperator.CHANGED:
        return False
    if op == TriggerOperator.EQ:
        return value == threshold
    if isinstance(value, bool) or isinstance(threshold, bool):
        return False
    if not isinstance(value, (int, float)) or not isinstance(threshold, (int, float)):
        return False
    if op == TriggerOperator.GT: return value > threshold
    if op == TriggerOperator.GTE: return value >= threshold
    if op == TriggerOperator.LT: return value < threshold
    if op == TriggerOperator.LTE: return value <= threshold
    return False


def evaluate_situation(
    rules: tuple[TriggerRule, ...],
    events: tuple[ObservationEvent, ...],
    *,
    as_of: datetime,
    ledger: SituationLedger = SituationLedger(),
    policy: SituationPolicy = SituationPolicy(),
) -> SituationReport:
    """Evaluate explicit trigger rules over a bounded, immutable event snapshot."""
    require_aware_datetime(as_of, "as_of")
    if len({r.rule_id for r in rules}) != len(rules):
        raise ValueError("rule_id values must be unique")
    updated = ledger
    for event in events:
        if event.observed_at > as_of:
            raise ValueError("future observation cannot be evaluated")
        if policy.require_source_ref and not event.source_ref:
            raise ValueError("observation source_ref is required")
        updated = updated.append_observation(event)
    evaluations: list[SignalEvaluation] = []
    new_transitions: list[SignalTransition] = []
    for rule in rules:
        matched = [e for e in updated.observations if e.metric == rule.metric
                   and (rule.subject_ref is None or e.subject_ref == rule.subject_ref)]
        groups = sorted({(e.case_ref, e.subject_ref) for e in matched})
        for case_ref, subject in groups:
            series = sorted((e for e in matched if e.case_ref == case_ref and e.subject_ref == subject), key=lambda x: (x.observed_at, x.event_id))
            series = series[-policy.max_events_per_rule:]
            in_window = [e for e in series if e.observed_at <= as_of
                         and e.observed_at >= as_of - timedelta(seconds=rule.window_seconds)]
            relevant = [e for e in in_window if e.unit == rule.unit]
            latest = relevant[-1] if relevant else None
            if not relevant and in_window:
                status, rationale, chosen = SignalStatus.INSUFFICIENT_DATA, "Matching metric exists, but no observation has the rule's required unit.", in_window[-1:]
            elif latest is None:
                status, rationale, chosen = SignalStatus.INSUFFICIENT_DATA, "No matching observation in the configured window.", []
            elif as_of - latest.observed_at > timedelta(seconds=rule.max_age_seconds):
                status, rationale, chosen = SignalStatus.STALE, "Latest matching observation exceeds the configured freshness window.", [latest]
            elif rule.operator == TriggerOperator.CHANGED:
                if len(relevant) < 2:
                    status, rationale, chosen = SignalStatus.INSUFFICIENT_DATA, "A prior observation is required to evaluate change.", relevant
                else:
                    changed = relevant[-1].value != relevant[-2].value
                    status = SignalStatus.ACTIVE if changed else SignalStatus.NOT_TRIGGERED
                    rationale = "Value differs from the immediately preceding observation." if changed else "Value is unchanged from the immediately preceding observation."
                    chosen = relevant[-2:]
            else:
                tail = relevant[-rule.consecutive_observations:]
                if len(tail) < rule.consecutive_observations:
                    status, rationale, chosen = SignalStatus.INSUFFICIENT_DATA, "Not enough observations for the configured consecutive-observation requirement.", tail
                elif all(_matches(e.value, rule) for e in tail):
                    status, rationale, chosen = SignalStatus.ACTIVE, "Configured condition met for the required consecutive observations.", tail
                else:
                    status, rationale, chosen = SignalStatus.NOT_TRIGGERED, "Configured condition is not met across the required observations.", tail
            ev = SignalEvaluation(rule.rule_id, case_ref, subject, status, latest.value if latest else None,
                                  rule.threshold, rule.unit, tuple(e.event_id for e in chosen),
                                  tuple(sorted({e.source_ref for e in chosen})), as_of, rationale)
            evaluations.append(ev)
            prior = [t for t in updated.transitions if t.rule_id == rule.rule_id and t.case_ref == case_ref and t.subject_ref == subject]
            previous = prior[-1].to_status if prior else None
            if previous != status or status == SignalStatus.ACTIVE:
                if status == SignalStatus.ACTIVE:
                    kind = SignalTransitionKind.OPENED if previous != SignalStatus.ACTIVE else SignalTransitionKind.CONTINUED
                elif status in {SignalStatus.NOT_TRIGGERED} and previous == SignalStatus.ACTIVE:
                    kind = SignalTransitionKind.RESOLVED
                elif status in {SignalStatus.STALE, SignalStatus.INSUFFICIENT_DATA}:
                    kind = SignalTransitionKind.BECAME_INDETERMINATE
                else:
                    kind = SignalTransitionKind.RESOLVED if previous == SignalStatus.ACTIVE else SignalTransitionKind.BECAME_INDETERMINATE
                tid = f"transition:{rule.rule_id}:{case_ref}:{subject}:{as_of.isoformat()}:{status.value}"
                transition = SignalTransition(tid, rule.rule_id, case_ref, subject, kind, previous, status,
                                              as_of, ev.observation_refs, ev.source_refs)
                updated = updated.append_transition(transition)
                new_transitions.append(transition)
    return SituationReport(as_of, tuple(evaluations), tuple(new_transitions),
                           tuple(e for e in evaluations if e.status == SignalStatus.ACTIVE), updated,
                           ("Trigger rules and thresholds are caller-authored; ERC supplies no domain thresholds.",
                            "A triggered signal is not a diagnosis or treatment recommendation.",
                            "No automatic alert delivery, registry mutation, or real-world action is performed.",
                            "Event ordering uses observed_at and event_id; source quality is not independently verified."))
