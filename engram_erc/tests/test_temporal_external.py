import unittest
from datetime import datetime, timezone, timedelta

from engram_erc import (
    Proposition, RuleDefinition, RuleSet, PropositionPattern, ConclusionTemplate,
    ConclusionSignature, RegressionCase, ExecutionLimits,
)
from engram_erc.generalization import ValidationVerdict
from engram_erc.temporal_external import (
    ValidationCohort, ValidationObservation, TemporalExternalPolicy,
    evaluate_temporal_external,
)


def ruleset(version, value="high"):
    rule = RuleDefinition("RISK", version,
        (PropositionPattern("patient", "finding", "positive"),),
        ConclusionTemplate("patient", "risk", value))
    return RuleSet((rule,), version)


def observation(cid, cohort, day, site, expected="high", context="robotic_colorectal"):
    case = RegressionCase(cid,
        (Proposition(f"p-{cid}", "patient", "finding", "positive",
                     qualifiers={"case_token": cid}),),
        (ConclusionSignature("patient", "risk", expected),), context,
        adjudication_refs=(f"adjudication:{cid}",))
    return ValidationObservation(case, cohort,
        datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=day), site)


def policy(**kwargs):
    values = dict(min_reference_cases=2, min_temporal_cases=2,
        min_external_cases=2, min_cases_per_external_site=2,
        min_candidate_accuracy=0.75, max_accuracy_drop_vs_baseline=0.05,
        max_regression_rate=0.25, max_temporal_drop_vs_reference=0.25,
        max_external_drop_vs_reference=0.25)
    values.update(kwargs)
    return TemporalExternalPolicy(**values)


def dataset():
    return tuple(
        [observation(f"r{i}", ValidationCohort.REFERENCE, i, "site-A") for i in range(4)] +
        [observation(f"t{i}", ValidationCohort.TEMPORAL, 100+i, "site-A") for i in range(4)] +
        [observation(f"e{i}", ValidationCohort.EXTERNAL, 200+i, "site-B") for i in range(4)]
    )


