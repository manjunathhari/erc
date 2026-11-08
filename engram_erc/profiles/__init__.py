"""Domain profiles: the words a field uses for the core's general concepts.

A profile is immutable and versioned. It supplies labels (what a case, an
activity, the practitioner, the reviewer and an exclusion are called) and maps
the profile's own evidence types and node subtypes onto core values.

The core never reads a profile to decide anything. Every rule, threshold,
status and fingerprint is computed from core values only, so the same input
gives the same decisions under every profile.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from ..knowledge_graph import KnowledgeNodeKind
from ..lifecycle import EvidenceClass


def _frozen(mapping: Mapping | None) -> Mapping:
    return MappingProxyType(dict(mapping or {}))


@dataclass(frozen=True, slots=True, eq=False)
class DomainProfile:
    profile_id: str
    version: str
    case_label: str
    activity_label: str
    practitioner_label: str
    reviewer_label: str
    exclusion_label: str
    adverse_event_label: str
    evidence_classes: Mapping[str, EvidenceClass] = field(default_factory=dict)
    node_subtypes: Mapping[str, KnowledgeNodeKind] = field(default_factory=dict)
    value_labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("profile_id", "version", "case_label", "activity_label",
                     "practitioner_label", "reviewer_label", "exclusion_label",
                     "adverse_event_label"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        for label, cls in dict(self.evidence_classes).items():
            if not label.strip() or not isinstance(cls, EvidenceClass):
                raise ValueError("evidence_classes must map non-empty labels to EvidenceClass")
        for label, kind in dict(self.node_subtypes).items():
            if not label.strip() or not isinstance(kind, KnowledgeNodeKind):
                raise ValueError("node_subtypes must map non-empty labels to KnowledgeNodeKind")
        for key, label in dict(self.value_labels).items():
            if not key.strip() or not label.strip():
                raise ValueError("value_labels must map non-empty core values to non-empty labels")
        object.__setattr__(self, "evidence_classes", _frozen(self.evidence_classes))
        object.__setattr__(self, "node_subtypes", _frozen(self.node_subtypes))
        object.__setattr__(self, "value_labels", _frozen(self.value_labels))

    # Identity is the (id, version) pair; two objects with the same pair are the same profile.
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DomainProfile):
            return NotImplemented
        return (self.profile_id, self.version) == (other.profile_id, other.version)

    def __hash__(self) -> int:
        return hash((self.profile_id, self.version))

    def label(self, core_value: Enum | str) -> str:
        """Return this profile's word for a core enum value (display only)."""
        value = core_value.value if isinstance(core_value, Enum) else str(core_value)
        if value in self.value_labels:
            return self.value_labels[value]
        return value.replace("_", " ")

    def evidence_class(self, evidence_label: str) -> EvidenceClass:
        """Map one of this profile's evidence types to the core class."""
        try:
            return self.evidence_classes[evidence_label]
        except KeyError:
            raise ValueError(f"profile {self.profile_id!r} has no evidence type {evidence_label!r}") from None

    def node_kind(self, subtype: str) -> KnowledgeNodeKind:
        """Map one of this profile's node subtypes to the core node kind."""
        try:
            return self.node_subtypes[subtype]
        except KeyError:
            raise ValueError(f"profile {self.profile_id!r} has no node subtype {subtype!r}") from None


_REGISTRY: dict[str, DomainProfile] = {}


def register_profile(profile: DomainProfile) -> DomainProfile:
    """Register a profile by id. Re-registering the same (id, version) is a no-op."""
    existing = _REGISTRY.get(profile.profile_id)
    if existing is not None and existing.version != profile.version:
        raise ValueError(f"profile {profile.profile_id!r} is already registered at version {existing.version}")
    _REGISTRY[profile.profile_id] = profile
    return profile


def get_profile(profile_id: str) -> DomainProfile:
    """Return a registered profile by id."""
    try:
        return _REGISTRY[profile_id]
    except KeyError:
        raise ValueError(f"unknown profile_id: {profile_id!r}") from None


def registered_profiles() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


__all__ = ["DomainProfile", "get_profile", "register_profile", "registered_profiles"]
