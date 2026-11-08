"""The general profile: the core's own neutral words. This is the default."""
from __future__ import annotations

from ..knowledge_graph import KnowledgeNodeKind
from ..lifecycle import EvidenceClass
from . import DomainProfile, register_profile

GENERAL_PROFILE = register_profile(DomainProfile(
    profile_id="general",
    version="1.0.0",
    case_label="case",
    activity_label="activity",
    practitioner_label="practitioner",
    reviewer_label="reviewer",
    exclusion_label="excluded",
    adverse_event_label="adverse event",
    evidence_classes={cls.value: cls for cls in EvidenceClass},
    node_subtypes={kind.value: kind for kind in KnowledgeNodeKind},
    value_labels={},
))

__all__ = ["GENERAL_PROFILE"]
