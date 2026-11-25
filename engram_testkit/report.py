"""The run report, in Markdown. While the run is simulated, the label is in the title, the first paragraph
and the last line, whatever title the caller gives."""
from .arms import FLOOR, FLOOR_CONTENTS, FLOOR_NAME, SLOTS
from .label import LABEL, LabelMissing

DEFAULT_TITLE = "Engram Comparative Conversation Test Kit: run report"


def _f(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.1f}" if abs(v) >= 0.1 or v == 0 else f"{v:.4f}"
    return str(v)


def _blind(v):
    return "pending" if v is None else _f(v)


def _run_value(d, n):
    """Per-run figures may have int keys (in memory) or string keys (read back from summary.json)."""
    if not d:
        return None
    return d.get(n, d.get(str(n)))


def _score_rows(name, part, runs):
    cells = [name, _f(part["questions"])]
    cells += [_blind(_run_value(part.get("strict_blind"), n)) for n in runs]
    cells += [_f(_run_value(part["strict"], n)) for n in runs]
    cells += [_f(_run_value(part["generous"], n)) for n in runs]
    cells += [_f(part["runs_agree"])]
    return "| " + " | ".join(cells) + " |"


def markdown(summary, state, title=None, notes=None):
    """The report for a summary and its run state. Notes, if given, are listed under "Limitations"."""
    state = state or {}
    # A state without the flag, or a summary that does not say otherwise, counts as simulated.
    simulated = not (state.get("simulated", True) is False and summary.get("simulated", True) is False)
    if simulated and summary.get("label") != LABEL:
        raise LabelMissing("the summary of a simulated run must carry the label")
    runs = list(range(1, int(summary.get("runs") or state.get("runs") or 2) + 1))
    head = title or DEFAULT_TITLE
    lines = [f"# {head}" + (f": {LABEL}" if simulated else ""), ""]

    status = "finished" if summary.get("finished") else f"stopped ({state.get('reason', 'reason not saved')})"
    first = (f"Run {status}. {summary.get('complete_questions')} questions complete in every arm and run. "
             f"Answer model {state.get('answer_model', summary.get('answer_model'))}; "
             f"judge model {state.get('judge_model', summary.get('judge_model'))}.")
    if simulated:
        first = (f"**{LABEL}.** At least one arm is bound to the stub memory or has not declared itself a real "
                 "configuration, so no figure here compares the Stage 4 configurations or says anything about Engram. "
                 + first)
    lines += [first, ""]

    bindings = state.get("bindings", {})
    lines += ["## Arms", "", "| Slot | Name | Stage | Status | Contents | In this run |", "|---|---|---|---|---|---|"]
    for k, s in SLOTS.items():
        here = bindings.get(k, "binding refused" if s.status == "reserved" else "not bound")
        lines.append(f"| {k} | {s.name} | {s.stage} | {s.status} | {s.contents} | {here} |")
    lines.append(f"| {FLOOR} | {FLOOR_NAME} | - | outside A to D | {FLOOR_CONTENTS} | {bindings.get(FLOOR, 'not bound')} |")
    lines.append("")

    cols = (["Arm", "Questions"] + [f"Blinded strict run {n}" for n in runs]
            + [f"Strict run {n} (gold-word rule)" for n in runs] + [f"Generous run {n}" for n in runs] + ["Runs agree"])
    lines += ["## Scores (per cent)", "",
              "Blinded strict labels are the reported figure; they say pending until labels are given. "
              "The gold-word rule (every content word of the gold answer, never \"not mentioned\") is the floor. "
              "Generous labels come from the judge. Adversarial questions are scored by the fixed rule only.", "",
              "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for k, part in summary["arms"].items():
        lines.append(_score_rows(k, part, runs))
    lines.append("")
    if summary.get("floor"):
        lines += ["Floor (no memory, outside A to D):", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols),
                  _score_rows(FLOOR, summary["floor"], runs), ""]

    parts = dict(summary["arms"], **({FLOOR: summary["floor"]} if summary.get("floor") else {}))
    cats = sorted({c for p in parts.values() for c in p["by_category"]})
    if cats:
        lines += ["## By category (gold-word rule, both runs, per cent)", "",
                  "Evidence found is the mean share of a question's evidence turns that the arm retrieved "
                  "(adversarial questions left out).", "",
                  "| Arm | " + " | ".join(cats) + " | Evidence found |", "|" + "---|" * (len(cats) + 2)]
        for k, p in parts.items():
            lines.append(f"| {k} | " + " | ".join(_f(p["by_category"].get(c)) for c in cats)
                         + f" | {_f(p['evidence_found'])} |")
        lines.append("")

    lines += ["## Against arm A", "",
              "Paired by question and run, gold-word rule, bootstrap 95 % interval.", "",
              "| Arm | Pairs | Points (arm minus A) | 95 % interval | Seed |", "|---|---|---|---|---|"]
    for k, v in (summary.get("vs_A") or {}).items():
        low, high = v["interval_95"]
        lines.append(f"| {k} | {v['pairs']} | {_f(v['points'])} | {_f(low)} to {_f(high)} | {v['seed']} |")
    if not summary.get("vs_A"):
        lines.append("| - | - | arm A not in this run | - | - |")
    lines.append("")

    lines += ["## Latency and token cost", "",
              "Seconds and tokens per arm. Tokens are as reported by the callable where given, else estimated "
              "(one per four characters).", "",
              "| Arm | Ingest s | Mean retrieval s | Mean answer-call s | Mean context tokens | Mean answer-call tokens "
              "| Tokens, all calls | Calls | Failed calls |", "|---|---|---|---|---|---|---|---|---|"]
    for k, p in parts.items():
        lines.append(f"| {k} | {_f(p['ingest_secs'])} | {_f(p['retrieve_secs'])} | {_f(p['answer_secs'])} | "
                     f"{_f(p['context_tokens'])} | {_f(p['answer_tokens'])} | {_f(p['tokens_all_calls'])} | "
                     f"{p['calls']} | {p['failed_calls']} |")
    lines.append("")

    settings = summary.get("call_settings") or {}
    if settings:
        lines += ["## Call settings used", "",
                  "Each callable reports the settings it actually used; a call that differs from the freeze, or reports "
                  "none, is saved as failed and stops the run. Every call's requested and used settings are in calls.jsonl.", "",
                  "| Call | Calls | Reported settings | Matching the freeze | Settings used |", "|---|---|---|---|---|"]
        for kind, s in settings.items():
            used = "; ".join(", ".join(f"{k} {v}" for k, v in e.items()) for e in s["effective"]) or "-"
            lines.append(f"| {kind} | {s['calls']} | {s['reported']} | {s['matching_freeze']} | {used} |")
        lines.append("")
    if notes:
        lines += ["## Limitations", ""] + [f"- {n}" for n in notes] + [""]

    audit = state.get("audit") or {}
    lines += ["## Run", "",
              f"- Calls used: {state.get('calls_used')} of a cap of {state.get('call_cap')}; sessions: {state.get('sessions')}.",
              f"- Stopped: {state.get('stopped')}; reason: {state.get('reason')}.",
              f"- Freeze: {state.get('freeze')}.",
              f"- Gold-answer audit: {audit.get('auditor')}, {audit.get('date')}; dropped: {audit.get('dropped') or 'none'}.",
              f"- Question set SHA-256: {summary.get('question_set')}.", ""]
    if simulated:
        lines.append(f"Label: {LABEL}.")
    return "\n".join(lines).rstrip() + "\n"
