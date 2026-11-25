"""TK-B2F (build revision 2, his ruling of 25 Nov 2026): the recorded freeze describes the configuration
actually used. New tests, separate from the 94 accepted ones.

The runner passes max_tokens, temperature and reasoning to both callables; each callable reports the
settings it used; a callable that cannot take them is refused before any call; a missing or different
report is saved as a failed call and stops the run; every call record carries both; resume refuses a
changed configuration.
"""
import json
import os

import pytest

from engram_testkit import runner as Rn
from engram_testkit.dry_run import dry_run
from engram_testkit.runner import FREEZE_FIELDS, SETTINGS

from .b2_helpers import FREEZE_B2, Echo, arms, config, legacy, records, synthetic

ADV = 3


def _run(out, answer=None, judge=None, cap=1000, freeze=FREEZE_B2, **kw):
    convs, qs = synthetic()
    c = config(out, cap=cap, freeze=freeze, **kw)
    answer = answer or Echo("ans-b2")
    judge = judge or Echo("jud-b2", reply="WRONG")
    return Rn.run(arms(), convs, qs, answer, judge, c), c, answer, judge


def test_b01_frozen_settings_reach_both_the_answer_and_the_judge_callable(tmp_path):
    state, _, answer, judge = _run(str(tmp_path / "run"))
    assert state["stopped"] is False
    want = {kind: {f: FREEZE_B2[kind][f] for f in SETTINGS} for kind in ("answer", "judge")}
    assert len(answer.received) == 2 * 2 * 13 and len(judge.received) == 2 * 2 * (13 - ADV)
    assert all({f: r[f] for f in SETTINGS} == want["answer"] for r in answer.received)
    assert all({f: r[f] for f in SETTINGS} == want["judge"] for r in judge.received)


def test_b02_requested_and_used_settings_recorded_on_every_call(tmp_path):
    out = str(tmp_path / "run")
    state, *_ = _run(out)
    _, _, calls = records(out)
    assert calls and len(calls) == state["calls_used"]
    for c in calls:
        want = {f: FREEZE_B2[c["kind"]][f] for f in FREEZE_FIELDS}
        assert c["requested"] == want and c["effective"] == want and c["ok"] is True, c
    assert state["freeze"] == FREEZE_B2


@pytest.mark.parametrize("kind", ["answer", "judge"])
def test_b03_a_callable_that_cannot_take_the_settings_is_refused_before_any_call(tmp_path, kind):
    out = str(tmp_path / "run")
    old = legacy(FREEZE_B2[kind]["model"])
    other = Echo(FREEZE_B2["judge" if kind == "answer" else "answer"]["model"])
    pair = dict(answer=old, judge=other) if kind == "answer" else dict(answer=other, judge=old)
    with pytest.raises(Rn.CallableRefused, match="temperature and reasoning"):
        _run(out, **pair)
    assert old.calls == [] and other.received == []
    assert not os.path.exists(out)


@pytest.mark.parametrize("kind", ["answer", "judge"])
@pytest.mark.parametrize("field,value", [("model", "someone-else"), ("max_tokens", 999), ("temperature", 0.9),
                                         ("reasoning", "high")])
def test_b04_a_used_setting_that_differs_from_the_freeze_is_saved_as_failed_and_stops_the_run(tmp_path, kind, field, value):
    out = str(tmp_path / "run")
    liar = Echo(FREEZE_B2[kind]["model"], reply="WRONG" if kind == "judge" else "not mentioned", override={field: value})
    with pytest.raises(Rn.EffectiveMismatch, match=field):
        _run(out, **{kind: liar})
    state, rows, calls = records(out)
    assert len(liar.received) == 1, "the run stops at the first mismatched call"
    bad = calls[-1]
    assert bad["kind"] == kind and bad["ok"] is False and bad["effective"][field] == value
    assert field in bad["error"] and bad["requested"][field] == FREEZE_B2[kind][field]
    assert rows == [] and state["stopped"] is True and "EffectiveMismatch" in state["reason"]
    assert state["calls_used"] == len(calls) == (1 if kind == "answer" else 2)


