import unittest

from engram_erc import (
    Proposition, RuleDefinition, RuleSet, PropositionPattern, ConclusionTemplate,
    ConclusionSignature, RegressionCase, DatasetSplit, ValidationCase,
    GeneralisationPolicy, ValidationVerdict, evaluate_generalisation,
    ExecutionLimits,
)


def ruleset(version, value="high"):
    rule = RuleDefinition("RISK", version,
        (PropositionPattern("patient", "finding", "positive"),),
        ConclusionTemplate("patient", "risk", value))
    return RuleSet((rule,), version)


def case(cid, expected="high", context="robotic_colorectal"):
    return RegressionCase(cid,
        (Proposition(f"p-{cid}", "patient", "finding", "positive",
                     qualifiers={"case_token": cid}),),
        (ConclusionSignature("patient", "risk", expected),), context)


def policy(**kwargs):
    base = dict(min_development_cases=2, min_holdout_cases=2,
                min_context_holdout_cases=2, min_candidate_holdout_accuracy=0.75,
                max_holdout_accuracy_drop_vs_baseline=0.05, max_regression_rate=0.25)
    base.update(kwargs)
    return GeneralisationPolicy(**base)


class GeneralisationTests(unittest.TestCase):
    def dataset(self, dev=4, hold=4, expected="high", context="robotic_colorectal"):
        return tuple([ValidationCase(case(f"d{i}", expected, context), DatasetSplit.DEVELOPMENT)
                      for i in range(dev)] +
                     [ValidationCase(case(f"h{i}", expected, context), DatasetSplit.HOLDOUT)
                      for i in range(hold)])

    def test_candidate_passes_holdout_and_context_thresholds(self):
        report = evaluate_generalisation(self.dataset(), ruleset("1"), ruleset("2"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.PASS)
        self.assertEqual(report.holdout.candidate_accuracy, 1.0)
        self.assertEqual(report.context_metrics[0].context_key, "robotic_colorectal")

    def test_candidate_fails_low_holdout_accuracy(self):
        cases = self.dataset(expected="low")
        report = evaluate_generalisation(cases, ruleset("1", "low"), ruleset("2", "high"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.FAIL)
        self.assertTrue(any("below the required threshold" in x for x in report.reasons))

    def test_context_strata_are_reported_separately(self):
        cases = tuple([ValidationCase(case(f"a{i}", context="robotic_colorectal"), DatasetSplit.HOLDOUT) for i in range(2)] +
                      [ValidationCase(case(f"b{i}", context="laparoscopic_colorectal"), DatasetSplit.HOLDOUT) for i in range(2)] +
                      [ValidationCase(case(f"d{i}"), DatasetSplit.DEVELOPMENT) for i in range(4)])
        report = evaluate_generalisation(cases, ruleset("1"), ruleset("2"), policy=policy())
        self.assertEqual(len(report.context_metrics), 2)
        self.assertTrue(all(x.adequately_represented for x in report.context_metrics))

    def test_underrepresented_context_abstains(self):
        cases = tuple([ValidationCase(case(f"a{i}"), DatasetSplit.DEVELOPMENT) for i in range(3)] +
                      [ValidationCase(case("h0", context="robotic"), DatasetSplit.HOLDOUT),
                       ValidationCase(case("h1", context="laparoscopic"), DatasetSplit.HOLDOUT)])
        report = evaluate_generalisation(cases, ruleset("1"), ruleset("2"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.INSUFFICIENT_DATA)

    def test_small_development_or_holdout_abstains(self):
        report = evaluate_generalisation(self.dataset(dev=1, hold=1), ruleset("1"), ruleset("2"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.INSUFFICIENT_DATA)

    def test_duplicate_case_ids_across_splits_rejected(self):
        c = case("same")
        with self.assertRaises(ValueError):
            evaluate_generalisation((ValidationCase(c, DatasetSplit.DEVELOPMENT),
                                     ValidationCase(c, DatasetSplit.HOLDOUT)), ruleset("1"), ruleset("2"))

    def test_identical_snapshots_across_splits_rejected(self):
        a, b = case("a"), case("b")
        # Normalize proposition IDs to demonstrate same semantic snapshot.
        from dataclasses import replace
        b = replace(b, propositions=(replace(b.propositions[0], id=a.propositions[0].id,
                                               qualifiers=a.propositions[0].qualifiers),))
        with self.assertRaises(ValueError):
            evaluate_generalisation((ValidationCase(a, DatasetSplit.DEVELOPMENT),
                                     ValidationCase(b, DatasetSplit.HOLDOUT)), ruleset("1"), ruleset("2"), policy=policy())

    def test_duplicate_snapshot_check_can_be_disabled_explicitly(self):
        from dataclasses import replace
        a, b = case("a"), case("b")
        b = replace(b, propositions=(replace(b.propositions[0], id=a.propositions[0].id,
                                               qualifiers=a.propositions[0].qualifiers),))
        report = evaluate_generalisation((ValidationCase(a, DatasetSplit.DEVELOPMENT),
            ValidationCase(b, DatasetSplit.HOLDOUT)), ruleset("1"), ruleset("2"),
            policy=policy(min_development_cases=1, min_holdout_cases=1,
                         min_context_holdout_cases=1, reject_duplicate_snapshots_across_splits=False))
        self.assertEqual(report.verdict, ValidationVerdict.PASS)

    def test_holdout_regression_rate_fails_policy(self):
        cases = self.dataset(expected="high")
        # Baseline is correct; candidate wrong on all holdout cases.
        report = evaluate_generalisation(cases, ruleset("1", "high"), ruleset("2", "low"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.FAIL)
        self.assertEqual(report.holdout.regressed_cases, 4)

    def test_accuracy_drop_vs_baseline_fails_policy(self):
        report = evaluate_generalisation(self.dataset(expected="high"), ruleset("1", "high"),
            ruleset("2", "low"), policy=policy(max_regression_rate=1.0))
        self.assertEqual(report.verdict, ValidationVerdict.FAIL)

    def test_no_holdout_produces_insufficient_data(self):
        cases = tuple(ValidationCase(case(f"d{i}"), DatasetSplit.DEVELOPMENT) for i in range(4))
        report = evaluate_generalisation(cases, ruleset("1"), ruleset("2"), policy=policy())
        self.assertEqual(report.verdict, ValidationVerdict.INSUFFICIENT_DATA)
        self.assertIsNone(report.holdout.candidate_accuracy)


    def test_indeterminate_holdout_execution_prevents_pass(self):
        props = (Proposition("p-h0", "patient", "finding", "positive"),
                 Proposition("p-h1", "patient", "finding", "positive"))
        many = RegressionCase("h-many", props,
            (ConclusionSignature("patient", "risk", "high"),), "robotic_colorectal")
        cases = tuple([ValidationCase(case(f"d{i}"), DatasetSplit.DEVELOPMENT) for i in range(2)] +
                      [ValidationCase(case("h0"), DatasetSplit.HOLDOUT),
                       ValidationCase(case("h1"), DatasetSplit.HOLDOUT),
                       ValidationCase(many, DatasetSplit.HOLDOUT)])
        report = evaluate_generalisation(cases, ruleset("1"), ruleset("2"), policy=policy(),
            limits=ExecutionLimits(max_rounds=2, max_total_firings=1))
        self.assertEqual(report.verdict, ValidationVerdict.INSUFFICIENT_DATA)
        self.assertGreater(report.holdout.indeterminate_cases, 0)

    def test_policy_rejects_invalid_threshold(self):
        with self.assertRaises(ValueError):
            GeneralisationPolicy(min_candidate_holdout_accuracy=1.1)

    def test_deterministic_order_and_metrics(self):
        report = evaluate_generalisation(tuple(reversed(self.dataset())), ruleset("1"), ruleset("2"), policy=policy())
        self.assertEqual(report.development.candidate_accuracy, 1.0)
        self.assertEqual(report.holdout.candidate_accuracy, 1.0)
        self.assertEqual(report.verdict, ValidationVerdict.PASS)


if __name__ == "__main__":
    unittest.main()
