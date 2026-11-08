"""Experience-based comparative reasoning over adjudicated case episodes (ERC-3.5).

All comparisons are descriptive. Action/outcome co-occurrence is not a treatment
effect, causal attribution, recommendation, or case-specific outcome prediction.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Iterable

from .contracts import require_aware_datetime, require_nonempty
from .temporal_patterns import (
    EpisodeOutcome, MatchDisposition, TemporalPatternReport,
)


class ComparisonStatus(str, Enum):
    COMPARABLE = "comparable"
    LIMITED = "limited"
    INSUFFICIENT_EXPERIENCE = "insufficient_experience"
    CONTEXT_NOT_COMPARABLE = "context_not_comparable"


@dataclass(frozen=True, slots=True)
class HistoricalAction:
    action_ref: str
    action_code: str
    relative_time_seconds: int
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        require_nonempty(self.action_ref, "action_ref")
        require_nonempty(self.action_code, "action_code")
        if self.relative_time_seconds < 0:
            raise ValueError("relative_time_seconds cannot be negative")
        if not self.source_refs or any(not x for x in self.source_refs):
            raise ValueError("historical action requires source_refs")


@dataclass(frozen=True, slots=True)
class HistoricalExperienceDetail:
    episode_id: str
    actions: tuple[HistoricalAction, ...]
    outcome: EpisodeOutcome
    adjudication_ref: str
    outcome_source_refs: tuple[str, ...]
    follow_up_days: int | None = None
    context_limitations: tuple[str, ...] = ()
    experience_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_nonempty(self.episode_id, "episode_id")
        require_nonempty(self.adjudication_ref, "adjudication_ref")
        if not self.outcome_source_refs or any(not x for x in self.outcome_source_refs):
            raise ValueError("outcome_source_refs are required")
        if self.follow_up_days is not None and self.follow_up_days < 0:
            raise ValueError("follow_up_days cannot be negative")
        if len({a.action_ref for a in self.actions}) != len(self.actions):
            raise ValueError("action references must be unique within an episode")
        if tuple(sorted(self.actions, key=lambda a: (a.relative_time_seconds, a.action_ref))) != self.actions:
            raise ValueError("actions must be ordered by relative_time_seconds then action_ref")


@dataclass(frozen=True, slots=True)
class ExperienceComparisonPolicy:
    minimum_match_score: float = 0.50
    minimum_episodes_per_action_pattern: int = 3
    require_same_activity: bool = True
    require_same_context: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_match_score <= 1:
            raise ValueError("minimum_match_score must be between 0 and 1")
        if self.minimum_episodes_per_action_pattern < 1:
            raise ValueError("minimum_episodes_per_action_pattern must be positive")


@dataclass(frozen=True, slots=True)
class OutcomeCounts:
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
class ActionOutcomeComparison:
    action_pattern: tuple[str, ...]
    episode_refs: tuple[str, ...]
    sample_size: int
    outcome_counts: OutcomeCounts
    status: ComparisonStatus
    limitations: tuple[str, ...]
    action_refs: tuple[str, ...]
    adjudication_refs: tuple[str, ...]
    outcome_source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExperienceCaseExplanation:
    episode_id: str
    similarity_score: float
    match_disposition: str
    historical_outcome: str
    action_pattern: tuple[str, ...]
    why_relevant: tuple[str, ...]
    why_not_equivalent: tuple[str, ...]
    source_refs: tuple[str, ...]
    adjudication_ref: str


@dataclass(frozen=True, slots=True)
class ExperienceReasoningReport:
    generated_at: datetime
    current_trajectory_ref: str
    explanations: tuple[ExperienceCaseExplanation, ...]
    action_outcome_comparisons: tuple[ActionOutcomeComparison, ...]
    excluded_episode_refs: tuple[str, ...]
    missing_detail_episode_refs: tuple[str, ...]
    overall_status: ComparisonStatus
    limitations: tuple[str, ...]


def _counts(details: list[HistoricalExperienceDetail]) -> OutcomeCounts:
    values = {x.value: 0 for x in EpisodeOutcome}
    for item in details:
        values[item.outcome.value] += 1
    return OutcomeCounts(**values)


def compare_case_experience(
    temporal_report: TemporalPatternReport,
    experience_details: Iterable[HistoricalExperienceDetail],
    *,
    generated_at: datetime,
    policy: ExperienceComparisonPolicy = ExperienceComparisonPolicy(),
) -> ExperienceReasoningReport:
    """Explain comparable prior episodes and summarize observed action/outcome patterns.

    Only eligible sequence matches meeting the configured score and context gates
    enter action/outcome groups. Details are joined by exact episode ID. Duplicate
    details, mismatched adjudication/outcome, and unreferenced episodes are rejected.
    """
    require_aware_datetime(generated_at, "generated_at")
    if generated_at < temporal_report.generated_at:
        raise ValueError("generated_at cannot precede temporal report generation")
    details = tuple(experience_details)
    detail_ids = [d.episode_id for d in details]
    if len(detail_ids) != len(set(detail_ids)):
        raise ValueError("experience detail episode IDs must be unique")
    by_id = {d.episode_id: d for d in details}
    matches = {m.episode_id: m for m in temporal_report.matches}
    extra = set(by_id) - set(matches)
    if extra:
        raise ValueError("experience details contain episode IDs absent from temporal report: " + ", ".join(sorted(extra)))

    eligible: list[tuple[object, HistoricalExperienceDetail]] = []
    explanations: list[ExperienceCaseExplanation] = []
    missing: list[str] = []
    excluded: list[str] = list(temporal_report.excluded_episode_refs)
    for match in temporal_report.matches:
        detail = by_id.get(match.episode_id)
        if detail is None:
            missing.append(match.episode_id)
            continue
        if detail.adjudication_ref != match.adjudication_ref or detail.outcome != match.historical_outcome:
            raise ValueError(f"experience detail does not match temporal adjudication/outcome for {match.episode_id}")
        eligible_disposition = match.disposition in {
            MatchDisposition.STRONG_SEQUENCE_MATCH, MatchDisposition.PARTIAL_SEQUENCE_MATCH,
            MatchDisposition.WEAK_SEQUENCE_MATCH,
        }
        proc_ok = match.activity_match or not policy.require_same_activity
        context_ok = match.context_match or not policy.require_same_context
        if not eligible_disposition or not proc_ok or not context_ok or match.similarity_score < policy.minimum_match_score:
            excluded.append(match.episode_id)
            continue
        eligible.append((match, detail))
        reasons = [f"Ordered event sequence similarity: {match.similarity_score:.3f}."]
        if match.alignments:
            reasons.append(f"{len(match.alignments)} event(s) aligned in temporal order.")
        if match.experience_refs:
            reasons.append("Linked practitioner experience references are available.")
        differences = [d.explanation for d in match.differences]
        differences.extend(detail.context_limitations)
        if not match.context_match:
            differences.append("Context differs from current case.")
        if not match.activity_match:
            differences.append("Activity differs from current case.")
        explanations.append(ExperienceCaseExplanation(
            match.episode_id, match.similarity_score, match.disposition.value,
            detail.outcome.value, tuple(a.action_code for a in detail.actions),
            tuple(reasons), tuple(differences),
            tuple(sorted(set(match.source_refs + detail.outcome_source_refs +
                             tuple(r for a in detail.actions for r in a.source_refs)))),
            detail.adjudication_ref,
        ))

    groups: dict[tuple[str, ...], list[HistoricalExperienceDetail]] = {}
    for _, detail in eligible:
        pattern = tuple(a.action_code for a in detail.actions)
        groups.setdefault(pattern, []).append(detail)
    comparisons: list[ActionOutcomeComparison] = []
    for pattern, items in sorted(groups.items(), key=lambda kv: (kv[0], len(kv[1]))):
        counts = _counts(items)
        n = len(items)
        enough = n >= policy.minimum_episodes_per_action_pattern
        adjudicated = counts.adjudicated
        status = ComparisonStatus.COMPARABLE if enough and adjudicated >= policy.minimum_episodes_per_action_pattern else ComparisonStatus.INSUFFICIENT_EXPERIENCE
        limitations = ["Observed action/outcome co-occurrence is descriptive and does not establish treatment effect or causality."]
        if not enough:
            limitations.append("Fewer episodes than the configured minimum for comparative interpretation.")
        if adjudicated < n:
            limitations.append("Inconclusive and unknown outcomes are retained but excluded from adjudicated outcome counts.")
        comparisons.append(ActionOutcomeComparison(
            pattern, tuple(sorted(x.episode_id for x in items)), n, counts, status,
            tuple(limitations), tuple(sorted({a.action_ref for x in items for a in x.actions})),
            tuple(sorted({x.adjudication_ref for x in items})),
            tuple(sorted({r for x in items for r in x.outcome_source_refs})),
        ))

    if not eligible:
        overall = ComparisonStatus.INSUFFICIENT_EXPERIENCE
    elif all(c.status == ComparisonStatus.INSUFFICIENT_EXPERIENCE for c in comparisons):
        overall = ComparisonStatus.INSUFFICIENT_EXPERIENCE
    elif excluded or missing:
        overall = ComparisonStatus.LIMITED
    else:
        overall = ComparisonStatus.COMPARABLE
    return ExperienceReasoningReport(
        generated_at, temporal_report.current_trajectory_ref,
        tuple(sorted(explanations, key=lambda x: (-x.similarity_score, x.episode_id))),
        tuple(comparisons), tuple(sorted(set(excluded))), tuple(sorted(missing)), overall,
        ("Historical cases are comparators, not controls or counterfactuals.",
         "Action/outcome patterns are observational; confounding by indication, case mix, practitioner selection, and follow-up may apply.",
         "No treatment effect, causal attribution, individual outcome probability, or treatment recommendation is produced.",
         "Interpretation requires review of source records, case comparability, adjudication quality, and follow-up completeness."),
    )
