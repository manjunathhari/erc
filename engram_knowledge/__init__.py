"""Engram's knowledge layer (P1): typed records traced to their sentences, entities and aliases, the review queue, migrations,
and export, import and backup. It sits outside the engine and works on the engine's own database. Fixed rules decide, never a language model.

Names load on first use, so importing one storage file does not load the rest.
"""
import importlib

_HOME = dict(
    models=("Entity", "EntityAlias", "KnowledgeFact", "FactEvidence", "FactWithEvidence", "SourceSentence", "RecordError", "normalize_name", "tidy"),
    schema=("SCHEMA", "SCHEMA_VERSION"), database=("KnowledgeBase", "prepare"), evidence=("forget_sentence",), migrations=("migrate",),
    serialization=("export_knowledge", "import_knowledge", "backup", "integrity_report"))
_WHERE = {name: module for module, names in _HOME.items() for name in names}
__all__ = sorted(_WHERE)


def __getattr__(name):
    if name in _WHERE: return getattr(importlib.import_module(f".{_WHERE[name]}", __name__), name)
    raise AttributeError(name)
