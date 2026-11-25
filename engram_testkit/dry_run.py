"""The no-key dry run: the synthetic set, stub arms A to C plus the floor, and a fake answer and judge.

It shows only that the pipeline runs. Its figures say nothing about Engram: simulated arms (stub), not a
Stage 4 comparison.

  python -m engram_testkit.dry_run OUT_DIR      (OUT_DIR outside any git repository)
"""
import datetime
import json
import os
import re
import sys

from . import report
from .arms import Registry, StubMemory
from .audit import make_audit
from .formats import estimate_tokens, load_synthetic
from .runner import NO_EXCERPTS, RunConfig, cap_for, read_jsonl, run
from .scoring import strict, summarise, write_sheet, write_summary

TITLE = "Engram Comparative Conversation Test Kit: dry run (synthetic set, fake answer and judge)"

# Stated on the dry run's report and summary (his ruling, 25 Nov 2026).
LIMITATIONS = [
    "The dry-run scores show only that the pipeline runs. They come from stub arms and fake answer and judge "
    "callables, and they cannot compare memory configurations.",
    "LoCoMo image-caption handling (kept as a separate caption field, shown as [image: ...] in the excerpt) has not "
    "been checked on the real LoCoMo dataset, which is kept outside the repository and was not used here.",
    "Neither point authorises opening the held-out LoCoMo conversations 5 to 9 or using real personal conversations.",
]


def _excerpts(prompt):
    m = re.search(r"Excerpts:\n(.*?)\n\nQuestion: (.*?)\n", prompt, re.S)
    return (m.group(1), m.group(2)) if m else ("", "")


_STOP = frozenset("a an the of in on at to and or for is are was what which who when where how did does do s her his".split())


class FakeAnswer:
    """A fake answer callable, labelled as fake. It replies with the excerpt sharing most words with the
    question (at least two), or "not mentioned" when none does. No model, no network."""
    model = "fake-answer-1"
    min_shared = 2

    def __call__(self, prompt, max_tokens=60, temperature=None, reasoning=None):
        ctx, question = _excerpts(prompt)
        want = set(re.findall(r"[a-z0-9]+", question.lower())) - _STOP
        best, hits = None, self.min_shared - 1
        for line in ctx.splitlines():
            if line.strip() == NO_EXCERPTS:
                continue
            body = line.split(": ", 1)[-1]
            n = len(want & set(re.findall(r"[a-z0-9]+", line.lower())))
            if n > hits:
                best, hits = body, n
        text = best if best is not None else "not mentioned"
        text = " ".join(text.split()[: max(1, max_tokens)])
        used = dict(model=self.model, max_tokens=max_tokens, temperature=temperature, reasoning=reasoning)
        return text, dict(prompt_tokens=estimate_tokens(prompt), completion_tokens=estimate_tokens(text), effective=used), 0.0


class FakeJudge:
    """A fake judge callable, labelled as fake: CORRECT when the gold-word rule holds, else WRONG."""
    model = "fake-judge-1"

    def __call__(self, prompt, max_tokens=16, temperature=None, reasoning=None):
        gold = re.search(r"Gold answer: (.*)\n", prompt)
        pred = re.search(r"Generated answer: (.*)\n", prompt)
        ok = bool(gold and pred) and strict(pred.group(1), gold.group(1))
        text = "CORRECT" if ok else "WRONG"
        used = dict(model=self.model, max_tokens=max_tokens, temperature=temperature, reasoning=reasoning)
        return text, dict(prompt_tokens=estimate_tokens(prompt), completion_tokens=1, effective=used), 0.0


def dry_freeze():
    return dict(answer=dict(model=FakeAnswer.model, max_tokens=60, temperature=0, reasoning="none (fake callable)"),
                judge=dict(model=FakeJudge.model, max_tokens=16, temperature=0, reasoning="none (fake callable)"))


def dry_registry():
    return Registry().bind("A", StubMemory(k=2)).bind("B", StubMemory(k=3)).bind("C", StubMemory(k=4)).bind_floor()


def dry_run(out_dir, title=TITLE):
    """Run the dry run into out_dir. Returns (state, summary, report text). Writes state.json, answers.jsonl,
    calls.jsonl, summary.json, sheet.jsonl with its key and header, and report.md."""
    convs, qs = load_synthetic()
    registry = dry_registry()
    audit = make_audit(qs, auditor="dry run: synthetic set, gold set by construction",
                       date=datetime.date.today().isoformat())
    config = RunConfig(out_dir=out_dir, call_cap=cap_for(len(registry), len(qs)), freeze=dry_freeze(), audit=audit)
    state = run(registry, convs, qs, FakeAnswer(), FakeJudge(), config)
    rows = read_jsonl(os.path.join(out_dir, "answers.jsonl"))
    calls = read_jsonl(os.path.join(out_dir, "calls.jsonl"))
    summary = summarise(rows, calls, config.runs, finished=not state["stopped"], state=state)
    summary["limitations"] = list(LIMITATIONS)
    write_summary(summary, os.path.join(out_dir, "summary.json"))
    write_sheet(summary, os.path.join(out_dir, "sheet.jsonl"))
    text = report.markdown(summary, state, title=title, notes=LIMITATIONS)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    return state, summary, text


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip())
        return 2
    state, summary, _ = dry_run(argv[0])
    print(json.dumps(dict(stopped=state["stopped"], calls_used=state["calls_used"], call_cap=state["call_cap"],
                          complete_questions=summary["complete_questions"], label=state.get("label")), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
