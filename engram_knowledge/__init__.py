"""Engram's knowledge layers, outside the engine and working on the engine's own database. Fixed rules decide, never a language model.

P1, the store: models, schema, database, entities, facts, evidence, migrations, serialization.
P2, learning from sentences: interpreter, learning, candidate and learning_queue (P2.1 to P2.3, sentences to review envelopes), extraction,
normalizer, entity_resolver and fact_validator (a helper model's reply to checked facts). P2 uses P1; P1 uses nothing from P2.
P3 to P5, state over time: temporal, transition, conflict and state_engine (P3 projection, P4 changes and conflicts, P5 settle),
query_router, evidence_assembler and knowledge_retriever (structured questions beside ordinary memory). They use P1 and P2; neither uses them.

Names load on first use, so importing one storage file does not load the rest.
"""
import importlib

_HOME = dict(
    models=("Entity", "EntityAlias", "KnowledgeFact", "FactEvidence", "FactWithEvidence", "SourceSentence", "RecordError", "normalize_name", "tidy"),
    schema=("SCHEMA", "SCHEMA_VERSION"), database=("KnowledgeBase", "prepare"), evidence=("forget_sentence",), migrations=("migrate",),
    serialization=("export_knowledge", "import_knowledge", "backup", "integrity_report"),
    # P2: which entity a mention means, turning a helper model's reply into candidates, and whether a candidate may be stored
    entity_resolver=("EntityResolver", "Resolution"), extraction=("STRUCTURED_PROMPT", "parse_reply"),
    fact_validator=("ACCEPTED", "REJECTED", "UNCERTAIN", "Candidate", "Decision", "FactValidator", "KnowledgePipeline", "SourceLine"),
    # P3 to P5: what is true now and at any past date, changes and conflicts, people's decisions, and answering structured questions
    conflict=("Conflict",), state_engine=("Period", "SlotState", "StateEngine"), evidence_assembler=("EvidenceAssembler",),
    knowledge_retriever=("KnowledgeRetriever",), query_router=("QueryRouter",))
_WHERE = {name: module for module, names in _HOME.items() for name in names}
__all__ = sorted(_WHERE)


def __getattr__(name):
    if name in _WHERE: return getattr(importlib.import_module(f".{_WHERE[name]}", __name__), name)
    raise AttributeError(name)
