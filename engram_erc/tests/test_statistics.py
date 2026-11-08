import unittest
from datetime import datetime, timezone, timedelta

from engram_erc import (
    Proposition, RuleDefinition, RuleSet, PropositionPattern, ConclusionTemplate,
    ConclusionSignature, RegressionCase,
)
from engram_erc.temporal_external import (
    ValidationCohort, ValidationObservation, TemporalExternalPolicy,
    evaluate_temporal_external,
)
from engram_erc.statistics import (
    StatisticalPolicy, quantify_temporal_external, _holm,
)


def rs(version, value):
    return RuleSet((RuleDefinition("RISK", version,
        (PropositionPattern("patient", "finding", "positive"),),
        ConclusionTemplate("patient", "risk", value)),), version)


def obs(cid, cohort, day, site, context="robotic_colorectal"):
    case = RegressionCase(cid,
        (Proposition(f"p-{cid}", "patient", "finding", "positive",
                     qualifiers={"case_token": cid}),),
        (ConclusionSignature("patient", "risk", "high"),), context,
        adjudication_refs=(f"adjudication:{cid}",))
    return ValidationObservation(case, cohort,
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day), site)


def build_report():
    items = []
    for i in range(12):
        items.append(obs(f"r{i}", ValidationCohort.REFERENCE, i, "site-A"))
    for i in range(12):
        items.append(obs(f"t{i}", ValidationCohort.TEMPORAL, 100+i, "site-A"))
    for site_i, site in enumerate(("site-B", "site-C", "site-D")):
        for j in range(4):
            items.append(obs(f"e{site_i}-{j}", ValidationCohort.EXTERNAL,
                             200+site_i*10+j, site,
                             "robotic_colorectal" if j < 2 else "upper_gi"))
    return evaluate_temporal_external(items, rs("baseline", "low"), rs("candidate", "high"),
        policy=TemporalExternalPolicy(
            min_reference_cases=5, min_temporal_cases=5, min_external_cases=5,
            min_cases_per_external_site=2, min_candidate_accuracy=0.8,
            max_accuracy_drop_vs_baseline=0.05, max_regression_rate=0.1,
            max_temporal_drop_vs_reference=0.1, max_external_drop_vs_reference=0.1))


def pol(**kwargs):
    base = dict(bootstrap_replicates=250, permutation_replicates=300,
                min_cases_for_interval=5, min_external_sites_for_cluster_interval=3,
                random_seed=17)
    base.update(kwargs)
    return StatisticalPolicy(**base)


class StatisticalTests(unittest.TestCase):
    def test_paired_uncertainty_report(self):
        result = quantify_temporal_external(build_report(), policy=pol())
        self.assertEqual(result.temporal.sample_size, 12)
        self.assertEqual(result.external.sample_size, 12)
        self.assertAlmostEqual(result.temporal.paired_accuracy_change.estimate, 1.0)
        self.assertEqual(result.temporal.paired_accuracy_change.lower, 1.0)
        self.assertEqual(result.temporal.paired_accuracy_change.upper, 1.0)

    def test_external_cluster_bootstrap_used(self):
        result = quantify_temporal_external(build_report(), policy=pol())
        self.assertEqual(result.external.site_count, 3)
        self.assertIn("cluster bootstrap", result.external.candidate_accuracy.method)

    def test_external_cluster_bootstrap_withholds_when_sites_few(self):
        result = quantify_temporal_external(build_report(),
            policy=pol(min_external_sites_for_cluster_interval=4))
        self.assertIsNone(result.external.candidate_accuracy.lower)
        self.assertIn("independent-site cluster count is insufficient", result.external.interval_status)

    def test_context_metrics_generated(self):
        result = quantify_temporal_external(build_report(), policy=pol())
        keys = {x.context_key for x in result.external.contexts}
        self.assertEqual(keys, {"robotic_colorectal", "upper_gi"})

    def test_permutation_p_value_bounded(self):
        result = quantify_temporal_external(build_report(), policy=pol())
        self.assertGreaterEqual(result.temporal.paired_permutation_p, 0.0)
        self.assertLessEqual(result.temporal.paired_permutation_p, 1.0)

    def test_holm_adjustment_monotonic(self):
        self.assertEqual(_holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])

    def test_adjusted_p_values_present(self):
        result = quantify_temporal_external(build_report(), policy=pol())
        self.assertIsNotNone(result.temporal.holm_adjusted_p)
        self.assertIsNotNone(result.external.holm_adjusted_p)

    def test_deterministic_bootstrap(self):
        report = build_report()
        a = quantify_temporal_external(report, policy=pol(random_seed=44))
        b = quantify_temporal_external(report, policy=pol(random_seed=44))
        self.assertEqual(a.temporal.candidate_accuracy, b.temporal.candidate_accuracy)
        self.assertEqual(a.external.paired_permutation_p, b.external.paired_permutation_p)

    def test_small_sample_withholds_interval(self):
        result = quantify_temporal_external(build_report(),
            policy=pol(min_cases_for_interval=100))
        self.assertIsNone(result.temporal.candidate_accuracy.lower)
        self.assertIn("insufficient sample", result.temporal.interval_status)

    def test_invalid_confidence_level_rejected(self):
        with self.assertRaises(ValueError):
            StatisticalPolicy(confidence_level=1.0)

    def test_invalid_replicates_rejected(self):
        with self.assertRaises(ValueError):
            StatisticalPolicy(bootstrap_replicates=0)

    def test_requires_temporal_external_report(self):
        with self.assertRaises(ValueError):
            quantify_temporal_external(object(), policy=pol())

    def test_zero_difference_has_p_one(self):
        report = evaluate_temporal_external(
            [obs(f"r{i}", ValidationCohort.REFERENCE, i, "site-A") for i in range(6)] +
            [obs(f"t{i}", ValidationCohort.TEMPORAL, 100+i, "site-A") for i in range(6)] +
            [obs(f"e{i}", ValidationCohort.EXTERNAL, 200+i, "site-B") for i in range(6)],
            rs("same1", "high"), rs("same2", "high"),
            policy=TemporalExternalPolicy(min_reference_cases=2, min_temporal_cases=2,
                min_external_cases=2, min_cases_per_external_site=2,
                min_candidate_accuracy=0.8))
        result = quantify_temporal_external(report, policy=pol())
        self.assertEqual(result.temporal.paired_permutation_p, 1.0)

    def test_primary_test_family_explicit(self):
        result = quantify_temporal_external(build_report(), policy=pol())
        self.assertEqual(len(result.primary_test_family), 2)

    def test_report_preserves_versions(self):
        result = quantify_temporal_external(build_report(), policy=pol())
        self.assertEqual(result.baseline_ruleset_version, "baseline")
        self.assertEqual(result.candidate_ruleset_version, "candidate")

    def test_external_case_site_mapping_retained(self):
        report = build_report()
        self.assertEqual(len(report.external_case_sites), 12)
        self.assertEqual(len({site for _, site in report.external_case_sites}), 3)


if __name__ == "__main__":
    unittest.main()
