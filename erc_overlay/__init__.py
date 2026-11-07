"""ERC as an overlay on Engram: it reads the knowledge layers (P1 to P5) through a read-only adapter and reasons with engram_erc.

It stores nothing and changes nothing, so with ERC unused, or used, the engine and every layer behave exactly as before.
"""
from .knowledge import FUNCTIONAL, AdaptedRequest, KnowledgeAdapter
from .reasoner import Reasoner, Reasoning

__all__ = ["FUNCTIONAL", "AdaptedRequest", "KnowledgeAdapter", "Reasoner", "Reasoning"]
