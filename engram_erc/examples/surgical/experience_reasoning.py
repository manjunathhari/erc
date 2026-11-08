"""Synthetic ERC-3.5 example; all references and outcomes are illustrative."""
from datetime import datetime, timedelta, timezone
from engram_erc import (
    EpisodeOutcome, HistoricalEpisode, CaseTrajectory, TrajectoryEvent,
    match_temporal_experience, HistoricalAction, HistoricalExperienceDetail,
    ExperienceComparisonPolicy, compare_case_experience,
)

now = datetime.now(timezone.utc)

def trajectory(tid, case, start, source):
    events = tuple(TrajectoryEvent(
        f"{tid}:event:{i}", kind, start + timedelta(minutes=offset),
        (f"{source}:event:{i}",),
    ) for i, (kind, offset) in enumerate((("signal", 0), ("review", 20), ("reassessment", 60))))
    return CaseTrajectory(tid, case, "procedure:example", "context:example", "site:example",
        events, start + timedelta(hours=2), (source,))

current = trajectory("trajectory:current", "case:current", now - timedelta(days=1), "registry:current")
episodes = []
details = []
for i, outcome in enumerate((EpisodeOutcome.IMPROVED, EpisodeOutcome.IMPROVED, EpisodeOutcome.ADVERSE_EVENT), 1):
    hist = trajectory(f"trajectory:historical:{i}", f"case:historical:{i}",
        now - timedelta(days=30+i), f"registry:historical:{i}")
    episodes.append(HistoricalEpisode(f"episode:{i}", hist, outcome, f"adjudication:{i}",
        (f"surgeon-action:{i}",), (f"experience:{i}",)))
    actions = (
        HistoricalAction(f"action:{i}:1", "early_review", 300, (f"action-source:{i}:1",)),
        HistoricalAction(f"action:{i}:2", "repeat_assessment", 1800, (f"action-source:{i}:2",)),
    )
    details.append(HistoricalExperienceDetail(f"episode:{i}", actions, outcome,
        f"adjudication:{i}", (f"outcome-source:{i}",), 30, (), (f"experience:{i}",)))

matched = match_temporal_experience(current, episodes, generated_at=now)
report = compare_case_experience(matched, details, generated_at=now,
    policy=ExperienceComparisonPolicy(minimum_episodes_per_action_pattern=3))
print("Overall status:", report.overall_status.value)
for comparison in report.action_outcome_comparisons:
    print("Action pattern:", comparison.action_pattern)
    print("Observed outcomes:", comparison.outcome_counts)
    print("Interpretation:", comparison.status.value)
