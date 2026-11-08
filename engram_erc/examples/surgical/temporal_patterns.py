"""Small synthetic demonstration; values are illustrative, not clinical thresholds."""
from datetime import datetime, timedelta, timezone
from engram_erc.temporal_patterns import (
    EpisodeOutcome, HistoricalEpisode, CaseTrajectory, TrajectoryEvent,
    match_temporal_experience,
)

base = datetime(2026, 1, 1, tzinfo=timezone.utc)
def ev(ref, kind, minutes, **attrs):
    return TrajectoryEvent(ref, kind, base + timedelta(minutes=minutes),
        (f"registry-event:{ref}",), tuple(sorted((k, str(v)) for k, v in attrs.items())))
def trajectory(ref, case, events):
    return CaseTrajectory(ref, case, "procedure:example", "context:example", None,
        tuple(events), base + timedelta(days=1), (f"registry-case:{case}",))

current = trajectory("trajectory:current", "case:current", [
    ev("c1", "signal_detected", 0, trend="rising"),
    ev("c2", "clinical_review", 20),
    ev("c3", "reassessment", 60),
])
historical = trajectory("trajectory:historical", "case:historical", [
    ev("h1", "signal_detected", 0, trend="rising"),
    ev("h2", "clinical_review", 25),
    ev("h3", "reassessment", 65),
])
episode = HistoricalEpisode("episode:001", historical, EpisodeOutcome.IMPROVED,
    "adjudication:001", ("surgeon-action:001",), ("experience:001",))
report = match_temporal_experience(current, [episode], generated_at=base + timedelta(days=2))
for match in report.matches:
    print(match.episode_id, match.disposition.value, match.similarity_score)
    print("Outcome reference:", match.adjudication_ref)
    print("Differences:", match.differences)
