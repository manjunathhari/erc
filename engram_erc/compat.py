"""Deprecated names from the 0.4.0 surgical release, kept for one release.

Everything here maps a 0.4.0 name onto its ERC-4.0 General Core equivalent and emits a
``DeprecationWarning``. Nothing here changes behaviour: each old name returns
the very same class, function or enum member as the new name.

- Old class and function names resolve through module ``__getattr__`` hooks on
  the package and on each core module, so ``from engram_erc import X`` and
  ``from engram_erc.<module> import X`` both work for 0.4.0 code.
- Old enum members (``OptionAssessmentStatus.CONTRAINDICATED``, or by name
  ``OptionAssessmentStatus["CONTRAINDICATED"]``) are true aliases of the new
  members (attribute access to an enum alias cannot warn). Old enum *values*
  (``"contraindicated"`` ...) are accepted by the enum constructors, with a
  warning, e.g. when reading stored 0.4.0 data.
- Old field names are accepted by ``<Class>.from_legacy(**kwargs)`` on every
  dataclass that has a renamed field. Frozen slotted dataclasses cannot hold
  two names for one attribute, so old attribute *reads* are not supported.
"""
from __future__ import annotations

import dataclasses
import importlib
import sys
import warnings
from typing import Any, Callable

from .profiles.surgical import LEGACY_FIELDS, LEGACY_VALUES, legacy_kwargs

_PKG = __name__.rsplit(".", 1)[0]

# 0.4.0 name -> (module that defines the General Core name, General Core name)
DEPRECATED_NAMES: dict[str, tuple[str, str]] = {
    "SurgicalContext": ("application", "CaseContext"),
    "SurgicalReasoningPolicy": ("task_orchestration", "CaseReasoningPolicy"),
    "SurgicalReasoningReport": ("task_orchestration", "CaseReasoningReport"),
    "SurgicalTaskStatus": ("task_orchestration", "CaseTaskStatus"),
    "SurgicalTrajectory": ("temporal_patterns", "CaseTrajectory"),
    "SurgicalPatternSummary": ("longitudinal_learning", "CasePatternSummary"),
    "SurgicalKnowledgeGraph": ("knowledge_graph", "DomainKnowledgeGraph"),
    "SurgicalIntelligenceRequest": ("case_intelligence", "CaseIntelligenceRequest"),
    "SurgicalIntelligenceReport": ("case_intelligence", "CaseIntelligenceReport"),
    "ClinicianDecision": ("decision_support", "ReviewerDecision"),
    "ClinicianDecisionLedger": ("decision_support", "ReviewerDecisionLedger"),
    "ClinicianDisposition": ("decision_support", "ReviewerDisposition"),
    "orchestrate_surgical_reasoning": ("task_orchestration", "orchestrate_case_reasoning"),
    "compare_surgical_experience": ("experience_reasoning", "compare_case_experience"),
    "build_surgical_knowledge_graph": ("knowledge_graph", "build_knowledge_graph"),
    "execute_surgical_intelligence": ("case_intelligence", "execute_case_intelligence"),
    "record_clinician_decision": ("decision_support", "record_reviewer_decision"),
    "_validate_against_registry": ("longitudinal_learning", "_validate_against_source_records"),
}

# Enum class (module, name) -> {old member name: new member name}
DEPRECATED_MEMBERS: dict[tuple[str, str], dict[str, str]] = {
    ("decision_support", "OptionAssessmentStatus"): {"CONTRAINDICATED": "EXCLUDED"},
    ("decision_support", "DecisionSupportStatus"): {"READY_FOR_CLINICIAN_REVIEW": "READY_FOR_REVIEW"},
    ("temporal_patterns", "EpisodeOutcome"): {"COMPLICATION": "ADVERSE_EVENT"},
    ("knowledge_graph", "KnowledgeNodeKind"): {"ANATOMY": "ENTITY", "PROCEDURE": "ACTIVITY"},
    ("lifecycle", "EvidenceClass"): {
        "SURGICAL_EXPERIENCE": "PRACTITIONER_EXPERIENCE",
        "REGISTRY_ANALYSIS": "RECORDS_ANALYSIS",
        "OBSERVATIONAL_STUDY": "PUBLISHED_STUDY",
        "RANDOMIZED_TRIAL": "PUBLISHED_STUDY",
        "GUIDELINE": "STANDARD_OR_GUIDELINE",
    },
}

