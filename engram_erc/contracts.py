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


@dataclass(frozen=True, slots=True)
class TimeInterval:
    """Half-open interval [start, end); either boundary may be unknown."""
    start: datetime | None = None
    end: datetime | None = None

    def __post_init__(self) -> None:
        require_aware_datetime(self.start, "start")
        require_aware_datetime(self.end, "end")
        if self.start and self.end and self.start >= self.end:
            raise ValueError("TimeInterval.start must be earlier than end")


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

    def __post_init__(self) -> None:
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
