"""TK-C: the scoring sheet, both runs, and the per-arm latency and token columns."""
import pytest

from engram_testkit import scoring as S
from engram_testkit.runner import NotIdentical

from .conftest import Scripted, outputs, two_arms
from engram_testkit.runner import run


def test_c01_generous_label_comes_from_the_judge_reply():
    assert S.generous("CORRECT") and S.generous(" correct.")
    assert not S.generous("WRONG") and not S.generous("") and not S.generous(None)


def test_c02_strict_rule_needs_every_gold_word():
    assert S.strict("She lives in Porto now", "Porto")
    assert S.strict("May 9, 2026", "9 May 2026")
    assert not S.strict("May 2026", "9 May 2026")
    assert not S.strict("Lisbon", "Porto")
    # never credits an abstention
    assert not S.strict("not mentioned", "not mentioned")
    assert not S.strict("Not mentioned, though Porto is likely", "Porto")


def test_c03_adversarial_fixed_rule():
    adv = dict(category="adversarial", pred="Not mentioned.", judge=None, gold="not mentioned")
    assert S.score(adv)["generous"] and S.score(adv)["strict"]
    wrong = dict(adv, pred="Rex")
    assert not S.score(wrong)["generous"] and not S.score(wrong)["strict"]
    assert S.score(dict(adv, pred=None))["strict"] is False
    # the judge cannot rescue an adversarial answer
    assert S.score(dict(adv, pred="Rex", judge="CORRECT"))["generous"] is False


def _summary(synthetic, cfg, answer, judge, cap=1000):
    convs, qs = synthetic
    c = cfg(cap=cap)
    state = run(two_arms(), convs, qs, answer, judge, c)
    _, rows, calls = outputs(c.out_dir)
    return state, S.summarise(rows, calls, 2, finished=not state["stopped"])


def test_c04_both_runs_reported_separately_with_agreement(synthetic, cfg):
    flip = Scripted("ans-1", reply=lambda p: "Porto" if len(flip.prompts) % 2 else "Lisbon")
    _, s = _summary(synthetic, cfg, flip, Scripted("jud-1", "CORRECT"))
    a = s["arms"]["A"]
    assert set(a["strict"]) == {1, 2} and set(a["generous"]) == {1, 2}
    assert a["strict"][1] != a["strict"][2]
    assert a["runs_agree"] < 100


def test_c05_summary_carries_latency_and_token_cost_per_arm(synthetic, cfg):
    _, s = _summary(synthetic, cfg, Scripted("ans-1"), Scripted("jud-1", "WRONG"))
    for a in s["arms"].values():
        for k in ("retrieve_secs", "answer_secs", "context_tokens", "answer_tokens", "tokens_all_calls", "calls", "failed_calls"):
            assert a[k] is not None, k
        assert a["tokens_all_calls"] > 0


def test_c06_all_not_mentioned_scores_adversarial_only(synthetic, cfg):
    _, s = _summary(synthetic, cfg, Scripted("ans-1"), Scripted("jud-1", "WRONG"))
    a = s["arms"]["A"]
    assert a["by_category"]["adversarial"] == 100.0
    assert a["strict"][1] == round(100 * 3 / 13, 1)


def test_c07_stopped_run_scores_only_questions_complete_in_every_arm(synthetic, cfg):
    state, s = _summary(synthetic, cfg, Scripted("ans-1"), Scripted("jud-1", "WRONG"), cap=9)
    assert state["stopped"]
    assert s["complete_questions"] == 1
    assert {a["questions"] for a in s["arms"].values()} == {1}


def test_c08_summary_refuses_mixed_answer_models(synthetic, cfg):
    convs, qs = synthetic
    c = cfg()
    run(two_arms(), convs, qs, Scripted("ans-1"), Scripted("jud-1"), c)
    _, rows, calls = outputs(c.out_dir)
    rows[0]["answer_model"] = "ans-2"
    with pytest.raises(NotIdentical):
        S.summarise(rows, calls, 2, finished=True)


def test_c09_blinded_sheet_matches_judge_sheet_shape_and_hides_arms(synthetic, cfg):
    _, s = _summary(synthetic, cfg, Scripted("ans-1"), Scripted("jud-1", "WRONG"))
    sheet, key = S.blinded_sheet(s["scored"])
    assert all(set(r) == {"id", "cat", "q", "gold", "pred"} for r in sheet)
    assert set(key) == {r["id"] for r in sheet} and len(sheet) == len(s["scored"])
    assert {v[0] for v in key.values()} == {"A", "B"}
    assert S.blinded_sheet(s["scored"])[0] == sheet
