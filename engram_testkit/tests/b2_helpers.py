"""Helpers for the build revision 2 tests (test_tk_b2_freeze.py, test_tk_b2_boundaries.py).

Kept apart from conftest.py, which is an accepted file. Invented data and invented model names only;
no model, no network.
"""
import json
import os

from engram_testkit.arms import Registry, Retrieval, StubMemory
from engram_testkit.audit import make_audit
from engram_testkit.formats import load_synthetic
from engram_testkit.runner import RunConfig, read_jsonl

# Different values for answer and judge, so a test can tell which callable received which.
FREEZE_B2 = dict(answer=dict(model="ans-b2", max_tokens=48, temperature=0.3, reasoning="low"),
                 judge=dict(model="jud-b2", max_tokens=12, temperature=0, reasoning="off"))


class Echo:
    """A callable taking the frozen settings. It records what it was given and reports, in usage["effective"],
    what it used: by default exactly what it was given. `override` makes it report (as if it used) other values;
    `omit` drops fields from the report; report=False sends no report; interrupt_at raises KeyboardInterrupt on
    that call (counting from 1)."""

    def __init__(self, model, reply="not mentioned", override=None, omit=(), report=True, interrupt_at=None):
        self.model, self.reply, self.override, self.omit, self.report = model, reply, override or {}, omit, report
        self.interrupt_at = interrupt_at
        self.received = []

    def __call__(self, prompt, max_tokens=None, temperature=None, reasoning=None):
        self.received.append(dict(prompt=prompt, max_tokens=max_tokens, temperature=temperature, reasoning=reasoning))
        if self.interrupt_at is not None and len(self.received) == self.interrupt_at:
            raise KeyboardInterrupt
        used = dict(model=self.model, max_tokens=max_tokens, temperature=temperature, reasoning=reasoning)
        used.update(self.override)
        for f in self.omit:
            used.pop(f, None)
        usage = dict(prompt_tokens=7, completion_tokens=2)
        if self.report:
            usage["effective"] = used
        return self.reply, usage, 0.0


def legacy(model):
    """A callable in the old shape, (prompt, max_tokens): it cannot take temperature or reasoning."""
    calls = []

    def fn(prompt, max_tokens=60):
        calls.append(prompt)
        return "not mentioned", {}, 0.0
    fn.model, fn.calls = model, calls
    return fn


class LateArm:
    """A test arm that returns given turn ids whatever the question; used to break asked_on."""
    simulated = True

    def __init__(self, turn_ids):
        self.turn_ids = list(turn_ids)

    def reset(self): pass
    def ingest(self, c): pass

    def retrieve(self, question, conversation=None, asked_on=None):
        return Retrieval(context="[2026-05-10] Ines: I live in Porto now.", turn_ids=list(self.turn_ids), tokens=9)


def synthetic():
    return load_synthetic()


def audit_for(questions, **change):
    a = make_audit(questions, auditor="b2 test", date="2026-11-25")
    a.update(change)
    return a


def config(out_dir, questions=None, cap=1000, freeze=FREEZE_B2, audit=None, **kw):
    qs = questions if questions is not None else load_synthetic()[1]
    return RunConfig(out_dir=out_dir, call_cap=cap, freeze=freeze, audit=audit or audit_for(qs), **kw)


def arms(k_a=2, k_b=4):
    return Registry().bind("A", StubMemory(k=k_a)).bind("B", StubMemory(k=k_b))


def records(out_dir):
    path = os.path.join(out_dir, "state.json")
    state = json.load(open(path)) if os.path.exists(path) else None
    return state, read_jsonl(os.path.join(out_dir, "answers.jsonl")), read_jsonl(os.path.join(out_dir, "calls.jsonl"))
