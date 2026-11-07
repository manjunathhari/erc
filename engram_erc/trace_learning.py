"""Outcome-linked reasoning trace analysis (descriptive, non-causal).

The module associates an adjudicated conclusion with the deterministic
inference lineage that produced it. It reports recurring paths and step-level
outcome frequencies; it does not change rules, weights, evidence, or strategy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .contracts import ReasoningResult
from .feedback import FeedbackLedger, OutcomeEvent, OutcomeLabel


class TraceLearningStatus(str, Enum):
    ANALYZED = "analyzed"
    INSUFFICIENT_DATA = "insufficient_data"
    NO_MATCHING_TRACES = "no_matching_traces"


@dataclass(frozen=True, slots=True)
class TraceLearningPolicy:
    min_adjudicated_events: int = 5
    include_context_tags: bool = True

    def __post_init__(self) -> None:
        if self.min_adjudicated_events < 1:
            raise ValueError("min_adjudicated_events must be at least 1")


@dataclass(frozen=True, slots=True)
class TraceOutcomeCounts:
    verified_supported: int = 0
    contradicted: int = 0
    inconclusive: int = 0
    superseded: int = 0

    @property
    def adjudicated(self) -> int:
        return self.verified_supported + self.contradicted

    @property
    def observed_success_rate(self) -> float | None:
        return (self.verified_supported / self.adjudicated) if self.adjudicated else None


@dataclass(frozen=True, slots=True)
class TracePatternMetric:
    path_signature: tuple[str, ...]
    root_premise_signature: tuple[str, ...]
    context_key: str
    counts: TraceOutcomeCounts
    event_refs: tuple[str, ...]
    result_refs: tuple[str, ...]
    eligible_for_comparison: bool
    limitation: str


@dataclass(frozen=True, slots=True)
class TraceStepMetric:
    rule_id: str
    operation: str
    context_key: str
    counts: TraceOutcomeCounts
    event_refs: tuple[str, ...]
    eligible_for_comparison: bool
    limitation: str


@dataclass(frozen=True, slots=True)
class UnmatchedTraceOutcome:
    event_ref: str
    reason: str


@dataclass(frozen=True, slots=True)
class TraceLearningReport:
    status: TraceLearningStatus
    generated_at: datetime
    min_adjudicated_events: int
    patterns: tuple[TracePatternMetric, ...]
    steps: tuple[TraceStepMetric, ...]
    unmatched_outcomes: tuple[UnmatchedTraceOutcome, ...]
    limitations: tuple[str, ...]


def _lineage(result: ReasoningResult, conclusion_ref: str):
    """Return contributing steps and root premises for a conclusion."""
    producers: dict[str, object] = {}
    for step in result.inference_steps:
        for output in step.output_proposition_refs:
            producers[output] = step
    needed_steps: set[str] = set()
    visited_props: set[str] = set()
    root_refs: set[str] = set()

    def visit(prop_ref: str) -> None:
        if prop_ref in visited_props:
            return
        visited_props.add(prop_ref)
        step = producers.get(prop_ref)
        if step is None:
            root_refs.add(prop_ref)
            return
        if step.id in needed_steps:
            return
        needed_steps.add(step.id)
        for input_ref in step.input_refs:
            visit(input_ref)

    visit(conclusion_ref)
    ordered_steps = tuple(step for step in result.inference_steps if step.id in needed_steps)
    prop_map = {p.id: p for p in result.propositions}
    # Predicate/polarity descriptors preserve premise structure without
    # embedding patient-specific object values or raw source content.
    premise_signature = tuple(sorted(
        f"{prop_map[ref].predicate}|polarity={int(prop_map[ref].polarity)}"
        for ref in root_refs if ref in prop_map
    ))
    return ordered_steps, premise_signature


def _context(event: OutcomeEvent, include_tags: bool) -> str:
    if not include_tags or not event.context_tags:
        return event.task_type
    return event.task_type + "|" + "&".join(sorted(event.context_tags))


def _counts(events: Iterable[OutcomeEvent]) -> TraceOutcomeCounts:
    values = {label: 0 for label in OutcomeLabel}
    for event in events:
        values[event.outcome] += 1
    return TraceOutcomeCounts(
        values[OutcomeLabel.VERIFIED_SUPPORTED], values[OutcomeLabel.CONTRADICTED],
        values[OutcomeLabel.INCONCLUSIVE], values[OutcomeLabel.SUPERSEDED],
    )


def learn_reasoning_traces(
    ledger: FeedbackLedger,
    results: Iterable[ReasoningResult],
    *,
    policy: TraceLearningPolicy = TraceLearningPolicy(),
    generated_at=None,
) -> TraceLearningReport:
    """Summarize outcome associations for full paths and individual steps.

    The association is descriptive: an outcome on a conclusion is mapped to
    the steps in its recorded lineage, not asserted to have been caused by
    each step. Inconclusive/superseded observations remain visible but are
    excluded from the adjudicated success-rate denominator.
    """
    from datetime import timezone
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    result_map = {result.id: result for result in results}
    if len(result_map) == 0:
        return TraceLearningReport(TraceLearningStatus.NO_MATCHING_TRACES, generated_at,
            policy.min_adjudicated_events, (), (), (), ("No reasoning results were supplied.",))

    pattern_buckets: dict[tuple[tuple[str, ...], tuple[str, ...], str], list[OutcomeEvent]] = {}
    step_buckets: dict[tuple[str, str, str], list[OutcomeEvent]] = {}
    unmatched: list[UnmatchedTraceOutcome] = []
    matched = 0
    for event in ledger.events:
        result = result_map.get(event.result_id)
        if result is None:
            unmatched.append(UnmatchedTraceOutcome(event.event_id, "RESULT_NOT_SUPPLIED"))
            continue
        if event.conclusion_ref not in result.conclusion_refs:
            unmatched.append(UnmatchedTraceOutcome(event.event_id, "CONCLUSION_NOT_IN_RESULT"))
            continue
        lineage, premise_signature = _lineage(result, event.conclusion_ref)
        if not lineage:
            unmatched.append(UnmatchedTraceOutcome(event.event_id, "NO_RECORDED_INFERENCE_LINEAGE"))
            continue
        matched += 1
        context = _context(event, policy.include_context_tags)
        signature = tuple(f"{step.operation}:{step.rule_id}" for step in lineage)
        pattern_buckets.setdefault((signature, premise_signature, context), []).append(event)
        # One event counts once per distinct rule/operation in the lineage.
        unique_steps = {(step.rule_id, step.operation) for step in lineage}
        for rule_id, operation in unique_steps:
            step_buckets.setdefault((rule_id, operation, context), []).append(event)

    patterns = []
    for (signature, premise_signature, context), events in sorted(pattern_buckets.items()):
        counts = _counts(events)
        enough = counts.adjudicated >= policy.min_adjudicated_events
        patterns.append(TracePatternMetric(signature, premise_signature, context, counts,
            tuple(sorted(e.event_id for e in events)), tuple(sorted({e.result_id for e in events})),
            enough, ("Descriptive association only; not causal, predictive, or a rule-quality estimate." if enough
                     else f"Insufficient adjudicated support ({counts.adjudicated}/{policy.min_adjudicated_events}).")))
    steps = []
    for (rule_id, operation, context), events in sorted(step_buckets.items()):
        counts = _counts(events)
        enough = counts.adjudicated >= policy.min_adjudicated_events
        steps.append(TraceStepMetric(rule_id, operation, context, counts,
            tuple(sorted(e.event_id for e in events)), enough,
            ("Outcome is associated with a conclusion lineage containing this step; causality is not established." if enough
             else f"Insufficient adjudicated support ({counts.adjudicated}/{policy.min_adjudicated_events}).")))

    if not matched:
        status = TraceLearningStatus.NO_MATCHING_TRACES
    elif any(item.eligible_for_comparison for item in patterns):
        status = TraceLearningStatus.ANALYZED
    else:
        status = TraceLearningStatus.INSUFFICIENT_DATA
    limitations = (
        "Only outcomes explicitly linked to result_id and conclusion_ref are included.",
        "Lineage association does not establish that a rule or step caused the outcome.",
        "No automatic rule modification, strategy adaptation, or evidence reliability update occurs.",
        "Observed rates are descriptive frequencies, not calibrated probabilities or clinical predictions.",
        "Inconclusive and superseded outcomes are reported but excluded from success-rate denominators.",
    )
    return TraceLearningReport(status, generated_at, policy.min_adjudicated_events,
        tuple(patterns), tuple(steps), tuple(unmatched), limitations)
