"""Conversation and question formats, with consent and provenance on every conversation.

A conversation is one object: id, optional title, provenance, consent, source and turns. A question
points at one conversation and names its evidence turns. Hand-written sets are JSON lists; run records
are JSONL. The loader accepts both.

Real conversations are refused while no access control exists (the Stage 7 gate).
"""
import datetime
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SYNTHETIC = os.path.join(HERE, "data", "synthetic")

# No access control or deletion exists before the Stage 7 gate. Until it does, real data is refused,
# whatever a caller asks for.
ACCESS_CONTROL_AVAILABLE = False

PROVENANCES = ("synthetic", "benchmark", "real")
ROLES = ("user", "assistant", "other")
CATEGORIES = ("single-hop", "multi-hop", "temporal", "inference", "adversarial", "changed-fact")
NOT_MENTIONED = "not mentioned"

CONVERSATION_FIELDS = ("id", "provenance", "source", "turns")  # consent is checked on its own, below
TURN_FIELDS = ("id", "session", "speaker", "role", "date", "text")
QUESTION_FIELDS = ("id", "conversation", "question", "gold", "evidence", "category")

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}


class FormatError(ValueError):
    """A conversation or question does not follow the format."""


class RealDataRefused(FormatError):
    """A real conversation was offered before access control exists."""


