"""TK-T (revision 2): the settled decisions TK-2 to TK-18 and IF-8, as tests."""
import ast
import copy
import json
import os
import re
import subprocess
import sys

import pytest

from engram_testkit import arms as A
from engram_testkit import formats as F
from engram_testkit import runner as Rn
from engram_testkit import scoring as S
from engram_testkit.audit import AuditMissing, make_audit
from engram_testkit.dry_run import dry_run

from .conftest import FREEZE, Scripted, fake_locomo, outputs, synthetic_audit, two_arms

PKG = os.path.dirname(os.path.dirname(os.path.abspath(Rn.__file__)))
REPO = PKG  # the folder holding engram_testkit: the repository root


def go(synthetic, cfg, answer=None, judge=None, registry=None, **kw):
    convs, qs = synthetic
    c = cfg(**kw)
    state = Rn.run(registry or two_arms(), convs, qs, answer or Scripted("ans-1"), judge or Scripted("jud-1", "WRONG"), c)
    return (state,) + outputs(c.out_dir)[1:] + (c,)


def test_t01_tk2_arm_contents_and_floor_reported_outside_a_to_d(tmp_path):
    assert A.SLOTS["A"].contents == "today's search (the control)"
    assert A.SLOTS["B"].contents == "A plus vectors over validated facts"
    assert A.SLOTS["C"].contents == "B plus the entity channel and score fusion with time constraints"
    assert A.FLOOR not in A.SLOTS
    state, s, text = dry_run(str(tmp_path / "dry"))
    assert sorted(s["arms"]) == ["A", "B", "C"] and s["floor"]["questions"] == 13
    assert state["floor"] is True and "| floor | no memory |" in text
    assert s["floor"]["evidence_found"] == 0.0


def _vps_constant(name):
    tree = ast.parse(open(os.path.join(REPO, "vps_kit.py")).read())
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == name for t in n.targets):
            return n.value.value


@pytest.mark.skipif(not os.path.exists(os.path.join(REPO, "vps_kit.py")), reason="repository copy not present")
def test_t02_tk4_tk5_answer_and_judge_texts_are_vps_kit_copied_verbatim():
    assert Rn.ANSWER == _vps_constant("ANSWER")
    assert Rn.JUDGE == _vps_constant("JUDGE")


@pytest.mark.parametrize("kind,field", [(k, f) for k in ("answer", "judge") for f in Rn.FREEZE_FIELDS])
def test_t03_tk5_freeze_needs_model_tokens_temperature_reasoning(synthetic, cfg, kind, field):
    fz = copy.deepcopy(FREEZE)
    del fz[kind][field]
    with pytest.raises(Rn.FreezeError, match=field if field != "model" else "model"):
        go(synthetic, cfg, freeze=fz)


def test_t04_tk5_freeze_required_matched_recorded_and_used(synthetic, cfg):
    with pytest.raises(Rn.FreezeError):
        go(synthetic, cfg, freeze=None)
    with pytest.raises(Rn.FreezeError, match="names"):
        go(synthetic, cfg, answer=Scripted("ans-2"))
    state, _, calls, _ = go(synthetic, cfg)
    assert state["freeze"] == FREEZE
    assert {c["max_tokens"] for c in calls if c["kind"] == "judge"} == {64}
    assert {c["max_tokens"] for c in calls if c["kind"] == "answer"} == {60}


def test_t05_if8_no_model_named_in_kit_code():
    pattern = re.compile(r"\b(claude|gpt|gemma|sonnet|haiku|opus|o[134])[-_.\d]", re.I)
    for name in sorted(os.listdir(os.path.join(PKG, "engram_testkit"))):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(PKG, "engram_testkit", name)).read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                assert not pattern.search(n.value), (name, n.value[:60])


def test_t06_tk6_blinded_strict_labels_are_the_reported_figure_beside_the_rule(tmp_path):
    from engram_testkit import report as R
    state, s, text = dry_run(str(tmp_path / "dry"))
    assert "Blinded strict run 1" in text and "pending" in text and "gold-word rule" in text
    _, key = S.blinded_sheet(s["scored"])
    labels = {k: dict(strict=int(v[0] == "A")) for k, v in key.items()}
    S.apply_blind_labels(s, key, labels)
    assert s["arms"]["A"]["strict_blind"] == {1: 100.0, 2: 100.0}
    assert s["arms"]["B"]["strict_blind"] == {1: 0.0, 2: 0.0}
    out = R.markdown(s, state)
    assert "| A | 13 |" in out and "| 100.0 | 100.0 |" in out


def test_t07_tk7_cap_formula_and_dry_run_uses_it(tmp_path):
    assert Rn.cap_for(4, 13) == 312 and Rn.cap_for(3, 10) == 180 and Rn.cap_for(1, 1) == 6
    state, _, _ = dry_run(str(tmp_path / "dry"))
    assert state["call_cap"] == 312 and state["calls_used"] <= 312


def test_t08_tk8_sheet_files_score_with_judge_sheet_py(tmp_path):
    out = str(tmp_path / "dry")
    dry_run(out)
    sheet = os.path.join(out, "sheet.jsonl")
    rows = [json.loads(x) for x in open(sheet)]
    assert all(set(r) == {"id", "cat", "q", "gold", "pred"} for r in rows)
    key = json.load(open(sheet + ".key.json"))
    assert {v[2] for v in key.values()} == {"A", "B", "C", "floor"}
    tool = os.path.join(REPO, "kit_tools", "judge_sheet.py")
    if not os.path.exists(tool):
        pytest.skip("repository copy not present")
    labels = os.path.join(str(tmp_path), "labels.json")
    json.dump({r["id"]: dict(generous=1, strict=int(key[r["id"]][2] == "A")) for r in rows}, open(labels, "w"))
    got = subprocess.run([sys.executable, "-I", tool, "score", sheet, labels], capture_output=True, text=True, cwd=str(tmp_path))
    assert got.returncode == 0, got.stderr
    assert "'A': {'n': 26, 'generous': 1.0, 'strict': 1.0}" in got.stdout


