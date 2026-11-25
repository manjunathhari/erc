"""The memory interface contract: records, reasons and the abstract interface (section 4 of the r10 specification).

Every record is a frozen dataclass. Bad arguments raise ValueError; an empty result never raises and carries a
reason instead (IF-16).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

# ---- reasons for an empty or unavailable result (section 4.4) ----
E_NO_MEMORY = "nothing is stored yet"
E_NO_MATCH = "nothing stored matches the question"
E_SPEAKER = "nothing stored about this speaker matches the question"
E_NO_SPEAKER = "the question says I or my, but no speaker was given"
E_BUDGET = "matches were found but none fits the token budget"
R_EMPTY_TEXT = "empty text is not stored"
NOT_UNTIL_B8 = "profile is not available until B8 (profile) is built"
NOT_UNTIL_B9 = "feedback is not collected until B9 (feedback collection) is built"
NOT_UNTIL_GATE = "reserved: not available until the Stage 7 gate (deletion and access control)"

ROLES = ("user", "assistant")
VALIDATED, UNCERTAIN = "validated", "uncertain"

# IF-5: the caller passes the budget; the default equals engram_chat.Settings().retrieved_tokens (checked by T59).
DEFAULT_BUDGET = 800


@dataclass(frozen=True)
class Turn:
    speaker: str
    role: str
    text: str
    date: str = ""
    ref: str = ""


@dataclass(frozen=True)
class IngestResult:
    stored: tuple
    reason: str = ""


@dataclass(frozen=True)
class Excerpt:
    excerpt_id: str
    speaker: str
    role: str
    text: str
    date: str = ""
    ref: str = ""


@dataclass(frozen=True)
class Fact:
    fact_id: str
    subject: str
    statement: str
    date: str
    sources: tuple
    status: str = VALIDATED
    uncertain_because: str = ""


@dataclass(frozen=True)
class ProfileResult:
    available: bool
    stable: tuple
    recent: tuple
    reason: str


@dataclass(frozen=True)
class FeedbackResult:
    accepted: bool
    reason: str


@dataclass(frozen=True)
class Unavailable:
    call: str
    reason: str = NOT_UNTIL_GATE
    done: bool = False


@dataclass(frozen=True)
class TraceEntry:
    kind: str                 # "fact" or "excerpt"
    memory_id: str            # the engine's own stable id (IF-6)
    why: str
    matched: tuple
    included: bool
    dropped_because: str = ""


@dataclass(frozen=True)
class AuditTrace:
    trace_id: str
    question: str
    entries: tuple
    empty_reason: str = ""


@dataclass(frozen=True)
class ModelContext:
    trace_id: str
    question: str
    facts: tuple
    excerpts: tuple
    uncertain: tuple
    profile: Any
    tokens: int
    budget: int
    empty_reason: str = ""
    excluded_facts: tuple = ()      # D-A6: matching facts left out because the fact with its sentence did not fit
    omitted_excerpts: tuple = ()    # D-A18: standalone matching excerpts left out for budget
    over_budget: bool = False       # D-A19: an empty E_BUDGET block that does not fit; answer() fails closed

    @property
    def is_empty(self):
        return not (self.facts or self.excerpts or self.uncertain)

    @property
    def omitted_for_budget(self):
        return {"fact": len(self.excluded_facts), "excerpt": len(self.omitted_excerpts)}


@dataclass(frozen=True)
class RetrievalResult:
    context: ModelContext
    trace: AuditTrace


@dataclass(frozen=True)
class AnswerResult:
    text: str
    context: ModelContext
    trace: AuditTrace
    request: dict
    usage: Any
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    seconds: float
    warnings: tuple = ()
    api_version: Optional[str] = None
    sdk_version: Optional[str] = None
    profile_hash: Optional[str] = None


class MemoryInterface(ABC):
    """The seven calls (IF-2). forget and access are reserved and inert until the Stage 7 gate."""

    @abstractmethod
    def ingest(self, turn):
        """Store one turn (IF-3). Returns IngestResult."""

    @abstractmethod
    def retrieve(self, question, budget, speaker=None):
        """Validated context for the question within the token budget. Returns RetrievalResult."""

    @abstractmethod
    def profile(self, speaker):
        """Stable and recent profile (B8). Returns ProfileResult."""

    @abstractmethod
    def feedback(self, trace_id, memory_id, useful):
        """Useful or not, for one memory of one trace (B9). Returns FeedbackResult."""

    @abstractmethod
    def trace(self, trace_id):
        """The kept audit trace, or None."""

    @abstractmethod
    def forget(self, memory_id):
        """Reserved until the Stage 7 gate. Returns Unavailable."""

    @abstractmethod
    def access(self, principal, memory_id):
        """Reserved until the Stage 7 gate. Returns Unavailable."""
