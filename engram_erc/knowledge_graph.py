"""Domain knowledge graph and bounded cross-domain reasoning (ERC-3.9).

The graph represents explicit, provenance-bearing relationships among domain
concepts. Cross-domain traversal is deliberately conservative: shared-mechanism
paths can produce review candidates, while analogy paths remain hypotheses.
No path establishes domain equivalence, causality, or a treatment recommendation.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
from typing import Iterable

from .contracts import require_aware_datetime, require_nonempty


class KnowledgeNodeKind(str, Enum):
    ENTITY = "entity"
    ACTIVITY = "activity"
    CONTEXT = "context"
    EVENT = "event"
    ACTION = "action"
    OUTCOME = "outcome"
    MECHANISM = "mechanism"
    CONCEPT = "concept"
    EVIDENCE = "evidence"
    PRACTICE_CLAIM = "practice_claim"


class KnowledgeRelation(str, Enum):
    IS_A = "is_a"
    PART_OF = "part_of"
    LOCATED_IN = "located_in"
    INVOLVES = "involves"
    OBSERVED_IN = "observed_in"
    ADDRESSES = "addresses"
    ASSOCIATED_WITH = "associated_with"
    HAS_MECHANISM = "has_mechanism"
    SHARES_MECHANISM = "shares_mechanism"
    ANALOGOUS_TO = "analogous_to"
    SUPPORTED_BY = "supported_by"
    CONTRADICTED_BY = "contradicted_by"
    QUALIFIED_BY = "qualified_by"
    APPLIES_TO = "applies_to"
    PRECEDES = "precedes"


class TransferStatus(str, Enum):
    SAME_DOMAIN_PATH = "same_domain_path"
    MECHANISTIC_BRIDGE_CANDIDATE = "mechanistic_bridge_candidate"
    ANALOGICAL_HYPOTHESIS = "analogical_hypothesis"
    TRANSFER_NOT_JUSTIFIED = "transfer_not_justified"
    NO_PATH = "no_path"


@dataclass(frozen=True, slots=True)
class KnowledgeNode:
    node_ref: str
    kind: KnowledgeNodeKind
    label: str
    domain: str
    source_refs: tuple[str, ...]
    provenance_ref: str
    attributes: tuple[tuple[str, str], ...] = ()
    subtype: str | None = None

    def __post_init__(self) -> None:
        for name in ("node_ref", "label", "domain", "provenance_ref"):
            require_nonempty(getattr(self, name), name)
        if self.subtype is not None:
            require_nonempty(self.subtype, "subtype")
            core_values = {k.value for k in KnowledgeNodeKind}
            if self.subtype in core_values and self.subtype != self.kind.value:
                raise ValueError("subtype must not be the value of a different core node kind")
        if not self.source_refs or any(not x.strip() for x in self.source_refs):
            raise ValueError("node source_refs are required and cannot contain blanks")
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError("node source_refs must be unique")
        keys = [k for k, _ in self.attributes]
        if any(not k.strip() or not v.strip() for k, v in self.attributes):
            raise ValueError("attributes must contain non-empty key/value strings")
        if len(keys) != len(set(keys)):
            raise ValueError("attribute keys must be unique")


@dataclass(frozen=True, slots=True)
class KnowledgeEdge:
    edge_ref: str
    source_ref: str
    target_ref: str
    relation: KnowledgeRelation
    source_refs: tuple[str, ...]
    provenance_ref: str
    evidence_refs: tuple[str, ...] = ()
    directed: bool = True

    def __post_init__(self) -> None:
        for name in ("edge_ref", "source_ref", "target_ref", "provenance_ref"):
            require_nonempty(getattr(self, name), name)
        if self.source_ref == self.target_ref:
            raise ValueError("self-referential edges are not permitted")
        if not self.source_refs or any(not x.strip() for x in self.source_refs):
            raise ValueError("edge source_refs are required and cannot contain blanks")
        for name in ("source_refs", "evidence_refs"):
            values = getattr(self, name)
            if len(values) != len(set(values)) or any(not x.strip() for x in values):
                raise ValueError(f"{name} must be unique and contain no blanks")
        if self.relation == KnowledgeRelation.SHARES_MECHANISM and not self.evidence_refs:
            raise ValueError("SHARES_MECHANISM requires explicit evidence_refs")


@dataclass(frozen=True, slots=True)
class DomainKnowledgeGraph:
    nodes: tuple[KnowledgeNode, ...]
    edges: tuple[KnowledgeEdge, ...]
    graph_fingerprint: str

    def __post_init__(self) -> None:
        node_ids = [n.node_ref for n in self.nodes]
        edge_ids = [e.edge_ref for e in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node_ref values must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edge_ref values must be unique")
        subtype_kinds: dict[str, KnowledgeNodeKind] = {}
        for node in self.nodes:
            if node.subtype is not None:
                if subtype_kinds.setdefault(node.subtype, node.kind) != node.kind:
                    raise ValueError(f"subtype {node.subtype!r} is used with more than one node kind")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source_ref not in known or edge.target_ref not in known:
                raise ValueError(f"edge references unknown node: {edge.edge_ref}")


@dataclass(frozen=True, slots=True)
class CrossDomainPolicy:
    max_hops: int = 5
    max_paths_per_pair: int = 10
    allow_analogical_hypotheses: bool = True
    require_evidence_for_mechanistic_bridge: bool = True

    def __post_init__(self) -> None:
        if self.max_hops < 1 or self.max_paths_per_pair < 1:
            raise ValueError("max_hops and max_paths_per_pair must be positive")


@dataclass(frozen=True, slots=True)
class CrossDomainQuery:
    query_ref: str
    source_node_ref: str
    target_node_ref: str
    question: str

    def __post_init__(self) -> None:
        for name in ("query_ref", "source_node_ref", "target_node_ref", "question"):
            require_nonempty(getattr(self, name), name)
        if self.source_node_ref == self.target_node_ref:
            raise ValueError("source and target nodes must differ")


@dataclass(frozen=True, slots=True)
class KnowledgePath:
    node_refs: tuple[str, ...]
    edge_refs: tuple[str, ...]
    domains: tuple[str, ...]
    relation_sequence: tuple[KnowledgeRelation, ...]
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    transfer_status: TransferStatus
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrossDomainFinding:
    query_ref: str
    source_node_ref: str
    target_node_ref: str
    status: TransferStatus
    paths: tuple[KnowledgePath, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrossDomainReasoningReport:
    generated_at: datetime
    graph_fingerprint: str
    findings: tuple[CrossDomainFinding, ...]
    limitations: tuple[str, ...]


def build_knowledge_graph(
    nodes: Iterable[KnowledgeNode], edges: Iterable[KnowledgeEdge],
) -> DomainKnowledgeGraph:
    """Build a validated immutable graph; cycles are allowed as knowledge relations.

    A node's ``subtype`` (a profile's own word for its kind, for example a
    subtype of ENTITY) is part of the node's content and so of the fingerprint;
    it is never used by traversal or transfer logic.
    """
    node_rows, edge_rows = tuple(nodes), tuple(edges)
    payload = {
        "nodes": [
            {"id": n.node_ref, "kind": n.subtype or n.kind.value, "label": n.label,
             "domain": n.domain, "sources": list(n.source_refs),
             "provenance": n.provenance_ref, "attributes": list(n.attributes)}
            for n in sorted(node_rows, key=lambda x: x.node_ref)
        ],
        "edges": [
            {"id": e.edge_ref, "source": e.source_ref, "target": e.target_ref,
             "relation": e.relation.value, "sources": list(e.source_refs),
             "provenance": e.provenance_ref, "evidence": list(e.evidence_refs),
             "directed": e.directed}
            for e in sorted(edge_rows, key=lambda x: x.edge_ref)
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return DomainKnowledgeGraph(node_rows, edge_rows, fingerprint)


def _enumerate_paths(
    graph: DomainKnowledgeGraph, source_ref: str, target_ref: str,
    policy: CrossDomainPolicy,
) -> tuple[tuple[KnowledgeNode, ...], tuple[KnowledgeEdge, ...]]:
    nodes = {n.node_ref: n for n in graph.nodes}
    adjacency: dict[str, list[KnowledgeEdge]] = defaultdict(list)
    for edge in graph.edges:
        adjacency[edge.source_ref].append(edge)
        if not edge.directed:
            # Traversal over an undirected edge retains the original edge provenance.
            reverse = KnowledgeEdge(
                edge_ref=edge.edge_ref, source_ref=edge.target_ref, target_ref=edge.source_ref,
                relation=edge.relation, source_refs=edge.source_refs,
                provenance_ref=edge.provenance_ref, evidence_refs=edge.evidence_refs,
                directed=True,
            )
            adjacency[edge.target_ref].append(reverse)
    for rows in adjacency.values():
        rows.sort(key=lambda e: (e.target_ref, e.relation.value, e.edge_ref))

    found: list[tuple[tuple[KnowledgeNode, ...], tuple[KnowledgeEdge, ...]]] = []
    queue = deque([(source_ref, (source_ref,), ())])
    while queue and len(found) < policy.max_paths_per_pair:
        current, node_path, edge_path = queue.popleft()
        if current == target_ref:
            found.append((tuple(nodes[x] for x in node_path), edge_path))
            continue
        if len(edge_path) >= policy.max_hops:
            continue
        for edge in adjacency.get(current, ()):
            if edge.target_ref in node_path:
                continue
            queue.append((edge.target_ref, node_path + (edge.target_ref,), edge_path + (edge,)))
    return tuple(found)


def _classify_path(
    nodes: tuple[KnowledgeNode, ...], edges: tuple[KnowledgeEdge, ...],
    policy: CrossDomainPolicy,
) -> tuple[TransferStatus, tuple[str, ...]]:
    domains = {n.domain for n in nodes}
    if len(domains) == 1:
        return TransferStatus.SAME_DOMAIN_PATH, ("Same-domain graph connectivity is not itself proof of case applicability.",)

    mechanism_refs = {n.node_ref for n in nodes if n.kind == KnowledgeNodeKind.MECHANISM}
    mechanism_edges = [e for e in edges if e.relation == KnowledgeRelation.SHARES_MECHANISM]
    has_mechanism_bridge = bool(mechanism_refs and mechanism_edges)
    if has_mechanism_bridge:
        if policy.require_evidence_for_mechanistic_bridge and not all(e.evidence_refs for e in mechanism_edges):
            return TransferStatus.TRANSFER_NOT_JUSTIFIED, ("Mechanistic bridge lacks explicit evidence references.",)
        return TransferStatus.MECHANISTIC_BRIDGE_CANDIDATE, (
            "A shared-mechanism path is a candidate for expert review, not proof of transferable effect.",
            "Activity-specific entity, context, technique and population differences require separate appraisal.",
        )

    if any(e.relation == KnowledgeRelation.ANALOGOUS_TO for e in edges):
        if policy.allow_analogical_hypotheses:
            return TransferStatus.ANALOGICAL_HYPOTHESIS, (
                "Analogy is hypothesis-generating only; it does not establish equivalence or transfer an intervention.",
                "Independent evidence and domain-specific validation are required.",
            )
        return TransferStatus.TRANSFER_NOT_JUSTIFIED, ("Analogical transfer is disabled by policy.",)

    return TransferStatus.TRANSFER_NOT_JUSTIFIED, (
        "Cross-domain connectivity lacks an explicit shared-mechanism or permitted analogy relationship.",
    )


def reason_across_domains(
    graph: DomainKnowledgeGraph,
    queries: Iterable[CrossDomainQuery],
    *, generated_at: datetime,
    policy: CrossDomainPolicy = CrossDomainPolicy(),
) -> CrossDomainReasoningReport:
    """Find bounded, provenance-preserving paths between knowledge domains.

    This function exposes candidate relationships only. It does not infer a
    practice recommendation, causal effect, or equivalence between activities.
    """
    require_aware_datetime(generated_at, "generated_at")
    query_rows = tuple(queries)
    query_ids = [q.query_ref for q in query_rows]
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("query_ref values must be unique")
    node_ids = {n.node_ref for n in graph.nodes}
    findings: list[CrossDomainFinding] = []
    for query in query_rows:
        if query.source_node_ref not in node_ids or query.target_node_ref not in node_ids:
            raise ValueError(f"query references unknown node: {query.query_ref}")
        paths_raw = _enumerate_paths(graph, query.source_node_ref, query.target_node_ref, policy)
        paths: list[KnowledgePath] = []
        for nodes, edges in paths_raw:
            status, limits = _classify_path(nodes, edges, policy)
            paths.append(KnowledgePath(
                node_refs=tuple(n.node_ref for n in nodes),
                edge_refs=tuple(e.edge_ref for e in edges),
                domains=tuple(n.domain for n in nodes),
                relation_sequence=tuple(e.relation for e in edges),
                source_refs=tuple(sorted({r for n in nodes for r in n.source_refs} | {r for e in edges for r in e.source_refs})),
                evidence_refs=tuple(sorted({r for e in edges for r in e.evidence_refs})),
                transfer_status=status,
                limitations=limits,
            ))
        if not paths:
            status = TransferStatus.NO_PATH
            limitations = ("No provenance-bearing path was found within the configured hop and path limits.",)
        else:
            statuses = {p.transfer_status for p in paths}
            priority = (
                TransferStatus.MECHANISTIC_BRIDGE_CANDIDATE,
                TransferStatus.ANALOGICAL_HYPOTHESIS,
                TransferStatus.SAME_DOMAIN_PATH,
                TransferStatus.TRANSFER_NOT_JUSTIFIED,
            )
            status = next(s for s in priority if s in statuses)
            limitations = tuple(dict.fromkeys(x for p in paths for x in p.limitations))
        findings.append(CrossDomainFinding(
            query.query_ref, query.source_node_ref, query.target_node_ref,
            status, tuple(paths), limitations,
        ))
    return CrossDomainReasoningReport(
        generated_at, graph.graph_fingerprint, tuple(findings),
        (
            "Graph relationships are only as reliable as their supplied source and adjudication provenance.",
            "Cross-domain paths do not establish domain equivalence, causality, treatment effectiveness or case-level applicability.",
            "No authoritative knowledge store, registry, evidence record or P6 state is modified.",
        ),
    )
