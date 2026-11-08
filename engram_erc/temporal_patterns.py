"""Deterministic temporal pattern matching for case experience (ERC-3.4).

Matches an active case's ordered event trajectory against caller-selected,
adjudicated historical episodes. Similarity is descriptive, not predictive;
no treatment recommendation, causal claim, or outcome probability is produced.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .contracts import require_aware_datetime, require_nonempty


class EpisodeOutcome(str, Enum):
    IMPROVED = "improved"
    UNCHANGED = "unchanged"
    DETERIORATED = "deteriorated"
    ADVERSE_EVENT = "adverse_event"
    INCONCLUSIVE = "inconclusive"
    UNKNOWN = "unknown"


class MatchDisposition(str, Enum):
    STRONG_SEQUENCE_MATCH = "strong_sequence_match"
    PARTIAL_SEQUENCE_MATCH = "partial_sequence_match"
    WEAK_SEQUENCE_MATCH = "weak_sequence_match"
    INSUFFICIENT_SEQUENCE = "insufficient_sequence"
    CONTEXT_MISMATCH = "context_mismatch"


@dataclass(frozen=True, slots=True)
class TrajectoryEvent:
    event_id: str
    event_type: str
    occurred_at: datetime
    source_refs: tuple[str, ...]
    attributes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_nonempty(self.event_id, "event_id")
        require_nonempty(self.event_type, "event_type")
        require_aware_datetime(self.occurred_at, "occurred_at")
        if not self.source_refs or any(not x for x in self.source_refs):
            raise ValueError("each trajectory event requires source_refs")
        keys = [k for k, _ in self.attributes]
        if len(keys) != len(set(keys)):
            raise ValueError("trajectory attribute keys must be unique")


@dataclass(frozen=True, slots=True)
class CaseTrajectory:
    trajectory_id: str
    case_ref: str
    activity_ref: str
    context_key: str
    site_ref: str | None
    events: tuple[TrajectoryEvent, ...]
    recorded_at: datetime
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        for n in ("trajectory_id", "case_ref", "activity_ref", "context_key"):
            require_nonempty(getattr(self, n), n)
        require_aware_datetime(self.recorded_at, "recorded_at")
        if len(self.events) < 1:
            raise ValueError("trajectory requires at least one event")
        if not self.source_refs:
            raise ValueError("trajectory requires source_refs")
        ids = [e.event_id for e in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("event IDs must be unique within a trajectory")
        if tuple(sorted(self.events, key=lambda e: (e.occurred_at, e.event_id))) != self.events:
            raise ValueError("trajectory events must be ordered by occurred_at then event_id")
        if any(e.occurred_at > self.recorded_at for e in self.events):
            raise ValueError("trajectory event cannot occur after recorded_at")


@dataclass(frozen=True, slots=True)
class HistoricalEpisode:
    episode_id: str
    trajectory: CaseTrajectory
    outcome: EpisodeOutcome
    adjudication_ref: str
    practitioner_action_refs: tuple[str, ...] = ()
    experience_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_nonempty(self.episode_id, "episode_id")
        require_nonempty(self.adjudication_ref, "adjudication_ref")
        if self.trajectory.case_ref == "":
            raise ValueError("historical case_ref required")


@dataclass(frozen=True, slots=True)
class TemporalMatchPolicy:
    min_current_events: int = 2
    min_historical_events: int = 2
    max_candidates: int = 100
    max_event_gap_seconds: int = 7 * 24 * 3600
    max_relative_timing_error_seconds: int = 24 * 3600
    strong_match_threshold: float = 0.80
    partial_match_threshold: float = 0.50
    require_same_activity: bool = True
    require_same_context: bool = True
    require_different_case: bool = True

    def __post_init__(self) -> None:
        if min(self.min_current_events, self.min_historical_events, self.max_candidates,
               self.max_event_gap_seconds, self.max_relative_timing_error_seconds) < 1:
            raise ValueError("policy counts and time limits must be positive")
        if not (0 <= self.partial_match_threshold <= self.strong_match_threshold <= 1):
            raise ValueError("thresholds must satisfy 0 <= partial <= strong <= 1")


@dataclass(frozen=True, slots=True)
class EventAlignment:
    current_event_ref: str
    historical_event_ref: str
    event_type: str
    timing_delta_seconds: float
    matched_attributes: tuple[str, ...]
    differing_attributes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TrajectoryDifference:
    kind: str
    event_type: str
    current_event_ref: str | None
    historical_event_ref: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class EpisodeMatch:
    episode_id: str
    historical_case_ref: str
    disposition: MatchDisposition
    similarity_score: float
    event_coverage: float
    sequence_order_score: float
    timing_score: float
    context_match: bool
    activity_match: bool
    alignments: tuple[EventAlignment, ...]
    differences: tuple[TrajectoryDifference, ...]
    historical_outcome: EpisodeOutcome
    adjudication_ref: str
    practitioner_action_refs: tuple[str, ...]
    experience_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemporalPatternReport:
    generated_at: datetime
    current_trajectory_ref: str
    matches: tuple[EpisodeMatch, ...]
    excluded_episode_refs: tuple[str, ...]
    limitations: tuple[str, ...]


def _attrs(event: TrajectoryEvent) -> dict[str, str]:
    return dict(event.attributes)


def _align(current: tuple[TrajectoryEvent, ...], historical: tuple[TrajectoryEvent, ...],
           max_timing_error: int) -> tuple[EventAlignment, ...]:
    """LCS alignment by event type, maximizing count then minimizing timing error."""
    n, m = len(current), len(historical)
    # DP entries: (match count, cumulative timing error, alignment pairs)
    dp: list[list[tuple[int, float, tuple[tuple[int, int], ...]]]] = [
        [(0, 0.0, ()) for _ in range(m + 1)] for _ in range(n + 1)]
    c0, h0 = current[0].occurred_at, historical[0].occurred_at
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            options = [dp[i-1][j], dp[i][j-1]]
            if current[i-1].event_type == historical[j-1].event_type:
                c_delta = (current[i-1].occurred_at - c0).total_seconds()
                h_delta = (historical[j-1].occurred_at - h0).total_seconds()
                err = abs(c_delta - h_delta)
                if err <= max_timing_error:
                    prev = dp[i-1][j-1]
                    options.append((prev[0] + 1, prev[1] + err, prev[2] + ((i-1, j-1),)))
            dp[i][j] = sorted(options, key=lambda x: (-x[0], x[1], x[2]))[0]
    pairs = dp[n][m][2]
    result = []
    for ci, hi in pairs:
        ca, ha = _attrs(current[ci]), _attrs(historical[hi])
        common = tuple(sorted(k for k in ca.keys() & ha.keys() if ca[k] == ha[k]))
        different = tuple(sorted(k for k in ca.keys() & ha.keys() if ca[k] != ha[k]))
        result.append(EventAlignment(current[ci].event_id, historical[hi].event_id,
            current[ci].event_type, abs(((current[ci].occurred_at-c0) -
            (historical[hi].occurred_at-h0)).total_seconds()), common, different))
    return tuple(result)


def _differences(current: tuple[TrajectoryEvent, ...], historical: tuple[TrajectoryEvent, ...],
                 alignments: tuple[EventAlignment, ...]) -> tuple[TrajectoryDifference, ...]:
    ci = {a.current_event_ref for a in alignments}
    hi = {a.historical_event_ref for a in alignments}
    out = [TrajectoryDifference("current_only", e.event_type, e.event_id, None,
             "Event appears in current trajectory but has no aligned historical event.")
           for e in current if e.event_id not in ci]
    out.extend(TrajectoryDifference("historical_only", e.event_type, None, e.event_id,
             "Event appears in historical trajectory but not in the aligned current sequence.")
           for e in historical if e.event_id not in hi)
    for a in alignments:
        if a.differing_attributes:
            out.append(TrajectoryDifference("attribute_difference", a.event_type,
                a.current_event_ref, a.historical_event_ref,
                "Shared attributes differ: " + ", ".join(a.differing_attributes)))
    return tuple(out)


def _match(current: CaseTrajectory, episode: HistoricalEpisode,
           policy: TemporalMatchPolicy) -> EpisodeMatch:
    hist = episode.trajectory
    proc_ok = current.activity_ref == hist.activity_ref
    context_ok = current.context_key == hist.context_key
    context_gate = (proc_ok or not policy.require_same_activity) and (context_ok or not policy.require_same_context)
    aligned = _align(current.events, hist.events, policy.max_relative_timing_error_seconds)
    denom = max(len(current.events), len(hist.events))
    coverage = len(aligned) / denom if denom else 0.0
    # Order score is normalized aligned count; timing score penalizes mean relative-time deviation.
    order = len(aligned) / min(len(current.events), len(hist.events)) if min(len(current.events), len(hist.events)) else 0.0
    timing = 1.0 if not aligned else max(0.0, 1.0 - sum(a.timing_delta_seconds for a in aligned) /
            (len(aligned) * policy.max_relative_timing_error_seconds))
    # Event coverage is deliberately dominant; timing and attribute agreement are separately visible.
    attr_total = sum(len(a.matched_attributes) + len(a.differing_attributes) for a in aligned)
    attr_score = (sum(len(a.matched_attributes) for a in aligned) / attr_total) if attr_total else 0.5
    score = round(0.65 * coverage + 0.20 * timing + 0.15 * attr_score, 6)
    if not context_gate:
        disposition = MatchDisposition.CONTEXT_MISMATCH
    elif len(aligned) < min(policy.min_current_events, policy.min_historical_events):
        disposition = MatchDisposition.INSUFFICIENT_SEQUENCE
    elif score >= policy.strong_match_threshold:
        disposition = MatchDisposition.STRONG_SEQUENCE_MATCH
    elif score >= policy.partial_match_threshold:
        disposition = MatchDisposition.PARTIAL_SEQUENCE_MATCH
    else:
        disposition = MatchDisposition.WEAK_SEQUENCE_MATCH
    return EpisodeMatch(episode.episode_id, hist.case_ref, disposition, score, round(coverage, 6),
        round(order, 6), round(timing, 6), context_ok, proc_ok, aligned,
        _differences(current.events, hist.events, aligned), episode.outcome,
        episode.adjudication_ref, episode.practitioner_action_refs, episode.experience_refs,
        tuple(sorted(set(hist.source_refs + tuple(r for e in hist.events for r in e.source_refs)))),
        ("Similarity is deterministic and descriptive; it is not a predicted outcome or treatment effect.",
         "Historical outcome and practitioner actions are reported as observations, not causal evidence."))


def match_temporal_experience(current: CaseTrajectory,
    historical_episodes: Iterable[HistoricalEpisode], *, generated_at: datetime,
    policy: TemporalMatchPolicy = TemporalMatchPolicy()) -> TemporalPatternReport:
    """Compare a current ordered trajectory with a bounded historical episode set."""
    require_aware_datetime(generated_at, "generated_at")
    if generated_at < current.recorded_at:
        raise ValueError("generated_at cannot precede current trajectory recorded_at")
    if len(current.events) < policy.min_current_events:
        return TemporalPatternReport(generated_at, current.trajectory_id, (), (),
            ("Current trajectory has fewer events than the configured minimum.",
             "No inference is made from an insufficient sequence."))
    episodes = tuple(historical_episodes)
    ids = [e.episode_id for e in episodes]
    if len(ids) != len(set(ids)):
        raise ValueError("historical episode IDs must be unique")
    matches: list[EpisodeMatch] = []
    excluded: list[str] = []
    for ep in episodes:
        if policy.require_different_case and ep.trajectory.case_ref == current.case_ref:
            excluded.append(ep.episode_id)
            continue
        if len(ep.trajectory.events) < policy.min_historical_events:
            excluded.append(ep.episode_id)
            continue
        if ep.trajectory.recorded_at > generated_at:
            raise ValueError("historical episode cannot be recorded after generated_at")
        matches.append(_match(current, ep, policy))
    # Context mismatches remain visible but never outrank eligible comparisons.
    matches.sort(key=lambda x: (x.disposition == MatchDisposition.CONTEXT_MISMATCH,
        -x.similarity_score, x.episode_id))
    return TemporalPatternReport(generated_at, current.trajectory_id,
        tuple(matches[:policy.max_candidates]), tuple(excluded),
        ("Matching uses event-type order, relative timing, and explicitly supplied attributes.",
         "No semantic embedding, causal attribution, outcome prediction, or automatic treatment recommendation is used.",
         "Historical case selection and adjudication quality are caller responsibilities.",
         "Similarity scores are not calibrated probabilities and should not be interpreted as case risk."))
