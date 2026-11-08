from datetime import datetime, timezone, timedelta
import unittest

from engram_erc.contracts import (
    Proposition, PropositionKind, InferenceStep, ReasoningGraph,
    ReasoningResult, ReasoningStatus, TraceEntry,
)
from engram_erc.feedback import FeedbackLedger, OutcomeEvent, OutcomeLabel
from engram_erc.failure_analysis import (
    FailureCategory, FailureSymptom, SignalKind, AttributionStatus,
    FailureSignal, FailureCase, FailureAnalysisPolicy, analyze_reasoning_failures,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def make_result():
    props = (
        Proposition("p0", "patient", "finding", "A"),
        Proposition("p1", "patient", "risk", "high", kind=PropositionKind.INFERENCE),
        Proposition("p2", "patient", "plan", "review", kind=PropositionKind.INFERENCE),
    )
    steps = (
        InferenceStep("s1", "rule_application", ("p0",), ("p1",), "RISK_RULE"),
        InferenceStep("s2", "rule_application", ("p1",), ("p2",), "PLAN_RULE"),
    )
    trace = (TraceEntry(0, "extract", ("raw:1",), ("p0",), "complete", explanation_code="EXTRACT_OK"),)
    return ReasoningResult("res1", "req1", ReasoningStatus.COMPLETE, ("p2",),
        props, steps, ReasoningGraph(), trace=trace)


def make_event(outcome=OutcomeLabel.CONTRADICTED, result="res1", conclusion="p2"):
    return OutcomeEvent("ev1", result, conclusion, outcome, NOW,
        "adjudicator:source", "surgical_assessment", rule_refs=("RISK_RULE",))


def make_case(signals=(), event_ref="ev1", result="res1", conclusion="p2"):
    return FailureCase("case1", result, conclusion, event_ref,
        FailureSymptom.INCORRECT_CONCLUSION, ("s2",), tuple(signals), "robotic")


class FailureAnalysisTests(unittest.TestCase):
    def test_multiple_contributing_causes_are_retained(self):
        signals = (
            FailureSignal(FailureCategory.MISSING_KNOWLEDGE_OR_EVIDENCE,
                SignalKind.OBSERVED, ("p0",), "Required source absent from supplied snapshot."),
            FailureSignal(FailureCategory.RULE_APPLICATION_ERROR,
                SignalKind.HYPOTHESIZED, ("s2",), "Rule boundary may have been misapplied."),
        )
        report = analyze_reasoning_failures((make_case(signals),), (make_result(),),
            FeedbackLedger((make_event(),)))
        self.assertEqual(len(report.analyzed_cases[0].attributions), 2)
        self.assertTrue(report.analyzed_cases[0].unresolved)
        self.assertEqual({a.status for a in report.analyzed_cases[0].attributions},
            {AttributionStatus.SUPPORTED_HYPOTHESIS})

    def test_adjudicator_confirmation_requires_and_preserves_reference(self):
        signal = FailureSignal(FailureCategory.PREMISE_EXTRACTION_ERROR,
            SignalKind.OBSERVED, ("p0",), "Adjudicated extraction omission.",
            True, "adjudication:42")
        report = analyze_reasoning_failures((make_case((signal,)),), (make_result(),),
            FeedbackLedger((make_event(),)))
        attribution = report.analyzed_cases[0].attributions[0]
        self.assertEqual(attribution.status, AttributionStatus.CONFIRMED_BY_ADJUDICATOR)
        self.assertEqual(attribution.adjudication_refs, ("adjudication:42",))
        self.assertFalse(report.analyzed_cases[0].unresolved)

    def test_missing_basis_reference_abstains(self):
        signal = FailureSignal(FailureCategory.TEMPORAL_REASONING_ERROR,
            SignalKind.HYPOTHESIZED, ("not-in-result",), "Possible stale temporal premise.")
        report = analyze_reasoning_failures((make_case((signal,)),), (make_result(),),
            FeedbackLedger((make_event(),)))
        self.assertEqual(report.analyzed_cases[0].attributions[0].status,
            AttributionStatus.INSUFFICIENT_TRACE)

    def test_non_contradicted_event_excluded_by_default(self):
        report = analyze_reasoning_failures((make_case(),), (make_result(),),
            FeedbackLedger((make_event(OutcomeLabel.VERIFIED_SUPPORTED),)))
        self.assertEqual(report.excluded_cases[0][1], "OUTCOME_NOT_CONTRADICTED")

    def test_event_link_mismatch_excluded(self):
        report = analyze_reasoning_failures((make_case(),), (make_result(),),
            FeedbackLedger((make_event(result="other"),)))
        self.assertEqual(report.excluded_cases[0][1], "OUTCOME_EVENT_LINK_MISMATCH")

    def test_missing_result_excluded(self):
        report = analyze_reasoning_failures((make_case(result="absent"),), (),
            FeedbackLedger((make_event(),)))
        self.assertEqual(report.excluded_cases[0][1], "RESULT_NOT_SUPPLIED")

    def test_confirmed_flag_requires_adjudication_ref(self):
        with self.assertRaises(ValueError):
            FailureSignal(FailureCategory.OTHER, SignalKind.OBSERVED,
                ("p0",), "confirmed", True, None)

    def test_duplicate_basis_refs_rejected(self):
        with self.assertRaises(ValueError):
            FailureSignal(FailureCategory.OTHER, SignalKind.OBSERVED,
                ("p0", "p0"), "duplicate")

    def test_policy_minimum_must_be_positive(self):
        with self.assertRaises(ValueError):
            FailureAnalysisPolicy(min_basis_refs_for_supported_hypothesis=0)

    def test_category_counts_count_cases_not_signal_repetitions(self):
        signals = (
            FailureSignal(FailureCategory.CONTEXT_MISMATCH, SignalKind.OBSERVED,
                ("p0",), "context differs"),
            FailureSignal(FailureCategory.CONTEXT_MISMATCH, SignalKind.HYPOTHESIZED,
                ("s1",), "scope mismatch"),
        )
        report = analyze_reasoning_failures((make_case(signals),), (make_result(),),
            FeedbackLedger((make_event(),)))
        self.assertEqual(report.category_counts, ((FailureCategory.CONTEXT_MISMATCH, 1),))
        self.assertEqual(report.analyzed_cases[0].attributions[0].signal_count, 2)


if __name__ == "__main__":
    unittest.main()
