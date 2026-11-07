"""In-memory reasoning graph builder and read-only traversal API."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping

from .contracts import (
    EdgeKind, Evidence, EvidenceLink, EvidenceRelation, GraphEdge, GraphNode,
    InferenceStep, Proposition, ReasoningGraph, new_id,
)
from .validation import (
    find_inference_cycle, topological_inferences, validate_graph_bindings,
)


class ReasoningGraphBuilder:
    """Mutable construction API; build() returns an immutable ReasoningGraph.

    IDs for graph nodes are distinct from IDs of the typed objects they reference.
    Source content is never accepted by this builder; only typed objects/references.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._propositions: dict[str, Proposition] = {}
        self._evidence: dict[str, Evidence] = {}
        self._inferences: dict[str, InferenceStep] = {}

    def _add_node(self, node_type: str, ref_id: str, node_id: str | None = None) -> str:
        if node_id is None:
            node_id = new_id("node")
        if node_id in self._nodes:
            existing = self._nodes[node_id]
            if existing.node_type == node_type and existing.ref_id == ref_id:
                return node_id
            raise ValueError(f"graph node ID already exists: {node_id}")
        self._nodes[node_id] = GraphNode(node_id, node_type, ref_id)
        return node_id

    def add_proposition(self, proposition: Proposition, *, node_id: str | None = None) -> str:
        existing = self._propositions.get(proposition.id)
        if existing is not None and existing != proposition:
            raise ValueError(f"proposition ID already exists with different content: {proposition.id}")
        self._propositions[proposition.id] = proposition
        return self._add_node("proposition", proposition.id, node_id)

    def add_evidence(self, evidence: Evidence, *, node_id: str | None = None) -> str:
        existing = self._evidence.get(evidence.id)
        if existing is not None and existing != evidence:
            raise ValueError(f"evidence ID already exists with different content: {evidence.id}")
        self._evidence[evidence.id] = evidence
        return self._add_node("evidence", evidence.id, node_id)

    def add_inference(self, inference: InferenceStep, *, node_id: str | None = None) -> str:
        existing = self._inferences.get(inference.id)
        if existing is not None and existing != inference:
            raise ValueError(f"inference ID already exists with different content: {inference.id}")
        self._inferences[inference.id] = inference
        return self._add_node("inference", inference.id, node_id)

    def node_for(self, node_type: str, ref_id: str) -> str:
        for node in self._nodes.values():
            if node.node_type == node_type and node.ref_id == ref_id:
                return node.id
        raise KeyError(f"no {node_type} node for reference {ref_id}")

    def add_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        kind: EdgeKind,
        *,
        edge_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> str:
        if source_node_id not in self._nodes:
            raise KeyError(f"unknown source node: {source_node_id}")
        if target_node_id not in self._nodes:
            raise KeyError(f"unknown target node: {target_node_id}")
        if source_node_id == target_node_id:
            raise ValueError("self-edges are not permitted")
        edge_id = edge_id or new_id("edge")
        if edge_id in self._edges:
            raise ValueError(f"graph edge ID already exists: {edge_id}")
        edge = GraphEdge(
            edge_id, source_node_id, target_node_id, kind,
            dict(attributes or {}),
        )
        self._edges[edge_id] = edge
        return edge_id

    def link_evidence(self, link: EvidenceLink) -> str:
        evidence_node = self.node_for("evidence", link.evidence_id)
        proposition_node = self.node_for("proposition", link.proposition_id)
        kind = {
            EvidenceRelation.SUPPORTS: EdgeKind.SUPPORTS,
            EvidenceRelation.CONTRADICTS: EdgeKind.CONTRADICTS,
            EvidenceRelation.QUALIFIES: EdgeKind.QUALIFIES,
        }[link.relation]
        attrs = {"rationale_code": link.rationale_code} if link.rationale_code else {}
        return self.add_edge(evidence_node, proposition_node, kind, attributes=attrs)

    def connect_inference(
        self,
        inference_id: str,
        *,
        premise_proposition_ids: Iterable[str],
        output_proposition_ids: Iterable[str],
    ) -> tuple[str, ...]:
        """Connect premise propositions -> inference -> derived propositions."""
        inference_node = self.node_for("inference", inference_id)
        edge_ids: list[str] = []
        premises = tuple(premise_proposition_ids)
        outputs = tuple(output_proposition_ids)
        if not premises:
            raise ValueError("an inference must have at least one premise")
        if not outputs:
            raise ValueError("an inference must produce at least one proposition")
        for proposition_id in premises:
            pnode = self.node_for("proposition", proposition_id)
            edge_ids.append(self.add_edge(pnode, inference_node, EdgeKind.PREMISE_OF))
        for proposition_id in outputs:
            pnode = self.node_for("proposition", proposition_id)
            edge_ids.append(self.add_edge(inference_node, pnode, EdgeKind.DERIVES))
        return tuple(edge_ids)

    def build(self, *, validate: bool = True) -> ReasoningGraph:
        graph = ReasoningGraph(tuple(self._nodes.values()), tuple(self._edges.values()))
        if validate:
            validate_graph_bindings(
                graph,
                tuple(self._propositions.values()),
                tuple(self._evidence.values()),
                tuple(self._inferences.values()),
            )
        return graph

    @property
    def propositions(self) -> tuple[Proposition, ...]:
        return tuple(self._propositions.values())

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        return tuple(self._evidence.values())

    @property
    def inference_steps(self) -> tuple[InferenceStep, ...]:
        return tuple(self._inferences.values())


