"""Contextual holdout validation and generalisation testing for ERC rulesets.

This module deliberately wraps ERC-2.1 immutable RegressionCase snapshots. It
keeps development and holdout evaluation separate, reports context strata, and
abstains when the sample is too small or execution is indeterminate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable

from .counterfactual import (
    CaseComparisonStatus, CounterfactualReport, RegressionCase,
    run_counterfactual_suite,
)
from .inference import ExecutionLimits
from .rules import RuleSet


class DatasetSplit(str, Enum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"


class ValidationVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True, slots=True)
class ValidationCase:
    case: RegressionCase
    split: DatasetSplit

    def __post_init__(self) -> None:
        if not isinstance(self.case, RegressionCase):
            raise ValueError("case must be a RegressionCase")
        if not isinstance(self.split, DatasetSplit):
            raise ValueError("split must be a DatasetSplit")


@dataclass(frozen=True, slots=True)
class GeneralisationPolicy:
    min_development_cases: int = 5
    min_holdout_cases: int = 5
    min_context_holdout_cases: int = 3
    min_candidate_holdout_accuracy: float = 0.80
    max_holdout_accuracy_drop_vs_baseline: float = 0.05
    max_regression_rate: float = 0.10
    require_all_contexts_represented: bool = True
    reject_duplicate_snapshots_across_splits: bool = True

    def __post_init__(self) -> None:
        for name in ("min_development_cases", "min_holdout_cases", "min_context_holdout_cases"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")
        for name in ("min_candidate_holdout_accuracy", "max_holdout_accuracy_drop_vs_baseline", "max_regression_rate"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SplitMetrics:
    total_cases: int
    determinate_cases: int
    indeterminate_cases: int
    baseline_exact_match_cases: int
    candidate_exact_match_cases: int
    baseline_accuracy: float | None
    candidate_accuracy: float | None
    improved_cases: int
    regressed_cases: int
    regression_rate: float | None


@dataclass(frozen=True, slots=True)
class ContextMetrics:
    context_key: str
    total_cases: int
    determinate_cases: int
    indeterminate_cases: int
    baseline_accuracy: float | None
    candidate_accuracy: float | None
    improved_cases: int
    regressed_cases: int
    adequately_represented: bool


@dataclass(frozen=True, slots=True)
class GeneralisationReport:
    baseline_ruleset_version: str
    candidate_ruleset_version: str
    verdict: ValidationVerdict
    development: SplitMetrics
    holdout: SplitMetrics
    generalisation_gap: float | None
    context_metrics: tuple[ContextMetrics, ...]
    development_report: CounterfactualReport | None
    holdout_report: CounterfactualReport | None
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]


def _evidence_item(e) -> dict:
    item = {
        "source_ref": e.source_ref, "source_kind": e.source_kind.value,
        "evidence_kind": e.evidence_kind.value,
        "observed_at": e.observed_at.isoformat() if e.observed_at else None,
        "reliability_score": e.reliability_score,
        "reliability_method": e.reliability_method,
        "metadata": dict(e.metadata),
    }
    # ERC 0.5.0 temporal contract: evidence validity enters the fingerprint when it uses a field added in 0.5.0,
    # and then as a whole. Before 0.5.0 evidence validity was never part of the fingerprint; plain start/end
    # validity still is not, so every earlier fingerprint is unchanged.
    v = e.valid_time
    if v is not None:
        added = {name: getattr(v, name).isoformat() for name in ("start_latest", "end_earliest")
                 if getattr(v, name) is not None}
        added.update({name: True for name in ("start_unbounded", "end_unbounded", "start_is_lower_bound",
                                              "end_is_upper_bound") if getattr(v, name)})
        if added:
            item["valid_time"] = {"start": v.start.isoformat() if v.start else None,
                                  "end": v.end.isoformat() if v.end else None, **added}
    return item


def _snapshot_fingerprint(case: RegressionCase) -> str:
    # Exclude local proposition IDs so the same semantic snapshot cannot evade
    # leakage detection merely by being re-keyed in the second split.
    propositions = []
    for p in case.propositions:
        interval = None
        if p.valid_time is not None:
            interval = {"start": p.valid_time.start.isoformat() if p.valid_time.start else None,
                        "end": p.valid_time.end.isoformat() if p.valid_time.end else None}
            # ERC 0.5.0 temporal contract: a field enters the fingerprint only when it is set, so every
            # fingerprint computed before 0.5.0 is unchanged and two different intervals never share one.
            for name in ("start_latest", "end_earliest"):
                if getattr(p.valid_time, name) is not None:
                    interval[name] = getattr(p.valid_time, name).isoformat()
            for name in ("start_unbounded", "end_unbounded", "start_is_lower_bound", "end_is_upper_bound"):
                if getattr(p.valid_time, name):
                    interval[name] = True
        item = {
            "subject": p.subject, "predicate": p.predicate,
            "object": p.object_value, "polarity": p.polarity,
            "kind": p.kind.value, "source_refs": sorted(p.source_refs),
            "valid_time": interval, "qualifiers": dict(p.qualifiers),
        }
        if p.occurred is not None:
            item["occurred"] = {"earliest": p.occurred.earliest.isoformat() if p.occurred.earliest else None,
                                "latest": p.occurred.latest.isoformat() if p.occurred.latest else None}
        propositions.append(item)
    propositions.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
    proposition_by_id = {p.id: {"subject": p.subject, "predicate": p.predicate,
        "object": p.object_value, "polarity": p.polarity, "kind": p.kind.value,
        "source_refs": sorted(p.source_refs), "qualifiers": dict(p.qualifiers)}
        for p in case.propositions}
    evidence = [_evidence_item(e) for e in case.evidence]
    evidence.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
    evidence_by_id = {e.id: _evidence_item(e) for e in case.evidence}
    links = [{"proposition": proposition_by_id.get(link.proposition_id),
              "evidence": evidence_by_id.get(link.evidence_id),
              "relation": link.relation.value,
              "rationale_code": link.rationale_code} for link in case.evidence_links]
    links.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
    payload = {
        "propositions": propositions,
        "expected": sorted(x.key() for x in case.expected_conclusions),
        "context": case.context_key,
        "evidence": evidence,
        "evidence_links": links,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _metrics(report: CounterfactualReport | None) -> SplitMetrics:
    if report is None:
        return SplitMetrics(0, 0, 0, 0, 0, None, None, 0, 0, None)
    s = report.summary
    determinate = s.total_cases - s.indeterminate
    base = s.baseline_exact_match_cases / determinate if determinate else None
    cand = s.candidate_exact_match_cases / determinate if determinate else None
    regressions = s.regressed
    regression_rate = regressions / determinate if determinate else None
    return SplitMetrics(s.total_cases, determinate, s.indeterminate,
                        s.baseline_exact_match_cases, s.candidate_exact_match_cases,
                        base, cand, s.improved, regressions, regression_rate)


def _context_metrics(report: CounterfactualReport | None, minimum: int) -> tuple[ContextMetrics, ...]:
    if report is None:
        return ()
    groups: dict[str, list] = {}
    for replay in report.case_replays:
        groups.setdefault(replay.context_key, []).append(replay)
    rows = []
    for context, items in sorted(groups.items()):
        determinate_items = [x for x in items if x.status != CaseComparisonStatus.INDETERMINATE]
        n = len(determinate_items)
        # A regression means baseline exact-match and candidate not exact-match;
        # an improvement means the reverse. Unchanged incorrect/correct are explicit.
        base_ok = sum(x.status in (CaseComparisonStatus.UNCHANGED_CORRECT, CaseComparisonStatus.REGRESSED) for x in determinate_items)
        cand_ok = sum(x.status in (CaseComparisonStatus.UNCHANGED_CORRECT, CaseComparisonStatus.IMPROVED) for x in determinate_items)
        rows.append(ContextMetrics(
            context, len(items), n, len(items) - n,
            base_ok / n if n else None, cand_ok / n if n else None,
            sum(x.status == CaseComparisonStatus.IMPROVED for x in determinate_items),
            sum(x.status == CaseComparisonStatus.REGRESSED for x in determinate_items),
            n >= minimum,
        ))
    return tuple(rows)


def evaluate_generalisation(
    cases: Iterable[ValidationCase],
    baseline_ruleset: RuleSet,
    candidate_ruleset: RuleSet,
    *,
    policy: GeneralisationPolicy = GeneralisationPolicy(),
    limits: ExecutionLimits = ExecutionLimits(),
) -> GeneralisationReport:
    """Evaluate a candidate ruleset on development and untouched holdout cases.

    The caller owns split assignment. This function rejects duplicate case IDs
    and, by default, identical input/expected/context snapshots crossing splits.
    It never reassigns cases or tunes rules.
    """
    items = tuple(cases)
    ids = [x.case.case_id for x in items]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id must be unique across development and holdout")
    development = tuple(x.case for x in items if x.split == DatasetSplit.DEVELOPMENT)
    holdout = tuple(x.case for x in items if x.split == DatasetSplit.HOLDOUT)
    if policy.reject_duplicate_snapshots_across_splits:
        dev_fingerprints = {_snapshot_fingerprint(x) for x in development}
        hold_fingerprints = {_snapshot_fingerprint(x) for x in holdout}
        overlap = dev_fingerprints & hold_fingerprints
        if overlap:
            raise ValueError("identical case snapshots appear in both development and holdout splits")

    dev_report = run_counterfactual_suite(development, baseline_ruleset, candidate_ruleset, limits=limits) if development else None
    hold_report = run_counterfactual_suite(holdout, baseline_ruleset, candidate_ruleset, limits=limits) if holdout else None
    dev_metrics, hold_metrics = _metrics(dev_report), _metrics(hold_report)
    context_rows = _context_metrics(hold_report, policy.min_context_holdout_cases)
    reasons: list[str] = []

    enough = True
    if dev_metrics.total_cases < policy.min_development_cases:
        enough = False; reasons.append("development split is below the minimum case count")
    if hold_metrics.total_cases < policy.min_holdout_cases:
        enough = False; reasons.append("holdout split is below the minimum case count")
    if hold_metrics.indeterminate_cases:
        enough = False; reasons.append("holdout contains indeterminate executions")
    if dev_metrics.indeterminate_cases:
        enough = False; reasons.append("development contains indeterminate executions")
    if policy.require_all_contexts_represented and any(not x.adequately_represented for x in context_rows):
        enough = False; reasons.append("one or more holdout contexts are below the minimum representation")
    if not context_rows and holdout:
        enough = False; reasons.append("no evaluable holdout context strata")

    gap = None
    if dev_metrics.candidate_accuracy is not None and hold_metrics.candidate_accuracy is not None:
        gap = dev_metrics.candidate_accuracy - hold_metrics.candidate_accuracy

    if not enough:
        verdict = ValidationVerdict.INSUFFICIENT_DATA
    else:
        failures = []
        if hold_metrics.candidate_accuracy is None or hold_metrics.candidate_accuracy < policy.min_candidate_holdout_accuracy:
            failures.append("candidate holdout accuracy is below the required threshold")
        if hold_metrics.baseline_accuracy is not None and hold_metrics.candidate_accuracy is not None:
            if hold_metrics.candidate_accuracy < hold_metrics.baseline_accuracy - policy.max_holdout_accuracy_drop_vs_baseline:
                failures.append("candidate holdout accuracy drops too far below baseline")
        if hold_metrics.regression_rate is not None and hold_metrics.regression_rate > policy.max_regression_rate:
            failures.append("holdout regression rate exceeds the policy limit")
        if policy.require_all_contexts_represented:
            for row in context_rows:
                if row.candidate_accuracy is not None and row.candidate_accuracy < policy.min_candidate_holdout_accuracy:
                    failures.append(f"candidate accuracy below threshold in context: {row.context_key}")
        if failures:
            verdict = ValidationVerdict.FAIL
            reasons.extend(failures)
        else:
            verdict = ValidationVerdict.PASS
            reasons.append("candidate met the configured holdout and context-specific validation thresholds")

    return GeneralisationReport(
        baseline_ruleset.version, candidate_ruleset.version, verdict,
        dev_metrics, hold_metrics, gap, context_rows, dev_report, hold_report,
        tuple(reasons),
        ("Development and holdout splits are supplied by the caller; this function does not randomise or stratify them.",
         "Holdout accuracy is exact-set agreement with caller-supplied adjudicated conclusions, not real-world effectiveness.",
         "Context strata with small samples are flagged; passing does not establish safety for unrepresented contexts.",
         "No causal attribution, case-level counterfactual claim, rule update, registry write, or P6 mutation is performed.",
         "A temporal or external-site validation design requires appropriately sourced cases and explicit split assignment."),
    )
