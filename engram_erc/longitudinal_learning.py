"""Longitudinal, cross-case pattern analysis (ERC-3.7).

This module aggregates caller-normalized projections of existing, closed and
adjudicated registry cases. It reports recurrence and descriptive outcome
co-occurrence only; it does not estimate treatment effects, rank practitioners, or
predict individual outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Iterable

from .contracts import require_aware_datetime, require_nonempty
from .prospective_learning import (
    ProspectiveLearningLedger, ProspectiveEventKind, ProspectiveCaseStatus,
    inspect_prospective_case,
)
from .temporal_patterns import EpisodeOutcome


class PatternMaturity(str, Enum):
    INSUFFICIENT_DATA = "insufficient_data"
    SINGLE_CASE = "single_case"
    RECURRING_LOCAL = "recurring_local"
    CROSS_SITE_RECURRING = "cross_site_recurring"


@dataclass(frozen=True, slots=True)
class LongitudinalObservation:
    """A privacy-minimized projection of one completed registry case."""
    case_ref: str
    activity_ref: str
    context_key: str
    site_ref: str
    event_pattern: tuple[str, ...]
    action_pattern: tuple[str, ...]
    case_outcome: EpisodeOutcome
    adjudicated_at: datetime
    adjudication_ref: str
    source_refs: tuple[str, ...]
    practitioner_ref: str | None = None
    practitioner_perception_tags: tuple[str, ...] = ()
    follow_up_days: int | None = None

    def __post_init__(self) -> None:
        for name in ("case_ref", "activity_ref", "context_key", "site_ref", "adjudication_ref"):
            require_nonempty(getattr(self, name), name)
        require_aware_datetime(self.adjudicated_at, "adjudicated_at")
        if not self.event_pattern or any(not x.strip() for x in self.event_pattern):
            raise ValueError("event_pattern must contain non-empty event codes")
        if not self.action_pattern or any(not x.strip() for x in self.action_pattern):
            raise ValueError("action_pattern must contain non-empty action codes")
        if not self.source_refs or any(not x.strip() for x in self.source_refs):
            raise ValueError("source_refs are required")
        for name in ("source_refs", "practitioner_perception_tags"):
            values = getattr(self, name)
            if any(not x.strip() for x in values):
                raise ValueError(f"{name} cannot contain blank values")
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        if self.follow_up_days is not None and self.follow_up_days < 0:
            raise ValueError("follow_up_days cannot be negative")
        if self.practitioner_ref is not None:
            require_nonempty(self.practitioner_ref, "practitioner_ref")


@dataclass(frozen=True, slots=True)
class LongitudinalPolicy:
    minimum_cases_for_pattern: int = 3
    minimum_sites_for_cross_site: int = 2
    minimum_cases_for_outcome_summary: int = 5
    require_closed_cases: bool = True
    include_unknown_outcomes: bool = True

    def __post_init__(self) -> None:
        for name in ("minimum_cases_for_pattern", "minimum_sites_for_cross_site", "minimum_cases_for_outcome_summary"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class OutcomeDistribution:
    improved: int = 0
    unchanged: int = 0
    deteriorated: int = 0
    adverse_event: int = 0
    inconclusive: int = 0
    unknown: int = 0

    @property
    def adjudicated(self) -> int:
        return self.improved + self.unchanged + self.deteriorated + self.adverse_event


@dataclass(frozen=True, slots=True)
class CasePatternSummary:
    pattern_id: str
    activity_ref: str
    context_key: str
    event_pattern: tuple[str, ...]
    case_refs: tuple[str, ...]
    sample_size: int
    distinct_sites: int
    distinct_practitioners: int
    maturity: PatternMaturity
    outcome_distribution: OutcomeDistribution
    action_patterns: tuple[tuple[str, ...], ...]
    practitioner_perception_tags: tuple[str, ...]
    adjudication_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    outcome_summary_available: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ActionPatternSummary:
    pattern_id: str
    activity_ref: str
    context_key: str
    event_pattern: tuple[str, ...]
    action_pattern: tuple[str, ...]
    case_refs: tuple[str, ...]
    sample_size: int
    outcome_distribution: OutcomeDistribution
    distinct_sites: int
    descriptive_status: str
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LongitudinalLearningReport:
    generated_at: datetime
    eligible_cases: int
    excluded_cases: tuple[str, ...]
    patterns: tuple[CasePatternSummary, ...]
    action_outcome_summaries: tuple[ActionPatternSummary, ...]
    limitations: tuple[str, ...]


def _distribution(items: list[LongitudinalObservation]) -> OutcomeDistribution:
    counts = {x.value: 0 for x in EpisodeOutcome}
    for item in items:
        counts[item.case_outcome.value] += 1
    return OutcomeDistribution(**counts)


def _validate_against_source_records(item: LongitudinalObservation, ledger: ProspectiveLearningLedger,
                               require_closed: bool) -> None:
    case = next((c for c in ledger.cases if c.case_ref == item.case_ref), None)
    if case is None:
        raise ValueError(f"unknown prospective case: {item.case_ref}")
    if case.activity_ref != item.activity_ref or case.context_key != item.context_key:
        raise ValueError(f"activity/context mismatch for case: {item.case_ref}")
    if case.site_ref != item.site_ref:
        raise ValueError(f"site mismatch for case: {item.case_ref}")
    status = inspect_prospective_case(ledger, item.case_ref)
    if require_closed and status.status != ProspectiveCaseStatus.CLOSED:
        raise ValueError(f"case is not closed: {item.case_ref}")
    adjudication = next((e for e in reversed(ledger.events)
        if e.case_ref == item.case_ref and e.kind == ProspectiveEventKind.OUTCOME_ADJUDICATED), None)
    if adjudication is None:
        raise ValueError(f"case has no outcome adjudication: {item.case_ref}")
    if adjudication.adjudication_ref != item.adjudication_ref:
        raise ValueError(f"adjudication reference mismatch for case: {item.case_ref}")
    if adjudication.case_outcome != item.case_outcome or adjudication.occurred_at != item.adjudicated_at:
        raise ValueError(f"adjudicated outcome/timestamp mismatch for case: {item.case_ref}")
    if not set(adjudication.source_refs).issubset(set(item.source_refs)):
        raise ValueError(f"source provenance incomplete for case: {item.case_ref}")


def analyze_longitudinal_learning(
    observations: Iterable[LongitudinalObservation],
    prospective_ledger: ProspectiveLearningLedger,
    *, generated_at: datetime,
    policy: LongitudinalPolicy = LongitudinalPolicy(),
) -> LongitudinalLearningReport:
    """Summarize recurring event trajectories and observed action/outcome patterns.

    Grouping is exact on activity, context and ordered event codes. No semantic
    merging, inferred missing events, causal estimate, practitioner ranking, or
    case-level prediction is performed.
    """
    require_aware_datetime(generated_at, "generated_at")
    rows = tuple(observations)
    ids = [x.case_ref for x in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("case_ref values must be unique in one analysis")
    eligible: list[LongitudinalObservation] = []
    excluded: list[str] = []
    for item in rows:
        if item.adjudicated_at > generated_at:
            excluded.append(item.case_ref)
            continue
        if item.case_outcome in {EpisodeOutcome.INCONCLUSIVE, EpisodeOutcome.UNKNOWN} and not policy.include_unknown_outcomes:
            excluded.append(item.case_ref)
            continue
        _validate_against_source_records(item, prospective_ledger, policy.require_closed_cases)
        eligible.append(item)

    grouped: dict[tuple[str, str, tuple[str, ...]], list[LongitudinalObservation]] = {}
    for item in eligible:
        grouped.setdefault((item.activity_ref, item.context_key, item.event_pattern), []).append(item)

    patterns: list[CasePatternSummary] = []
    action_summaries: list[ActionPatternSummary] = []
    for key, group in sorted(grouped.items(), key=lambda kv: kv[0]):
        activity, context, events = key
        sites = {x.site_ref for x in group}
        practitioners = {x.practitioner_ref for x in group if x.practitioner_ref}
        n = len(group)
        if n < policy.minimum_cases_for_pattern:
            maturity = PatternMaturity.SINGLE_CASE if n == 1 else PatternMaturity.INSUFFICIENT_DATA
        elif len(sites) >= policy.minimum_sites_for_cross_site:
            maturity = PatternMaturity.CROSS_SITE_RECURRING
        else:
            maturity = PatternMaturity.RECURRING_LOCAL
        outcome_available = n >= policy.minimum_cases_for_outcome_summary and _distribution(group).adjudicated > 0
        limitations = [
            "Exact-code recurrence is descriptive and does not establish a causal mechanism.",
            "Case mix, practitioner selection, institutional practice and follow-up differences may confound comparisons.",
        ]
        if maturity != PatternMaturity.CROSS_SITE_RECURRING:
            limitations.append("Cross-site recurrence threshold was not met; portability is not established.")
        if not outcome_available:
            limitations.append("Outcome summary withheld by the configured minimum-case threshold or lack of adjudicated outcomes.")
        if any(x.case_outcome in {EpisodeOutcome.INCONCLUSIVE, EpisodeOutcome.UNKNOWN} for x in group):
            limitations.append("Inconclusive and unknown outcomes remain visible and are not counted as adjudicated outcomes.")
        signature = json.dumps([activity, context, events], ensure_ascii=False, separators=(",", ":"))
        pattern_id = "pattern:" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:20]
        visible_distribution = _distribution(group) if outcome_available else OutcomeDistribution()
        patterns.append(CasePatternSummary(
            pattern_id, activity, context, events,
            tuple(sorted(x.case_ref for x in group)), n, len(sites), len(practitioners), maturity,
            visible_distribution, tuple(sorted({x.action_pattern for x in group})),
            tuple(sorted({t for x in group for t in x.practitioner_perception_tags})),
            tuple(sorted({x.adjudication_ref for x in group})),
            tuple(sorted({r for x in group for r in x.source_refs})), outcome_available,
            tuple(limitations),
        ))
        by_action: dict[tuple[str, ...], list[LongitudinalObservation]] = {}
        for item in group:
            by_action.setdefault(item.action_pattern, []).append(item)
        for action_pattern, action_group in sorted(by_action.items()):
            action_n = len(action_group)
            enough = action_n >= policy.minimum_cases_for_outcome_summary and _distribution(action_group).adjudicated > 0
            action_limits = ["Action/outcome co-occurrence is observational; it is not a treatment-effect estimate or causal comparison."]
            if not enough:
                action_limits.append("Outcome summary withheld because the configured minimum was not met.")
            visible_action_distribution = _distribution(action_group) if enough else OutcomeDistribution()
            action_summaries.append(ActionPatternSummary(
                pattern_id + "|actions:" + ">".join(action_pattern), activity, context,
                events, action_pattern, tuple(sorted(x.case_ref for x in action_group)),
                action_n, visible_action_distribution, len({x.site_ref for x in action_group}),
                "descriptive_summary_available" if enough else "insufficient_experience",
                tuple(action_limits),
            ))

    return LongitudinalLearningReport(
        generated_at, len(eligible), tuple(sorted(excluded)), tuple(patterns),
        tuple(action_summaries), (
            "This report is a descriptive cross-case analysis, not a case prediction or treatment recommendation.",
            "Patterns are grouped by exact activity, context and ordered event codes; semantic equivalence is not inferred.",
            "Practitioner perception tags are descriptive annotations, not objective measures or performance rankings.",
            "Observed action/outcome associations do not establish treatment effects or causality.",
            "The caller must ensure the registry projection is privacy-minimized and that outcome adjudication is independent and reliable.",
        ),
    )
