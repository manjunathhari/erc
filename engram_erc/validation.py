"""Typed graph validation for ERC-1.2."""
from __future__ import annotations

from collections import defaultdict
from .contracts import (
    EdgeKind, GraphNode, ReasoningGraph, Proposition, Evidence, InferenceStep
)

NODE_TYPES = {"proposition", "evidence", "inference"}

_ALLOWED_ENDPOINTS = {
    EdgeKind.SUPPORTS: {("evidence", "proposition")},
    EdgeKind.CONTRADICTS: {("evidence", "proposition")},
    EdgeKind.QUALIFIES: {("evidence", "proposition")},
    EdgeKind.PREMISE_OF: {("proposition", "inference")},
    EdgeKind.DERIVES: {("inference", "proposition")},
    EdgeKind.DEPENDS_ON: {("inference", "inference")},
    EdgeKind.RELATES_TO: {
        ("proposition", "proposition"),
        ("evidence", "evidence"),
        ("inference", "inference"),
        ("proposition", "evidence"),
        ("evidence", "proposition"),
    },
    EdgeKind.TEMPORAL_SUCCESSOR: {("proposition", "proposition")},
}


def inference_dependencies(graph: ReasoningGraph) -> dict[str, set[str]]:
    """Return inference -> prerequisite-inference adjacency.

    Dependencies arise either from an explicit DEPENDS_ON edge (A depends on B),
    or from A deriving a proposition which is then used as a premise by B.
    """
    node_by_id = {n.id: n for n in graph.nodes}
    adjacency: dict[str, set[str]] = defaultdict(set)
    for node in graph.nodes:
        if node.node_type == "inference":
            adjacency[node.id]  # retain isolated inference nodes

    for edge in graph.edges:
        src = node_by_id[edge.source_id]
        dst = node_by_id[edge.target_id]
        if edge.kind == EdgeKind.DEPENDS_ON:
            adjacency[src.id].add(dst.id)
        elif edge.kind == EdgeKind.DERIVES:
            # Inference A produces proposition P; any inference using P
            # depends on A.
            for premise_edge in graph.edges:
                if premise_edge.kind == EdgeKind.PREMISE_OF and premise_edge.source_id == dst.id:
                    adjacency[premise_edge.target_id].add(src.id)
    return dict(adjacency)


def find_inference_cycle(graph: ReasoningGraph) -> tuple[str, ...] | None:
    """Return one cycle path, including the repeated closing node, if present."""
    adjacency = inference_dependencies(graph)
    color: dict[str, int] = {node_id: 0 for node_id in adjacency}
    stack: list[str] = []
    positions: dict[str, int] = {}

    def visit(node_id: str):
        color[node_id] = 1
        positions[node_id] = len(stack)
        stack.append(node_id)
        for dep in sorted(adjacency.get(node_id, ())):
            if dep not in color:
                # A dependency target must itself be an inference node.
                continue
            if color[dep] == 0:
                found = visit(dep)
                if found:
                    return found
            elif color[dep] == 1:
                return tuple(stack[positions[dep]:] + [dep])
        stack.pop()
        positions.pop(node_id, None)
        color[node_id] = 2
        return None

    for node_id in sorted(adjacency):
        if color[node_id] == 0:
            found = visit(node_id)
            if found:
                return found
    return None


def topological_inferences(graph: ReasoningGraph) -> tuple[str, ...]:
    """Return inference node IDs in prerequisite-first order.

    Raises ValueError when the inference dependency graph contains a cycle.
    """
    adjacency = inference_dependencies(graph)
    cycle = find_inference_cycle(graph)
    if cycle:
        raise ValueError("inference dependency cycle: " + " -> ".join(cycle))

    visited: set[str] = set()
    ordered: list[str] = []

    def visit(node_id: str):
        if node_id in visited:
            return
        visited.add(node_id)
        for prerequisite in sorted(adjacency.get(node_id, ())):
            visit(prerequisite)
        ordered.append(node_id)

    for node_id in sorted(adjacency):
        visit(node_id)
    return tuple(ordered)


def validate_graph_bindings(
    graph: ReasoningGraph,
    propositions: tuple[Proposition, ...],
    evidence: tuple[Evidence, ...],
    inference_steps: tuple[InferenceStep, ...] = (),
    *,
    reject_inference_cycles: bool = True,
) -> None:
    """Validate node bindings, edge semantics and inference dependency acyclicity."""
    known = {
        "proposition": {item.id for item in propositions},
        "evidence": {item.id for item in evidence},
        "inference": {item.id for item in inference_steps},
    }
    node_by_id = {node.id: node for node in graph.nodes}

    for node in graph.nodes:
        if node.node_type not in NODE_TYPES:
            raise ValueError(f"unsupported graph node type: {node.node_type}")
        if node.ref_id not in known[node.node_type]:
            raise ValueError(
                f"graph node {node.id} points to unknown {node.node_type}: {node.ref_id}"
            )

    for edge in graph.edges:
        source_type = node_by_id[edge.source_id].node_type
        target_type = node_by_id[edge.target_id].node_type
        allowed = _ALLOWED_ENDPOINTS.get(edge.kind, set())
        if (source_type, target_type) not in allowed:
            raise ValueError(
                f"invalid endpoints for {edge.kind.value}: "
                f"{source_type} -> {target_type}"
            )

    # Check the inference-step references themselves against typed objects.
    proposition_ids = known["proposition"]
    evidence_ids = known["evidence"]
    inference_ids = known["inference"]
    node_for_ref = {(node.node_type, node.ref_id): node.id for node in graph.nodes}
    for step in inference_steps:
        for ref in step.input_refs:
            if ref not in proposition_ids | evidence_ids | inference_ids:
                raise ValueError(f"inference {step.id} has unresolved input: {ref}")
        for ref in step.output_proposition_refs:
            if ref not in proposition_ids:
                raise ValueError(f"inference {step.id} has unresolved output: {ref}")

        inference_node_id = node_for_ref.get(("inference", step.id))
        if inference_node_id is None:
            raise ValueError(f"inference step {step.id} has no graph node")
        actual_premises = {
            node_by_id[edge.source_id].ref_id
            for edge in graph.edges
            if edge.kind == EdgeKind.PREMISE_OF and edge.target_id == inference_node_id
            and node_by_id[edge.source_id].node_type == "proposition"
        }
        expected_premises = set(step.input_refs) & proposition_ids
        if actual_premises != expected_premises:
            raise ValueError(
                f"inference {step.id} premise edges do not match proposition input_refs"
            )
        actual_outputs = {
            node_by_id[edge.target_id].ref_id
            for edge in graph.edges
            if edge.kind == EdgeKind.DERIVES and edge.source_id == inference_node_id
            and node_by_id[edge.target_id].node_type == "proposition"
        }
        if actual_outputs != set(step.output_proposition_refs):
            raise ValueError(
                f"inference {step.id} derived edges do not match output_proposition_refs"
            )

    if reject_inference_cycles:
        cycle = find_inference_cycle(graph)
        if cycle:
            raise ValueError("inference dependency cycle: " + " -> ".join(cycle))
