"""TK-G (revision 2, R2-B): the label "simulated arms (stub), not a Stage 4 comparison" on every output
while any arm is bound to the stub, and no way to drop it."""
import json
import os

import pytest

from engram_testkit import report as R
from engram_testkit.arms import Registry, Retrieval, StubMemory
from engram_testkit.dry_run import dry_run
from engram_testkit.label import LABEL, LabelMissing, is_simulated
from engram_testkit.runner import read_jsonl, run
from engram_testkit.scoring import summarise

from .conftest import Scripted, outputs


class DeclaredReal:
    """A test arm that declares itself a real configuration. Not a Stage 4 arm; used only to show
    when the label is and is not required."""
    simulated = False

    def reset(self): pass
    def ingest(self, c): pass
    def retrieve(self, question, conversation=None, asked_on=None):
        return Retrieval(context="", turn_ids=[], tokens=0)


class Silent(DeclaredReal):
    """An arm that says nothing about itself."""
    simulated = None


def test_g01_label_wording_is_the_approved_text():
    assert LABEL == "simulated arms (stub), not a Stage 4 comparison"


def test_g02_dry_run_report_carries_the_label(tmp_path):
    _, _, text = dry_run(str(tmp_path / "dry"))
    first = text.splitlines()[0]
    assert LABEL in first
    assert text.count(LABEL) >= 3
    assert text.rstrip().endswith(f"Label: {LABEL}.")
    assert "bound (stub)" in text


def test_g03_every_output_file_of_the_dry_run_carries_the_label(tmp_path):
    out = str(tmp_path / "dry")
    dry_run(out)
    state = json.load(open(os.path.join(out, "state.json")))
    assert state["label"] == LABEL and state["simulated"] is True
    for name in ("answers.jsonl", "calls.jsonl"):
        rows = read_jsonl(os.path.join(out, name))
        assert rows and all(r.get("label") == LABEL for r in rows), name
    assert json.load(open(os.path.join(out, "summary.json")))["label"] == LABEL
    assert json.load(open(os.path.join(out, "sheet.jsonl.header.json")))["label"] == LABEL


def _sim_run(tmp_path, cfg):
    from engram_testkit.formats import load_synthetic
    convs, qs = load_synthetic()
    c = cfg()
    state = run(Registry().bind("A", StubMemory()), convs, qs, Scripted("ans-1"), Scripted("jud-1", "WRONG"), c)
    _, rows, calls = outputs(c.out_dir)
    return state, rows, calls


def test_g04_label_cannot_be_stripped_from_records_summary_or_report(tmp_path, cfg):
    state, rows, calls = _sim_run(tmp_path, cfg)
    with pytest.raises(LabelMissing):
        summarise(rows[:-1] + [{k: v for k, v in rows[-1].items() if k != "label"}], calls, 2, True)
    with pytest.raises(LabelMissing):
        summarise([{k: v for k, v in r.items() if k != "label"} for r in rows], calls, 2, True, state=state)
    s = summarise(rows, calls, 2, True, state=state)
    with pytest.raises(LabelMissing):
        R.markdown({k: v for k, v in s.items() if k != "label"}, state)
    no_label_state = {k: v for k, v in state.items() if k not in ("label", "simulated")}
    assert LABEL in R.markdown(s, no_label_state, title="A title without it")


def test_g05_one_stub_binding_is_enough_to_require_the_label(tmp_path, cfg):
    from engram_testkit.formats import load_synthetic
    convs, qs = load_synthetic()
    assert is_simulated([DeclaredReal(), StubMemory()]) and is_simulated([Silent()])
    assert not is_simulated([DeclaredReal()])
    c = cfg()
    state = run(Registry().bind("A", DeclaredReal()).bind("B", StubMemory()), convs, qs, Scripted("ans-1"), Scripted("jud-1"), c)
    _, rows, _ = outputs(c.out_dir)
    assert state["label"] == LABEL and all(r["label"] == LABEL for r in rows)


def test_g06_no_label_only_when_every_arm_declares_itself_real(tmp_path, cfg):
    from engram_testkit.formats import load_synthetic
    convs, qs = load_synthetic()
    c = cfg()
    state = run(Registry().bind("A", DeclaredReal()).bind_floor(), convs, qs, Scripted("ans-1"), Scripted("jud-1"), c)
    _, rows, calls = outputs(c.out_dir)
    assert state["simulated"] is False and "label" not in state
    assert all("label" not in r for r in rows + calls)
    text = R.markdown(summarise(rows, calls, 2, True, state=state), state)
    assert LABEL not in text
