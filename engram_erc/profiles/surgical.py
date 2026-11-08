"""The surgical profile: the 0.4.0 surgical release's words, as a profile over the general core.

Labels here reproduce the 0.4.0 release's names and values exactly, so a surgical host
can show the words its users know. ``legacy_kwargs`` translates 0.4.0
keyword arguments (field names and enum values) onto the General Core names; it is used
by the deprecated ``from_legacy`` constructors and will be removed with them.
"""
from __future__ import annotations

from typing import Any

from ..knowledge_graph import KnowledgeNodeKind
from ..lifecycle import EvidenceClass
from ..temporal_patterns import EpisodeOutcome
from . import DomainProfile, register_profile

# 0.4.0 field name -> General Core field name.
LEGACY_FIELDS: dict[str, str] = {
    "procedure_ref": "activity_ref",
    "distinct_procedures": "distinct_activities",
    "min_distinct_procedures": "min_distinct_activities",
    "require_same_procedure": "require_same_activity",
    "procedure_match": "activity_match",
    "surgeon_ref": "practitioner_ref",
    "distinct_surgeons": "distinct_practitioners",
    "surgeon_action_refs": "practitioner_action_refs",
    "surgeon_perception_tags": "practitioner_perception_tags",
    "clinician_ref": "reviewer_ref",
    "surgical_context": "case_context",
    "contraindication_refs": "exclusion_refs",
    "clinical_outcome": "case_outcome",
    "complication": "adverse_event",
    "independent_of_local_registry": "independent_of_local_records",
}

# 0.4.0 evidence class values: surgical evidence types and their core class.
SURGICAL_EVIDENCE_TYPES: dict[str, EvidenceClass] = {
    "surgical_experience": EvidenceClass.PRACTITIONER_EXPERIENCE,
    "registry_analysis": EvidenceClass.RECORDS_ANALYSIS,
    "observational_study": EvidenceClass.PUBLISHED_STUDY,
    "randomized_trial": EvidenceClass.PUBLISHED_STUDY,
    "systematic_review": EvidenceClass.SYSTEMATIC_REVIEW,
    "guideline": EvidenceClass.STANDARD_OR_GUIDELINE,
    "expert_opinion": EvidenceClass.EXPERT_OPINION,
    "other": EvidenceClass.OTHER,
}

# 0.4.0 node kind values that became a core kind plus a subtype.
SURGICAL_NODE_SUBTYPES: dict[str, KnowledgeNodeKind] = {
    "anatomy": KnowledgeNodeKind.ENTITY,
    "procedure": KnowledgeNodeKind.ACTIVITY,
}

# Core value -> 0.4.0 value (display words).
SURGICAL_VALUE_LABELS: dict[str, str] = {
    "excluded": "contraindicated",
    "ready_for_review": "ready_for_clinician_review",
    "adverse_event": "complication",
    "practitioner_experience": "surgical_experience",
    "records_analysis": "registry_analysis",
    "standard_or_guideline": "guideline",
    "entity": "anatomy",
    "activity": "procedure",
    "task_or_activity_mismatch": "task_or_procedure_mismatch",
}

# 0.4.0 enum value -> General Core enum value, for values that were renamed.
LEGACY_VALUES: dict[str, str] = {
    "contraindicated": "excluded",
    "ready_for_clinician_review": "ready_for_review",
    "complication": "adverse_event",
    "surgical_experience": "practitioner_experience",
    "registry_analysis": "records_analysis",
    "observational_study": "published_study",
    "randomized_trial": "published_study",
    "guideline": "standard_or_guideline",
    "anatomy": "entity",
    "procedure": "activity",
}

SURGICAL_PROFILE = register_profile(DomainProfile(
    profile_id="surgical",
    version="1.0.0",
    case_label="patient case",
    activity_label="procedure",
    practitioner_label="surgeon",
    reviewer_label="clinician",
    exclusion_label="contraindicated",
    adverse_event_label="complication",
    evidence_classes=SURGICAL_EVIDENCE_TYPES,
    node_subtypes=SURGICAL_NODE_SUBTYPES,
    value_labels=SURGICAL_VALUE_LABELS,
))


def _value(v: Any) -> Any:
    return v.value if hasattr(v, "value") else v


def legacy_kwargs(_fields: frozenset[str] | None = None, /, **kwargs: Any) -> dict[str, Any]:
    """Translate 0.4.0 keyword arguments to General Core ones.

    - Renamed field names are mapped (``procedure_ref`` -> ``activity_ref`` ...).
    - A 0.4.0 evidence class string becomes the core class, and the 0.4.0 word is
      kept as ``evidence_label`` (unless one is given).
    - A 0.4.0 node kind ``"anatomy"``/``"procedure"`` becomes ENTITY/ACTIVITY
      with that word as ``subtype``, which keeps the 0.4.0 graph fingerprint.
    - A 0.4.0 outcome ``"complication"`` becomes ``ADVERSE_EVENT``.
    Supplying both an old and a new name for one field is an error.

    ``_fields`` (optional) is the target class's field names. When given, a
    node kind is converted only for a class with a ``subtype`` field, an
    evidence class only for a class with ``evidence_label``, and outcomes only
    for fields that exist, so unrelated ``kind``/``outcome`` fields are left alone.
    """
    def has(name: str) -> bool:
        return _fields is None or name in _fields

    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        new_key = LEGACY_FIELDS.get(key, key)
        if new_key in out:
            raise TypeError(f"field given twice (old and new name): {new_key}")
        out[new_key] = value
    if "evidence_class" in out and has("evidence_label"):
        raw = _value(out["evidence_class"])
        if isinstance(raw, str) and raw in SURGICAL_EVIDENCE_TYPES:
            out["evidence_class"] = SURGICAL_EVIDENCE_TYPES[raw]
            if raw not in {c.value for c in EvidenceClass}:
                out.setdefault("evidence_label", raw)
    if "kind" in out and has("subtype"):
        raw = _value(out["kind"])
        if isinstance(raw, str) and raw in SURGICAL_NODE_SUBTYPES:
            out["kind"] = SURGICAL_NODE_SUBTYPES[raw]
            out.setdefault("subtype", raw)
    for name in ("outcome", "case_outcome", "historical_outcome"):
        raw = _value(out.get(name))
        if raw == "complication":
            out[name] = EpisodeOutcome.ADVERSE_EVENT
    return out


__all__ = ["SURGICAL_PROFILE", "LEGACY_FIELDS", "LEGACY_VALUES", "SURGICAL_EVIDENCE_TYPES",
           "SURGICAL_NODE_SUBTYPES", "SURGICAL_VALUE_LABELS", "legacy_kwargs"]
