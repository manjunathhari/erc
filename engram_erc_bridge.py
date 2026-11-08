"""Engram -> ERC bridge: typed memory records, an ERC knowledge graph over them, and a profile for the answer model.

Engram (frozen as Engram base 1) finds and keeps the raw record. This bridge adds the structure layer:

1. At chat close a writer model reads what the USER said in the chat and returns typed records
   (preference, event, state), each with a category from a fixed taxonomy, a date when one is given,
   and the ids of the source lines. Records are cached per chat, so they are written once.
2. The records become ERC objects: one Proposition per record (subject, predicate, object, polarity, valid
   time, source refs) and one KnowledgeNode per record, linked by IS_A edges to category nodes. ERC's own
   contradiction finder marks older states superseded by newer ones on the same topic.
3. For a question, the current preference records are ranked against the question and shown first, as a
   short profile, within a token budget; the raw Engram excerpts fill the rest of the same total budget.

The bridge registers its own ERC DomainProfile ("engram-memory") and does not change ERC core or Engram base 1.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from engram_erc.contracts import Proposition, TimeInterval
from engram_erc.knowledge_graph import (
    DomainKnowledgeGraph, KnowledgeEdge, KnowledgeNode, KnowledgeNodeKind, KnowledgeRelation, build_knowledge_graph,
)
from engram_erc.lifecycle import EvidenceClass
from engram_erc.primitives.contradiction import find_contradictions
from engram_erc.profiles import DomainProfile, get_profile, register_profile

# ---------- taxonomy and the memory profile ----------
TAXONOMY = (
    "food and drink", "cooking and baking", "home and furniture", "garden and plants", "travel and places",
    "films, TV and books", "music", "games", "sport and fitness", "health and wellbeing", "technology and devices",
    "work and career", "study and learning", "money and shopping", "family and friends", "pets",
    "hobbies and crafts", "events and celebrations", "vehicles and transport", "other",
)
RECORD_TYPES = {"preference": KnowledgeNodeKind.CONCEPT, "event": KnowledgeNodeKind.EVENT, "state": KnowledgeNodeKind.ENTITY}
# States are functional: a newer state on the same topic replaces an older one ("owns 3 bikes" -> "owns 4 bikes").
FUNCTIONAL_TYPES = ("state",)


def _memory_profile() -> DomainProfile:
    try:
        return get_profile("engram-memory")
    except Exception:
        return register_profile(DomainProfile(
            profile_id="engram-memory", version="1.0.0",
            case_label="conversation", activity_label="chat", practitioner_label="user", reviewer_label="reviewer",
            exclusion_label="excluded", adverse_event_label="error",
            evidence_classes={cls.value: cls for cls in EvidenceClass},
            node_subtypes={"preference": KnowledgeNodeKind.CONCEPT, "event": KnowledgeNodeKind.EVENT,
                           "state": KnowledgeNodeKind.ENTITY, "category": KnowledgeNodeKind.CONTEXT},
            value_labels={},
        ))


MEMORY_PROFILE = _memory_profile()

# ---------- the writer ----------
WRITER_PROMPT = """You read the user's side of one past conversation with an assistant, dated {date}. Write down what the USER says about themselves that could matter in later conversations: their tastes, habits, plans, possessions, circumstances and things they did. Ignore general questions and knowledge; the assistant's replies are not shown.

Return a JSON object {{"records": [...]}}. Each record has:
- "type": "preference" (likes, dislikes, tastes, habits, goals, values, ways they like things done), "event" (something they did or that happened to them) or "state" (something they have, are or plan: possessions, roles, counts, plans, situations);
- "about": the topic in one to three words (e.g. "coffee creamer", "bedroom dresser", "commute");
- "text": one short self-contained sentence about the user, keeping names, numbers and specifics (e.g. "Likes mid-century modern furniture and plans to replace the bedroom dresser");
- "category": exactly one of: {taxonomy};
- "date": when it happened or became true, as YYYY-MM-DD, if the conversation says or implies it (work out "last week" from {date}); otherwise null;
- "polarity": false only when the user says they no longer like, have or do something; otherwise true;
- "lines": the ids of the lines it comes from.
Write at most 12 records, the most useful first. If the user says nothing about themselves, return {{"records": []}}.

Lines:
{lines}"""


def writer_prompt(lines: Iterable[tuple[str, str]], date: str) -> str:
    """lines: (line_id, text) for the user's sentences in one chat."""
    body = "\n".join(f"{i} {t}" for i, t in lines)
    return WRITER_PROMPT.format(date=date, taxonomy="; ".join(TAXONOMY), lines=body)


