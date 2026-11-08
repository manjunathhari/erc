"""Deterministic, context-aware application of governed knowledge.

ERC assesses applicability; it does not diagnose, prescribe, or execute a
real-world action. All case context and applicability constraints are
explicit caller-supplied structured data with provenance references.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TypeAlias

from .contracts import require_aware_datetime
from .consolidation import ExperienceCandidate
from .lifecycle import KnowledgeLifecycleLedger, KnowledgeStage

Scalar: TypeAlias = str | int | float | bool


class ConditionOperator(str, Enum):
    EQUALS = "equals"
    ONE_OF = "one_of"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    PRESENT = "present"
    ABSENT = "absent"


class ConditionPolarity(str, Enum):
    REQUIRED = "required"
    EXCLUSION = "exclusion"


class ApplicabilityStatus(str, Enum):
    APPLICABLE = "applicable"
    CONDITIONALLY_APPLICABLE = "conditionally_applicable"
    NOT_APPLICABLE = "not_applicable"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    NOT_GOVERNED = "not_governed"
    CONFLICTED = "conflicted"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ContextFact:
    key: str
    value: Scalar
    source_ref: str
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.source_ref.strip():
            raise ValueError("context fact key and source_ref must be non-empty")
        if isinstance(self.value, float) and (self.value != self.value or abs(self.value) == float("inf")):
            raise ValueError("context fact value must be finite")
        if self.observed_at is not None:
            require_aware_datetime(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class CaseContext:
    context_id: str
    task_type: str
    activity_ref: str
    facts: tuple[ContextFact, ...]
    as_of: datetime
    site_ref: str | None = None

    def __post_init__(self) -> None:
        for name in ("context_id", "task_type", "activity_ref"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        require_aware_datetime(self.as_of, "as_of")
        keys = [f.key for f in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("context facts must have unique keys")
        if self.site_ref is not None and not self.site_ref.strip():
            raise ValueError("site_ref cannot be blank")


@dataclass(frozen=True, slots=True)
class ApplicabilityCondition:
    condition_id: str
    key: str
    operator: ConditionOperator
    polarity: ConditionPolarity = ConditionPolarity.REQUIRED
    value: Scalar | tuple[Scalar, ...] | None = None
    rationale: str = ""
    max_age_hours: float | None = None

    def __post_init__(self) -> None:
        if not self.condition_id.strip() or not self.key.strip():
            raise ValueError("condition_id and key must be non-empty")
        if self.operator in {ConditionOperator.EQUALS, ConditionOperator.MINIMUM, ConditionOperator.MAXIMUM} and self.value is None:
            raise ValueError(f"{self.operator.value} requires a value")
        if self.operator == ConditionOperator.ONE_OF and (not isinstance(self.value, tuple) or not self.value):
            raise ValueError("one_of requires a non-empty tuple")
        if self.operator in {ConditionOperator.PRESENT, ConditionOperator.ABSENT} and self.value is not None:
            raise ValueError("present/absent do not take a value")
        if self.operator in {ConditionOperator.MINIMUM, ConditionOperator.MAXIMUM} and (isinstance(self.value, bool) or not isinstance(self.value, (int, float))):
            raise ValueError("minimum/maximum require a numeric value")
        if self.max_age_hours is not None and self.max_age_hours <= 0:
            raise ValueError("max_age_hours must be > 0")


@dataclass(frozen=True, slots=True)
class GovernedKnowledge:
    candidate: ExperienceCandidate
    topic_key: str
    stance: str
    conditions: tuple[ApplicabilityCondition, ...]
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    conflict_refs: tuple[str, ...] = ()
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("topic_key", "stance"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        for name in ("source_refs", "evidence_refs", "conflict_refs"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        if not self.source_refs:
            raise ValueError("governed knowledge requires source provenance")
        if self.valid_from is not None:
            require_aware_datetime(self.valid_from, "valid_from")
        if self.valid_until is not None:
            require_aware_datetime(self.valid_until, "valid_until")
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be later than valid_from")
        ids = [c.condition_id for c in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("condition IDs must be unique")


@dataclass(frozen=True, slots=True)
class ConditionResult:
    condition_id: str
    key: str
    polarity: ConditionPolarity
    matched: bool | None
    observed_value: Scalar | None
    context_source_ref: str | None
    explanation: str


@dataclass(frozen=True, slots=True)
class KnowledgeApplication:
    candidate_id: str
    context_id: str
    status: ApplicabilityStatus
    lifecycle_stage: KnowledgeStage
    matched_conditions: tuple[str, ...]
    failed_conditions: tuple[str, ...]
    unknown_conditions: tuple[str, ...]
    condition_results: tuple[ConditionResult, ...]
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    conflict_refs: tuple[str, ...]
    rationale: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ApplicationReport:
    context_id: str
    applications: tuple[KnowledgeApplication, ...]
    conflicting_candidate_groups: tuple[tuple[str, ...], ...]
    limitations: tuple[str, ...]


def _evaluate_condition(condition: ApplicabilityCondition, facts: dict[str, ContextFact], context_time: datetime) -> ConditionResult:
    fact = facts.get(condition.key)
    if condition.operator == ConditionOperator.ABSENT:
        matched = fact is None
        return ConditionResult(condition.condition_id, condition.key, condition.polarity, matched,
                               None if fact is None else fact.value,
                               None if fact is None else fact.source_ref,
                               "Required absence observed" if matched else "Fact is present")
    if fact is None:
        return ConditionResult(condition.condition_id, condition.key, condition.polarity, None, None, None,
                               "Required context fact was not supplied")
    if condition.max_age_hours is not None:
        if fact.observed_at is None:
            return ConditionResult(condition.condition_id, condition.key, condition.polarity, None, fact.value, fact.source_ref,
                                   "Freshness cannot be checked because observed_at is missing")
        age_hours = (context_time - fact.observed_at).total_seconds() / 3600
        if age_hours < 0:
            return ConditionResult(condition.condition_id, condition.key, condition.polarity, None, fact.value, fact.source_ref,
                                   "Context fact is dated after the application time")
        if age_hours > condition.max_age_hours:
            return ConditionResult(condition.condition_id, condition.key, condition.polarity, None, fact.value, fact.source_ref,
                                   "Context fact exceeds the configured freshness window")
    value = condition.value
    try:
        if condition.operator == ConditionOperator.PRESENT:
            matched = True
        elif condition.operator == ConditionOperator.EQUALS:
            matched = type(fact.value) is type(value) and fact.value == value
        elif condition.operator == ConditionOperator.ONE_OF:
            matched = any(type(fact.value) is type(v) and fact.value == v for v in value)  # type: ignore[union-attr]
        elif condition.operator == ConditionOperator.MINIMUM:
            matched = not isinstance(fact.value, bool) and isinstance(fact.value, (int, float)) and fact.value >= value  # type: ignore[operator]
        elif condition.operator == ConditionOperator.MAXIMUM:
            matched = not isinstance(fact.value, bool) and isinstance(fact.value, (int, float)) and fact.value <= value  # type: ignore[operator]
        else:
            matched = None
    except (TypeError, ValueError):
        matched = None
    return ConditionResult(condition.condition_id, condition.key, condition.polarity, matched,
                           fact.value, fact.source_ref,
                           "Condition matched" if matched else "Condition did not match" if matched is False else "Values are not comparable")


def assess_knowledge_application(
    knowledge: GovernedKnowledge,
    context: CaseContext,
    lifecycle: KnowledgeLifecycleLedger,
    *,
    minimum_stage: KnowledgeStage = KnowledgeStage.EVIDENCE_CORROBORATED,
) -> KnowledgeApplication:
    """Evaluate one knowledge item against one explicit case context."""
    stage = lifecycle.current_stage(knowledge.candidate.candidate_id)
    base = dict(candidate_id=knowledge.candidate.candidate_id, context_id=context.context_id,
                lifecycle_stage=stage, source_refs=knowledge.source_refs,
                evidence_refs=knowledge.evidence_refs, conflict_refs=knowledge.conflict_refs)
    limitations = list(knowledge.limitations)
    limitations.extend((
        "Applicability is only as complete and accurate as the structured context supplied by the caller.",
        "This result is not a diagnosis, order, case-specific recommendation or substitute for reviewer judgement.",
        "ERC does not infer missing case facts, estimate case risk, or grade source quality in this application step.",
    ))
    if stage in {KnowledgeStage.REJECTED, KnowledgeStage.SUPERSEDED, KnowledgeStage.RETIRED}:
        return KnowledgeApplication(**base, status=ApplicabilityStatus.NOT_GOVERNED,
            matched_conditions=(), failed_conditions=(), unknown_conditions=(), condition_results=(),
            rationale=("Knowledge item is in a terminal lifecycle state",), limitations=tuple(limitations))
    if list(KnowledgeStage).index(stage) < list(KnowledgeStage).index(minimum_stage):
        return KnowledgeApplication(**base, status=ApplicabilityStatus.NOT_GOVERNED,
            matched_conditions=(), failed_conditions=(), unknown_conditions=(), condition_results=(),
            rationale=("Knowledge item has not reached the required governance stage",), limitations=tuple(limitations))
    if knowledge.valid_from and context.as_of < knowledge.valid_from:
        return KnowledgeApplication(**base, status=ApplicabilityStatus.NOT_APPLICABLE,
            matched_conditions=(), failed_conditions=(), unknown_conditions=(), condition_results=(),
            rationale=("Knowledge item is not yet effective",), limitations=tuple(limitations))
    if knowledge.valid_until and context.as_of >= knowledge.valid_until:
        return KnowledgeApplication(**base, status=ApplicabilityStatus.EXPIRED,
            matched_conditions=(), failed_conditions=(), unknown_conditions=(), condition_results=(),
            rationale=("Knowledge item has passed its validity end date",), limitations=tuple(limitations))
    if knowledge.candidate.task_type != context.task_type or knowledge.candidate.activity_ref != context.activity_ref:
        return KnowledgeApplication(**base, status=ApplicabilityStatus.NOT_APPLICABLE,
            matched_conditions=(), failed_conditions=("task_or_activity_mismatch",), unknown_conditions=(), condition_results=(),
            rationale=("Task type or activity reference does not match exactly",), limitations=tuple(limitations))
    facts = {f.key: f for f in context.facts}
    results = tuple(_evaluate_condition(c, facts, context.as_of) for c in knowledge.conditions)
    matched = tuple(r.condition_id for r in results if r.matched is True)
    failed_required = tuple(r.condition_id for r in results if r.matched is False and r.polarity == ConditionPolarity.REQUIRED)
    matched_exclusions = tuple(r.condition_id for r in results if r.matched is True and r.polarity == ConditionPolarity.EXCLUSION)
    unknown_required = tuple(r.condition_id for r in results if r.matched is None and r.polarity == ConditionPolarity.REQUIRED)
    unknown_exclusions = tuple(r.condition_id for r in results if r.matched is None and r.polarity == ConditionPolarity.EXCLUSION)
    if knowledge.conflict_refs:
        status = ApplicabilityStatus.CONFLICTED
        rationale = ("Unresolved knowledge conflict references are attached",)
    elif matched_exclusions:
        status = ApplicabilityStatus.NOT_APPLICABLE
        rationale = ("At least one explicit exclusion condition matched",)
    elif failed_required:
        status = ApplicabilityStatus.NOT_APPLICABLE
        rationale = ("At least one required applicability condition failed",)
    elif unknown_required or unknown_exclusions:
        status = ApplicabilityStatus.INSUFFICIENT_CONTEXT
        rationale = ("One or more applicability conditions cannot be evaluated from supplied context",)
    else:
        status = ApplicabilityStatus.APPLICABLE if results else ApplicabilityStatus.CONDITIONALLY_APPLICABLE
        rationale = (("All explicit applicability conditions matched",) if results else
                     ("No explicit applicability conditions were supplied; manual context review is required",))
    return KnowledgeApplication(**base, status=status, matched_conditions=matched,
        failed_conditions=failed_required + matched_exclusions,
        unknown_conditions=unknown_required + unknown_exclusions,
        condition_results=results, rationale=rationale, limitations=tuple(limitations))


def apply_contextual_knowledge(
    knowledge_items: tuple[GovernedKnowledge, ...], context: CaseContext,
    lifecycle: KnowledgeLifecycleLedger,
    *, minimum_stage: KnowledgeStage = KnowledgeStage.EVIDENCE_CORROBORATED,
) -> ApplicationReport:
    """Assess a set of items and flag opposing stances in the same topic group."""
    applications = [assess_knowledge_application(k, context, lifecycle, minimum_stage=minimum_stage)
                    for k in knowledge_items]
    eligible_by_topic: dict[str, list[tuple[int, str]]] = {}
    for i, item in enumerate(knowledge_items):
        if applications[i].status in {ApplicabilityStatus.APPLICABLE, ApplicabilityStatus.CONDITIONALLY_APPLICABLE}:
            eligible_by_topic.setdefault(item.topic_key, []).append((i, item.stance))
    conflict_groups: list[tuple[str, ...]] = []
    for members in eligible_by_topic.values():
        stances = {stance for _, stance in members}
        if len(stances) > 1:
            refs = tuple(sorted(knowledge_items[i].candidate.candidate_id for i, _ in members))
            conflict_groups.append(refs)
            for i, _ in members:
                old = applications[i]
                applications[i] = KnowledgeApplication(
                    candidate_id=old.candidate_id, context_id=old.context_id,
                    status=ApplicabilityStatus.CONFLICTED, lifecycle_stage=old.lifecycle_stage,
                    matched_conditions=old.matched_conditions, failed_conditions=old.failed_conditions,
                    unknown_conditions=old.unknown_conditions, condition_results=old.condition_results,
                    source_refs=old.source_refs, evidence_refs=old.evidence_refs,
                    conflict_refs=tuple(sorted(set(old.conflict_refs).union(refs))),
                    rationale=old.rationale + ("Opposing stances are applicable within the same topic; expert resolution required",),
                    limitations=old.limitations)
    return ApplicationReport(context.context_id, tuple(applications), tuple(sorted(conflict_groups)), (
        "Exact task and activity matching is intentionally conservative; aliases and semantic matching belong in a separately audited resolver.",
        "Condition semantics are deterministic and typed; no LLM-generated condition is trusted without caller validation.",
        "Conflicting applicable knowledge is surfaced, never silently ranked or resolved.",
    ))
