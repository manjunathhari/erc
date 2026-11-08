"""Context-gated case reasoning orchestration.

This layer composes ERC-3.0 knowledge applicability with the existing ERC
reasoning orchestrator. It does not diagnose, recommend treatment, or execute
real-world actions. Inputs remain caller-supplied and provenance-bearing.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .application import (
    ApplicabilityStatus, ApplicationReport, GovernedKnowledge,
    CaseContext, apply_contextual_knowledge,
)
from .contracts import ReasoningRequest, ReasoningStatus
from .inference import ExecutionLimits
from .lifecycle import KnowledgeLifecycleLedger, KnowledgeStage
from .orchestration import (
    OrchestrationLimits, OrchestrationResult, StrategyCatalog, orchestrate,
)
from .rules import RuleSet


class CaseTaskStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    CONFLICTED = "conflicted"
    BLOCKED_CONTEXT = "blocked_context"
    BLOCKED_KNOWLEDGE = "blocked_knowledge"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class CaseReasoningPolicy:
    minimum_knowledge_stage: KnowledgeStage = KnowledgeStage.EVIDENCE_CORROBORATED
    allow_unknown_context_with_review: bool = False
    require_at_least_one_applicable_item: bool = True
    include_context_source_refs: bool = True


@dataclass(frozen=True, slots=True)
class CaseReasoningReport:
    request_id: str
    context_id: str
    status: CaseTaskStatus
    application_report: ApplicationReport
    orchestration: OrchestrationResult | None
    applied_knowledge_refs: tuple[str, ...]
    excluded_knowledge: tuple[tuple[str, str], ...]
    blocking_reasons: tuple[str, ...]
    review_requirements: tuple[str, ...]
    context_source_refs: tuple[str, ...]
    limitations: tuple[str, ...]


def orchestrate_case_reasoning(
    request: ReasoningRequest,
    context: CaseContext,
    knowledge_items: tuple[GovernedKnowledge, ...],
    lifecycle: KnowledgeLifecycleLedger,
    *,
    ruleset: RuleSet | None = None,
    catalog: StrategyCatalog | None = None,
    limits: OrchestrationLimits = OrchestrationLimits(),
    policy: CaseReasoningPolicy = CaseReasoningPolicy(),
    strategy_ref_override: str | None = None,
) -> CaseReasoningReport:
    """Run one reasoning task after explicit knowledge/context applicability gates.

    Definite knowledge conflicts and insufficient context block inference by
    default. With the explicit policy override, unknown context permits a
    review-only result; the engine still does not claim case applicability.
    """
    if request.task_type != context.task_type:
        raise ValueError("ReasoningRequest.task_type must exactly match CaseContext.task_type")
    if request.as_of is not None and request.as_of != context.as_of:
        raise ValueError("ReasoningRequest.as_of must match CaseContext.as_of")

    application = apply_contextual_knowledge(
        knowledge_items, context, lifecycle,
        minimum_stage=policy.minimum_knowledge_stage,
    )
    applied_statuses = {ApplicabilityStatus.APPLICABLE, ApplicabilityStatus.CONDITIONALLY_APPLICABLE}
    applicable = tuple(
        app.candidate_id for app in application.applications if app.status in applied_statuses
    )
    excluded = tuple(sorted(
        (app.candidate_id, app.status.value)
        for app in application.applications if app.status not in applied_statuses
    ))
    conflicted = tuple(app.candidate_id for app in application.applications
                       if app.status == ApplicabilityStatus.CONFLICTED)
    unknown = tuple(app.candidate_id for app in application.applications
                    if app.status == ApplicabilityStatus.INSUFFICIENT_CONTEXT)
    blockers: list[str] = []
    reviews: list[str] = []

    if conflicted:
        blockers.append("Conflicting applicable knowledge requires expert resolution: " + ", ".join(sorted(conflicted)))
    if unknown:
        message = "Some knowledge applicability conditions cannot be evaluated: " + ", ".join(sorted(unknown))
        if policy.allow_unknown_context_with_review and not conflicted:
            reviews.append(message)
        else:
            blockers.append(message)
    if policy.require_at_least_one_applicable_item and not applicable and not (unknown and policy.allow_unknown_context_with_review):
        blockers.append("No governed knowledge item is applicable to this context")

    source_refs = tuple(sorted({fact.source_ref for fact in context.facts}))
    if blockers:
        status = CaseTaskStatus.CONFLICTED if conflicted else (
            CaseTaskStatus.BLOCKED_CONTEXT if unknown else CaseTaskStatus.BLOCKED_KNOWLEDGE
        )
        return CaseReasoningReport(
            request.id, context.context_id, status, application, None, (), excluded,
            tuple(blockers), tuple(reviews), source_refs,
            ("Reasoning inference was not executed because a preflight gate failed.",
             "No real-world action or recommendation is generated by this gate."),
        )

    context_refs = set(request.context_refs)
    if policy.include_context_source_refs:
        context_refs.update(source_refs)
    prepared = replace(request, context_refs=tuple(sorted(context_refs)), as_of=context.as_of)
    result = orchestrate(prepared, ruleset=ruleset, catalog=catalog, limits=limits,
                         strategy_ref_override=strategy_ref_override)
    if result.result.status == ReasoningStatus.CONFLICT:
        status = CaseTaskStatus.CONFLICTED
        reviews.append("Reasoning propositions contain a definite conflict; expert review is required.")
    elif result.result.status == ReasoningStatus.PARTIAL:
        status = CaseTaskStatus.PARTIAL
        reviews.append("Reasoning execution was partial; inspect limits and trace before use.")
    elif result.result.status == ReasoningStatus.INDETERMINATE:
        status = CaseTaskStatus.REVIEW_REQUIRED
        reviews.append("The reasoning result is indeterminate; inspect missing evidence and uncertainty.")
    elif reviews:
        status = CaseTaskStatus.REVIEW_REQUIRED
    else:
        status = CaseTaskStatus.COMPLETED

    return CaseReasoningReport(
        request.id, context.context_id, status, application, result,
        tuple(sorted(applicable)), excluded, (), tuple(reviews), source_refs,
        ("Knowledge applicability is based only on explicit caller-supplied conditions.",
         "Evidence assessment and inference are limited to the supplied request snapshot.",
         "The output is decision support for human review, not an autonomous decision."),
    )