_CORE_MODULES = (
    "application", "calibration", "case_intelligence", "consolidation", "counterfactual",
    "decision_support", "experience_reasoning", "failure_analysis", "generalization",
    "improvement", "knowledge_graph", "knowledge_synthesis", "lifecycle",
    "longitudinal_learning", "prospective_learning", "recovery", "situation_awareness",
    "statistics", "task_orchestration", "temporal_external", "temporal_patterns",
)


def _warn(old: str, new: str, stacklevel: int = 3) -> None:
    warnings.warn(f"{old} is deprecated since ERC-4.0 General Core; use {new}. It will be removed in the next release.",
                  DeprecationWarning, stacklevel=stacklevel)


def resolve(old: str) -> Any:
    """Return the General Core object for a 0.4.0 name, with a DeprecationWarning."""
    module_name, new = DEPRECATED_NAMES[old]
    _warn(old, new)
    return getattr(importlib.import_module(f"{_PKG}.{module_name}"), new)


def _module_getattr(module: Any) -> Callable[[str], Any]:
    previous = module.__dict__.get("__getattr__")

    def __getattr__(name: str) -> Any:
        target = DEPRECATED_NAMES.get(name)
        if target is not None:
            module_name, new = target
            source = importlib.import_module(f"{_PKG}.{module_name}")
            if module is source or new in module.__dict__:
                _warn(f"{module.__name__}.{name}", new)
                return getattr(source, new)
        if previous is not None:
            return previous(name)
        raise AttributeError(f"module {module.__name__!r} has no attribute {name!r}")

    return __getattr__


def _install_name_hooks() -> None:
    for short in (*_CORE_MODULES, ""):
        full = f"{_PKG}.{short}" if short else _PKG
        module = sys.modules.get(full) or importlib.import_module(full)
        module.__getattr__ = _module_getattr(module)


def _install_enum_aliases() -> None:
    for (module_name, enum_name), members in DEPRECATED_MEMBERS.items():
        enum_cls = getattr(importlib.import_module(f"{_PKG}.{module_name}"), enum_name)
        for old, new in members.items():
            # A true Enum alias: reachable as Cls.OLD and Cls["OLD"], never iterated.
            setattr(enum_cls, old, enum_cls[new])
            enum_cls._member_map_[old] = enum_cls[new]
        legacy = {old_value: new_value for old_value, new_value in LEGACY_VALUES.items()
                  if new_value in {m.value for m in enum_cls}}

        def _missing_(cls, value, _legacy=legacy):
            if isinstance(value, str) and value in _legacy:
                _warn(f"{cls.__name__}({value!r})", f"{cls.__name__}({_legacy[value]!r})", stacklevel=5)
                return cls(_legacy[value])
            return None

        enum_cls._missing_ = classmethod(_missing_)


def _make_from_legacy(cls: type) -> classmethod:
    def from_legacy(klass, *args: Any, **kwargs: Any):
        """Construct from 0.4.0 keyword names and values (deprecated)."""
        _warn(f"{klass.__name__}.from_legacy", f"{klass.__name__}(...) with General Core field names")
        names = frozenset(f.name for f in dataclasses.fields(klass))
        return klass(*args, **legacy_kwargs(names, **kwargs))
    return classmethod(from_legacy)


def _install_from_legacy() -> None:
    renamed_targets = set(LEGACY_FIELDS.values()) | {"evidence_class", "kind", "outcome",
                                                     "historical_outcome"}
    for short in _CORE_MODULES:
        module = importlib.import_module(f"{_PKG}.{short}")
        for obj in list(vars(module).values()):
            if (isinstance(obj, type) and dataclasses.is_dataclass(obj)
                    and obj.__module__ == module.__name__
                    and {f.name for f in dataclasses.fields(obj)} & renamed_targets):
                obj.from_legacy = _make_from_legacy(obj)


def install() -> None:
    _install_enum_aliases()
    _install_from_legacy()
    _install_name_hooks()


__all__ = ["DEPRECATED_NAMES", "DEPRECATED_MEMBERS", "resolve", "install"]