class TemporalExternalTests(unittest.TestCase):
    def test_passes_with_chronological_and_external_cohorts(self):
        report = evaluate_temporal_external(dataset(), ruleset("base"), ruleset("candidate"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.PASS)
        self.assertEqual(report.temporal.candidate_accuracy, 1.0)
        self.assertEqual(report.external.candidate_accuracy, 1.0)
        self.assertEqual(report.external_site_metrics[0].site_id, "site-B")

    def test_temporal_cohort_must_be_strictly_later(self):
        items = list(dataset())
        items[4] = observation("t0", ValidationCohort.TEMPORAL, 3, "site-A")
        with self.assertRaisesRegex(ValueError, "strictly later"):
            evaluate_temporal_external(items, ruleset("b"), ruleset("c"), policy=policy())

    def test_temporal_cohort_must_use_reference_sites(self):
        items = list(dataset())
        items[4] = observation("t0", ValidationCohort.TEMPORAL, 100, "site-C")
        with self.assertRaisesRegex(ValueError, "only reference-site IDs"):
            evaluate_temporal_external(items, ruleset("b"), ruleset("c"), policy=policy())

    def test_external_site_must_not_be_in_reference(self):
        items = list(dataset())
        items[-1] = observation("e3", ValidationCohort.EXTERNAL, 203, "site-A")
        with self.assertRaisesRegex(ValueError, "external cohort contains"):
            evaluate_temporal_external(items, ruleset("b"), ruleset("c"), policy=policy())

    def test_duplicate_case_ids_rejected(self):
        items = list(dataset())
        items[1] = observation("r0", ValidationCohort.REFERENCE, 1, "site-A")
        with self.assertRaisesRegex(ValueError, "case_id"):
            evaluate_temporal_external(items, ruleset("b"), ruleset("c"), policy=policy())

    def test_duplicate_semantic_snapshots_across_cohorts_rejected(self):
        from dataclasses import replace
        items = list(dataset())
        dup_case = replace(items[0].case, case_id="later-copy")
        dup_case = replace(dup_case, propositions=(replace(dup_case.propositions[0], id="different-id"),))
        items.append(ValidationObservation(dup_case, ValidationCohort.TEMPORAL,
            datetime(2026, 1, 1, tzinfo=timezone.utc), "site-A"))
        with self.assertRaisesRegex(ValueError, "identical case snapshots"):
            evaluate_temporal_external(items, ruleset("b"), ruleset("c"), policy=policy())

    def test_missing_adjudication_provenance_rejected(self):
        from dataclasses import replace
        base = observation("x", ValidationCohort.REFERENCE, 0, "site-A")
        with self.assertRaisesRegex(ValueError, "adjudication_refs"):
            ValidationObservation(replace(base.case, adjudication_refs=()), base.cohort, base.observed_at, base.site_id)

    def test_naive_timestamp_rejected(self):
        base = observation("x", ValidationCohort.REFERENCE, 0, "site-A")
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            ValidationObservation(base.case, base.cohort, datetime(2025, 1, 1), base.site_id)

    def test_insufficient_cohort_counts_abstain(self):
        report = evaluate_temporal_external(dataset()[:2], ruleset("b"), ruleset("c"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.INSUFFICIENT_DATA)
        self.assertTrue(any("all three cohorts" in x for x in report.reasons))

    def test_external_site_underrepresentation_abstains(self):
        items = list(dataset())
        items.pop()
        report = evaluate_temporal_external(items, ruleset("b"), ruleset("c"),
            policy=policy(min_cases_per_external_site=4))
        self.assertEqual(report.verdict, ValidationVerdict.INSUFFICIENT_DATA)

    def test_temporal_drop_fails_even_if_external_passes(self):
        items = list(dataset())
        items = [observation(f"t{i}", ValidationCohort.TEMPORAL, 100+i, "site-A", expected="low")
                 if x.cohort == ValidationCohort.TEMPORAL else x for i, x in enumerate(items)]
        report = evaluate_temporal_external(items, ruleset("b", "low"), ruleset("c", "high"),
            policy=policy(max_regression_rate=1.0, max_accuracy_drop_vs_baseline=1.0,
                          max_temporal_drop_vs_reference=0.1))
        self.assertEqual(report.verdict, ValidationVerdict.FAIL)
        self.assertTrue(any("temporal accuracy declines" in x for x in report.reasons))

    def test_external_regression_fails(self):
        report = evaluate_temporal_external(dataset(), ruleset("b", "high"), ruleset("c", "low"),
            policy=policy(max_accuracy_drop_vs_baseline=1.0, max_temporal_drop_vs_reference=1.0,
                          max_external_drop_vs_reference=1.0, max_regression_rate=0.1))
        self.assertEqual(report.verdict, ValidationVerdict.FAIL)
        self.assertTrue(any("external regression rate" in x for x in report.reasons))

    def test_underlying_execution_limits_produce_insufficient_data(self):
        from dataclasses import replace
        items = []
        for item in dataset():
            expanded = replace(item.case, propositions=(
                item.case.propositions[0],
                Proposition(f"extra-{item.case.case_id}", "patient", "finding", "positive")))
            items.append(replace(item, case=expanded))
        report = evaluate_temporal_external(items, ruleset("b"), ruleset("c"),
            policy=policy(), limits=ExecutionLimits(max_rounds=2, max_total_firings=1))
        self.assertEqual(report.verdict, ValidationVerdict.INSUFFICIENT_DATA)

    def test_deterministic_results(self):
        a = evaluate_temporal_external(dataset(), ruleset("b"), ruleset("c"), policy=policy())
        b = evaluate_temporal_external(tuple(reversed(dataset())), ruleset("b"), ruleset("c"), policy=policy())
        self.assertEqual(a.verdict, b.verdict)
        self.assertEqual(a.temporal.candidate_accuracy, b.temporal.candidate_accuracy)

    def test_invalid_policy_rejected(self):
        with self.assertRaises(ValueError):
            TemporalExternalPolicy(min_external_cases=0)
        with self.assertRaises(ValueError):
            TemporalExternalPolicy(max_external_drop_vs_reference=1.2)


if __name__ == "__main__":
    unittest.main()
