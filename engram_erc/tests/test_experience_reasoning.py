from datetime import datetime, timedelta, timezone
import pytest
from engram_erc.temporal_patterns import (
    EpisodeOutcome, HistoricalEpisode, CaseTrajectory, TrajectoryEvent,
    TemporalPatternReport, MatchDisposition, EpisodeMatch,
)
from engram_erc.experience_reasoning import (
    ComparisonStatus, HistoricalAction, HistoricalExperienceDetail,
    ExperienceComparisonPolicy, compare_case_experience,
)

T = datetime(2026, 1, 1, tzinfo=timezone.utc)

def make_match(i, outcome=EpisodeOutcome.IMPROVED, score=.9, proc=True, ctx=True, disposition=MatchDisposition.STRONG_SEQUENCE_MATCH):
    return EpisodeMatch(
        f"ep{i}", f"case:{i}", disposition, score, .9, 1.0, .95, ctx, proc,
        (), (), outcome, f"adj:{i}", (f"action-ref:{i}",), (f"experience:{i}",),
        (f"registry:{i}",), ("descriptive only",),
    )

def detail(i, outcome=EpisodeOutcome.IMPROVED, actions=("early_review", "reassess")):
    acts = tuple(HistoricalAction(f"a:{i}:{j}", code, j * 600, (f"action-src:{i}:{j}",)) for j, code in enumerate(actions))
    return HistoricalExperienceDetail(f"ep{i}", acts, outcome, f"adj:{i}", (f"outcome-src:{i}",), 30, (), (f"exp:{i}",))

def report(matches):
    return TemporalPatternReport(T + timedelta(days=2), "trajectory:current", tuple(matches), (), ("match source",))

def test_compares_action_patterns_and_preserves_observed_outcomes():
    ms = [make_match(i, EpisodeOutcome.IMPROVED if i < 2 else EpisodeOutcome.ADVERSE_EVENT) for i in range(3)]
    ds = [detail(i, EpisodeOutcome.IMPROVED if i < 2 else EpisodeOutcome.ADVERSE_EVENT) for i in range(3)]
    out = compare_case_experience(report(ms), ds, generated_at=T + timedelta(days=3),
        policy=ExperienceComparisonPolicy(minimum_episodes_per_action_pattern=3))
    assert out.overall_status == ComparisonStatus.COMPARABLE
    c = out.action_outcome_comparisons[0]
    assert c.sample_size == 3
    assert c.outcome_counts.improved == 2
    assert c.outcome_counts.adverse_event == 1
    assert c.status == ComparisonStatus.COMPARABLE
    assert "not establish treatment effect" in c.limitations[0]

def test_small_sample_is_insufficient_not_a_recommendation():
    out = compare_case_experience(report([make_match(1)]), [detail(1)], generated_at=T + timedelta(days=3))
    assert out.overall_status == ComparisonStatus.INSUFFICIENT_EXPERIENCE
    assert out.action_outcome_comparisons[0].status == ComparisonStatus.INSUFFICIENT_EXPERIENCE

def test_context_mismatch_excluded_by_default():
    out = compare_case_experience(report([make_match(1, ctx=False, disposition=MatchDisposition.CONTEXT_MISMATCH)]),
        [detail(1)], generated_at=T + timedelta(days=3))
    assert out.excluded_episode_refs == ("ep1",)
    assert not out.explanations

def test_low_similarity_excluded():
    out = compare_case_experience(report([make_match(1, score=.2, disposition=MatchDisposition.WEAK_SEQUENCE_MATCH)]),
        [detail(1)], generated_at=T + timedelta(days=3))
    assert out.excluded_episode_refs == ("ep1",)

def test_missing_detail_is_reported_not_fabricated():
    out = compare_case_experience(report([make_match(1)]), [], generated_at=T + timedelta(days=3))
    assert out.missing_detail_episode_refs == ("ep1",)

def test_adjudication_or_outcome_mismatch_rejected():
    with pytest.raises(ValueError):
        compare_case_experience(report([make_match(1)]), [detail(1, EpisodeOutcome.DETERIORATED)], generated_at=T + timedelta(days=3))

def test_duplicate_details_rejected():
    with pytest.raises(ValueError):
        compare_case_experience(report([make_match(1)]), [detail(1), detail(1)], generated_at=T + timedelta(days=3))

def test_unreferenced_detail_rejected():
    with pytest.raises(ValueError):
        compare_case_experience(report([make_match(1)]), [detail(2)], generated_at=T + timedelta(days=3))

def test_inconclusive_outcomes_retained_but_not_adjudicated_denominator():
    ms = [make_match(1, EpisodeOutcome.IMPROVED), make_match(2, EpisodeOutcome.INCONCLUSIVE)]
    ds = [detail(1, EpisodeOutcome.IMPROVED), detail(2, EpisodeOutcome.INCONCLUSIVE)]
    out = compare_case_experience(report(ms), ds, generated_at=T + timedelta(days=3),
        policy=ExperienceComparisonPolicy(minimum_episodes_per_action_pattern=1))
    c = out.action_outcome_comparisons[0]
    assert c.sample_size == 2
    assert c.outcome_counts.inconclusive == 1
    assert c.outcome_counts.adjudicated == 1

def test_different_action_patterns_separated():
    ms = [make_match(1), make_match(2)]
    ds = [detail(1, actions=("review",)), detail(2, actions=("intervene",))]
    out = compare_case_experience(report(ms), ds, generated_at=T + timedelta(days=3),
        policy=ExperienceComparisonPolicy(minimum_episodes_per_action_pattern=1))
    assert len(out.action_outcome_comparisons) == 2

def test_generated_time_must_follow_temporal_report():
    with pytest.raises(ValueError):
        compare_case_experience(report([make_match(1)]), [detail(1)], generated_at=T + timedelta(days=1))

def test_action_order_must_be_chronological():
    with pytest.raises(ValueError):
        HistoricalExperienceDetail("ep", (
            HistoricalAction("a2", "later", 20, ("s2",)),
            HistoricalAction("a1", "earlier", 10, ("s1",)),
        ), EpisodeOutcome.IMPROVED, "adj", ("outcome",))
