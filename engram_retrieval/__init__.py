"""Engram Retrieval Foundation (Roadmap B7, Plan Stage 4).

A standalone package beside the engine, connected to nothing. It takes a unit (an id, a kind, the text, and a day
or none) and gives back ranked ids: by meaning (VectorIndex), by words (LexicalIndex), or both fused
(HybridSearch). Three measures judge a ranked answer.

It reads no Engram table and imports no Engram or ERC module, and nothing outside this folder imports it.
The embedding model is handed in from outside; this package contains none.
"""
from ._common import AddReport, Hit, IndexMismatch, Unit
from .hybrid import HybridSearch
from .lexical import LexicalIndex
from .measures import mrr, ndcg_at_k, recall_at_k
from .vector import VectorIndex

__all__ = ["Unit", "Hit", "AddReport", "IndexMismatch", "VectorIndex", "LexicalIndex", "HybridSearch",
           "recall_at_k", "mrr", "ndcg_at_k"]
