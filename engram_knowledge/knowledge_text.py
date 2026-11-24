"""Increment 6: the knowledge store's answer to a question, as text a model can read, or the reason there is none.

Read-only. Built on KnowledgeRetriever, which is given a view of the memory with two members only: `db`, the memory's own
connection, and `find`, a stub that returns nothing at once, so no ordinary-memory search is performed (P6). The ordinary
memory stays with the caller (Q3, Q4a). Specification: Increment 6 Specification Draft 6 as amended by Amendment 1.
"""
from engram_chat import count_tokens

from .evidence_assembler import LABELS
from .knowledge_retriever import KnowledgeRetriever
from .normalizer import tokens

HEAD = "[Records from the knowledge store: each fact with the original sentences behind it]"

R1 = "the question is not about a stored kind of fact"
R2 = "a name in the question belongs to more than one known entity"
R3 = "the question names more than one known entity"
R4 = "the question names both the supplied speaker and another known entity"
R5 = "no known entity is named"
R6 = "the kind of fact asked about is not one the router knows"
R8 = "the supplied speaker is not one known entity"
R9 = "the records did not fit the budget"
R10 = "the question is in the first person and names another known entity"
R11 = "no record has a supporting sentence to show"

FIRST_PERSON = frozenset({"i", "me"})       # Q3a: "my" and "mine" are not mapped; "I'm" reads as "im" and is not "i" (P4)
CASE_REASON = dict(shared_name=R2, several_named=R3)
SHOWN_ROLES = ("supports", "qualifies")     # a contradicting sentence is not shown (P5)


class _MemoryView:
    """What the retriever may use of the memory: its connection, and a search that searches nothing (P6)."""

    def __init__(self, db):
        self.db = db

    def find(self, question):
        return [], {}


def knowledge_section(memory, question, budget, speaker=None):
    """(text, tokens, reason): exactly one of text and reason is non-empty; tokens counts text, 0 with a reason."""
    retriever = KnowledgeRetriever(_MemoryView(memory.db))
    kind = retriever.router.classify(question)
    if kind == "general_memory": return _none(R1)
    first_person = bool(FIRST_PERSON & set(tokens(question)))
    named, case = retriever.find_entity(question, report=True)
    if first_person and speaker is not None:
        own = retriever.kb.resolve(speaker)
        if own is None: return _none(R8)
        if case != "none" and not (case == "one" and named == own): return _none(R4)
        entity = own
    elif first_person:
        return _none(R5 if case == "none" else R10)
    elif case == "one":
        entity = named
    else:
        return _none(R5 if case == "none" else CASE_REASON[case])
    if retriever.router.slot(question) is None and kind != "conflict": return _none(R6)
    result = retriever.retrieve(question, entity_id=entity)
    if not result["facts"]: return _none(result["note"])
    who = retriever.kb.entity(entity)
    waiting = bool(result.get("waiting_review"))
    facts = [_prepared(f) for f in result["facts"]]
    facts = [f for f in facts if any(s["role"] == "supports" for s in f["sentences"])]
    if not facts: return _none(R11)
    shown = []
    for f in facts:                                   # each tentative addition rendered in full and counted
        if count_tokens(_render(who, shown + [f], waiting)) <= budget: shown.append(f)
    if not shown: return _none(R9)
    text = _render(who, shown, waiting)
    return text, count_tokens(text), ""


def _none(reason):
    return "", 0, reason


def _prepared(f):
    """The fact with its shown sentences in their order: supporting sentences, then name lines, each in sentence order."""
    lines = [s for s in f["sentences"] if s["role"] in SHOWN_ROLES]
    return dict(f, sentences=sorted(lines, key=lambda s: (SHOWN_ROLES.index(s["role"]), s["sid"])))


def _period(f, waiting):
    start = f"from {f['valid_from']}" if f["valid_from"] else \
        f"start not stated; first said {f['first_said']}" if f["first_said"] else "start not stated"
    parts = [start, f"to {f['valid_to']}" if f["valid_to"] else "still held"]
    if f["conflict"]: parts.append("sources disagree")
    if waiting: parts.append("newer statements may be waiting for review")
    return "; ".join(parts)


def _render(who, facts, waiting):
    first_at, later = {}, {}
    for n, f in enumerate(facts, 1):
        for s in f["sentences"]: first_at.setdefault(s["sid"], n)
    for n, f in enumerate(facts, 1):
        for s in f["sentences"]:
            if first_at[s["sid"]] != n: later.setdefault(s["sid"], dict(supports=[], qualifies=[]))[s["role"]].append(n)
    lines = [HEAD]
    for n, f in enumerate(facts, 1):
        lines.append(f"[{n}] {who.canonical_name} ({who.entity_type}) — {LABELS.get(f['slot'], f['slot'])}: {f['value']} ({_period(f, waiting)})")
        for s in f["sentences"]:
            supports = s["role"] == "supports"
            if first_at[s["sid"]] != n:               # shown in full under an earlier fact: point back, in this fact's role
                lines.append(f"  {'said' if supports else 'name line'}: see [{first_at[s['sid']]}]")
                continue
            line = f"  said {s['date']}, {s['speaker']}: {s['text']}" if supports else f"  name line, {s['date']}, {s['speaker']}: {s['text']}"
            also = later.get(s["sid"], {})
            if also.get("supports"): line += " (also supports " + ", ".join(f"[{k}]" for k in also["supports"]) + ")"
            if also.get("qualifies"): line += " (also the name line for " + ", ".join(f"[{k}]" for k in also["qualifies"]) + ")"
            lines.append(line)
    return "\n".join(lines)
