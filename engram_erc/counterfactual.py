"""Deterministic counterfactual replay and regression evaluation.

Runs baseline and candidate declarative rulesets against immutable, explicitly
adjudicated case snapshots. It compares derived conclusion signatures with the
case's expected conclusions and reports changed outputs, regressions and
improvements. It never mutates rulesets, registry, P6, evidence, or storage.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Iterable

from .contracts import Evidence, EvidenceLink, Proposition, PropositionKind, ReasoningStatus
from .inference import ExecutionLimits, RuleExecution, execute_rules
from .rules import RuleSet


@dataclass(frozen=True, slots=True)
class ConclusionSignature:
    subject: str
    predicate: str
    object_value: Any
    polarity: bool = True

    def __post_init__(self) -> None:
        if not self.subject or not self.subject.strip():
            raise ValueError("conclusion subject must be non-empty")
        if not self.predicate or not self.predicate.strip():
            raise ValueError("conclusion predicate must be non-empty")
        if not isinstance(self.polarity, bool):
            raise ValueError("conclusion polarity must be bool")
        # Ensure the object can be represented by ERC's JSON-value contract.
        try:
            json.dumps(self.object_value, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValueError("object_value must be JSON serializable") from exc

    def key(self) -> str:
        return json.dumps((self.subject, self.predicate, self.object_value, self.polarity),
                          sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class RegressionCase:
    case_id: str
    propositions: tuple[Proposition, ...]
    expected_conclusions: tuple[ConclusionSignature, ...]
    context_key: str = "unspecified"
    evidence: tuple[Evidence, ...] = ()
    evidence_links: tuple[EvidenceLink, ...] = ()
    adjudication_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id or not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        if not self.context_key or not self.context_key.strip():
            raise ValueError("context_key must be non-empty")
        ids = [p.id for p in self.propositions]
        if len(ids) != len(set(ids)):
            raise ValueError("case contains duplicate proposition IDs")
        keys = [item.key() for item in self.expected_conclusions]
        if len(keys) != len(set(keys)):
            raise ValueError("expected_conclusions contains duplicates")


class CaseComparisonStatus(str, Enum):
    IMPROVED = "improved"
    REGRESSED = "regressed"
    UNCHANGED_CORRECT = "unchanged_correct"
    UNCHANGED_INCORRECT = "unchanged_incorrect"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class CaseReplay:
    case_id: str
    context_key: str
    status: CaseComparisonStatus
    baseline_status: ReasoningStatus
    candidate_status: ReasoningStatus
    expected: tuple[str, ...]
    baseline_conclusions: tuple[str, ...]
    candidate_conclusions: tuple[str, ...]
    baseline_missing: tuple[str, ...]
    baseline_extra: tuple[str, ...]
    candidate_missing: tuple[str, ...]
    candidate_extra: tuple[str, ...]
    added_by_candidate: tuple[str, ...]
    removed_by_candidate: tuple[str, ...]
    adjudication_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RegressionSummary:
    total_cases: int
    improved: int
    regressed: int
    unchanged_correct: int
    unchanged_incorrect: int
    indeterminate: int
    baseline_exact_match_cases: int
    candidate_exact_match_cases: int


@dataclass(frozen=True, slots=True)
class CounterfactualReport:
    baseline_ruleset_version: str
    candidate_ruleset_version: str
    case_replays: tuple[CaseReplay, ...]
    summary: RegressionSummary
    limitations: tuple[str, ...]


def _signature_key(proposition: Proposition) -> str:
    return ConclusionSignature(proposition.subject, proposition.predicate,
                               proposition.object_value, proposition.polarity).key()


def _derived_signatures(execution: RuleExecution) -> tuple[str, ...]:
    # Only propositions actually produced by this execution are compared.
    produced = {ref for step in execution.inference_steps
                for ref in step.output_proposition_refs}
    by_id = {p.id: p for p in execution.propositions}
    return tuple(sorted({_signature_key(by_id[ref]) for ref in produced if ref in by_id}))


def _run(case: RegressionCase, ruleset: RuleSet, limits: ExecutionLimits) -> RuleExecution:
    return execute_rules(case.propositions, ruleset, evidence=case.evidence,
                         evidence_links=case.evidence_links, limits=limits,
                         request_id=f"erc-counterfactual:{case.case_id}")


def _diff(actual: tuple[str, ...], expected: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    a, e = set(actual), set(expected)
    return tuple(sorted(e - a)), tuple(sorted(a - e))


def run_counterfactual_suite(
    cases: Iterable[RegressionCase],
    baseline_ruleset: RuleSet,
    candidate_ruleset: RuleSet,
    *,
    limits: ExecutionLimits = ExecutionLimits(),
) -> CounterfactualReport:
    """Replay identical case snapshots under baseline and candidate rulesets.

    A case is exact-match correct only when its complete derived conclusion set
    equals the adjudicated expected set and execution is COMPLETE. PARTIAL runs
    are indeterminate, never counted as successes or failures.
    """
    case_items = tuple(sorted(cases, key=lambda item: item.case_id))
    ids = [case.case_id for case in case_items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case_id in regression suite")

    replays: list[CaseReplay] = []
    counts = {status: 0 for status in CaseComparisonStatus}
    baseline_correct = candidate_correct = 0
    for case in case_items:
        base_exec = _run(case, baseline_ruleset, limits)
        cand_exec = _run(case, candidate_ruleset, limits)
        base = _derived_signatures(base_exec)
        cand = _derived_signatures(cand_exec)
        expected = tuple(sorted(item.key() for item in case.expected_conclusions))
        base_missing, base_extra = _diff(base, expected)
        cand_missing, cand_extra = _diff(cand, expected)
        base_complete = base_exec.status == ReasoningStatus.COMPLETE
        cand_complete = cand_exec.status == ReasoningStatus.COMPLETE
        base_ok = base_complete and not base_missing and not base_extra
        cand_ok = cand_complete and not cand_missing and not cand_extra
        if base_ok:
            baseline_correct += 1
        if cand_ok:
            candidate_correct += 1
        if not base_complete or not cand_complete:
            status = CaseComparisonStatus.INDETERMINATE
        elif cand_ok and not base_ok:
            status = CaseComparisonStatus.IMPROVED
        elif base_ok and not cand_ok:
            status = CaseComparisonStatus.REGRESSED
        elif base_ok and cand_ok:
            status = CaseComparisonStatus.UNCHANGED_CORRECT
        else:
            status = CaseComparisonStatus.UNCHANGED_INCORRECT
        counts[status] += 1
        base_set, cand_set = set(base), set(cand)
        replays.append(CaseReplay(
            case.case_id, case.context_key, status, base_exec.status, cand_exec.status,
            expected, base, cand, base_missing, base_extra, cand_missing, cand_extra,
            tuple(sorted(cand_set - base_set)), tuple(sorted(base_set - cand_set)),
            tuple(sorted(case.adjudication_refs)),
            ("Exact-set comparison against supplied adjudicated expected conclusions; this is not a clinical outcome prediction.",
             "A conclusion appearing in the expected set is treated as correct only for this explicitly adjudicated case snapshot.",
             "Ruleset changes may alter outputs through interactions; this report does not assign causal responsibility to an individual rule."),
        ))
    summary = RegressionSummary(
        len(case_items), counts[CaseComparisonStatus.IMPROVED],
        counts[CaseComparisonStatus.REGRESSED],
        counts[CaseComparisonStatus.UNCHANGED_CORRECT],
        counts[CaseComparisonStatus.UNCHANGED_INCORRECT],
        counts[CaseComparisonStatus.INDETERMINATE], baseline_correct, candidate_correct,
    )
    return CounterfactualReport(
        baseline_ruleset.version, candidate_ruleset.version, tuple(replays), summary,
        ("Both rulesets are executed independently against the same immutable inputs.",
         "Expected conclusions must come from explicit adjudication; absent conclusions are not assumed false beyond the supplied case contract.",
         "Exact-set matching is intentionally strict and should be supplemented with domain-specific equivalence policies where clinically justified.",
         "No rules, registry records, evidence stores, P6 policies, or persistent data are modified.",
         "This is deterministic replay, not a causal counterfactual about what would have happened to a patient."),
    )
