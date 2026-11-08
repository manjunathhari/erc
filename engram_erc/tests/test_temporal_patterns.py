from datetime import datetime, timedelta, timezone
import pytest
from engram_erc.temporal_patterns import (
    EpisodeOutcome, HistoricalEpisode, MatchDisposition, CaseTrajectory,
    TemporalMatchPolicy, TrajectoryEvent, match_temporal_experience,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

def event(i, kind, minutes, **attrs):
    return TrajectoryEvent(f"e{i}", kind, T0 + timedelta(minutes=minutes),
                           (f"src:{i}",), tuple(sorted((k, str(v)) for k,v in attrs.items())))

def trajectory(tid, case, events, procedure="proc:colectomy", context="postop:standard", site="site:a"):
    return CaseTrajectory(tid, case, procedure, context, site, tuple(events),
        T0 + timedelta(days=2), (f"registry:{case}",))

def episode(eid, traj, outcome=EpisodeOutcome.IMPROVED):
    return HistoricalEpisode(eid, traj, outcome, f"adjudication:{eid}", (f"action:{eid}",), (f"experience:{eid}",))

def test_identical_ordered_sequence_matches_and_carries_provenance():
    cur = trajectory("current", "case:new", [event(1,"tachycardia",0,grade="mild"), event(2,"lab_change",30,trend="rising"), event(3,"review",60)])
    hist = trajectory("hist", "case:old", [event(11,"tachycardia",0,grade="mild"), event(12,"lab_change",30,trend="rising"), event(13,"review",60)])
    report = match_temporal_experience(cur, [episode("ep1", hist)], generated_at=T0+timedelta(days=3))
    m = report.matches[0]
    assert m.disposition == MatchDisposition.STRONG_SEQUENCE_MATCH
    assert m.similarity_score == 1.0
    assert m.historical_outcome == EpisodeOutcome.IMPROVED
    assert m.adjudication_ref == "adjudication:ep1"
    assert m.practitioner_action_refs == ("action:ep1",)

def test_order_matters_and_differences_are_explained():
    cur = trajectory("current", "case:new", [event(1,"A",0),event(2,"B",10),event(3,"C",20)])
    hist = trajectory("hist", "case:old", [event(11,"B",0),event(12,"A",10),event(13,"C",20)])
    m = match_temporal_experience(cur,[episode("ep",hist)],generated_at=T0+timedelta(days=3)).matches[0]
    assert len(m.alignments) < 3
    assert m.differences

def test_context_mismatch_is_retained_but_not_presented_as_eligible_match():
    cur = trajectory("current", "case:new", [event(1,"A",0),event(2,"B",10)])
    hist = trajectory("hist", "case:old", [event(11,"A",0),event(12,"B",10)], context="postop:complex")
    m = match_temporal_experience(cur,[episode("ep",hist)],generated_at=T0+timedelta(days=3)).matches[0]
    assert m.disposition == MatchDisposition.CONTEXT_MISMATCH

def test_different_procedure_blocks_by_default():
    cur = trajectory("current", "case:new", [event(1,"A",0),event(2,"B",10)])
    hist = trajectory("hist", "case:old", [event(11,"A",0),event(12,"B",10)], procedure="proc:whipple")
    m = match_temporal_experience(cur,[episode("ep",hist)],generated_at=T0+timedelta(days=3)).matches[0]
    assert m.disposition == MatchDisposition.CONTEXT_MISMATCH

def test_same_case_excluded():
    cur = trajectory("current", "case:same", [event(1,"A",0),event(2,"B",10)])
    hist = trajectory("hist", "case:same", [event(11,"A",0),event(12,"B",10)])
    r = match_temporal_experience(cur,[episode("ep",hist)],generated_at=T0+timedelta(days=3))
    assert r.matches == () and r.excluded_episode_refs == ("ep",)

def test_insufficient_current_sequence_returns_no_match():
    cur = trajectory("current", "case:new", [event(1,"A",0)])
    hist = trajectory("hist", "case:old", [event(11,"A",0),event(12,"B",10)])
    r = match_temporal_experience(cur,[episode("ep",hist)],generated_at=T0+timedelta(days=3))
    assert r.matches == ()

def test_duplicate_episode_ids_rejected():
    cur = trajectory("current", "case:new", [event(1,"A",0),event(2,"B",10)])
    hist = trajectory("hist", "case:old", [event(11,"A",0),event(12,"B",10)])
    with pytest.raises(ValueError):
        match_temporal_experience(cur,[episode("ep",hist),episode("ep",hist)],generated_at=T0+timedelta(days=3))

def test_future_generated_time_rejected():
    cur = trajectory("current", "case:new", [event(1,"A",0),event(2,"B",10)])
    with pytest.raises(ValueError):
        match_temporal_experience(cur,[],generated_at=T0)

def test_attribute_differences_reported():
    cur = trajectory("current", "case:new", [event(1,"A",0,state="high"),event(2,"B",10)])
    hist = trajectory("hist", "case:old", [event(11,"A",0,state="low"),event(12,"B",10)])
    m = match_temporal_experience(cur,[episode("ep",hist)],generated_at=T0+timedelta(days=3)).matches[0]
    assert any(d.kind == "attribute_difference" for d in m.differences)

def test_policy_threshold_validation():
    with pytest.raises(ValueError):
        TemporalMatchPolicy(strong_match_threshold=.4, partial_match_threshold=.6)
