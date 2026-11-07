"""Append-only outcome feedback and temporal reliability summaries.

This module records externally adjudicated outcomes. It does not learn or
rewrite rules, alter evidence, or persist data; callers retain the ledger in
their authoritative store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from hashlib import sha256
from typing import Iterable


class OutcomeLabel(str, Enum):
    VERIFIED_SUPPORTED = "verified_supported"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"
    SUPERSEDED = "superseded"


class FeedbackTargetKind(str, Enum):
    CONCLUSION = "conclusion"
    RULE = "rule"
    SOURCE = "source"
    STRATEGY = "strategy"


@dataclass(frozen=True, slots=True)
class OutcomeEvent:
    """One adjudicated outcome, with provenance and context.

    `rule_refs` and `source_refs` are explicit attribution supplied by the
    caller; ERC does not infer causality from mere co-occurrence.
    """
    event_id: str
    result_id: str
    conclusion_ref: str
    outcome: OutcomeLabel
    observed_at: datetime
    adjudication_source_ref: str
    task_type: str
    context_tags: tuple[str, ...] = ()
    rule_refs: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    strategy_ref: str | None = None
    notes_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("event_id", "result_id", "conclusion_ref",
                     "adjudication_source_ref", "task_type"):
            if not getattr(self, name) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        for name in ("context_tags", "rule_refs", "source_refs"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")


@dataclass(frozen=True, slots=True)
class FeedbackLedger:
    """Immutable append-only ledger with event-ID idempotency."""
    events: tuple[OutcomeEvent, ...] = ()

    def __post_init__(self) -> None:
        ids = [event.event_id for event in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate feedback event_id")

    def append(self, event: OutcomeEvent) -> "FeedbackLedger":
        existing = {item.event_id: item for item in self.events}
        if event.event_id in existing:
            if existing[event.event_id] != event:
                raise ValueError("event_id already exists with different content")
            return self
        return FeedbackLedger(self.events + (event,))

    def append_many(self, events: Iterable[OutcomeEvent]) -> "FeedbackLedger":
        ledger = self
        for event in events:
            ledger = ledger.append(event)
        return ledger


@dataclass(frozen=True, slots=True)
class FeedbackCounts:
    verified_supported: int = 0
    contradicted: int = 0
    inconclusive: int = 0
    superseded: int = 0

    @property
    def adjudicated(self) -> int:
        return self.verified_supported + self.contradicted

    @property
    def total(self) -> int:
        return self.adjudicated + self.inconclusive + self.superseded

    @property
    def observed_success_rate(self) -> float | None:
        if not self.adjudicated:
            return None
        return self.verified_supported / self.adjudicated


@dataclass(frozen=True, slots=True)
class FeedbackMetric:
    target_kind: FeedbackTargetKind
    target_ref: str
    context_key: str
    period_start: datetime | None
    period_end: datetime | None
    counts: FeedbackCounts
    event_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeedbackReport:
    generated_at: datetime
    window_days: int | None
    metrics: tuple[FeedbackMetric, ...]
    excluded_future_events: int
    excluded_out_of_window_events: int


def _counts(events: Iterable[OutcomeEvent]) -> FeedbackCounts:
    values = [0, 0, 0, 0]
    mapping = {
        OutcomeLabel.VERIFIED_SUPPORTED: 0,
        OutcomeLabel.CONTRADICTED: 1,
        OutcomeLabel.INCONCLUSIVE: 2,
        OutcomeLabel.SUPERSEDED: 3,
    }
    for event in events:
        values[mapping[event.outcome]] += 1
    return FeedbackCounts(*values)


def summarize_feedback(
    ledger: FeedbackLedger,
    *,
    generated_at: datetime | None = None,
    window_days: int | None = None,
    include_context_tags: bool = True,
    period_granularity: str = "month",
) -> FeedbackReport:
    """Aggregate outcome counts by explicitly attributed target and context.

    Contexts are task type plus optional context tags. Time windows are
    evaluated against `observed_at`; future and expired events are excluded.
    Rates are descriptive observed frequencies, not causal estimates or
    predictive probabilities.
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    if window_days is not None and window_days <= 0:
        raise ValueError("window_days must be positive or None")
    if period_granularity not in {"all", "week", "month"}:
        raise ValueError("period_granularity must be all, week, or month")
    start = generated_at - timedelta(days=window_days) if window_days else None

    selected = []
    future = expired = 0
    for event in ledger.events:
        if event.observed_at > generated_at:
            future += 1
            continue
        if start is not None and event.observed_at < start:
            expired += 1
            continue
        selected.append(event)

    buckets: dict[tuple[FeedbackTargetKind, str, str, datetime | None], list[OutcomeEvent]] = {}
    def period_key(moment: datetime) -> datetime | None:
        if period_granularity == "all":
            return None
        if period_granularity == "week":
            day = moment.date()
            monday = day - timedelta(days=day.weekday())
            return datetime(monday.year, monday.month, monday.day, tzinfo=moment.tzinfo)
        return datetime(moment.year, moment.month, 1, tzinfo=moment.tzinfo)

    for event in selected:
        context_values = [event.task_type]
        if include_context_tags:
            context_values.extend(f"{event.task_type}|{tag}" for tag in event.context_tags)
        targets = [(FeedbackTargetKind.CONCLUSION, event.conclusion_ref)]
        targets.extend((FeedbackTargetKind.RULE, ref) for ref in event.rule_refs)
        targets.extend((FeedbackTargetKind.SOURCE, ref) for ref in event.source_refs)
        if event.strategy_ref:
            targets.append((FeedbackTargetKind.STRATEGY, event.strategy_ref))
        for kind, ref in targets:
            for context in context_values:
                buckets.setdefault(
                    (kind, ref, context, period_key(event.observed_at)), []
                ).append(event)

    metrics = []
    for (kind, ref, context, bucket_start), events in sorted(
        buckets.items(), key=lambda item: (
            item[0][0].value, item[0][1], item[0][2],
            item[0][3] or datetime.min.replace(tzinfo=timezone.utc),
        )
    ):
        dates = [event.observed_at for event in events]
        counts = _counts(events)
        limitations = []
        if counts.inconclusive or counts.superseded:
            limitations.append("INCONCLUSIVE_AND_SUPERSEDED_EVENTS_EXCLUDED_FROM_SUCCESS_RATE")
        if counts.adjudicated < 5:
            limitations.append("SMALL_ADJUDICATED_SAMPLE")
        if kind != FeedbackTargetKind.CONCLUSION:
            limitations.append("ATTRIBUTION_IS_CALLER_SUPPLIED_NOT_CAUSAL")
        metrics.append(FeedbackMetric(
            target_kind=kind, target_ref=ref, context_key=context,
            period_start=bucket_start or min(dates), period_end=max(dates), counts=counts,
            event_refs=tuple(event.event_id for event in events),
            limitations=tuple(limitations),
        ))

    return FeedbackReport(
        generated_at=generated_at, window_days=window_days,
        metrics=tuple(metrics), excluded_future_events=future,
        excluded_out_of_window_events=expired,
    )


def make_feedback_event_id(
    result_id: str, conclusion_ref: str, adjudication_source_ref: str,
    observed_at: datetime,
) -> str:
    """Stable convenience ID; callers may instead supply their own event ID."""
    stamp = observed_at.isoformat()
    raw = f"{result_id}|{conclusion_ref}|{adjudication_source_ref}|{stamp}".encode()
    return "erc_feedback_" + sha256(raw).hexdigest()[:24]
