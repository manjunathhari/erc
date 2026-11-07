import unittest
from datetime import datetime, timezone

from engram_erc import (
    EdgeKind, Evidence, EvidenceKind, EvidenceLink, EvidenceRelation, GraphEdge,
    GraphNode, Proposition, ReasoningGraph, ReasoningRequest, SourceKind,
    TimeInterval, validate_graph_bindings,
)


class ContractTests(unittest.TestCase):
    def test_request_rejects_dangling_evidence_link(self):
        p = Proposition("p1", "patient", "has", "fever")
        e = Evidence("e1", "record:1", SourceKind.REGISTRY)
        with self.assertRaises(ValueError):
            ReasoningRequest("r1", "evaluate", (p,), (e,),
                             (EvidenceLink("missing", "p1", EvidenceRelation.SUPPORTS),))

    def test_time_interval_requires_aware_datetimes(self):
        with self.assertRaises(ValueError):
            TimeInterval(datetime(2026, 1, 1), None)

    def test_graph_rejects_dangling_edge(self):
        node = GraphNode("n1", "proposition", "p1")
        edge = GraphEdge("g1", "n1", "missing", EdgeKind.SUPPORTS)
        with self.assertRaises(ValueError):
            ReasoningGraph((node,), (edge,))

    def test_valid_graph_bindings(self):
        p = Proposition("p1", "patient", "has", "fever")
        e = Evidence("e1", "registry:row-1", SourceKind.REGISTRY, EvidenceKind.OBSERVATION)
        graph = ReasoningGraph(
            (GraphNode("np1", "proposition", "p1"), GraphNode("ne1", "evidence", "e1")),
            (GraphEdge("g1", "ne1", "np1", EdgeKind.SUPPORTS),),
        )
        validate_graph_bindings(graph, (p,), (e,))


if __name__ == "__main__":
    unittest.main()
