from datetime import datetime, timezone
import pytest

from engram_erc.knowledge_graph import (
    KnowledgeNodeKind, KnowledgeRelation, TransferStatus,
    KnowledgeNode, KnowledgeEdge, CrossDomainPolicy, CrossDomainQuery,
    build_knowledge_graph, reason_across_domains,
)

NOW = datetime(2026, 11, 8, 10, 0, tzinfo=timezone.utc)


def node(ref, kind, domain, label=None, subtype=None):
    return KnowledgeNode(ref, kind, label or ref, domain, (f"src:{ref}",), f"prov:{ref}", subtype=subtype)


def edge(ref, a, b, relation, evidence=()):
    return KnowledgeEdge(ref, a, b, relation, (f"src:{ref}",), f"prov:{ref}", tuple(evidence))


def query():
    return CrossDomainQuery("q1", "proc:a", "proc:b", "Can the mechanism inform another procedure?")


def test_mechanistic_bridge_is_candidate_with_evidence_and_limitations():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "colorectal", subtype="procedure"),
         node("mech:1", KnowledgeNodeKind.MECHANISM, "shared"),
         node("proc:b", KnowledgeNodeKind.ACTIVITY, "upper_gi", subtype="procedure")],
        [edge("e1", "proc:a", "mech:1", KnowledgeRelation.HAS_MECHANISM),
         edge("e2", "mech:1", "proc:b", KnowledgeRelation.SHARES_MECHANISM, ("paper:1",))],
    )
    report = reason_across_domains(graph, [query()], generated_at=NOW)
    finding = report.findings[0]
    assert finding.status == TransferStatus.MECHANISTIC_BRIDGE_CANDIDATE
    assert finding.paths[0].evidence_refs == ("paper:1",)
    assert "not proof" in finding.paths[0].limitations[0]


def test_analogy_is_hypothesis_not_transfer():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "colorectal", subtype="procedure"),
         node("proc:b", KnowledgeNodeKind.ACTIVITY, "hpb", subtype="procedure")],
        [edge("e1", "proc:a", "proc:b", KnowledgeRelation.ANALOGOUS_TO)],
    )
    result = reason_across_domains(graph, [query()], generated_at=NOW)
    assert result.findings[0].status == TransferStatus.ANALOGICAL_HYPOTHESIS


def test_analogy_can_be_disabled():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure"), node("proc:b", KnowledgeNodeKind.ACTIVITY, "b", subtype="procedure")],
        [edge("e1", "proc:a", "proc:b", KnowledgeRelation.ANALOGOUS_TO)],
    )
    result = reason_across_domains(graph, [query()], generated_at=NOW,
                                   policy=CrossDomainPolicy(allow_analogical_hypotheses=False))
    assert result.findings[0].status == TransferStatus.TRANSFER_NOT_JUSTIFIED


def test_no_path_reported():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure"), node("proc:b", KnowledgeNodeKind.ACTIVITY, "b", subtype="procedure")], [])
    result = reason_across_domains(graph, [query()], generated_at=NOW)
    assert result.findings[0].status == TransferStatus.NO_PATH
    assert result.findings[0].paths == ()


def test_same_domain_path_not_cross_domain_transfer():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "colorectal", subtype="procedure"),
         node("event:1", KnowledgeNodeKind.EVENT, "colorectal"),
         node("proc:b", KnowledgeNodeKind.ACTIVITY, "colorectal", subtype="procedure")],
        [edge("e1", "proc:a", "event:1", KnowledgeRelation.INVOLVES),
         edge("e2", "event:1", "proc:b", KnowledgeRelation.ASSOCIATED_WITH)],
    )
    result = reason_across_domains(graph, [query()], generated_at=NOW)
    assert result.findings[0].status == TransferStatus.SAME_DOMAIN_PATH


def test_unqualified_cross_domain_connectivity_not_justified():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure"), node("concept:x", KnowledgeNodeKind.CONCEPT, "shared"),
         node("proc:b", KnowledgeNodeKind.ACTIVITY, "b", subtype="procedure")],
        [edge("e1", "proc:a", "concept:x", KnowledgeRelation.ASSOCIATED_WITH),
         edge("e2", "concept:x", "proc:b", KnowledgeRelation.ASSOCIATED_WITH)],
    )
    result = reason_across_domains(graph, [query()], generated_at=NOW)
    assert result.findings[0].status == TransferStatus.TRANSFER_NOT_JUSTIFIED


