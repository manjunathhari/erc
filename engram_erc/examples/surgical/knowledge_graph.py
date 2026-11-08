"""Synthetic ERC-3.9 example: shared mechanism across two surgical domains."""
from datetime import datetime, timezone
from engram_erc.knowledge_graph import (
    KnowledgeNodeKind, KnowledgeRelation, KnowledgeNode, KnowledgeEdge,
    CrossDomainQuery, build_knowledge_graph, reason_across_domains,
)

nodes = (
    KnowledgeNode("procedure:colorectal", KnowledgeNodeKind.ACTIVITY, "Colorectal procedure", "colorectal", ("registry:pattern-1",), "review:1", subtype="procedure"),
    KnowledgeNode("mechanism:tension", KnowledgeNodeKind.MECHANISM, "Tissue tension mechanism", "shared_mechanism", ("paper:mechanism-1",), "review:2"),
    KnowledgeNode("procedure:upper-gi", KnowledgeNodeKind.ACTIVITY, "Upper GI procedure", "upper_gi", ("registry:pattern-2",), "review:3", subtype="procedure"),
)
edges = (
    KnowledgeEdge("edge:1", "procedure:colorectal", "mechanism:tension", KnowledgeRelation.HAS_MECHANISM, ("review:1",), "review:1"),
    KnowledgeEdge("edge:2", "mechanism:tension", "procedure:upper-gi", KnowledgeRelation.SHARES_MECHANISM, ("review:2",), "review:2", ("paper:mechanism-1",)),
)
graph = build_knowledge_graph(nodes, edges)
report = reason_across_domains(
    graph,
    (CrossDomainQuery("query:1", "procedure:colorectal", "procedure:upper-gi", "Is the mechanism relevant across domains?"),),
    generated_at=datetime.now(timezone.utc),
)
print(report.findings[0].status.value)
print(report.findings[0].limitations)