def test_t09_tk13_results_inside_a_git_repository_refused(synthetic, cfg, tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    inside = Rn.RunConfig(out_dir=str(tmp_path / "repo" / "results"), call_cap=10, freeze=FREEZE, audit=synthetic_audit())
    with pytest.raises(Rn.InsideRepository):
        Rn.run(two_arms(), synthetic[0], synthetic[1], Scripted("ans-1"), Scripted("jud-1"), inside)
    assert not (tmp_path / "repo" / "results").exists()


def test_t10_tk15_resume_skips_done_rows_and_counts_the_cap_across_sessions(synthetic, cfg):
    state1, rows1, calls1, c = go(synthetic, cfg, cap=9)
    assert state1["stopped"] and len(calls1) == 9
    c.call_cap = 1000
    state2 = Rn.run(two_arms(), synthetic[0], synthetic[1], Scripted("ans-1"), Scripted("jud-1", "WRONG"), c)
    _, rows, calls = outputs(c.out_dir)
    assert state2["stopped"] is False and state2["sessions"] == 2
    keys = [(r["arm"], r["qid"], r["run"]) for r in rows]
    assert len(keys) == len(set(keys)) == 2 * 2 * 13
    assert state2["calls_used"] == len(calls)


def test_t11_tk15_a_second_session_cannot_exceed_the_cap(synthetic, cfg):
    _, _, _, c = go(synthetic, cfg, cap=9)
    state = Rn.run(two_arms(), synthetic[0], synthetic[1], Scripted("ans-1"), Scripted("jud-1"), c)
    _, _, calls = outputs(c.out_dir)
    assert state["stopped"] and len(calls) == 9 and state["calls_used"] == 9


def test_t12_tk15_resume_refused_with_other_models(synthetic, cfg):
    _, _, _, c = go(synthetic, cfg, cap=9)
    c.freeze = dict(FREEZE, answer=dict(FREEZE["answer"], model="ans-2"))
    with pytest.raises(Rn.NotIdentical):
        Rn.run(two_arms(), synthetic[0], synthetic[1], Scripted("ans-2"), Scripted("jud-1"), c)


def test_t13_tk16_audit_required_matching_complete_and_well_formed(synthetic, cfg):
    _, qs = synthetic
    bad = [None, make_audit(qs[:-1], "x", "2026-11-24"), dict(synthetic_audit(), auditor="")]
    gap = synthetic_audit()
    del gap["entries"]["q05"]
    odd = synthetic_audit()
    odd["entries"]["q05"] = dict(status="maybe", reason="r")
    for audit in bad + [gap, odd]:
        with pytest.raises(AuditMissing):
            go(synthetic, cfg, audit=audit)


def test_t14_tk16_dropped_question_is_not_asked_and_is_recorded(synthetic, cfg):
    audit = synthetic_audit()
    audit["entries"]["q03"] = dict(status="dropped", reason="gold date disputed")
    state, rows, calls, _ = go(synthetic, cfg, audit=audit)
    assert "q03" not in {r["qid"] for r in rows} and "q03" not in {c["qid"] for c in calls}
    assert state["audit"]["dropped"] == ["q03"] and state["audit"]["auditor"] == "test"


def test_t15_tk17_asked_on_checked_required_for_real_and_honoured(synthetic, cfg):
    convs, qs = synthetic
    q02 = next(q for q in qs if q["id"] == "q02")
    with pytest.raises(F.FormatError, match="asked_on"):
        F.validate_question(dict(q02, asked_on="10/05/2026"), convs)
    real = {"syn-1": dict(convs["syn-1"], provenance="real")}
    with pytest.raises(F.FormatError, match="required"):
        F.validate_question(q02, real)
    assert F.validate_question(dict(q02, asked_on="2026-06-01"), real)
    early = [dict(q02, asked_on="2026-04-01")]
    audit = make_audit(early, "test", "2026-11-24")
    _, rows, _, _ = go((convs, early), cfg, audit=audit)
    assert rows and all("s1:4" not in r["retrieved"] for r in rows)


def test_t16_tk18_paired_bootstrap_against_a_with_fixed_seed(tmp_path, monkeypatch):
    _, s1, _ = dry_run(str(tmp_path / "one"))
    _, s2, _ = dry_run(str(tmp_path / "two"))
    assert sorted(s1["vs_A"]) == ["B", "C", "floor"] and s1["vs_A"] == s2["vs_A"]
    f = s1["vs_A"]["floor"]
    assert f["seed"] == 7 and f["interval_95"][0] <= f["points"] <= f["interval_95"][1]
    seeds, real = [], S.random.Random
    monkeypatch.setattr(S.random, "Random", lambda *a: seeds.append(a) or real(*a))
    S.bootstrap_diff([(1, 0), (0, 0), (1, 1)], seed=3)
    assert seeds == [(3,)]


def test_t17_tk10_tk11_locomo_turns_whole_and_both_speakers_user(tmp_path):
    from engram_testkit import locomo as L
    convs, _ = L.load(fake_locomo(str(tmp_path / "fake.json")), indices=[0])
    turns = convs["locomo-0"]["turns"]
    assert {t["role"] for t in turns} == {"user"} and {t["speaker"] for t in turns} == {"Ana", "Ben"}
    assert turns[2]["text"] == "Blue, and I sold it yesterday."
