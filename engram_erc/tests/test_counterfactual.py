import unittest

from engram_erc.contracts import Proposition
from engram_erc.rules import RuleDefinition, RuleSet, PropositionPattern, ConclusionTemplate
from engram_erc.counterfactual import (
    ConclusionSignature, RegressionCase, CaseComparisonStatus,
    run_counterfactual_suite,
)
from engram_erc.inference import ExecutionLimits


def ruleset(version, predicate="risk", value="high", max_firings=10):
    rule = RuleDefinition(
        "RISK", version,
        (PropositionPattern("patient", "finding", "positive"),),
        ConclusionTemplate("patient", predicate, value),
        max_firings=max_firings,
    )
    return RuleSet((rule,), version)


def case(case_id="c1", expected="risk", value="high"):
    return RegressionCase(
        case_id,
        (Proposition("p1", "patient", "finding", "positive"),),
        (ConclusionSignature("patient", expected, value),),
        "robotic_colorectal", adjudication_refs=(f"adjudication:{case_id}",),
    )


class CounterfactualTests(unittest.TestCase):
    def test_identical_rulesets_are_unchanged_correct(self):
        report = run_counterfactual_suite((case(),), ruleset("1"), ruleset("1"))
        self.assertEqual(report.case_replays[0].status, CaseComparisonStatus.UNCHANGED_CORRECT)
        self.assertEqual(report.summary.baseline_exact_match_cases, 1)
        self.assertEqual(report.summary.candidate_exact_match_cases, 1)

    def test_candidate_fix_is_improvement(self):
        report = run_counterfactual_suite((case(),), ruleset("1", value="low"), ruleset("2"))
        self.assertEqual(report.case_replays[0].status, CaseComparisonStatus.IMPROVED)

    def test_candidate_breaking_correct_case_is_regression(self):
        report = run_counterfactual_suite((case(),), ruleset("1"), ruleset("2", value="low"))
        self.assertEqual(report.case_replays[0].status, CaseComparisonStatus.REGRESSED)

    def test_both_wrong_is_unchanged_incorrect(self):
        report = run_counterfactual_suite((case(),), ruleset("1", value="low"), ruleset("2", value="medium"))
        self.assertEqual(report.case_replays[0].status, CaseComparisonStatus.UNCHANGED_INCORRECT)

    def test_added_and_removed_conclusions_reported(self):
        baseline = RuleSet((
            RuleDefinition("R1", "1", (PropositionPattern("patient", "finding", "positive"),),
                           ConclusionTemplate("patient", "risk", "low")),
        ), "base")
        candidate = RuleSet((
            RuleDefinition("R1", "2", (PropositionPattern("patient", "finding", "positive"),),
                           ConclusionTemplate("patient", "risk", "high")),
            RuleDefinition("R2", "1", (PropositionPattern("patient", "finding", "positive"),),
                           ConclusionTemplate("patient", "review", "needed")),
        ), "cand")
        replay = run_counterfactual_suite((case(),), baseline, candidate).case_replays[0]
        self.assertEqual(len(replay.added_by_candidate), 2)
        self.assertEqual(len(replay.removed_by_candidate), 1)

    def test_partial_execution_is_indeterminate(self):
        many = RegressionCase(
            "many", tuple(Proposition(f"p{i}", "patient", "finding", "positive") for i in range(3)),
            (ConclusionSignature("patient", "risk", "high"),),
        )
        limited = RuleSet((RuleDefinition(
            "RISK", "1", (PropositionPattern("patient", "finding", "positive"),),
            ConclusionTemplate("patient", "risk", "high"), max_firings=10,
        ),), "limited")
        report = run_counterfactual_suite((many,), limited, limited,
                                          limits=ExecutionLimits(max_rounds=2, max_total_firings=1))
        self.assertEqual(report.case_replays[0].status, CaseComparisonStatus.INDETERMINATE)
        self.assertEqual(report.summary.indeterminate, 1)

    def test_duplicate_case_ids_rejected(self):
        with self.assertRaises(ValueError):
            run_counterfactual_suite((case("x"), case("x")), ruleset("1"), ruleset("2"))

    def test_duplicate_expected_conclusions_rejected(self):
        with self.assertRaises(ValueError):
            RegressionCase("x", (), (ConclusionSignature("s", "p", 1), ConclusionSignature("s", "p", 1)))

    def test_duplicate_input_proposition_ids_rejected(self):
        with self.assertRaises(ValueError):
            RegressionCase("x", (Proposition("p", "s", "p", 1), Proposition("p", "s", "q", 2)), ())

    def test_suite_sorted_deterministically(self):
        report = run_counterfactual_suite((case("z"), case("a")), ruleset("1"), ruleset("1"))
        self.assertEqual([r.case_id for r in report.case_replays], ["a", "z"])

    def test_empty_suite_is_valid(self):
        report = run_counterfactual_suite((), ruleset("1"), ruleset("2"))
        self.assertEqual(report.summary.total_cases, 0)


if __name__ == "__main__":
    unittest.main()