def test_shared_mechanism_requires_evidence_reference():
    with pytest.raises(ValueError, match="evidence_refs"):
        edge("e", "a", "b", KnowledgeRelation.SHARES_MECHANISM)


def test_unknown_edge_endpoint_rejected():
    with pytest.raises(ValueError, match="unknown node"):
        build_knowledge_graph([node("a", KnowledgeNodeKind.CONCEPT, "x")],
                                       [edge("e", "a", "missing", KnowledgeRelation.IS_A)])


def test_duplicate_node_ids_rejected():
    n = node("a", KnowledgeNodeKind.CONCEPT, "x")
    with pytest.raises(ValueError, match="node_ref"):
        build_knowledge_graph([n, n], [])


def test_duplicate_query_ids_rejected():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure"), node("proc:b", KnowledgeNodeKind.ACTIVITY, "b", subtype="procedure")], [])
    with pytest.raises(ValueError, match="query_ref"):
        reason_across_domains(graph, [query(), query()], generated_at=NOW)


def test_unknown_query_node_rejected():
    graph = build_knowledge_graph([node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure")], [])
    with pytest.raises(ValueError, match="unknown node"):
        reason_across_domains(graph, [query()], generated_at=NOW)


def test_hop_limit_is_enforced():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure"), node("c1", KnowledgeNodeKind.CONCEPT, "x"),
         node("c2", KnowledgeNodeKind.CONCEPT, "y"), node("proc:b", KnowledgeNodeKind.ACTIVITY, "b", subtype="procedure")],
        [edge("e1", "proc:a", "c1", KnowledgeRelation.ASSOCIATED_WITH),
         edge("e2", "c1", "c2", KnowledgeRelation.ASSOCIATED_WITH),
         edge("e3", "c2", "proc:b", KnowledgeRelation.ASSOCIATED_WITH)],
    )
    result = reason_across_domains(graph, [query()], generated_at=NOW,
                                   policy=CrossDomainPolicy(max_hops=2))
    assert result.findings[0].status == TransferStatus.NO_PATH


def test_cycles_do_not_cause_unbounded_traversal():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure"), node("c1", KnowledgeNodeKind.CONCEPT, "x"),
         node("proc:b", KnowledgeNodeKind.ACTIVITY, "b", subtype="procedure")],
        [edge("e1", "proc:a", "c1", KnowledgeRelation.ASSOCIATED_WITH),
         edge("e2", "c1", "proc:a", KnowledgeRelation.ASSOCIATED_WITH),
         edge("e3", "c1", "proc:b", KnowledgeRelation.ANALOGOUS_TO)],
    )
    result = reason_across_domains(graph, [query()], generated_at=NOW)
    assert len(result.findings[0].paths) == 1


def test_graph_fingerprint_is_order_independent():
    a, b = node("a", KnowledgeNodeKind.CONCEPT, "x"), node("b", KnowledgeNodeKind.CONCEPT, "y")
    e = edge("e", "a", "b", KnowledgeRelation.IS_A)
    g1 = build_knowledge_graph([a, b], [e])
    g2 = build_knowledge_graph([b, a], [e])
    assert g1.graph_fingerprint == g2.graph_fingerprint


def test_path_carries_node_and_edge_provenance():
    graph = build_knowledge_graph(
        [node("proc:a", KnowledgeNodeKind.ACTIVITY, "a", subtype="procedure"), node("proc:b", KnowledgeNodeKind.ACTIVITY, "b", subtype="procedure")],
        [edge("e1", "proc:a", "proc:b", KnowledgeRelation.ANALOGOUS_TO)],
    )
    path = reason_across_domains(graph, [query()], generated_at=NOW).findings[0].paths[0]
    assert "src:proc:a" in path.source_refs and "src:e1" in path.source_refs
    assert path.edge_refs == ("e1",)


def test_report_requires_timezone_aware_timestamp():
    graph = build_knowledge_graph([], [])
    with pytest.raises(ValueError):
        reason_across_domains(graph, [], generated_at=datetime(2026, 11, 8))
