from datetime import datetime, timezone, timedelta
import unittest

from engram_erc.contracts import (
    Proposition, PropositionKind, InferenceStep, ReasoningGraph,
    ReasoningResult, ReasoningStatus,
)
from engram_erc.feedback import (
    FeedbackLedger, OutcomeEvent, OutcomeLabel,
)
from engram_erc.trace_learning import (
    TraceLearningPolicy, TraceLearningStatus, learn_reasoning_traces,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def make_result():
    props = (
        Proposition("p0", "patient", "finding", "A"),
        Proposition("p1", "patient", "risk", "high", kind=PropositionKind.INFERENCE),
        Proposition("p2", "patient", "plan", "review", kind=PropositionKind.INFERENCE),
        Proposition("p3", "patient", "recommendation", "review", kind=PropositionKind.INFERENCE),
    )
    steps = (
        InferenceStep("s1", "rule_application", ("p0",), ("p1",), "RISK_RULE"),
        InferenceStep("s2", "rule_application", ("p1",), ("p2",), "PLAN_RULE"),
        InferenceStep("s3", "rule_application", ("p0",), ("p3",), "UNRELATED_RULE"),
    )
    return ReasoningResult("res1", "req1", ReasoningStatus.COMPLETE, ("p2",),
        props, steps, ReasoningGraph())


def event(i, outcome=OutcomeLabel.VERIFIED_SUPPORTED, result="res1", conclusion="p2"):
    return OutcomeEvent(f"ev{i}", result, conclusion, outcome,
        NOW - timedelta(days=i), "adjudicator:1", "surgical_assessment",
        ("robotic",), rule_refs=("RISK_RULE", "PLAN_RULE"))


class TraceLearningTests(unittest.TestCase):
    def test_lineage_excludes_unrelated_steps_and_preserves_order(self):
        report = learn_reasoning_traces(FeedbackLedger((event(1),)), (make_result(),),
            policy=TraceLearningPolicy(min_adjudicated_events=1), generated_at=NOW)
        self.assertEqual(report.patterns[0].path_signature, (
            "rule_application:RISK_RULE", "rule_application:PLAN_RULE"))
        self.assertEqual({step.rule_id for step in report.steps}, {"RISK_RULE", "PLAN_RULE"})
        self.assertEqual(report.patterns[0].root_premise_signature, ("finding|polarity=1",))

    def test_minimum_sample_threshold_controls_comparison_eligibility(self):
        ledger = FeedbackLedger(tuple(event(i) for i in range(1, 5)))
        report = learn_reasoning_traces(ledger, (make_result(),), generated_at=NOW)
        self.assertEqual(report.status, TraceLearningStatus.INSUFFICIENT_DATA)
        self.assertEqual(report.patterns[0].counts.adjudicated, 4)
        self.assertFalse(report.patterns[0].eligible_for_comparison)

    def test_adjudicated_counts_and_rate_exclude_inconclusive_superseded(self):
        ledger = FeedbackLedger((event(1), event(2, OutcomeLabel.CONTRADICTED),
            event(3, OutcomeLabel.INCONCLUSIVE), event(4, OutcomeLabel.SUPERSEDED)))
        report = learn_reasoning_traces(ledger, (make_result(),),
            policy=TraceLearningPolicy(min_adjudicated_events=2), generated_at=NOW)
        counts = report.patterns[0].counts
        self.assertEqual(counts.adjudicated, 2)
        self.assertEqual(counts.inconclusive, 1)
        self.assertEqual(counts.superseded, 1)
        self.assertEqual(counts.observed_success_rate, 0.5)

    def test_unmatched_result_and_conclusion_are_reported(self):
        ledger = FeedbackLedger((event(1, result="missing"), event(2, conclusion="not_a_conclusion")))
        report = learn_reasoning_traces(ledger, (make_result(),), generated_at=NOW)
        self.assertEqual({x.reason for x in report.unmatched_outcomes}, {
            "RESULT_NOT_SUPPLIED", "CONCLUSION_NOT_IN_RESULT"})
        self.assertEqual(report.status, TraceLearningStatus.NO_MATCHING_TRACES)

    def test_no_inference_lineage_is_not_fabricated(self):
        result = make_result()
        direct = ReasoningResult("direct", "req", ReasoningStatus.COMPLETE, ("p0",),
            result.propositions, (), ReasoningGraph())
        ledger = FeedbackLedger((event(1, result="direct", conclusion="p0"),))
        report = learn_reasoning_traces(ledger, (direct,), generated_at=NOW)
        self.assertEqual(report.unmatched_outcomes[0].reason, "NO_RECORDED_INFERENCE_LINEAGE")

    def test_contexts_are_separated(self):
        a = event(1)
        b = OutcomeEvent("ev-b", "res1", "p2", OutcomeLabel.CONTRADICTED,
            NOW - timedelta(days=2), "adjudicator:1", "surgical_assessment",
            ("open",), rule_refs=("RISK_RULE",))
        report = learn_reasoning_traces(FeedbackLedger((a, b)), (make_result(),),
            policy=TraceLearningPolicy(min_adjudicated_events=1), generated_at=NOW)
        self.assertEqual({p.context_key for p in report.patterns}, {
            "surgical_assessment|robotic", "surgical_assessment|open"})

    def test_naive_report_time_rejected(self):
        with self.assertRaises(ValueError):
            learn_reasoning_traces(FeedbackLedger(), (), generated_at=datetime(2026, 1, 1))
