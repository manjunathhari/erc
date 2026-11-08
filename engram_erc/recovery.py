"""Failure prevention and guarded, review-required reasoning recovery.

ERC-2.7 uses prior adjudicated failure analyses to trigger explicit guardrails.
It replays only a caller-supplied immutable input snapshot and never changes
rules, evidence, registry records, P6 state, or confidence values.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .contracts import Evidence, EvidenceLink, Proposition, ReasoningStatus, require_aware_datetime
from .failure_analysis import (
    AttributionStatus, FailureAnalysisReport, FailureCategory,
    FailureCaseAnalysis,
)
from .inference import ExecutionLimits, RuleExecution, execute_rules
from .primitives.contradiction import ContradictionCertainty, find_contradictions
from .rules import RuleSet


class GuardStatus(str, Enum):
    PASS = "pass"
    BLOCK = "block"
    REVIEW_REQUIRED = "review_required"
    NOT_TRIGGERED = "not_triggered"


class RecoveryStatus(str, Enum):
    BLOCKED = "blocked"
    EXECUTED_REVIEW_REQUIRED = "executed_review_required"
    INDETERMINATE = "indeterminate"


class GuardKind(str, Enum):
    EVIDENCE_COMPLETENESS = "evidence_completeness"
    CONTRADICTION_RECHECK = "contradiction_recheck"
    TEMPORAL_SCOPE_REVIEW = "temporal_scope_review"
    PREMISE_EXTRACTION_ACK = "premise_extraction_ack"
    RULE_APPLICATION_ACK = "rule_application_ack"
    INFERENCE_DEPENDENCY_ACK = "inference_dependency_ack"
    CONTEXT_MATCH_ACK = "context_match_ack"
    CONFIDENCE_REVIEW_ACK = "confidence_review_ack"


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """Conservative controls; adjudicated history triggers guards by default."""
    use_supported_hypotheses: bool = False
    require_evidence_for_all_premises: bool = False
    block_on_definite_contradiction: bool = True
    block_on_potential_contradiction: bool = False
    require_temporal_as_of: bool = True
    required_acknowledgements: tuple[GuardKind, ...] = (
        GuardKind.PREMISE_EXTRACTION_ACK,
        GuardKind.RULE_APPLICATION_ACK,
        GuardKind.INFERENCE_DEPENDENCY_ACK,
        GuardKind.CONTEXT_MATCH_ACK,
        GuardKind.CONFIDENCE_REVIEW_ACK,
    )

    def __post_init__(self) -> None:
        if len(set(self.required_acknowledgements)) != len(self.required_acknowledgements):
            raise ValueError("required_acknowledgements must be unique")


@dataclass(frozen=True, slots=True)
class RecoveryRequest:
    case_id: str
    context_key: str
    propositions: tuple[Proposition, ...]
    ruleset: RuleSet
    evidence: tuple[Evidence, ...] = ()
    evidence_links: tuple[EvidenceLink, ...] = ()
    required_evidence_proposition_refs: tuple[str, ...] = ()
    acknowledged_controls: tuple[GuardKind, ...] = ()
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        if not self.context_key.strip():
            raise ValueError("context_key must be non-empty")
        require_aware_datetime(self.as_of, "as_of")
        pids = {p.id for p in self.propositions}
        if len(pids) != len(self.propositions):
            raise ValueError("duplicate proposition IDs")
        eids = {e.id for e in self.evidence}
        if len(eids) != len(self.evidence):
            raise ValueError("duplicate evidence IDs")
        for link in self.evidence_links:
            if link.proposition_id not in pids or link.evidence_id not in eids:
                raise ValueError("evidence link references an unknown input")
        if not set(self.required_evidence_proposition_refs).issubset(pids):
            raise ValueError("required evidence refs must identify input propositions")
        if len(set(self.required_evidence_proposition_refs)) != len(self.required_evidence_proposition_refs):
            raise ValueError("required evidence refs must be unique")
        if len(set(self.acknowledged_controls)) != len(self.acknowledged_controls):
            raise ValueError("acknowledged_controls must be unique")


@dataclass(frozen=True, slots=True)
class GuardCheck:
    kind: GuardKind
    status: GuardStatus
    reason: str
    related_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    case_id: str
    context_key: str
    triggered_categories: tuple[FailureCategory, ...]
    guards: tuple[GuardCheck, ...]
    status: RecoveryStatus
    execution: RuleExecution | None
    derived_proposition_refs: tuple[str, ...]
    limitations: tuple[str, ...]


def _analyses(history: FailureAnalysisReport | Iterable[FailureCaseAnalysis]) -> tuple[FailureCaseAnalysis, ...]:
    if isinstance(history, FailureAnalysisReport):
        return history.analyzed_cases
    return tuple(history)


def _triggered_categories(
    history: FailureAnalysisReport | Iterable[FailureCaseAnalysis],
    policy: RecoveryPolicy,
    context_key: str,
) -> tuple[FailureCategory, ...]:
    allowed = {AttributionStatus.CONFIRMED_BY_ADJUDICATOR}
    if policy.use_supported_hypotheses:
        allowed.add(AttributionStatus.SUPPORTED_HYPOTHESIS)
    return tuple(sorted({
        attribution.category
        for case in _analyses(history)
        if case.context_key == context_key
        for attribution in case.attributions
        if attribution.status in allowed
    }, key=lambda item: item.value))


def run_guarded_recovery(
    request: RecoveryRequest,
    failure_history: FailureAnalysisReport | Iterable[FailureCaseAnalysis],
    *,
    policy: RecoveryPolicy = RecoveryPolicy(),
    limits: ExecutionLimits = ExecutionLimits(),
) -> RecoveryReport:
    """Run preflight guards, then bounded replay; output always needs review.

    The history is used to trigger guard types, not to infer that a failure
    will recur in the present case. Callers supply context matching and
    acknowledgements explicitly.
    """
    categories = _triggered_categories(failure_history, policy, request.context_key)
    guards: list[GuardCheck] = []
    links_by_prop: dict[str, set[str]] = {}
    for link in request.evidence_links:
        links_by_prop.setdefault(link.proposition_id, set()).add(link.evidence_id)

    if policy.require_evidence_for_all_premises:
        missing = tuple(sorted(ref for ref in request.required_evidence_proposition_refs
                               if not links_by_prop.get(ref)))
        no_scope = not request.required_evidence_proposition_refs
        guards.append(GuardCheck(
            GuardKind.EVIDENCE_COMPLETENESS,
            GuardStatus.BLOCK if missing or no_scope else GuardStatus.PASS,
            ("No required evidence scope was supplied; completeness cannot be established." if no_scope else
             "Required propositions lack linked evidence." if missing else
             "Every caller-designated proposition has at least one evidence link."),
            missing,
        ))
    elif FailureCategory.MISSING_KNOWLEDGE_OR_EVIDENCE in categories:
        missing = tuple(sorted(ref for ref in request.required_evidence_proposition_refs
                               if not links_by_prop.get(ref)))
        no_scope = not request.required_evidence_proposition_refs
        guards.append(GuardCheck(
            GuardKind.EVIDENCE_COMPLETENESS,
            GuardStatus.BLOCK if missing or no_scope else GuardStatus.PASS,
            ("Historical evidence failure triggered a check, but no required evidence scope was supplied." if no_scope else
             "Historical evidence failure triggered a completeness check; missing links block replay."
             if missing else "Historical evidence failure triggered a check; caller-designated evidence links are present."),
            missing,
        ))

    if FailureCategory.MISSED_CONTRADICTION in categories:
        conflicts = find_contradictions(request.propositions)
        definite = tuple(f"{c.left_id}|{c.right_id}" for c in conflicts
                         if c.certainty == ContradictionCertainty.DEFINITE)
        potential = tuple(f"{c.left_id}|{c.right_id}" for c in conflicts
                          if c.certainty == ContradictionCertainty.POTENTIAL)
        blocked = ((policy.block_on_definite_contradiction and bool(definite)) or
                   (policy.block_on_potential_contradiction and bool(potential)))
        guards.append(GuardCheck(
            GuardKind.CONTRADICTION_RECHECK,
            GuardStatus.BLOCK if blocked else GuardStatus.PASS,
            "Contradiction recheck found a conflict requiring resolution." if blocked else
            "Contradiction recheck completed; no policy-blocking conflict found.",
            tuple(sorted(definite + potential)),
        ))

    if FailureCategory.TEMPORAL_REASONING_ERROR in categories:
        timed = tuple(sorted(p.id for p in request.propositions if p.valid_time is not None))
        missing_as_of = policy.require_temporal_as_of and bool(timed) and request.as_of is None
        guards.append(GuardCheck(
            GuardKind.TEMPORAL_SCOPE_REVIEW,
            GuardStatus.BLOCK if missing_as_of else GuardStatus.REVIEW_REQUIRED,
            "Temporal propositions are present but no as-of time was supplied." if missing_as_of else
            "Temporal failure history triggered explicit temporal review; ERC does not validate domain time semantics.",
            timed,
        ))

    category_guard = {
        FailureCategory.PREMISE_EXTRACTION_ERROR: GuardKind.PREMISE_EXTRACTION_ACK,
        FailureCategory.RULE_APPLICATION_ERROR: GuardKind.RULE_APPLICATION_ACK,
        FailureCategory.INFERENCE_DEPENDENCY_ERROR: GuardKind.INFERENCE_DEPENDENCY_ACK,
        FailureCategory.CONTEXT_MISMATCH: GuardKind.CONTEXT_MATCH_ACK,
        FailureCategory.CONFIDENCE_MISCALIBRATION: GuardKind.CONFIDENCE_REVIEW_ACK,
    }
    for category, guard_kind in category_guard.items():
        if category in categories:
            acknowledged = guard_kind in request.acknowledged_controls
            mandatory = guard_kind in policy.required_acknowledgements
            guards.append(GuardCheck(
                guard_kind,
                GuardStatus.PASS if acknowledged else (
                    GuardStatus.BLOCK if mandatory else GuardStatus.REVIEW_REQUIRED
                ),
                "Required human control acknowledged." if acknowledged else (
                    "Historical failure pattern requires explicit caller acknowledgement before replay."
                    if mandatory else
                    "Historical failure pattern is flagged for review; policy does not make acknowledgement a hard block."
                ),
            ))

    blocked = any(guard.status == GuardStatus.BLOCK for guard in guards)
    if blocked:
        status = RecoveryStatus.BLOCKED
        execution = None
        derived = ()
    else:
        execution = execute_rules(
            request.propositions, request.ruleset, evidence=request.evidence,
            evidence_links=request.evidence_links, limits=limits,
            request_id=f"erc-recovery:{request.case_id}",
        )
        produced = {ref for step in execution.inference_steps for ref in step.output_proposition_refs}
        derived = tuple(sorted(produced))
        if execution.status != ReasoningStatus.COMPLETE:
            status = RecoveryStatus.INDETERMINATE
        else:
            status = RecoveryStatus.EXECUTED_REVIEW_REQUIRED
        if not guards:
            guards.append(GuardCheck(
                GuardKind.CONTEXT_MATCH_ACK, GuardStatus.NOT_TRIGGERED,
                "No eligible adjudicated failure pattern triggered a specialised guard.",
            ))

    return RecoveryReport(
        request.case_id, request.context_key, categories, tuple(guards), status,
        execution, derived,
        (
            "A historical failure category triggers a safeguard; it does not prove recurrence in this case.",
            "Failure history without an exact matching context_key is not used to trigger guards.",
            "Caller-supplied context_key and acknowledgements are not independently verified by ERC.",
            "Execution is a deterministic replay of the supplied snapshot, not an automatic repair of source data.",
            "Every executed result requires external review; no conclusion is auto-accepted.",
            "No rule rewrite, strategy update, confidence recalibration, evidence mutation, registry write, or P6 mutation occurs.",
        ),
    )
