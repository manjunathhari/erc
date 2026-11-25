"""TK-R: the run record, identical questions and answer model, call cap, retries, stop-and-save, latency and tokens."""
import ast
import os

import pytest

from engram_testkit import runner as Rn

from .conftest import Scripted, outputs, two_arms

ADV = 3  # adversarial questions in the synthetic set


def go(synthetic, cfg, answer=None, judge=None, **kw):
    convs, qs = synthetic
    c = cfg(**kw)
    state = Rn.run(two_arms(), convs, qs, answer or Scripted("ans-1"), judge or Scripted("jud-1", "CORRECT"), c)
    return (state,) + outputs(c.out_dir)[1:]


def test_r01_every_question_answered_twice_per_arm_and_judged_twice(synthetic, cfg):
    state, rows, calls = go(synthetic, cfg)
    n = len(synthetic[1])
    assert state["stopped"] is False and state["runs"] == 2
    assert len(rows) == 2 * 2 * n
    assert sum(c["kind"] == "answer" for c in calls) == 2 * 2 * n
    assert sum(c["kind"] == "judge" for c in calls) == 2 * 2 * (n - ADV)


def test_r02_adversarial_questions_are_not_sent_to_the_judge(synthetic, cfg):
    judge = Scripted("jud-1", "CORRECT")
    _, rows, _ = go(synthetic, cfg, judge=judge)
    assert all(r["judge"] is None for r in rows if r["category"] == "adversarial")
    assert not any("Tomas's dog" in p for p in judge.prompts)


def test_r03_every_call_saved_with_prompt_reply_model_and_attempt(synthetic, cfg):
    state, _, calls = go(synthetic, cfg)
    assert len(calls) == state["calls_used"]
    for c in calls:
        assert {"arm", "qid", "run", "kind", "model", "attempt", "prompt", "reply", "secs"} <= set(c)


def test_r04_same_question_set_and_answer_model_on_every_row(synthetic, cfg):
    _, rows, _ = go(synthetic, cfg)
    assert {r["answer_model"] for r in rows} == {"ans-1"}
    assert len({r["question_set"] for r in rows}) == 1
    by_arm = {a: sorted((r["qid"], r["run"]) for r in rows if r["arm"] == a) for a in "AB"}
    assert by_arm["A"] == by_arm["B"]
    assert Rn.check_identical(rows)


def test_r05_check_refuses_mixed_answer_models_or_question_sets(synthetic, cfg):
    _, rows, _ = go(synthetic, cfg)
    with pytest.raises(Rn.NotIdentical, match="answer model"):
        Rn.check_identical(rows[:-1] + [dict(rows[-1], answer_model="other")])
    with pytest.raises(Rn.NotIdentical, match="question set"):
        Rn.check_identical(rows[:-1] + [dict(rows[-1], question_set="x")])
    with pytest.raises(Rn.NotIdentical, match="same questions"):
        Rn.check_identical([r for r in rows if not (r["arm"] == "B" and r["qid"] == "q01")])


def test_r06_callables_must_name_their_model(synthetic, cfg):
    anon = Scripted(None)
    with pytest.raises(ValueError, match="model"):
        go(synthetic, cfg, answer=anon)


def test_r07_hard_cap_stops_exactly_at_the_cap_and_saves(synthetic, cfg):
    state, rows, calls = go(synthetic, cfg, cap=7)
    assert state["stopped"] is True and "cap" in state["reason"]
    assert state["calls_used"] == 7 and len(calls) == 7
    assert rows, "finished questions are kept"


def test_r08_retries_count_against_the_cap_and_stop_at_max_tries(synthetic, cfg):
    bad = Scripted("ans-1", always_fail=True)
    state, rows, calls = go(synthetic, cfg, answer=bad, cap=1000)
    assert all(c["ok"] is False for c in calls)
    assert {c["attempt"] for c in calls} == {1, 2, 3}
    assert state["calls_used"] == len(calls) == 3 * len(rows)
    assert all(r["pred"] is None and r["error"] for r in rows)


def test_r09_a_retry_that_succeeds_keeps_both_tries(synthetic, cfg):
    flaky = Scripted("ans-1", fail_first=1)
    _, rows, calls = go(synthetic, cfg, answer=flaky)
    first = [c for c in calls if c["kind"] == "answer" and c["qid"] == "q01" and c["arm"] == "A" and c["run"] == 1]
    assert [(c["attempt"], c["ok"]) for c in first] == [(1, False), (2, True)]
    assert rows[0]["pred"] == "not mentioned"


def test_r10_interruption_saves_state_then_raises(synthetic, cfg):
    def boom(prompt, max_tokens=60, temperature=None, reasoning=None):
        raise KeyboardInterrupt
    boom.model = "ans-1"
    convs, qs = synthetic
    c = cfg()
    with pytest.raises(KeyboardInterrupt):
        Rn.run(two_arms(), convs, qs, boom, Scripted("jud-1"), c)
    state, _, calls = outputs(c.out_dir)
    assert state["stopped"] is True and "KeyboardInterrupt" in state["reason"]
    assert state["calls_used"] == 1 and len(calls) == 1 and "KeyboardInterrupt" in calls[0]["error"]


def test_r11_latency_recorded_for_every_call_retrieval_and_ingest(synthetic, cfg):
    state, rows, calls = go(synthetic, cfg)
    assert all(isinstance(c["secs"], float) for c in calls)
    assert all(isinstance(r["retrieve_secs"], float) and isinstance(r["answer_secs"], float) for r in rows)
    assert set(state["ingest"]) == {"A", "B"}


def test_r12_tokens_recorded_reported_and_estimated(synthetic, cfg):
    _, rows, calls = go(synthetic, cfg, answer=Scripted("ans-1", usage=False))
    answers = [c for c in calls if c["kind"] == "answer"]
    assert all(c["prompt_tokens"] is None and c["prompt_tokens_est"] > 0 for c in answers)
    judged = [c for c in calls if c["kind"] == "judge"]
    assert all(c["prompt_tokens"] == 11 and c["completion_tokens"] == 3 for c in judged)
    assert all(r["answer_tokens"] > 0 and r["context_tokens"] >= 0 for r in rows)


def test_r13_evidence_found_recorded_except_for_adversarial(synthetic, cfg):
    _, rows, _ = go(synthetic, cfg)
    for r in rows:
        assert (r["evidence_found"] is None) == (r["category"] == "adversarial")


def test_r14_kit_modules_open_no_network():
    here = os.path.dirname(os.path.dirname(os.path.abspath(Rn.__file__)))
    banned = {"socket", "urllib", "http", "requests", "httpx", "anthropic", "openai"}
    for name in os.listdir(os.path.join(here, "engram_testkit")):
        if name.endswith(".py"):
            tree = ast.parse(open(os.path.join(here, "engram_testkit", name)).read())
            mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
            assert not mods & banned, (name, mods & banned)
