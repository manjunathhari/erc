"""The rendered memory block shared by both adapters (section 4.5), and token counting (IF-5)."""

HEADER = "MEMORY (from Engram; use only what is supported here)"
NOTICE = ("Some matching memories were omitted to fit the memory budget. The supplied evidence may therefore be "
          "incomplete; do not infer the omitted content.")
NONE_LINE = "- none"


def count_tokens(text):
    """The engine's count (engram_chat.count_tokens), copied so the package needs nothing outside itself. T59 checks
    that the two agree."""
    return max(1, len(text) // 4)


def _date(value):
    return value if value else "undated"


def _fact_line(f):
    line = f"- [{f.fact_id}] ({_date(f.date)}) {f.subject}: {f.statement} (sources: {', '.join(f.sources)})"
    if f.status != "validated":
        line += f" (uncertain: {f.uncertain_because or 'not stated'})"
    return line


def _excerpt_line(e):
    return f'- [{e.excerpt_id}] ({_date(e.date)}) {e.speaker} ({e.role}): "{e.text}"'


def _profile_line(p):
    if p is None or not getattr(p, "available", False):
        return f"- not available: {getattr(p, 'reason', '') or 'no profile'}"
    parts = [f"stable: {'; '.join(p.stable) or 'none'}", f"recent: {'; '.join(p.recent) or 'none'}"]
    return "- " + " | ".join(parts)


def render_context(ctx, notice=None):
    """One block for the model. The budget-exclusion notice is the last line if and only if matching evidence was
    omitted for budget (D-A13, D-A18); `notice` forces it on or off, which the stub uses to reserve its space."""
    with_notice = bool(ctx.excluded_facts or ctx.omitted_excerpts) if notice is None else bool(notice)
    if ctx.is_empty:
        lines = [f"MEMORY: nothing given. Reason: {ctx.empty_reason}"]
    else:
        lines = [HEADER, "Validated facts:"]
        lines += [_fact_line(f) for f in ctx.facts] or [NONE_LINE]
        lines.append("Original excerpts:")
        lines += [_excerpt_line(e) for e in ctx.excerpts] or [NONE_LINE]
        lines.append("Uncertain:")
        lines += [_fact_line(f) for f in ctx.uncertain] or [NONE_LINE]
        lines += ["Profile:", _profile_line(ctx.profile)]
    if with_notice:
        lines.append(NOTICE)
    return "\n".join(lines)
