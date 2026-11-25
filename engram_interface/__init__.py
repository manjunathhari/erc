"""engram_interface: one memory interface for any answering model, with Claude and OpenAI adapters (B10, track P-A).

Built against the frozen tests-first package, revision 10. The memory behind the interface is a stub, not Engram
(D-A5); profile (B8) and feedback (B9) are declared only; forget and access are reserved until the Stage 7 gate.
Importing this package imports neither SDK (D-A3).
"""
from .contract import (Turn, IngestResult, Excerpt, Fact, ProfileResult, FeedbackResult, Unavailable, TraceEntry,
                       AuditTrace, ModelContext, RetrievalResult, AnswerResult, MemoryInterface, DEFAULT_BUDGET,
                       E_NO_MEMORY, E_NO_MATCH, E_SPEAKER, E_NO_SPEAKER, E_BUDGET, R_EMPTY_TEXT,
                       NOT_UNTIL_B8, NOT_UNTIL_B9, NOT_UNTIL_GATE)
from .render import render_context, count_tokens, NOTICE
from .stub import StubMemory
from .profiles import ClaudeProfile, OpenAIProfile, profile_canon, canonical_json, profile_hash, CANON_SCHEMA
from .adapters import (ClaudeAdapter, OpenAIAdapter, KitCallable, BudgetClosed, DEFAULT_TEMPERATURE, DEFAULT_EFFORT,
                       INSTRUCTION)
from .readiness import (check_real_run, readiness_findings, source_findings, RealRunRefused, Finding, FAULTS,
                        FAULT_ORDER, DOC_HOSTS, BARE_TLDS, protect as _protect)

__all__ = [
    "Turn", "IngestResult", "Excerpt", "Fact", "ProfileResult", "FeedbackResult", "Unavailable", "TraceEntry",
    "AuditTrace", "ModelContext", "RetrievalResult", "AnswerResult", "MemoryInterface", "DEFAULT_BUDGET",
    "E_NO_MEMORY", "E_NO_MATCH", "E_SPEAKER", "E_NO_SPEAKER", "E_BUDGET", "R_EMPTY_TEXT",
    "NOT_UNTIL_B8", "NOT_UNTIL_B9", "NOT_UNTIL_GATE",
    "render_context", "count_tokens", "NOTICE", "StubMemory",
    "ClaudeProfile", "OpenAIProfile", "profile_canon", "canonical_json", "profile_hash", "CANON_SCHEMA",
    "ClaudeAdapter", "OpenAIAdapter", "KitCallable", "BudgetClosed", "DEFAULT_TEMPERATURE", "DEFAULT_EFFORT",
    "INSTRUCTION",
    "check_real_run", "readiness_findings", "source_findings", "RealRunRefused", "Finding", "FAULTS", "FAULT_ORDER",
    "DOC_HOSTS", "BARE_TLDS",
]

_protect(__name__)      # build r2: the reviewed data exported here cannot be rebound through the package either
