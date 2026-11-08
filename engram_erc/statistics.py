"""Statistical robustness and uncertainty quantification for ERC-2.3 reports.

Uses paired case-level replay outcomes from temporal/external validation.
Bootstrap intervals quantify sampling uncertainty; paired label-swap
permutation tests compare baseline and candidate on the same cases.
External-site uncertainty can use cluster bootstrap when enough sites exist.
This is descriptive validation, not domain inference or deployment approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Iterable

from .counterfactual import CaseComparisonStatus, CaseReplay, CounterfactualReport
from .temporal_external import TemporalExternalReport


@dataclass(frozen=True, slots=True)
class StatisticalPolicy:
    confidence_level: float = 0.95
    bootstrap_replicates: int = 2000
    permutation_replicates: int = 5000
    random_seed: int = 20261107
    min_cases_for_interval: int = 10
    min_external_sites_for_cluster_interval: int = 3
    cluster_bootstrap_external: bool = True
    apply_holm_to_primary_tests: bool = True

    def __post_init__(self) -> None:
        if not 0.5 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be between 0.5 and 1")
        for name in ("bootstrap_replicates", "permutation_replicates",
                     "min_cases_for_interval", "min_external_sites_for_cluster_interval"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        if not isinstance(self.random_seed, int):
            raise ValueError("random_seed must be an integer")


@dataclass(frozen=True, slots=True)
class Interval:
    estimate: float | None
    lower: float | None
    upper: float | None
    confidence_level: float
    method: str
    sample_size: int


@dataclass(frozen=True, slots=True)
class ContextUncertainty:
    context_key: str
    sample_size: int
    candidate_accuracy: Interval
    paired_accuracy_change: Interval


@dataclass(frozen=True, slots=True)
class CohortUncertainty:
    cohort: str
    sample_size: int
    site_count: int
    baseline_accuracy: Interval
    candidate_accuracy: Interval
    paired_accuracy_change: Interval
    regression_rate: Interval
    paired_permutation_p: float | None
    holm_adjusted_p: float | None
    interval_status: str
    contexts: tuple[ContextUncertainty, ...]


@dataclass(frozen=True, slots=True)
class StatisticalRobustnessReport:
    baseline_ruleset_version: str
    candidate_ruleset_version: str
    confidence_level: float
    temporal: CohortUncertainty
    external: CohortUncertainty
    primary_test_family: tuple[str, ...]
    limitations: tuple[str, ...]


def _correctness(row: CaseReplay) -> tuple[int, int] | None:
    if row.status == CaseComparisonStatus.INDETERMINATE:
        return None
    baseline = int(row.status in (CaseComparisonStatus.UNCHANGED_CORRECT,
                                  CaseComparisonStatus.REGRESSED))
    candidate = int(row.status in (CaseComparisonStatus.UNCHANGED_CORRECT,
                                   CaseComparisonStatus.IMPROVED))
    return baseline, candidate


def _percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _interval(values: list[float], estimate: float | None, policy: StatisticalPolicy,
              method: str, n: int) -> Interval:
    if n < policy.min_cases_for_interval or not values:
        return Interval(estimate, None, None, policy.confidence_level,
                        f"{method}; insufficient sample", n)
    tail = (1.0 - policy.confidence_level) / 2.0
    return Interval(estimate, _percentile(values, tail),
                    _percentile(values, 1.0 - tail),
                    policy.confidence_level, method, n)


def _sample_stats(pairs: list[tuple[int, int]]) -> tuple[float, float, float, float]:
    n = len(pairs)
    b = sum(x for x, _ in pairs) / n
    c = sum(y for _, y in pairs) / n
    delta = sum(y - x for x, y in pairs) / n
    regressions = sum(x == 1 and y == 0 for x, y in pairs) / n
    return b, c, delta, regressions


def _bootstrap_pairs(pairs: list[tuple[int, int]], reps: int, rng: Random):
    n = len(pairs)
    base, cand, delta, regress = [], [], [], []
    for _ in range(reps):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        b, c, d, r = _sample_stats(sample)
        base.append(b); cand.append(c); delta.append(d); regress.append(r)
    return base, cand, delta, regress


def _permutation_p(pairs: list[tuple[int, int]], reps: int, rng: Random) -> float | None:
    differences = [c - b for b, c in pairs]
    observed = abs(sum(differences) / len(differences))
    nonzero = [d for d in differences if d != 0]
    if not nonzero:
        return 1.0
    extreme = 0
    for _ in range(reps):
        permuted = sum(d * (1 if rng.getrandbits(1) else -1) for d in nonzero) / len(differences)
        if abs(permuted) >= observed - 1e-15:
            extreme += 1
    return (extreme + 1) / (reps + 1)



def _cluster_permutation_p(site_pairs: dict[str, list[tuple[int, int]]],
                           reps: int, rng: Random) -> float | None:
    """Two-sided paired label-swap test, flipping all cases within each site."""
    sites = sorted(site_pairs)
    if len(sites) < 2:
        return None
    site_sums = [sum(c - b for b, c in site_pairs[site]) for site in sites]
    total_n = sum(len(site_pairs[site]) for site in sites)
    observed = abs(sum(site_sums) / total_n)
    nonzero = [value for value in site_sums if value != 0]
    if not nonzero:
        return 1.0
    extreme = 0
    for _ in range(reps):
        permuted = sum(value * (1 if rng.getrandbits(1) else -1)
                       for value in nonzero) / total_n
        if abs(permuted) >= observed - 1e-15:
            extreme += 1
    return (extreme + 1) / (reps + 1)

def _cluster_bootstrap(site_pairs: dict[str, list[tuple[int, int]]], reps: int,
                       rng: Random):
    sites = sorted(site_pairs)
    nsites = len(sites)
    base, cand, delta, regress = [], [], [], []
    for _ in range(reps):
        selected = [sites[rng.randrange(nsites)] for _ in range(nsites)]
        sample = [pair for site in selected for pair in site_pairs[site]]
        if not sample:
            continue
        b, c, d, r = _sample_stats(sample)
        base.append(b); cand.append(c); delta.append(d); regress.append(r)
    return base, cand, delta, regress


def _rows(report: CounterfactualReport | None) -> tuple[CaseReplay, ...]:
    return report.case_replays if report else ()


def _cohort(
    name: str,
    report: CounterfactualReport | None,
    site_by_case: dict[str, str],
    policy: StatisticalPolicy,
    seed_offset: int,
) -> CohortUncertainty:
    rows = _rows(report)
    usable = [(row, _correctness(row)) for row in rows]
    usable = [(row, pair) for row, pair in usable if pair is not None]
    pairs = [pair for _, pair in usable]
    contexts: dict[str, list[tuple[int, int]]] = {}
    site_pairs: dict[str, list[tuple[int, int]]] = {}
    for row, pair in usable:
        contexts.setdefault(row.context_key, []).append(pair)
        if row.case_id in site_by_case:
            site_pairs.setdefault(site_by_case[row.case_id], []).append(pair)
    rng = Random(policy.random_seed + seed_offset)
    if pairs:
        b, c, d, r = _sample_stats(pairs)
        base_boot, cand_boot, delta_boot, regress_boot = _bootstrap_pairs(
            pairs, policy.bootstrap_replicates, rng)
        method = "paired case bootstrap percentile interval"
        if name == "external" and policy.cluster_bootstrap_external:
            if len(site_pairs) >= policy.min_external_sites_for_cluster_interval:
                base_boot, cand_boot, delta_boot, regress_boot = _cluster_bootstrap(
                    site_pairs, policy.bootstrap_replicates, rng)
                method = "external-site cluster bootstrap percentile interval"
            else:
                base_boot = cand_boot = delta_boot = regress_boot = []
                method = "cluster bootstrap unavailable: too few independent sites"
        n = len(pairs)
        if name == "external" and policy.cluster_bootstrap_external:
            p = (_cluster_permutation_p(site_pairs, policy.permutation_replicates, rng)
                 if len(site_pairs) >= policy.min_external_sites_for_cluster_interval else None)
        else:
            p = _permutation_p(pairs, policy.permutation_replicates, rng)
        base_i = _interval(base_boot, b, policy, method, n)
        cand_i = _interval(cand_boot, c, policy, method, n)
        delta_i = _interval(delta_boot, d, policy, method, n)
        regress_i = _interval(regress_boot, r, policy, method, n)
    else:
        n = 0; p = None
        base_i = cand_i = delta_i = regress_i = Interval(
            None, None, None, policy.confidence_level, "not estimable", 0)
    context_rows = []
    for key, vals in sorted(contexts.items()):
        cn = len(vals)
        _, cc, cd, _ = _sample_stats(vals)
        crng = Random(policy.random_seed + seed_offset + sum(map(ord, key)))
        _, cb, cdb, _ = _bootstrap_pairs(vals, policy.bootstrap_replicates, crng)
        context_rows.append(ContextUncertainty(
            key, cn,
            _interval(cb, cc, policy, "case bootstrap percentile interval", cn),
            _interval(cdb, cd, policy, "paired case bootstrap percentile interval", cn),
        ))
    status = "adequate" if n >= policy.min_cases_for_interval else "insufficient sample for interval"
    if name == "external" and policy.cluster_bootstrap_external and len(site_pairs) < policy.min_external_sites_for_cluster_interval:
        status += "; independent-site cluster count is insufficient"
    return CohortUncertainty(name, n, len(site_pairs), base_i, cand_i,
                             delta_i, regress_i, p, None, status, tuple(context_rows))


def _holm(pvalues: list[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in original order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        value = min(1.0, (m - rank) * pvalues[idx])
        running = max(running, value)
        adjusted[idx] = running
    return adjusted


def quantify_temporal_external(
    report: TemporalExternalReport,
    *,
    policy: StatisticalPolicy = StatisticalPolicy(),
) -> StatisticalRobustnessReport:
    """Add paired uncertainty estimates to an ERC-2.3 temporal/external report.

    The bootstrap preserves baseline/candidate pairing. External-site cluster
    bootstrap resamples sites, not individual cases, when enough sites exist.
    Primary paired permutation tests are Holm-adjusted across temporal/external.
    """
    if not isinstance(report, TemporalExternalReport):
        raise ValueError("report must be a TemporalExternalReport")
    site_by_case = dict(report.external_case_sites)
    temporal = _cohort("temporal", report.temporal_report, {}, policy, 101)
    external = _cohort("external", report.external_report, site_by_case, policy, 211)
    family = ("temporal paired baseline-vs-candidate", "external paired baseline-vs-candidate")
    raw = [x.paired_permutation_p for x in (temporal, external)]
    valid_indices = [i for i, p in enumerate(raw) if p is not None]
    adjusted = _holm([raw[i] for i in valid_indices]) if policy.apply_holm_to_primary_tests and valid_indices else [raw[i] for i in valid_indices]
    adjusted_map = dict(zip(valid_indices, adjusted))
    from dataclasses import replace
    temporal = replace(temporal, holm_adjusted_p=adjusted_map.get(0))
    external = replace(external, holm_adjusted_p=adjusted_map.get(1))
    limitations = (
        "Bootstrap intervals quantify sampling uncertainty under the supplied case-sampling design; they do not correct selection bias or confounding.",
        "The temporal paired permutation test swaps baseline/candidate labels within cases; the external paired permutation test flips labels at the site-cluster level when enough sites are available. Both depend on an exchangeability null and are not causal tests.",
        "External-site cluster bootstrap resamples institutions when the configured minimum number of independent external sites is met; with fewer sites, external confidence intervals are withheld rather than treating cases as independent clusters.",
        "Context-specific intervals are exploratory; no multiplicity correction is applied across all context strata.",
        "Exact-set agreement with adjudicated conclusions is not real-world effectiveness, case benefit, safety, or causal attribution.",
        "Intervals and p-values do not replace prospective validation, domain review, or a prespecified statistical analysis plan.",
    )
    return StatisticalRobustnessReport(report.baseline_ruleset_version,
        report.candidate_ruleset_version, policy.confidence_level,
        temporal, external, family, limitations)