class ReasoningGraphView:
    """Read-only query/traversal façade over a validated graph and typed objects."""

    def __init__(
        self,
        graph: ReasoningGraph,
        propositions: Iterable[Proposition],
        evidence: Iterable[Evidence],
        inference_steps: Iterable[InferenceStep] = (),
        *,
        validate: bool = True,
    ) -> None:
        self.graph = graph
        self.propositions = {item.id: item for item in propositions}
        self.evidence = {item.id: item for item in evidence}
        self.inferences = {item.id: item for item in inference_steps}
        self.nodes = {node.id: node for node in graph.nodes}
        self._by_ref = {(n.node_type, n.ref_id): n.id for n in graph.nodes}
        self._out: dict[str, list[GraphEdge]] = {n.id: [] for n in graph.nodes}
        self._in: dict[str, list[GraphEdge]] = {n.id: [] for n in graph.nodes}
        for edge in graph.edges:
            self._out[edge.source_id].append(edge)
            self._in[edge.target_id].append(edge)
        if validate:
            validate_graph_bindings(
                graph, tuple(self.propositions.values()), tuple(self.evidence.values()),
                tuple(self.inferences.values()),
            )

    def node_id(self, node_type: str, ref_id: str) -> str:
        try:
            return self._by_ref[(node_type, ref_id)]
        except KeyError:
            raise KeyError(f"no graph node for {node_type}:{ref_id}") from None

    def _linked_refs(self, node_id: str, *, outgoing: bool, kinds: set[EdgeKind] | None = None):
        edges = self._out[node_id] if outgoing else self._in[node_id]
        for edge in edges:
            if kinds is not None and edge.kind not in kinds:
                continue
            other_id = edge.target_id if outgoing else edge.source_id
            yield self.nodes[other_id]

    def evidence_for(self, proposition_id: str, *, relations: set[EdgeKind] | None = None) -> tuple[Evidence, ...]:
        """Return evidence directly linked to a proposition, preserving graph order."""
        pnode = self.node_id("proposition", proposition_id)
        allowed = relations or {EdgeKind.SUPPORTS, EdgeKind.CONTRADICTS, EdgeKind.QUALIFIES}
        found = []
        for node in self._linked_refs(pnode, outgoing=False, kinds=allowed):
            if node.node_type == "evidence":
                found.append(self.evidence[node.ref_id])
        return tuple(found)

    def evidence_by_relation(self, proposition_id: str) -> dict[str, tuple[Evidence, ...]]:
        pnode = self.node_id("proposition", proposition_id)
        result = {"supports": [], "contradicts": [], "qualifies": []}
        relation_map = {
            EdgeKind.SUPPORTS: "supports",
            EdgeKind.CONTRADICTS: "contradicts",
            EdgeKind.QUALIFIES: "qualifies",
        }
        for edge in self._in[pnode]:
            key = relation_map.get(edge.kind)
            if key:
                evidence_node = self.nodes[edge.source_id]
                if evidence_node.node_type == "evidence":
                    result[key].append(self.evidence[evidence_node.ref_id])
        return {key: tuple(value) for key, value in result.items()}

    def premises_for(self, inference_id: str) -> tuple[Proposition, ...]:
        inode = self.node_id("inference", inference_id)
        return tuple(
            self.propositions[node.ref_id]
            for node in self._linked_refs(inode, outgoing=False, kinds={EdgeKind.PREMISE_OF})
            if node.node_type == "proposition"
        )

    def conclusions_from(self, inference_id: str) -> tuple[Proposition, ...]:
        inode = self.node_id("inference", inference_id)
        return tuple(
            self.propositions[node.ref_id]
            for node in self._linked_refs(inode, outgoing=True, kinds={EdgeKind.DERIVES})
            if node.node_type == "proposition"
        )

    def inferences_using(self, proposition_id: str) -> tuple[InferenceStep, ...]:
        pnode = self.node_id("proposition", proposition_id)
        return tuple(
            self.inferences[node.ref_id]
            for node in self._linked_refs(pnode, outgoing=True, kinds={EdgeKind.PREMISE_OF})
            if node.node_type == "inference"
        )

    def supporting_evidence(self, proposition_id: str) -> tuple[Evidence, ...]:
        return self.evidence_by_relation(proposition_id)["supports"]

    def contradicting_evidence(self, proposition_id: str) -> tuple[Evidence, ...]:
        return self.evidence_by_relation(proposition_id)["contradicts"]

    def qualifying_evidence(self, proposition_id: str) -> tuple[Evidence, ...]:
        return self.evidence_by_relation(proposition_id)["qualifies"]

    def ancestors(self, node_id: str, *, edge_kinds: set[EdgeKind] | None = None) -> tuple[GraphNode, ...]:
        """Return all upstream nodes reachable through incoming edges."""
        if node_id not in self.nodes:
            raise KeyError(node_id)
        visited: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            for edge in self._in[current]:
                if edge_kinds is not None and edge.kind not in edge_kinds:
                    continue
                if edge.source_id not in visited:
                    visited.add(edge.source_id)
                    stack.append(edge.source_id)
        visited.discard(node_id)
        return tuple(self.nodes[item] for item in sorted(visited))

    def descendants(self, node_id: str, *, edge_kinds: set[EdgeKind] | None = None) -> tuple[GraphNode, ...]:
        """Return all downstream nodes reachable through outgoing edges."""
        if node_id not in self.nodes:
            raise KeyError(node_id)
        visited: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            for edge in self._out[current]:
                if edge_kinds is not None and edge.kind not in edge_kinds:
                    continue
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    stack.append(edge.target_id)
        visited.discard(node_id)
        return tuple(self.nodes[item] for item in sorted(visited))

    def inference_order(self) -> tuple[str, ...]:
        """Inference IDs in prerequisite-first execution order."""
        node_order = topological_inferences(self.graph)
        return tuple(self.nodes[node_id].ref_id for node_id in node_order)

    def inference_cycle(self) -> tuple[str, ...] | None:
        """Return a cycle in graph-node IDs, if any."""
        return find_inference_cycle(self.graph)

    def to_dict(self) -> dict[str, Any]:
        """Canonical JSON-compatible graph representation (no source-text fetch)."""
        def convert(value):
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, dict):
                return {str(k): convert(v) for k, v in value.items()}
            if isinstance(value, (tuple, list)):
                return [convert(v) for v in value]
            return value

        return {
            "schema_version": "erc.graph.v1",
            "nodes": [
                {"id": n.id, "node_type": n.node_type, "ref_id": n.ref_id}
                for n in sorted(self.graph.nodes, key=lambda x: x.id)
            ],
            "edges": [
                {
                    "id": e.id, "source_id": e.source_id, "target_id": e.target_id,
                    "kind": e.kind.value, "attributes": convert(dict(e.attributes)),
                }
                for e in sorted(self.graph.edges, key=lambda x: x.id)
            ],
        }
