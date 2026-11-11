"""Deterministic strategy selection and multi-operation reasoning orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable, Mapping

from .contracts import (
    ReasoningRequest, ReasoningResult, ReasoningStatus, TraceEntry,
    UncertaintyItem, UncertaintyKind, Proposition,
)
from .graph import ReasoningGraphBuilder, ReasoningGraphView
from .inference import ExecutionLimits, RuleExecution, execute_rules
from .primitives.contradiction import (
    Contradiction, ContradictionCertainty, find_contradictions,
)
from .primitives.evidence_assessment import (
    EvidenceAssessment, EvidenceAssessmentStatus, assess_evidence,
)
from .rules import RuleSet
from .temporal_requirements import RESOLUTION_HINT, _describe_not_applied, check_temporal_requirements

# ERC 0.7.0: the engine reports the package's own version (it reported a fixed "0.1.8" before).
_ENGINE_VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()


class StrategyOperation(str, Enum):
    DETECT_CONTRADICTIONS = "detect_contradictions"
    ASSESS_EVIDENCE = "assess_evidence"
    APPLY_RULES = "apply_rules"


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """Declarative strategy metadata; it cannot execute arbitrary user code."""
    strategy_id: str
    version: str
    task_types: tuple[str, ...]
    operations: tuple[StrategyOperation, ...]
    priority: int = 0
    requires_evidence: bool = False
    requires_rules: bool = False
    halt_on_definite_conflict: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        if not self.strategy_id.strip() or not self.version.strip():
            raise ValueError("strategy_id and version must be non-empty")
        if not self.task_types:
            raise ValueError("strategy must declare at least one task type")
        if not self.operations:
            raise ValueError("strategy must contain at least one operation")
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("strategy operations must be unique")
        if any(not item.strip() for item in self.task_types):
            raise ValueError("task types must be non-empty")
        if self.requires_rules and StrategyOperation.APPLY_RULES not in self.operations:
            raise ValueError("requires_rules strategy must include APPLY_RULES")


@dataclass(frozen=True, slots=True)
class StrategyCatalog:
    strategies: tuple[StrategyDefinition, ...]

    def __post_init__(self) -> None:
        keys = [(s.strategy_id, s.version) for s in self.strategies]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate strategy id/version")

    def eligible(
        self, request: ReasoningRequest, *, has_rules: bool
    ) -> tuple[StrategyDefinition, ...]:
        """Return strategies passing the canonical task/evidence/rules gates."""
        eligible = []
        for strategy in self.strategies:
            task_match = request.task_type in strategy.task_types or "*" in strategy.task_types
            if not task_match:
                continue
            if strategy.requires_evidence and not request.evidence:
                continue
            if strategy.requires_rules and not has_rules:
                continue
            if StrategyOperation.APPLY_RULES in strategy.operations and not has_rules:
                continue
            eligible.append(strategy)
        return tuple(sorted(eligible, key=lambda s: (-s.priority, s.strategy_id, s.version)))

    def select(
        self, request: ReasoningRequest, *, has_rules: bool
    ) -> StrategyDefinition:
        eligible = self.eligible(request, has_rules=has_rules)
        if not eligible:
            raise LookupError(
                f"no strategy for task_type={request.task_type!r}, "
                f"has_evidence={bool(request.evidence)}, has_rules={has_rules}"
            )
        # Highest priority wins; lexical tie-break makes selection reproducible.
        return eligible[0]


def default_strategy_catalog() -> StrategyCatalog:
    """Small safe baseline; production strategies should be domain-reviewed."""
    return StrategyCatalog((
        StrategyDefinition(
            strategy_id="rule_reasoning", version="1.0",
            task_types=("*",),
            operations=(
                StrategyOperation.DETECT_CONTRADICTIONS,
                StrategyOperation.ASSESS_EVIDENCE,
                StrategyOperation.APPLY_RULES,
            ),
            priority=30, requires_rules=True, halt_on_definite_conflict=True,
            description="Preflight consistency and evidence checks, then bounded rules.",
        ),
        StrategyDefinition(
            strategy_id="evidence_review", version="1.0",
            task_types=("*",),
            operations=(
                StrategyOperation.DETECT_CONTRADICTIONS,
                StrategyOperation.ASSESS_EVIDENCE,
            ),
            priority=20, requires_evidence=True,
            description="Review explicit evidence links and proposition conflicts.",
        ),
        StrategyDefinition(
            strategy_id="consistency_review", version="1.0",
            task_types=("*",),
            operations=(StrategyOperation.DETECT_CONTRADICTIONS,),
            priority=0,
            description="Conservative consistency-only review.",
        ),
    ))


@dataclass(frozen=True, slots=True)
class OrchestrationLimits:
    execution: ExecutionLimits = ExecutionLimits()
    functional_predicates: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    result: ReasoningResult
    selected_strategy: StrategyDefinition
    contradictions: tuple[Contradiction, ...]
    evidence_assessments: tuple[EvidenceAssessment, ...]
    rule_execution: RuleExecution | None
    stopped_before_inference: bool


def _stable_result_id(request_id: str, strategy: StrategyDefinition) -> str:
    raw = f"{request_id}|{strategy.strategy_id}|{strategy.version}".encode()
    return "erc_result_" + sha256(raw).hexdigest()[:24]


def _build_graph(propositions, evidence, evidence_links, inference_steps=()):
    builder = ReasoningGraphBuilder()
    for proposition in propositions:
        builder.add_proposition(proposition)
    for item in evidence:
        builder.add_evidence(item)
    for link in evidence_links:
        builder.link_evidence(link)
    for step in inference_steps:
        builder.add_inference(step)
        builder.connect_inference(
            step.id,
            premise_proposition_ids=step.input_refs,
            output_proposition_ids=step.output_proposition_refs,
        )
    graph = builder.build()
    view = ReasoningGraphView(graph, propositions, evidence, inference_steps)
    return graph, view


def orchestrate(
    request: ReasoningRequest,
    *,
    ruleset: RuleSet | None = None,
    catalog: StrategyCatalog | None = None,
    limits: OrchestrationLimits = OrchestrationLimits(),
    strategy_ref_override: str | None = None,
) -> OrchestrationResult:
    """Select and execute one deterministic strategy for a reasoning request.

    Checks are run before rule execution. Definite contradictions stop rule
    execution when the selected strategy says to halt. Potential contradictions
    are retained as uncertainty and do not silently become definite conflicts.
    """
    catalog = catalog or default_strategy_catalog()
    eligible = catalog.eligible(request, has_rules=ruleset is not None)
    if not eligible:
        raise LookupError(
            f"no strategy for task_type={request.task_type!r}, "
            f"has_evidence={bool(request.evidence)}, has_rules={ruleset is not None}"
        )
    if strategy_ref_override is not None:
        matches = [s for s in eligible if f"{s.strategy_id}@{s.version}" == strategy_ref_override]
        if not matches:
            raise LookupError("strategy_ref_override is not eligible for this request")
        strategy = matches[0]
    else:
        strategy = eligible[0]
    propositions = list(request.propositions)
    trace: list[TraceEntry] = []
    contradictions: tuple[Contradiction, ...] = ()
    assessments: list[EvidenceAssessment] = []
    rule_execution: RuleExecution | None = None
    stopped = False

    for operation in strategy.operations:
        if operation == StrategyOperation.DETECT_CONTRADICTIONS:
            contradictions = find_contradictions(
                propositions,
                functional_predicates=limits.functional_predicates,
            )
            trace.append(TraceEntry(
                sequence=len(trace), operation=operation.value,
                input_refs=tuple(p.id for p in propositions), output_refs=(),
                status="completed",
                explanation_code="CONTRADICTION_SCAN_COMPLETED",
                details={
                    "definite_count": sum(c.certainty == ContradictionCertainty.DEFINITE for c in contradictions),
                    "potential_count": sum(c.certainty == ContradictionCertainty.POTENTIAL for c in contradictions),
                },
            ))
            definite = any(c.certainty == ContradictionCertainty.DEFINITE for c in contradictions)
            if definite and strategy.halt_on_definite_conflict and StrategyOperation.APPLY_RULES in strategy.operations:
                stopped = True
                trace.append(TraceEntry(
                    sequence=len(trace), operation="strategy_gate",
                    input_refs=tuple(p.id for p in propositions), output_refs=(),
                    status="halted",
                    explanation_code="DEFINITE_CONFLICT_BLOCKED_INFERENCE",
                    details={"strategy_id": strategy.strategy_id},
                ))
                break

        elif operation == StrategyOperation.ASSESS_EVIDENCE:
            _, view = _build_graph(
                propositions, request.evidence, request.evidence_links
            )
            for proposition in propositions:
                assessments.append(assess_evidence(view, proposition.id))
            trace.append(TraceEntry(
                sequence=len(trace), operation=operation.value,
                input_refs=tuple(p.id for p in propositions),
                output_refs=tuple(a.proposition_id for a in assessments),
                status="completed",
                explanation_code="EXPLICIT_EVIDENCE_RELATIONS_ASSESSED",
                details={"assessed_propositions": len(assessments)},
            ))

        elif operation == StrategyOperation.APPLY_RULES:
            if ruleset is None:
                raise RuntimeError("selected strategy requires a ruleset")
            rule_execution = execute_rules(
                propositions, ruleset,
                evidence=request.evidence,
                evidence_links=request.evidence_links,
                limits=limits.execution,
                request_id=request.id,
            )
            propositions = list(rule_execution.propositions)
            for entry in rule_execution.trace:
                trace.append(TraceEntry(
                    sequence=len(trace), operation=f"rule:{entry.operation}",
                    input_refs=entry.input_refs, output_refs=entry.output_refs,
                    status=entry.status, rule_id=entry.rule_id,
                    explanation_code=entry.explanation_code, details=entry.details,
                ))

    # Re-scan after inference so conflicts involving derived propositions remain visible.
    if rule_execution is not None:
        contradictions = find_contradictions(
            propositions, functional_predicates=limits.functional_predicates
        )

    definite = tuple(c for c in contradictions if c.certainty == ContradictionCertainty.DEFINITE)
    potential = tuple(c for c in contradictions if c.certainty == ContradictionCertainty.POTENTIAL)
    uncertainty: list[UncertaintyItem] = []
    for index, contradiction in enumerate(potential):
        uncertainty.append(UncertaintyItem(
            id=f"uncertainty_potential_conflict_{index+1}",
            kind=UncertaintyKind.TEMPORAL_AMBIGUITY,
            description=f"Potential contradiction between {contradiction.left_id} and {contradiction.right_id}: {contradiction.explanation}",
            affected_refs=(contradiction.left_id, contradiction.right_id),
            resolution_hint="Clarify proposition validity intervals before adjudication.",
        ))
    for assessment in assessments:
        if assessment.status == EvidenceAssessmentStatus.NO_LINKED_EVIDENCE:
            uncertainty.append(UncertaintyItem(
                id=f"uncertainty_no_evidence_{assessment.proposition_id}",
                kind=UncertaintyKind.MISSING_PREMISE,
                description=f"No explicit evidence is linked to proposition {assessment.proposition_id}; this does not establish falsehood.",
                affected_refs=(assessment.proposition_id,),
                resolution_hint="Retrieve or link authoritative evidence if available.",
            ))
        elif assessment.status == EvidenceAssessmentStatus.CONFLICT:
            uncertainty.append(UncertaintyItem(
                id=f"uncertainty_evidence_conflict_{assessment.proposition_id}",
                kind=UncertaintyKind.CONFLICTING_EVIDENCE,
                description=f"Supporting and contradicting evidence are both linked to {assessment.proposition_id}; no automatic adjudication was performed.",
                affected_refs=(assessment.proposition_id,),
                resolution_hint="Review source quality, population, methods and applicability.",
            ))

    # ERC 0.7.0: a match whose temporal requirement could not be established is reported as an uncertainty, one item
    # per match, in trace order. The wording needs more than the trace entry holds (which premise a reason applies
    # to), so the check is run a second time on the same rule and the same matched premises. That second result is
    # used only if it agrees with the trace entry in every constraint, field and order; the wording is then built
    # from it. A disagreement is an internal fault: nothing is built from it.
    if rule_execution is not None:
        rules_by_ref = {(rule.rule_id, rule.version): rule for rule in ruleset.rules}
        propositions_by_id = {p.id: p for p in rule_execution.propositions}
        temporal_items = 0
        for entry in rule_execution.trace:
            if entry.status != "temporal_requirement_indeterminate":
                continue
            rule = rules_by_ref[(entry.rule_id, entry.details["rule_version"])]
            premises = [propositions_by_id[ref] for ref in entry.input_refs]
            verified = [dict(item) for item in check_temporal_requirements(rule, premises).constraints]
            if verified != [dict(item) for item in entry.details["temporal"]]:
                raise RuntimeError(f"Temporal recheck for rule {rule.rule_id}@{rule.version} disagrees with the "
                                   "recorded trace entry; no uncertainty item was produced.")
            temporal_items += 1
            uncertainty.append(UncertaintyItem(
                id=f"uncertainty_temporal_requirement_{temporal_items}",
                kind=UncertaintyKind.TEMPORAL_AMBIGUITY,
                description=_describe_not_applied(rule, premises, verified),
                affected_refs=entry.input_refs,
                resolution_hint=RESOLUTION_HINT,
            ))

    if definite:
        status = ReasoningStatus.CONFLICT
    elif rule_execution is not None and rule_execution.status == ReasoningStatus.PARTIAL:
        status = ReasoningStatus.PARTIAL
    elif stopped:
        status = ReasoningStatus.CONFLICT
    elif uncertainty and not (rule_execution and rule_execution.firings_executed):
        status = ReasoningStatus.INDETERMINATE
    else:
        status = ReasoningStatus.COMPLETE

    graph, _ = _build_graph(
        propositions, request.evidence, request.evidence_links,
        rule_execution.inference_steps if rule_execution else (),
    )
    conclusions = tuple(
        p.id for p in propositions
        if p.kind.value == "inference"
    )
    result = ReasoningResult(
        id=_stable_result_id(request.id, strategy),
        request_id=request.id,
        status=status,
        conclusion_refs=conclusions,
        propositions=tuple(propositions),
        inference_steps=rule_execution.inference_steps if rule_execution else (),
        graph=graph,
        uncertainty=tuple(uncertainty),
        trace=tuple(trace),
        engine_version=_ENGINE_VERSION,
    )
    return OrchestrationResult(
        result=result,
        selected_strategy=strategy,
        contradictions=contradictions,
        evidence_assessments=tuple(assessments),
        rule_execution=rule_execution,
        stopped_before_inference=stopped,
    )
