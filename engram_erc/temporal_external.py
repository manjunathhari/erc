"""Temporal and external-site validation for ERC rulesets.

This module replays immutable, adjudicated case snapshots across an explicitly
chronological validation cohort and an explicitly external-site cohort. It is
an evaluation layer only: it does not tune rules, persist outcomes, or claim
real-world effectiveness or causal effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .counterfactual import (
    RegressionCase, CounterfactualReport, run_counterfactual_suite,
)
from .generalization import (
    SplitMetrics, ContextMetrics, ValidationVerdict,
    _metrics, _context_metrics, _snapshot_fingerprint,
)
from .inference import ExecutionLimits
from .rules import RuleSet


class ValidationCohort(str, Enum):
    REFERENCE = "reference"
    TEMPORAL = "temporal"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class ValidationObservation:
    case: RegressionCase
    cohort: ValidationCohort
    observed_at: datetime
    site_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.case, RegressionCase):
            raise ValueError("case must be a RegressionCase")
        if not isinstance(self.cohort, ValidationCohort):
            raise ValueError("cohort must be a ValidationCohort")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if not isinstance(self.site_id, str) or not self.site_id.strip():
            raise ValueError("site_id must be non-empty")
        if not self.case.adjudication_refs:
            raise ValueError("each validation case requires explicit adjudication_refs")


@dataclass(frozen=True, slots=True)
class TemporalExternalPolicy:
    min_reference_cases: int = 10
    min_temporal_cases: int = 10
    min_external_cases: int = 10
    min_cases_per_external_site: int = 5
    min_candidate_accuracy: float = 0.80
    max_accuracy_drop_vs_baseline: float = 0.05
    max_regression_rate: float = 0.10
    max_temporal_drop_vs_reference: float = 0.10
    max_external_drop_vs_reference: float = 0.10
    require_all_external_sites_adequate: bool = True
    reject_duplicate_snapshots_across_cohorts: bool = True
    require_distinct_external_sites: bool = True

    def __post_init__(self) -> None:
        for name in ("min_reference_cases", "min_temporal_cases", "min_external_cases", "min_cases_per_external_site"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        for name in ("min_candidate_accuracy", "max_accuracy_drop_vs_baseline", "max_regression_rate", "max_temporal_drop_vs_reference", "max_external_drop_vs_reference"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class SiteMetrics:
    site_id: str
    total_cases: int
    determinate_cases: int
    candidate_accuracy: float | None
    baseline_accuracy: float | None
    regression_rate: float | None
    adequately_represented: bool


@dataclass(frozen=True, slots=True)
class TemporalExternalReport:
    baseline_ruleset_version: str
    candidate_ruleset_version: str
    verdict: ValidationVerdict
    reference: SplitMetrics
    temporal: SplitMetrics
    external: SplitMetrics
    temporal_accuracy_change: float | None
    external_accuracy_change: float | None
    temporal_context_metrics: tuple[ContextMetrics, ...]
    external_context_metrics: tuple[ContextMetrics, ...]
    external_site_metrics: tuple[SiteMetrics, ...]
    reference_report: CounterfactualReport | None
    temporal_report: CounterfactualReport | None
    external_report: CounterfactualReport | None
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    external_case_sites: tuple[tuple[str, str], ...] = ()



def evaluate_temporal_external(
    observations: Iterable[ValidationObservation],
    baseline_ruleset: RuleSet,
    candidate_ruleset: RuleSet,
    *,
    policy: TemporalExternalPolicy = TemporalExternalPolicy(),
    limits: ExecutionLimits = ExecutionLimits(),
) -> TemporalExternalReport:
    """Evaluate a candidate against later cases and independently sourced sites.

    Caller assigns cohorts and supplies source/adjudication provenance. Temporal
    validation is strictly later than the reference cohort's latest timestamp.
    External validation requires site IDs absent from the reference cohort.
    No automatic split, resampling, tuning, or persistent writes occur.
    """
    items = tuple(observations)
    ids = [x.case.case_id for x in items]
    if len(ids) != len(set(ids)):
        raise ValueError("case_id must be unique across validation cohorts")
    reference = tuple(x for x in items if x.cohort == ValidationCohort.REFERENCE)
    temporal = tuple(x for x in items if x.cohort == ValidationCohort.TEMPORAL)
    external = tuple(x for x in items if x.cohort == ValidationCohort.EXTERNAL)
    if reference and temporal:
        latest_reference = max(x.observed_at for x in reference)
        earliest_temporal = min(x.observed_at for x in temporal)
        if earliest_temporal <= latest_reference:
            raise ValueError("temporal cohort must be strictly later than every reference case")
    reference_sites = {x.site_id for x in reference}
    temporal_sites = {x.site_id for x in temporal}
    external_sites = {x.site_id for x in external}
    if reference and temporal and not temporal_sites.issubset(reference_sites):
        raise ValueError("temporal cohort must use only reference-site IDs; use external cohort for new sites")
    if policy.require_distinct_external_sites and reference_sites & external_sites:
        raise ValueError("external cohort contains a site represented in the reference cohort")
    if policy.reject_duplicate_snapshots_across_cohorts:
        fingerprints = {
            cohort: {_snapshot_fingerprint(x.case) for x in group}
            for cohort, group in (("reference", reference), ("temporal", temporal), ("external", external))
        }
        names = tuple(fingerprints)
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                if fingerprints[left] & fingerprints[right]:
                    raise ValueError(f"identical case snapshots appear in {left} and {right} cohorts")

    def replay(group: tuple[ValidationObservation, ...]) -> CounterfactualReport | None:
        return run_counterfactual_suite((x.case for x in group), baseline_ruleset, candidate_ruleset, limits=limits) if group else None

    ref_report, time_report, ext_report = replay(reference), replay(temporal), replay(external)
    ref_metrics, time_metrics, ext_metrics = _metrics(ref_report), _metrics(time_report), _metrics(ext_report)
    temporal_context = _context_metrics(time_report, policy.min_temporal_cases) if time_report else ()
    external_context = _context_metrics(ext_report, policy.min_external_cases) if ext_report else ()

    sites: list[SiteMetrics] = []
    if ext_report:
        replay_by_id = {x.case_id: x for x in ext_report.case_replays}
        for site in sorted(external_sites):
            site_cases = [x for x in external if x.site_id == site]
            site_replays = [replay_by_id[x.case.case_id] for x in site_cases]
            determinate = [x for x in site_replays if x.status.value != "indeterminate"]
            n = len(determinate)
            base_ok = sum(x.status.value in ("unchanged_correct", "regressed") for x in determinate)
            cand_ok = sum(x.status.value in ("unchanged_correct", "improved") for x in determinate)
            regressions = sum(x.status.value == "regressed" for x in determinate)
            sites.append(SiteMetrics(site, len(site_cases), n, cand_ok / n if n else None,
                base_ok / n if n else None, regressions / n if n else None,
                n >= policy.min_cases_per_external_site))

    reasons: list[str] = []
    sufficient = True
    for label, metrics, minimum in (("reference", ref_metrics, policy.min_reference_cases),
                                     ("temporal", time_metrics, policy.min_temporal_cases),
                                     ("external", ext_metrics, policy.min_external_cases)):
        if metrics.total_cases < minimum:
            sufficient = False
            reasons.append(f"{label} cohort is below the minimum case count")
        if metrics.indeterminate_cases:
            sufficient = False
            reasons.append(f"{label} cohort contains indeterminate executions")
    if not reference or not temporal or not external:
        sufficient = False
        reasons.append("all three cohorts are required")
    if policy.require_all_external_sites_adequate and any(not x.adequately_represented for x in sites):
        sufficient = False
        reasons.append("one or more external sites are underrepresented")

    temporal_change = (time_metrics.candidate_accuracy - ref_metrics.candidate_accuracy
                       if time_metrics.candidate_accuracy is not None and ref_metrics.candidate_accuracy is not None else None)
    external_change = (ext_metrics.candidate_accuracy - ref_metrics.candidate_accuracy
                       if ext_metrics.candidate_accuracy is not None and ref_metrics.candidate_accuracy is not None else None)
    if not sufficient:
        verdict = ValidationVerdict.INSUFFICIENT_DATA
    else:
        failures: list[str] = []
        for label, metrics in (("temporal", time_metrics), ("external", ext_metrics)):
            if metrics.candidate_accuracy is None or metrics.candidate_accuracy < policy.min_candidate_accuracy:
                failures.append(f"candidate {label} accuracy is below the required threshold")
            if metrics.baseline_accuracy is not None and metrics.candidate_accuracy is not None and metrics.candidate_accuracy < metrics.baseline_accuracy - policy.max_accuracy_drop_vs_baseline:
                failures.append(f"candidate {label} accuracy drops too far below baseline")
            if metrics.regression_rate is not None and metrics.regression_rate > policy.max_regression_rate:
                failures.append(f"{label} regression rate exceeds the policy limit")
        if temporal_change is not None and temporal_change < -policy.max_temporal_drop_vs_reference:
            failures.append("candidate temporal accuracy declines beyond the permitted reference gap")
        if external_change is not None and external_change < -policy.max_external_drop_vs_reference:
            failures.append("candidate external accuracy declines beyond the permitted reference gap")
        if policy.require_all_external_sites_adequate:
            for site in sites:
                if site.candidate_accuracy is not None and site.candidate_accuracy < policy.min_candidate_accuracy:
                    failures.append(f"candidate accuracy below threshold at external site: {site.site_id}")
        if failures:
            verdict = ValidationVerdict.FAIL
            reasons.extend(failures)
        else:
            verdict = ValidationVerdict.PASS
            reasons.append("candidate met configured temporal, external-site and regression thresholds")

    return TemporalExternalReport(
        baseline_ruleset.version, candidate_ruleset.version, verdict,
        ref_metrics, time_metrics, ext_metrics, temporal_change, external_change,
        temporal_context, external_context, tuple(sites), ref_report, time_report, ext_report,
        tuple(reasons),
        ("Cohort assignment, site identity, timestamps and adjudication are supplied by the caller and are not independently verified.",
         "Temporal and external replay measures agreement with adjudicated conclusions, not case outcomes, real-world effectiveness or safety.",
         "Site-level metrics can be unstable with small samples; configured minimums are engineering safeguards, not statistical sample-size justification.",
         "No confidence intervals, causal attribution, rule tuning, registry writes, P6 updates or automatic release are performed.",
         "Passing these thresholds does not establish transportability to unrepresented sites, practitioners, populations or future periods."),
        tuple(sorted((x.case.case_id, x.site_id) for x in external))
    )
