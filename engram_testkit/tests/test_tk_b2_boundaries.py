"""TK-B2X (build revision 2, his ruling of 25 Nov 2026): the boundary gaps found in the review, as new tests.
Separate from the 94 accepted tests. Each makes the failure condition happen and checks the kit's specific
refusal, and that nothing was called or written where that matters.
"""
import copy
import json
import os

import pytest

from engram_testkit import formats as F
from engram_testkit import runner as Rn
from engram_testkit.arms import Registry, StubMemory
from engram_testkit.audit import AuditMissing, check_audit

from .b2_helpers import Echo, LateArm, arms, audit_for, config, records, synthetic


def _go(out, registry=None, questions=None, conversations=None, answer=None, judge=None, **kw):
    convs, qs = synthetic()
    qs = qs if questions is None else questions
    c = config(out, questions=qs, **kw)
    answer = answer or Echo("ans-b2")
    judge = judge or Echo("jud-b2", reply="WRONG")
    state = Rn.run(registry or arms(), conversations or convs, qs, answer, judge, c)
    return state, c, answer, judge


# --- freeze refusal, stricter than R06 -----------------------------------------------------------------

@pytest.mark.parametrize("kind", ["answer", "judge"])
def test_x01_a_callable_without_a_model_name_is_refused_specifically_and_nothing_is_called(tmp_path, kind):
    out = str(tmp_path / "run")
    anon, other = Echo(None), Echo("jud-b2" if kind == "answer" else "ans-b2")
    pair = dict(answer=anon, judge=other) if kind == "answer" else dict(answer=other, judge=anon)
    with pytest.raises(Rn.CallableRefused, match="must name its model"):
        _go(out, **pair)
    assert anon.received == [] and other.received == [] and not os.path.exists(out)


# --- real data and consent ----------------------------------------------------------------------------

@pytest.mark.parametrize("asked_on", [None, "2026-06-01"], ids=["without-asked_on", "with-asked_on"])
def test_x02_a_real_conversation_passed_straight_to_a_run_is_refused_as_real_data(tmp_path, asked_on):
    out = str(tmp_path / "run")
    convs, qs = synthetic()
    convs = copy.deepcopy(convs)
    convs["syn-1"]["provenance"] = "real"
    qs = [dict(q, asked_on=asked_on) if asked_on else dict(q) for q in qs]
    answer = Echo("ans-b2")
    with pytest.raises(F.RealDataRefused):
        _go(out, conversations=convs, questions=qs, answer=answer)
    assert answer.received == [] and not os.path.exists(out)


def test_x03_a_conversation_with_the_consent_key_removed_is_refused(tmp_path):
    convs, qs = synthetic()
    c = copy.deepcopy(convs["syn-2"])
    del c["consent"]
    with pytest.raises(F.FormatError, match="consent") as got:
        F.validate_conversation(c)
    assert not isinstance(got.value, F.RealDataRefused)
    records_ = F.read_records(F.SYNTHETIC + "/conversations.json")
    del records_[0]["consent"]
    (tmp_path / "c.json").write_text(json.dumps(records_))
    with pytest.raises(F.FormatError, match="consent"):
        F.load_set(str(tmp_path / "c.json"), F.SYNTHETIC + "/questions.json")


# --- output isolation from git repositories ------------------------------------------------------------

