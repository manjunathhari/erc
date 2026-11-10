"""Public, versioned contracts for the Engram Reasoning Core (ERC-1.1).

This module intentionally depends only on the Python standard library.
It contains data contracts, not reasoning algorithms or storage code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, TypeAlias
from uuid import uuid4

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def require_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def require_aware_datetime(value: datetime | None, name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")


def require_unit_interval(value: float | None, name: str) -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


class PropositionKind(str, Enum):
    ASSERTION = "assertion"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"


class EvidenceKind(str, Enum):
    OBSERVATION = "observation"
    STUDY_RESULT = "study_result"
    DOCUMENT = "document"
    EXPERT_JUDGMENT = "expert_judgment"
    STRUCTURED_RECORD = "structured_record"
    OTHER = "other"


class SourceKind(str, Enum):
    ENGRAM_MEMORY = "engram_memory"
    ENGRAM_KNOWLEDGE = "engram_knowledge"
    REGISTRY = "registry"
    EXTERNAL_DATABASE = "external_database"
    USER_PROVIDED = "user_provided"
    OTHER = "other"


class EdgeKind(str, Enum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    QUALIFIES = "qualifies"
    PREMISE_OF = "premise_of"
    DERIVES = "derives"
    DEPENDS_ON = "depends_on"
    RELATES_TO = "relates_to"
    TEMPORAL_SUCCESSOR = "temporal_successor"


class ReasoningStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    INDETERMINATE = "indeterminate"
    CONFLICT = "conflict"
    REJECTED = "rejected"


class UncertaintyKind(str, Enum):
    MISSING_PREMISE = "missing_premise"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    LOW_EVIDENCE_QUALITY = "low_evidence_quality"
    TEMPORAL_AMBIGUITY = "temporal_ambiguity"
    SCOPE_AMBIGUITY = "scope_ambiguity"
    RULE_LIMITATION = "rule_limitation"
    OTHER = "other"


class BoundaryStatus(str, Enum):
    """What is known about one boundary of a time (ERC 0.5.0). Derived from the fields; never stored."""
    EXACT = "exact"                      # one known instant
    WITHIN = "within"                    # somewhere between two known instants
    NO_LATER_THAN = "no_later_than"      # an upper bound only; how much earlier is not known
    NO_EARLIER_THAN = "no_earlier_than"  # a lower bound only; how much later is not known
    UNKNOWN = "unknown"                  # the boundary exists and nothing is known about it
    UNBOUNDED = "unbounded"              # explicitly no boundary in that direction


def _require_datetime(value: datetime | None, name: str) -> None:
    if value is not None and not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime, not {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class TimeInterval:
    """When a state holds: the half-open interval [start, end).

    ``TimeInterval(start, end)`` means what it always has: two exact instants, and a missing one is unknown.
    The keyword-only fields (ERC 0.5.0) let a caller say more without inventing a date. For each boundary:

    ============== ======================================== ======================================
    status         start                                    end
    ============== ======================================== ======================================
    exact          ``start``                                ``end``
    within         ``start`` .. ``start_latest``            ``end_earliest`` .. ``end``
    no later than  ``start_latest`` only                    ``end`` with ``end_is_upper_bound``
    no earlier     ``start`` with ``start_is_lower_bound``  ``end_earliest`` only
    unknown        nothing given                            nothing given
    unbounded      ``start_unbounded``                      ``end_unbounded``
    ============== ======================================== ======================================

    So ``start`` is always the earliest the state could have begun and ``end`` the latest it could have ended;
    they are exact unless another field says otherwise. A window includes both of its instants. Unknown and
    unbounded are different statements: an interval with a start and no end *ended at a moment not known*;
    only ``end_unbounded`` says it has no end so far.

    This type states what is known. It answers no question; nothing in ERC reads the keyword-only fields yet.
    """
    start: datetime | None = None
    end: datetime | None = None
    start_latest: datetime | None = field(default=None, kw_only=True)
    end_earliest: datetime | None = field(default=None, kw_only=True)
    start_unbounded: bool = field(default=False, kw_only=True)
    end_unbounded: bool = field(default=False, kw_only=True)
    start_is_lower_bound: bool = field(default=False, kw_only=True)
    end_is_upper_bound: bool = field(default=False, kw_only=True)

    def __post_init__(self) -> None:
        for name in ("start", "end", "start_latest", "end_earliest"):
            _require_datetime(getattr(self, name), f"TimeInterval.{name}")
            require_aware_datetime(getattr(self, name), name)
        for name in ("start_unbounded", "end_unbounded", "start_is_lower_bound", "end_is_upper_bound"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"TimeInterval.{name} must be bool")
        if self.start and self.end and self.start >= self.end:
            raise ValueError("TimeInterval.start must be earlier than end")
        if self.start_unbounded and (self.start or self.start_latest or self.start_is_lower_bound):
            raise ValueError("TimeInterval: an unbounded start carries no date and no bound")
        if self.end_unbounded and (self.end or self.end_earliest or self.end_is_upper_bound):
            raise ValueError("TimeInterval: an unbounded end carries no date and no bound")
        if self.start and self.start_latest and self.start_latest <= self.start:
            raise ValueError("TimeInterval.start_latest must be later than start (omit it for an exact start)")
        if self.end and self.end_earliest and self.end_earliest >= self.end:
            raise ValueError("TimeInterval.end_earliest must be earlier than end (omit it for an exact end)")
        if self.start_is_lower_bound and (self.start is None or self.start_latest is not None):
            raise ValueError("TimeInterval.start_is_lower_bound needs a start and no start_latest")
        if self.end_is_upper_bound and (self.end is None or self.end_earliest is not None):
            raise ValueError("TimeInterval.end_is_upper_bound needs an end and no end_earliest")

    @property
    def start_status(self) -> BoundaryStatus:
        if self.start_unbounded:
            return BoundaryStatus.UNBOUNDED
        if self.start is None:
            return BoundaryStatus.UNKNOWN if self.start_latest is None else BoundaryStatus.NO_LATER_THAN
        if self.start_latest is not None:
            return BoundaryStatus.WITHIN
        return BoundaryStatus.NO_EARLIER_THAN if self.start_is_lower_bound else BoundaryStatus.EXACT

    @property
    def end_status(self) -> BoundaryStatus:
        if self.end_unbounded:
            return BoundaryStatus.UNBOUNDED
        if self.end is None:
            return BoundaryStatus.UNKNOWN if self.end_earliest is None else BoundaryStatus.NO_EARLIER_THAN
        if self.end_earliest is not None:
            return BoundaryStatus.WITHIN
        return BoundaryStatus.NO_LATER_THAN if self.end_is_upper_bound else BoundaryStatus.EXACT


@dataclass(frozen=True, slots=True)
class Occurrence:
    """When an event happened (ERC 0.5.0): one instant, known to lie from ``earliest`` to ``latest`` inclusive.

    Equal values are an exact moment. One value alone is a one-sided bound. Neither means the event has a time
    that is not known. An occurrence is not a period: it says nothing about any state holding before or after.
    """
    earliest: datetime | None = None
    latest: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("earliest", "latest"):
            _require_datetime(getattr(self, name), f"Occurrence.{name}")
            require_aware_datetime(getattr(self, name), name)
        if self.earliest and self.latest and self.earliest > self.latest:
            raise ValueError("Occurrence.earliest must not be later than latest")

    @property
    def status(self) -> BoundaryStatus:
        if self.earliest is None:
            return BoundaryStatus.UNKNOWN if self.latest is None else BoundaryStatus.NO_LATER_THAN
        if self.latest is None:
            return BoundaryStatus.NO_EARLIER_THAN
        return BoundaryStatus.EXACT if self.earliest == self.latest else BoundaryStatus.WITHIN


@dataclass(frozen=True, slots=True)
class Proposition:
    """A claim under evaluation; it is not itself proof of the claim."""
    id: str
    subject: str
    predicate: str
    object_value: JSONValue
    polarity: bool = True
    kind: PropositionKind = PropositionKind.ASSERTION
    source_refs: tuple[str, ...] = ()
    valid_time: TimeInterval | None = None
    qualifiers: Mapping[str, JSONValue] = field(default_factory=dict)
    # ERC 0.5.0. A state carries valid_time, an event carries occurred, never both. With neither, the
    # proposition makes no temporal statement (which is not the same as TimeInterval(): a time that is unknown).
    occurred: Occurrence | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.occurred is not None and not isinstance(self.occurred, Occurrence):
            raise ValueError("occurred must be an Occurrence")
        if self.valid_time is not None and self.occurred is not None:
            raise ValueError("a proposition carries either valid_time (a state) or occurred (an event), not both")
        for name in ("id", "subject", "predicate"):
            require_nonempty(getattr(self, name), name)
        if not isinstance(self.polarity, bool):
            raise ValueError("polarity must be bool")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("source_refs must not contain duplicates")


@dataclass(frozen=True, slots=True)
class Evidence:
    """Evidence pointer. Raw source text stays in its authoritative store."""
    id: str
    source_ref: str
    source_kind: SourceKind
    evidence_kind: EvidenceKind = EvidenceKind.OTHER
    observed_at: datetime | None = None
    valid_time: TimeInterval | None = None
    reliability_score: float | None = None
    reliability_method: str | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_nonempty(self.id, "id")
        require_nonempty(self.source_ref, "source_ref")
        require_aware_datetime(self.observed_at, "observed_at")
        require_unit_interval(self.reliability_score, "reliability_score")
        if self.reliability_score is not None and not self.reliability_method:
            raise ValueError("reliability_method is required when reliability_score is supplied")


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    evidence_id: str
    proposition_id: str
    relation: EvidenceRelation
    rationale_code: str | None = None

    def __post_init__(self) -> None:
        require_nonempty(self.evidence_id, "evidence_id")
        require_nonempty(self.proposition_id, "proposition_id")


@dataclass(frozen=True, slots=True)
class ReasoningRequest:
    id: str
    task_type: str
    propositions: tuple[Proposition, ...]
    evidence: tuple[Evidence, ...] = ()
    evidence_links: tuple[EvidenceLink, ...] = ()
    context_refs: tuple[str, ...] = ()
    as_of: datetime | None = None
    constraints: Mapping[str, JSONValue] = field(default_factory=dict)
    options: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_nonempty(self.id, "id")
        require_nonempty(self.task_type, "task_type")
        require_aware_datetime(self.as_of, "as_of")
        _unique_ids(self.propositions, "proposition")
        _unique_ids(self.evidence, "evidence")
        pids = {p.id for p in self.propositions}
        eids = {e.id for e in self.evidence}
        for link in self.evidence_links:
            if link.proposition_id not in pids:
                raise ValueError(f"EvidenceLink references unknown proposition: {link.proposition_id}")
            if link.evidence_id not in eids:
                raise ValueError(f"EvidenceLink references unknown evidence: {link.evidence_id}")


def _unique_ids(items: tuple[Any, ...], label: str) -> None:
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {label} id")


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    node_type: str  # proposition | evidence | inference
    ref_id: str

    def __post_init__(self) -> None:
        require_nonempty(self.id, "id")
        require_nonempty(self.node_type, "node_type")
        require_nonempty(self.ref_id, "ref_id")


@dataclass(frozen=True, slots=True)
class GraphEdge:
    id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    attributes: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("id", "source_id", "target_id"):
            require_nonempty(getattr(self, name), name)
        if self.source_id == self.target_id:
            raise ValueError("self-edges are not permitted in ERC-1.1")


@dataclass(frozen=True, slots=True)
class ReasoningGraph:
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    def __post_init__(self) -> None:
        node_ids = [n.id for n in self.nodes]
        edge_ids = [e.id for e in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate graph node id")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("duplicate graph edge id")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source_id not in known or edge.target_id not in known:
                raise ValueError(f"edge {edge.id} references an unknown graph node")


@dataclass(frozen=True, slots=True)
class InferenceStep:
    id: str
    operation: str
    input_refs: tuple[str, ...]
    output_proposition_refs: tuple[str, ...]
    rule_id: str
    parameters: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("id", "operation", "rule_id"):
            require_nonempty(getattr(self, name), name)
        if not self.input_refs:
            raise ValueError("InferenceStep requires at least one input reference")
        if not self.output_proposition_refs:
            raise ValueError("InferenceStep requires at least one output proposition")


@dataclass(frozen=True, slots=True)
class UncertaintyItem:
    id: str
    kind: UncertaintyKind
    description: str
    affected_refs: tuple[str, ...] = ()
    resolution_hint: str | None = None

    def __post_init__(self) -> None:
        require_nonempty(self.id, "id")
        require_nonempty(self.description, "description")


@dataclass(frozen=True, slots=True)
class TraceEntry:
    sequence: int
    operation: str
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    status: str
    rule_id: str | None = None
    explanation_code: str | None = None
    details: Mapping[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("trace sequence must be non-negative")
        require_nonempty(self.operation, "operation")
        require_nonempty(self.status, "status")


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    id: str
    request_id: str
    status: ReasoningStatus
    conclusion_refs: tuple[str, ...]
    propositions: tuple[Proposition, ...]
    inference_steps: tuple[InferenceStep, ...]
    graph: ReasoningGraph
    uncertainty: tuple[UncertaintyItem, ...] = ()
    trace: tuple[TraceEntry, ...] = ()
    engine_version: str = "0.1.0"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        require_nonempty(self.id, "id")
        require_nonempty(self.request_id, "request_id")
        require_aware_datetime(self.created_at, "created_at")
        proposition_ids = {p.id for p in self.propositions}
        if not set(self.conclusion_refs).issubset(proposition_ids):
            raise ValueError("conclusion_refs must refer to propositions in the result")
        if tuple(sorted(self.trace, key=lambda item: item.sequence)) != self.trace:
            raise ValueError("trace entries must be ordered by sequence")