_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_records(reply: str, chat_date: str, valid_lines: set[str] | None = None) -> list[dict]:
    """Writer reply -> clean records. Bad fields are repaired or the record dropped; never raises on bad JSON."""
    try:
        m = re.search(r"\{.*\}", reply or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except (ValueError, AttributeError):
        return []
    out = []
    for r in data.get("records", []) if isinstance(data, dict) else []:
        if not isinstance(r, dict): continue
        kind = str(r.get("type", "")).strip().lower()
        text = str(r.get("text", "")).strip()
        if kind not in RECORD_TYPES or not text: continue
        about = str(r.get("about", "")).strip().lower()[:60] or text.lower()[:40]
        cat = str(r.get("category", "other")).strip().lower()
        cat = next((c for c in TAXONOMY if c == cat), next((c for c in TAXONOMY if cat and cat.split()[0] in c), "other"))
        date = str(r.get("date") or "").strip()
        date = date if _DATE.match(date) else None
        lines = [str(x) for x in r.get("lines", []) if str(x).strip()]
        if valid_lines is not None: lines = [x for x in lines if x in valid_lines]
        out.append(dict(type=kind, about=about, text=text[:300], category=cat, date=date, said_on=chat_date,
                        polarity=r.get("polarity") is not False, lines=sorted(set(lines))))
    return out[:12]


# ---------- records -> ERC ----------
def _when(day: str | None) -> datetime | None:
    if not day: return None
    try:
        return datetime.strptime(day[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass(frozen=True)
class MemoryState:
    graph: DomainKnowledgeGraph
    records: dict[str, dict]           # record id -> record
    superseded: dict[str, str]         # record id -> id of the newer record that replaced it


def build_memory_state(records_by_chat: dict[str, list[dict]]) -> MemoryState:
    """records_by_chat: chat key -> parsed records (in chat order). Builds the ERC graph and runs ERC's contradiction finder."""
    records, props = {}, []
    nodes, edges, cats = [], [], {}
    for chat, rows in records_by_chat.items():
        for n, r in enumerate(rows):
            rid = f"{chat}#{n}"
            records[rid] = r
            when = _when(r.get("date")) or _when(r.get("said_on"))
            refs = tuple(r.get("lines") or [chat])
            props.append(Proposition(
                id=rid, subject="user", predicate=f"{r['type']}:{r['about']}", object_value=r["text"],
                polarity=bool(r.get("polarity", True)), source_refs=refs,
                valid_time=TimeInterval(start=when) if when else None))
            cat = r["category"]
            if cat not in cats:
                cats[cat] = f"category:{cat}"
                nodes.append(KnowledgeNode(node_ref=cats[cat], kind=KnowledgeNodeKind.CONTEXT, label=cat, domain="memory",
                                           source_refs=("taxonomy",), provenance_ref="engram_erc_bridge.TAXONOMY", subtype="category"))
            attrs = tuple((k, str(v)) for k, v in (("about", r["about"]), ("date", r.get("date") or ""), ("said_on", r.get("said_on") or "")) if str(v).strip())
            nodes.append(KnowledgeNode(node_ref=rid, kind=RECORD_TYPES[r["type"]], label=r["text"], domain="memory",
                                       source_refs=refs, provenance_ref=f"chat:{chat}", attributes=attrs, subtype=r["type"]))
            edges.append(KnowledgeEdge(edge_ref=f"{rid}->is_a", source_ref=rid, target_ref=cats[cat], relation=KnowledgeRelation.IS_A,
                                       source_refs=refs, provenance_ref="writer"))
    graph = build_knowledge_graph(nodes, edges)
    functional = frozenset(p.predicate for p in props if p.predicate.split(":", 1)[0] in FUNCTIONAL_TYPES)
    superseded = {}
    by_id = {p.id: p for p in props}
    for c in find_contradictions(props, functional_predicates=functional):
        a, b = by_id[c.left_id], by_id[c.right_id]
        ta = a.valid_time.start if a.valid_time and a.valid_time.start else None
        tb = b.valid_time.start if b.valid_time and b.valid_time.start else None
        if ta is None or tb is None or ta == tb: continue
        old, new = (a, b) if ta < tb else (b, a)
        superseded[old.id] = new.id
    return MemoryState(graph=graph, records=records, superseded=superseded)


# ---------- ERC -> context ----------
def count_tokens(text: str) -> int:
    return max(1, len(text) // 4)  # same rule as engram_chat.count_tokens


def _overlap_scores(question: str, texts: list[str]) -> list[float]:
    words = lambda s: {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}
    q = words(question)
    return [len(q & words(t)) / (1 + len(words(t))) ** 0.5 for t in texts]


def make_scorer() -> Callable[[str, list[str]], list[float]]:
    """Cosine similarity with WordLlama when it loads (as on Kaggle); word overlap otherwise."""
    try:
        import numpy as np
        from wordllama import WordLlama
        wl = WordLlama.load()

        def score(question, texts):
            if not texts: return []
            v = np.asarray(wl.embed([question] + texts), dtype=np.float32)
            v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-9
            return list(map(float, v[1:] @ v[0]))
        score("test", ["test"])
        return score
    except Exception:
        return _overlap_scores


def profile_section(state: MemoryState, question: str, budget: int, scorer=_overlap_scores,
                    types: tuple[str, ...] = ("preference",)) -> str:
    """Current records of the given types, most relevant to the question first, within `budget` tokens."""
    rows = [(rid, r) for rid, r in state.records.items() if r["type"] in types and rid not in state.superseded and r.get("polarity", True)]
    if not rows or budget <= 0: return ""
    texts = [f"{r['category']}: {r['about']}. {r['text']}" for _, r in rows]
    ranked = sorted(zip(scorer(question, texts), range(len(rows))), key=lambda x: (-x[0], x[1]))
    head = "[What the user has said about themselves in past chats: tastes, habits and plans, most relevant first]"
    out, used = [head], count_tokens(head)
    for _, i in ranked:
        r = rows[i][1]
        line = f"- ({r.get('date') or r.get('said_on')}; {r['category']}) {r['text']}"
        t = count_tokens(line)
        if used + t > budget: continue
        out.append(line); used += t
    return "\n".join(out) if len(out) > 1 else ""


__all__ = ["TAXONOMY", "MEMORY_PROFILE", "WRITER_PROMPT", "writer_prompt", "parse_records", "MemoryState",
           "build_memory_state", "profile_section", "make_scorer", "count_tokens"]