def test_x04_a_worktree_git_file_counts_as_a_repository(tmp_path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/wt\n")
    out = str(tmp_path / "wt" / "results")
    answer = Echo("ans-b2")
    with pytest.raises(Rn.InsideRepository):
        _go(out, answer=answer)
    assert answer.received == [] and not os.path.exists(out)


def test_x05_deep_nesting_inside_a_repository_is_refused(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    out = str(tmp_path / "repo" / "a" / "b" / "c" / "results")
    with pytest.raises(Rn.InsideRepository):
        _go(out)
    assert not os.path.exists(tmp_path / "repo" / "a")


# --- gold-answer audit ---------------------------------------------------------------------------------

@pytest.mark.parametrize("change,match", [
    (lambda a: a["entries"]["q05"].update(reason=""), "reason"),
    (lambda a: a["entries"]["q05"].update(reason="   "), "reason"),
    (lambda a: a.update(date="24/11/2026"), "date"),
    (lambda a: a.update(date="2026-13-01"), "date"),
    (lambda a: a.update(date=None), "date"),
], ids=["empty-reason", "blank-reason", "date-format", "date-impossible", "date-missing"])
def test_x06_audit_with_empty_reason_or_bad_date_is_refused_before_any_call(tmp_path, change, match):
    _, qs = synthetic()
    audit = audit_for(qs)
    change(audit)
    with pytest.raises(AuditMissing, match=match):
        check_audit(audit, qs)
    answer = Echo("ans-b2")
    with pytest.raises(AuditMissing, match=match):
        _go(str(tmp_path / "run"), audit=audit, answer=answer)
    assert answer.received == [] and not os.path.exists(tmp_path / "run")


def test_x07_a_corrected_question_is_asked_and_the_correction_recorded(tmp_path):
    out = str(tmp_path / "run")
    _, qs = synthetic()
    audit = audit_for(qs)
    audit["entries"]["q05"] = dict(status="corrected", reason="gold reworded after review")
    state, *_ = _go(out, audit=audit)
    _, rows, _ = records(out)
    assert state["audit"]["corrected"] == ["q05"] and state["audit"]["dropped"] == []
    assert {r["qid"] for r in rows} >= {"q05"}


# --- resume integrity ----------------------------------------------------------------------------------

def _stopped(out):
    state, c, *_ = _go(out, cap=9)
    assert state["stopped"] and "cap" in state["reason"]
    c.call_cap = 1000
    return c, records(out)


def _audit_dropping(qs, qid):
    a = audit_for(qs)
    a["entries"][qid] = dict(status="dropped", reason="disputed")
    return a


@pytest.mark.parametrize("change,match", [
    ("question set", "question set"),
    ("arms", "arms"),
    ("runs", "runs"),
    ("asked", "asked"),
    ("freeze setting", "freeze"),
])
def test_x08_resume_refuses_any_change_to_the_run_identity(tmp_path, change, match):
    out = str(tmp_path / "run")
    c, before = _stopped(out)
    convs, qs = synthetic()
    registry = arms()
    if change == "question set":
        qs = qs[:-1]
        c.audit = audit_for(qs)
    elif change == "arms":
        registry = arms().bind("C", StubMemory(k=3))
    elif change == "runs":
        c.runs = 1
    elif change == "asked":
        c.audit = _audit_dropping(qs, "q13")
    else:
        c.freeze = dict(c.freeze, answer=dict(c.freeze["answer"], max_tokens=50))
    answer = Echo(c.freeze["answer"]["model"])
    with pytest.raises(Rn.NotIdentical, match=match):
        Rn.run(registry, convs, qs, answer, Echo("jud-b2"), c)
    assert answer.received == [] and records(out)[1:] == before[1:]


def test_x09_resume_after_an_interruption_completes_without_duplicates(tmp_path):
    out = str(tmp_path / "run")
    with pytest.raises(KeyboardInterrupt):
        _go(out, answer=Echo("ans-b2", interrupt_at=3))
    state1, rows1, calls1 = records(out)
    assert state1["stopped"] is True and "KeyboardInterrupt" in state1["reason"]
    assert "KeyboardInterrupt" in calls1[-1]["error"] and calls1[-1]["effective"] is None
    state2, *_ = _go(out)
    _, rows, calls = records(out)
    keys = [(r["arm"], r["qid"], r["run"]) for r in rows]
    assert state2["stopped"] is False and state2["sessions"] == 2
    assert len(keys) == len(set(keys)) == 2 * 2 * 13
    assert rows[: len(rows1)] == rows1 and calls[: len(calls1)] == calls1
    assert state2["calls_used"] == len(calls)


# --- asked_on, enforced by the runner -------------------------------------------------------------------

@pytest.mark.parametrize("turns,why", [(["s1:2", "s1:4"], "after"), (["s3:1"], "other conversation")],
                         ids=["turn-after-asked_on", "turn-from-another-conversation"])
def test_x10_the_runner_refuses_turns_an_arm_returns_from_after_asked_on(tmp_path, turns, why):
    out = str(tmp_path / "run")
    convs, qs = synthetic()
    q02 = [dict(next(q for q in qs if q["id"] == "q02"), asked_on="2026-04-01")]
    answer = Echo("ans-b2")
    with pytest.raises(Rn.AskedOnBreach, match="asked on 2026-04-01"):
        _go(out, registry=Registry().bind("A", LateArm(turns)), questions=q02, answer=answer)
    state, rows, calls = records(out)
    assert answer.received == [] and rows == [] and calls == []
    assert state["stopped"] is True and "AskedOnBreach" in state["reason"]


def test_x11_turns_on_or_before_asked_on_pass_the_runner_check(tmp_path):
    convs, qs = synthetic()
    q02 = [dict(next(q for q in qs if q["id"] == "q02"), asked_on="2026-05-10")]
    state, *_ = _go(str(tmp_path / "run"), registry=Registry().bind("A", LateArm(["s1:2", "s1:4"])), questions=q02)
    assert state["stopped"] is False