@pytest.mark.parametrize("how", ["no-report", "field-missing"])
def test_b05_missing_used_settings_are_a_mismatch(tmp_path, how):
    out = str(tmp_path / "run")
    quiet = Echo("ans-b2", report=False) if how == "no-report" else Echo("ans-b2", omit=("reasoning",))
    with pytest.raises(Rn.EffectiveMismatch, match="reported"):
        _run(out, answer=quiet)
    state, rows, calls = records(out)
    assert len(calls) == 1 and calls[0]["ok"] is False and rows == [] and state["stopped"] is True


def test_b06_resume_refuses_a_changed_frozen_configuration(tmp_path):
    out = str(tmp_path / "run")
    state, c, *_ = _run(out, cap=9)
    assert state["stopped"] and "cap" in state["reason"]
    before = records(out)[2]
    convs, qs = synthetic()
    c.call_cap = 1000
    c.freeze = dict(FREEZE_B2, judge=dict(FREEZE_B2["judge"], temperature=0.5))
    with pytest.raises(Rn.NotIdentical, match="freeze"):
        Rn.run(arms(), convs, qs, Echo("ans-b2"), Echo("jud-b2"), c)
    assert records(out)[2] == before


def test_b07_resume_refuses_when_an_earlier_session_used_other_settings(tmp_path):
    """The freeze is unchanged, but an earlier session's call used other settings: resume is refused."""
    out = str(tmp_path / "run")
    with pytest.raises(Rn.EffectiveMismatch):
        _run(out, judge=Echo("jud-b2", reply="WRONG", override=dict(temperature=1.0)))
    before = records(out)[2]
    with pytest.raises(Rn.NotIdentical, match="used other settings"):
        _run(out)
    assert records(out)[2] == before


def test_b08_resume_refuses_earlier_call_records_that_disagree_with_the_freeze(tmp_path):
    """Call records edited after a stop (the freeze in state.json untouched) are caught on resume."""
    out = str(tmp_path / "run")
    _run(out, cap=9)
    path = os.path.join(out, "calls.jsonl")
    calls = [json.loads(x) for x in open(path)]
    calls[3]["effective"] = dict(calls[3]["effective"], reasoning="high")
    with open(path, "w") as f:
        f.write("".join(json.dumps(x) + "\n" for x in calls))
    with pytest.raises(Rn.NotIdentical, match="used other settings"):
        _run(out)
    calls[3]["effective"] = None
    calls[3]["requested"] = dict(calls[3]["requested"], max_tokens=1)
    with open(path, "w") as f:
        f.write("".join(json.dumps(x) + "\n" for x in calls))
    with pytest.raises(Rn.NotIdentical, match="asked for other settings"):
        _run(out)


def test_b09_resume_with_the_same_configuration_completes(tmp_path):
    out = str(tmp_path / "run")
    _run(out, cap=9)
    state, *_ = _run(out)
    _, rows, calls = records(out)
    assert state["stopped"] is False and state["sessions"] == 2 and len(rows) == 2 * 2 * 13
    assert all(c["effective"] == c["requested"] for c in calls)


def test_b10_dry_run_shows_the_settings_used_per_call(tmp_path):
    out = str(tmp_path / "dry")
    state, s, text = dry_run(out)
    _, _, calls = records(out)
    assert calls and all(c["effective"] == c["requested"] == {f: state["freeze"][c["kind"]][f] for f in FREEZE_FIELDS}
                         for c in calls)
    assert s["call_settings"]["answer"]["matching_freeze"] == s["call_settings"]["answer"]["calls"] == 104
    assert "## Call settings used" in text and "## Limitations" in text
    assert "cannot compare memory configurations" in text
    assert "has not been checked on the real LoCoMo dataset" in text
    assert json.load(open(os.path.join(out, "summary.json")))["limitations"] == s["limitations"]
