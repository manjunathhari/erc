"""Shared helpers for the test kit's tests. Synthetic and invented data only; no model, no network."""
import copy
import json
import os

import pytest

from engram_testkit.arms import Registry, StubMemory
from engram_testkit.audit import make_audit
from engram_testkit.formats import load_synthetic
from engram_testkit.runner import RunConfig, read_jsonl

# Revision 2: every run needs a freeze (TK-5, IF-8) and a gold-answer audit record (TK-16).
# The test models are invented names; no real model is named.
FREEZE = dict(answer=dict(model="ans-1", max_tokens=60, temperature=0, reasoning="off"),
              judge=dict(model="jud-1", max_tokens=64, temperature=0, reasoning="off"))


def synthetic_audit():
    return make_audit(load_synthetic()[1], auditor="test", date="2026-11-24")


class Scripted:
    """A callable in the repository's shape: (prompt, max_tokens) -> (text, usage, secs)."""

    def __init__(self, model, reply="not mentioned", fail_first=0, always_fail=False, usage=True):
        self.model, self.reply, self.fail_first, self.always_fail, self.usage = model, reply, fail_first, always_fail, usage
        self.prompts = []

    def __call__(self, prompt, max_tokens=60, temperature=None, reasoning=None):
        self.prompts.append(prompt)
        if self.always_fail or len(self.prompts) <= self.fail_first:
            raise TimeoutError("scripted failure")
        text = self.reply(prompt) if callable(self.reply) else self.reply
        used = dict(model=self.model, max_tokens=max_tokens, temperature=temperature, reasoning=reasoning)
        return text, dict((dict(prompt_tokens=11, completion_tokens=3) if self.usage else {}), effective=used), 0.0


@pytest.fixture
def synthetic():
    return load_synthetic()


@pytest.fixture
def conv():
    """One small valid conversation dict to break in tests."""
    convs, _ = load_synthetic()
    return copy.deepcopy(convs["syn-1"])


def two_arms():
    return Registry().bind("A", StubMemory(k=2)).bind("B", StubMemory(k=4))


def outputs(out_dir):
    state = json.load(open(os.path.join(out_dir, "state.json")))
    return state, read_jsonl(os.path.join(out_dir, "answers.jsonl")), read_jsonl(os.path.join(out_dir, "calls.jsonl"))


@pytest.fixture
def cfg(tmp_path):
    def make(cap=1000, **kw):
        kw.setdefault("freeze", FREEZE)
        kw.setdefault("audit", synthetic_audit())
        return RunConfig(out_dir=str(tmp_path / "run"), call_cap=cap, **kw)
    return make


def fake_locomo(path, n=10):
    """A LoCoMo-shaped file with invented text, so the loader is tested without the real data."""
    data = []
    for i in range(n):
        data.append(dict(
            conversation=dict(speaker_a="Ana", speaker_b="Ben",
                              session_1_date_time="1:00 pm on 8 May, 2023", session_1=[
                                  dict(speaker="Ana", dia_id="D1:1", text=f"I painted a boat in conversation {i}."),
                                  dict(speaker="Ben", dia_id="D1:2", text="Nice, what colour?", blip_caption="a boat")],
                              session_2_date_time="2:00 pm on 9 June, 2023", session_2=[
                                  dict(speaker="Ana", dia_id="D2:1", text="Blue, and I sold it yesterday.")]),
            qa=[dict(question="What did Ana paint?", answer="a boat", evidence=["D1:1"], category=4),
                dict(question="When did Ana sell the boat?", answer="8 June 2023", evidence=["D2:1"], category=2),
                dict(question="What did Ben paint?", adversarial_answer="a boat", evidence=["D1:1"], category=5)]))
    with open(path, "w") as f:
        json.dump(data, f)
    return path
