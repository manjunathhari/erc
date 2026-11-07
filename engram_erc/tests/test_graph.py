import unittest

from engram_erc import (
    EdgeKind, Evidence, EvidenceKind, EvidenceLink, EvidenceRelation,
    InferenceStep, Proposition, PropositionKind, ReasoningGraphBuilder,
    ReasoningGraphView, SourceKind, find_inference_cycle, validate_graph_bindings,
)


def proposition(pid, predicate="has"):
    return Proposition(pid, "patient_A", predicate, True)


def evidence(eid):
    return Evidence(eid, f"registry:{eid}", SourceKind.REGISTRY, EvidenceKind.OBSERVATION)


class GraphBuilderTests(unittest.TestCase):
    def test_add_nodes_and_evidence_links(self):
        b = ReasoningGraphBuilder()
        b.add_proposition(proposition("p1"))
        b.add_evidence(evidence("e1"))
        b.link_evidence(EvidenceLink("e1", "p1", EvidenceRelation.SUPPORTS))
        graph = b.build()
        view = ReasoningGraphView(graph, b.propositions, b.evidence, b.inference_steps)
        self.assertEqual([e.id for e in view.supporting_evidence("p1")], ["e1"])
        self.assertEqual(view.contradicting_evidence("p1"), ())

    def test_contradicting_and_qualifying_evidence_are_separate(self):
        b = ReasoningGraphBuilder()
        b.add_proposition(proposition("p1"))
        for eid in ("e1", "e2", "e3"):
            b.add_evidence(evidence(eid))
        b.link_evidence(EvidenceLink("e1", "p1", EvidenceRelation.SUPPORTS))
        b.link_evidence(EvidenceLink("e2", "p1", EvidenceRelation.CONTRADICTS))
        b.link_evidence(EvidenceLink("e3", "p1", EvidenceRelation.QUALIFIES))
        view = ReasoningGraphView(b.build(), b.propositions, b.evidence)
        result = view.evidence_by_relation("p1")
        self.assertEqual([e.id for e in result["supports"]], ["e1"])
        self.assertEqual([e.id for e in result["contradicts"]], ["e2"])
        self.assertEqual([e.id for e in result["qualifies"]], ["e3"])

    def test_inference_connections_and_traversal(self):
        b = ReasoningGraphBuilder()
        p1, p2, p3 = proposition("p1"), proposition("p2"), proposition("p3")
        for p in (p1, p2, p3):
            b.add_proposition(p)
        step = InferenceStep("i1", "deduction", ("p1", "p2"), ("p3",), "rule:test")
        b.add_inference(step)
        b.connect_inference("i1", premise_proposition_ids=("p1", "p2"),
                            output_proposition_ids=("p3",))
        view = ReasoningGraphView(b.build(), b.propositions, b.evidence, b.inference_steps)
        self.assertEqual({p.id for p in view.premises_for("i1")}, {"p1", "p2"})
        self.assertEqual([p.id for p in view.conclusions_from("i1")], ["p3"])
        self.assertEqual([i.id for i in view.inferences_using("p1")], ["i1"])

    def test_prerequisite_first_inference_order(self):
        b = ReasoningGraphBuilder()
        for p in (proposition("p0"), proposition("p1"), proposition("p2")):
            b.add_proposition(p)
        b.add_inference(InferenceStep("i1", "derive", ("p0",), ("p1",), "r1"))
        b.add_inference(InferenceStep("i2", "derive", ("p1",), ("p2",), "r2"))
        b.connect_inference("i1", premise_proposition_ids=("p0",), output_proposition_ids=("p1",))
        b.connect_inference("i2", premise_proposition_ids=("p1",), output_proposition_ids=("p2",))
        view = ReasoningGraphView(b.build(), b.propositions, b.evidence, b.inference_steps)
        self.assertEqual(view.inference_order(), ("i1", "i2"))

    def test_detects_indirect_inference_cycle(self):
        b = ReasoningGraphBuilder()
        for p in (proposition("p1"), proposition("p2")):
            b.add_proposition(p)
        b.add_inference(InferenceStep("i1", "derive", ("p2",), ("p1",), "r1"))
        b.add_inference(InferenceStep("i2", "derive", ("p1",), ("p2",), "r2"))
        b.connect_inference("i1", premise_proposition_ids=("p2",), output_proposition_ids=("p1",))
        b.connect_inference("i2", premise_proposition_ids=("p1",), output_proposition_ids=("p2",))
        graph = b.build(validate=False)
        self.assertIsNotNone(find_inference_cycle(graph))
        with self.assertRaisesRegex(ValueError, "inference dependency cycle"):
            validate_graph_bindings(graph, b.propositions, b.evidence, b.inference_steps)

    def test_non_inference_relationship_cycle_is_allowed(self):
        b = ReasoningGraphBuilder()
        b.add_proposition(proposition("p1"))
        b.add_proposition(proposition("p2"))
        n1, n2 = b.node_for("proposition", "p1"), b.node_for("proposition", "p2")
        b.add_edge(n1, n2, EdgeKind.RELATES_TO)
        b.add_edge(n2, n1, EdgeKind.RELATES_TO)
        self.assertEqual(len(b.build().edges), 2)

    def test_rejects_wrong_edge_endpoint_types(self):
        b = ReasoningGraphBuilder()
        b.add_proposition(proposition("p1"))
        b.add_evidence(evidence("e1"))
        pnode, enode = b.node_for("proposition", "p1"), b.node_for("evidence", "e1")
        b.add_edge(pnode, enode, EdgeKind.SUPPORTS)
        with self.assertRaisesRegex(ValueError, "invalid endpoints"):
            b.build()

    def test_ancestors_descendants_and_stable_export(self):
        b = ReasoningGraphBuilder()
        b.add_proposition(proposition("p1"))
        b.add_evidence(evidence("e1"))
        b.link_evidence(EvidenceLink("e1", "p1", EvidenceRelation.SUPPORTS))
        graph = b.build()
        view = ReasoningGraphView(graph, b.propositions, b.evidence)
        pnode = view.node_id("proposition", "p1")
        enode = view.node_id("evidence", "e1")
        self.assertEqual([n.id for n in view.ancestors(pnode)], [enode])
        self.assertEqual([n.id for n in view.descendants(enode)], [pnode])
        exported = view.to_dict()
        self.assertEqual(exported["schema_version"], "erc.graph.v1")
        self.assertEqual(exported, view.to_dict())


if __name__ == "__main__":
    unittest.main()
