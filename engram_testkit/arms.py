"""The arm protocol, the A to D registry, the stub memory and the "no memory" floor.

An arm has reset(), ingest(conversation) and retrieve(question, conversation=..., asked_on=...), and
retrieve returns a Retrieval: context text, turn ids and a token count. An arm may say simulated = False
to declare itself a real configuration; an arm that says nothing is treated as simulated.

Slot D is reserved. It is opened at Stage 6 by an explicit change to SLOTS, not by a caller.
"""
import re
from collections import OrderedDict
from dataclasses import dataclass, field

from .formats import estimate_tokens, turn_day


@dataclass(frozen=True)
class Slot:
    key: str
    name: str
    stage: int
    status: str
    contents: str


SLOTS = OrderedDict((s.key, s) for s in (
    Slot("A", "today-search", 4, "defined", "today's search (the control)"),
    Slot("B", "plus-vectors", 4, "defined", "A plus vectors over validated facts"),
    Slot("C", "plus-entity-fusion", 4, "defined", "B plus the entity channel and score fusion with time constraints"),
    Slot("D", "erc-learned", 6, "reserved", "ERC and learned ranking; opened at Stage 6 by an explicit registry change"),
))

FLOOR = "floor"
FLOOR_NAME = "no memory"
FLOOR_CONTENTS = "no memory at all (outside A to D)"


class ReservedSlot(PermissionError):
    """The slot exists but is reserved for a later stage."""


class NotAnArm(TypeError):
    """The object does not have the arm protocol."""


@dataclass
class Retrieval:
    context: str = ""
    turn_ids: list = field(default_factory=list)
    tokens: int = 0


PROTOCOL = ("reset", "ingest", "retrieve")


def is_arm(obj):
    return all(callable(getattr(obj, name, None)) for name in PROTOCOL)


def excerpt(turn):
    """One excerpt line, in the shape the repository's answer prompt expects: date in brackets, speaker, text."""
    line = f"[{turn['date']}] {turn['speaker']}: {turn['text']}"
    if turn.get("caption"):
        line += f" [image: {turn['caption']}]"
    return line


_STOP = frozenset("""a an the of in on at to and or for is are was were be been do does did what which who whom
whose when where why how s her his their my your our its it this that these those with from by as now""".split())


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _STOP


class StubMemory:
    """A tiny fake memory: keeps the turns and returns the k turns sharing most words with the question.

    It is a stub, not a Stage 4 configuration, and it always counts as simulated.
    """
    simulated = True
    stub = True

    def __init__(self, k=3):
        if not isinstance(k, int) or k < 1:
            raise ValueError("k must be a positive whole number")
        self.k = k
        self._turns = OrderedDict()

    def reset(self):
        self._turns = OrderedDict()

    def ingest(self, conversation):
        self._turns[conversation["id"]] = list(conversation["turns"])

    def retrieve(self, question, conversation=None, asked_on=None):
        if conversation is None:
            pool = [t for turns in self._turns.values() for t in turns]
        else:
            pool = list(self._turns.get(conversation, []))
        if asked_on:
            # A turn whose date cannot be read is left out: it cannot be shown to come before asked_on.
            pool = [t for t in pool if (turn_day(t["date"]) or "9999") <= asked_on]
        want = _words(question)
        ranked = []
        for n, t in enumerate(pool):
            hits = len(want & _words(f"{t['speaker']} {t['text']}"))
            if hits:
                ranked.append((hits, n, t))
        top = sorted(ranked, key=lambda r: (-r[0], r[1]))[: self.k]
        top.sort(key=lambda r: r[1])
        context = "\n".join(excerpt(t) for _, _, t in top)
        return Retrieval(context=context, turn_ids=[t["id"] for _, _, t in top], tokens=estimate_tokens(context))


class NoMemory:
    """The floor: no memory at all. It is exactly what it says, so it declares itself real."""
    simulated = False

    def reset(self):
        pass

    def ingest(self, conversation):
        pass

    def retrieve(self, question, conversation=None, asked_on=None):
        return Retrieval(context="", turn_ids=[], tokens=0)


def binding(arm):
    """How an arm is bound, in words for the report."""
    if isinstance(arm, StubMemory):
        return "bound (stub)"
    if isinstance(arm, NoMemory):
        return "bound (no memory)"
    if getattr(arm, "simulated", None) is False:
        return "bound (declared real)"
    return "bound (undeclared, treated as simulated)"


class Registry:
    """Arms bound to slots A to D, plus the optional floor. Reserved slots cannot be bound."""

    def __init__(self):
        self._arms = OrderedDict()

    def bind(self, key, arm):
        if key not in SLOTS:
            raise KeyError(f"unknown slot {key!r}; the slots are {', '.join(SLOTS)}")
        if SLOTS[key].status == "reserved":
            raise ReservedSlot(f"slot {key} is reserved until Stage {SLOTS[key].stage}")
        if not is_arm(arm):
            raise NotAnArm(f"{type(arm).__name__} lacks the arm protocol ({', '.join(PROTOCOL)})")
        if key in self._arms:
            raise ValueError(f"slot {key} is already bound")
        self._arms[key] = arm
        return self

    def bind_floor(self, arm=None):
        arm = NoMemory() if arm is None else arm
        if not is_arm(arm):
            raise NotAnArm(f"{type(arm).__name__} lacks the arm protocol ({', '.join(PROTOCOL)})")
        self._arms[FLOOR] = arm
        return self

    def items(self):
        """Bound arms in slot order, the floor last."""
        order = [k for k in SLOTS if k in self._arms] + ([FLOOR] if FLOOR in self._arms else [])
        return [(k, self._arms[k]) for k in order]

    def keys(self):
        return [k for k, _ in self.items()]

    def __len__(self):
        return len(self._arms)