def estimate_tokens(text):
    """About one token per four characters; 0 for empty text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def turn_day(date):
    """The ISO day of a turn date, or None when it cannot be read.

    Accepts ISO dates ("2026-05-10") and LoCoMo session dates ("2:00 pm on 9 June, 2023").
    """
    if not isinstance(date, str):
        return None
    head = date.strip()[:10]
    if _ISO_DAY.match(head):
        return head
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})", date)
    if m and m.group(2).lower() in _MONTHS:
        try:
            return datetime.date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def is_iso_day(value):
    if not isinstance(value, str) or not _ISO_DAY.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _present(obj, field, where):
    if field not in obj or obj[field] is None or obj[field] == "":
        raise FormatError(f"{where}: missing '{field}'")
    return obj[field]


def validate_conversation(c, access_control=False):
    """Check one conversation. Returns it unchanged, or raises FormatError (RealDataRefused for real data)."""
    if not isinstance(c, dict):
        raise FormatError("a conversation must be an object")
    where = f"conversation {c.get('id', '?')!r}"
    for field in CONVERSATION_FIELDS:
        if field not in c:
            raise FormatError(f"{where}: missing '{field}'")
    if not isinstance(c["id"], str) or not c["id"]:
        raise FormatError(f"{where}: 'id' must be a non-empty string")

    prov = c["provenance"]
    if prov not in PROVENANCES:
        raise FormatError(f"{where}: unknown provenance {prov!r}; expected one of {', '.join(PROVENANCES)}")
    # Both must hold: the caller asks for it, and access control actually exists. Neither alone is enough.
    if prov == "real":
        allowed = access_control is True and ACCESS_CONTROL_AVAILABLE is True
        if not allowed:
            raise RealDataRefused(f"{where}: real conversations are refused until access control and "
                                  "deletion pass the Stage 7 gate")

    consent = c.get("consent")
    if not isinstance(consent, dict) or not isinstance(consent.get("basis"), str) or not consent["basis"].strip():
        raise FormatError(f"{where}: consent must be an object with a non-empty 'basis'")

    source = c["source"]
    if not isinstance(source, dict) or not source.get("kind"):
        raise FormatError(f"{where}: source must be an object with 'kind' and 'pointer'")
    if not source.get("pointer"):
        raise FormatError(f"{where}: source needs a 'pointer' to the original")

    turns = c["turns"]
    if not isinstance(turns, list) or not turns:
        raise FormatError(f"{where}: 'turns' must be a non-empty list")
    seen = set()
    for n, t in enumerate(turns):
        if not isinstance(t, dict):
            raise FormatError(f"{where}, turn {n}: a turn must be an object")
        tw = f"{where}, turn {t.get('id', n)!r}"
        for field in TURN_FIELDS:
            _present(t, field, tw)
        if t["role"] not in ROLES:
            raise FormatError(f"{tw}: unknown role {t['role']!r}; expected one of {', '.join(ROLES)}")
        if not isinstance(t["text"], str):
            raise FormatError(f"{tw}: 'text' must be a string")
        if t["id"] in seen:
            raise FormatError(f"{tw}: duplicate turn id")
        seen.add(t["id"])
        if "source" in t and (not isinstance(t["source"], str) or not t["source"]):
            raise FormatError(f"{tw}: a turn's own source must be a non-empty pointer string")
    return c


def validate_question(q, conversations):
    """Check one question against the conversations it may point at. Returns it, or raises FormatError."""
    if not isinstance(q, dict):
        raise FormatError("a question must be an object")
    where = f"question {q.get('id', '?')!r}"
    for field in QUESTION_FIELDS:
        if field not in q or q[field] is None:
            raise FormatError(f"{where}: missing '{field}'")
    if q["conversation"] not in conversations:
        raise FormatError(f"{where}: unknown conversation {q['conversation']!r}")
    conv = conversations[q["conversation"]]
    cat = q["category"]
    if cat not in CATEGORIES:
        raise FormatError(f"{where}: unknown category {cat!r}; expected one of {', '.join(CATEGORIES)}")
    if not isinstance(q["question"], str) or not q["question"].strip():
        raise FormatError(f"{where}: 'question' must be non-empty text")
    if not isinstance(q["gold"], str) or not q["gold"].strip():
        raise FormatError(f"{where}: 'gold' must be non-empty text")

    ev = q["evidence"]
    if not isinstance(ev, list):
        raise FormatError(f"{where}: 'evidence' must be a list of turn ids")
    turn_ids = {t["id"] for t in conv.get("turns", [])}
    stray = [e for e in ev if e not in turn_ids]
    if stray:
        raise FormatError(f"{where}: evidence {stray} are not turns of conversation {q['conversation']!r}")
    if not ev and cat != "adversarial":
        raise FormatError(f"{where}: evidence may be empty only for adversarial questions")
    if cat == "adversarial" and q["gold"].strip().lower() != NOT_MENTIONED:
        raise FormatError(f"{where}: an adversarial gold answer must be '{NOT_MENTIONED}'")
    if cat == "changed-fact" and len(set(ev)) < 2:
        raise FormatError(f"{where}: a changed-fact question must name at least the earlier and the later turn")

    if "asked_on" in q and q["asked_on"] is not None:
        if not is_iso_day(q["asked_on"]):
            raise FormatError(f"{where}: asked_on must be an ISO date (YYYY-MM-DD), not {q['asked_on']!r}")
    elif conv.get("provenance") == "real":
        raise FormatError(f"{where}: asked_on is required for questions on real conversations")
    return q


def read_records(path):
    """Read a JSON list (or one object) or a JSONL file into a list of objects."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    body = text.strip()
    if not body:
        return []
    if body[0] == "[":
        data = json.loads(body)
        if not isinstance(data, list):
            raise FormatError(f"{path}: expected a JSON list")
        return data
    if not path.endswith(".jsonl"):
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return [data]
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise FormatError(f"{path}, line {n}: not JSON ({e})") from None
    return out


def build_set(conv_records, question_records, access_control=False):
    """Validate conversations and questions. Any real conversation stops the whole load."""
    convs = {}
    for c in conv_records:
        validate_conversation(c, access_control=access_control)
        if c["id"] in convs:
            raise FormatError(f"duplicate conversation id {c['id']!r}")
        convs[c["id"]] = c
    qs, seen = [], set()
    for q in question_records:
        validate_question(q, convs)
        if q["id"] in seen:
            raise FormatError(f"duplicate question id {q['id']!r}")
        seen.add(q["id"])
        qs.append(q)
    return convs, qs


def load_set(conversations_path, questions_path, access_control=False):
    """Load and check a conversation file and a question file (JSON or JSONL). Returns (conversations by id, questions)."""
    return build_set(read_records(conversations_path), read_records(questions_path), access_control=access_control)


def load_synthetic():
    """The invented synthetic set shipped with the kit: three conversations, thirteen questions."""
    return load_set(os.path.join(SYNTHETIC, "conversations.json"), os.path.join(SYNTHETIC, "questions.json"))
