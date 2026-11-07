import unittest
from datetime import datetime, timezone, timedelta

from engram_erc import (
    AdaptationPolicy, AdaptationStatus, FeedbackLedger, OutcomeEvent,
    OutcomeLabel, ScoreOrigin, StrategyDefinition, StrategyExperienceScore,
    StrategyOperation, StrategyCatalog, ReasoningRequest,
    rank_eligible_strategies, rank_catalog_strategies, strategy_ref,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def strategy(name, priority=0):
    return StrategyDefinition(name, "1.0", ("surgical_case_review",),
        (StrategyOperation.DETECT_CONTRADICTIONS,), priority=priority)


def event(i, strat, outcome, tags=("robotic", "colorectal")):
    return OutcomeEvent(
        event_id=f"e{i}", result_id=f"r{i}", conclusion_ref=f"c{i}",
        outcome=outcome, observed_at=NOW - timedelta(days=i),
        adjudication_source_ref=f"registry:{i}", task_type="surgical_case_review",
        context_tags=tags, strategy_ref=strat,
    )


class AdaptationTests(unittest.TestCase):
    def setUp(self):
        self.a = strategy("strategy_a", 20)
        self.b = strategy("strategy_b", 10)

    def test_no_experience_abstains_and_preserves_catalog_priority(self):
        report = rank_eligible_strategies((self.b, self.a), task_type="surgical_case_review")
        self.assertEqual(report.status, AdaptationStatus.INSUFFICIENT_EXPERIENCE)
        self.assertEqual(report.selected_strategy_ref, "strategy_a@1.0")
        self.assertTrue(report.abstention_reason)

    def test_outcome_rate_ranks_only_eligible_strategies(self):
        events = [event(i, "strategy_a@1.0", OutcomeLabel.VERIFIED_SUPPORTED) for i in range(1, 6)]
        events += [event(i + 10, "strategy_b@1.0", OutcomeLabel.CONTRADICTED) for i in range(1, 6)]
        report = rank_eligible_strategies((self.a,), task_type="surgical_case_review",
                                         feedback=FeedbackLedger(tuple(events)))
        self.assertEqual(len(report.rankings), 1)
        self.assertEqual(report.selected_strategy_ref, "strategy_a@1.0")
        self.assertEqual(report.rankings[0].score, 1.0)

    def test_exact_context_preferred(self):
        events = [event(i, "strategy_a@1.0", OutcomeLabel.VERIFIED_SUPPORTED) for i in range(1, 6)]
        events += [event(i + 10, "strategy_a@1.0", OutcomeLabel.CONTRADICTED,
                         tags=("robotic",)) for i in range(1, 8)]
        report = rank_eligible_strategies((self.a,), task_type="surgical_case_review",
            context_tags=("robotic", "colorectal"), feedback=FeedbackLedger(tuple(events)),
            policy=AdaptationPolicy(5, allow_task_level_fallback=False))
        self.assertEqual(report.rankings[0].score, 1.0)
        self.assertFalse(report.rankings[0].context_fallback)

    def test_task_level_fallback_is_explicit(self):
        events = [event(i, "strategy_a@1.0", OutcomeLabel.VERIFIED_SUPPORTED,
                        tags=("robotic",)) for i in range(1, 6)]
        report = rank_eligible_strategies((self.a,), task_type="surgical_case_review",
            context_tags=("robotic", "colorectal"), feedback=FeedbackLedger(tuple(events)))
        self.assertTrue(report.rankings[0].context_fallback)
        self.assertEqual(report.rankings[0].context_used, "surgical_case_review")

    def test_inconclusive_and_superseded_do_not_enter_rate_or_n(self):
        events = [event(i, "strategy_a@1.0", OutcomeLabel.VERIFIED_SUPPORTED) for i in range(1, 5)]
        events.append(event(5, "strategy_a@1.0", OutcomeLabel.INCONCLUSIVE))
        events.append(event(6, "strategy_a@1.0", OutcomeLabel.SUPERSEDED))
        report = rank_eligible_strategies((self.a,), task_type="surgical_case_review",
            context_tags=("robotic", "colorectal"), feedback=FeedbackLedger(tuple(events)))
        self.assertEqual(report.rankings[0].sample_size, 4)
        self.assertIsNone(report.rankings[0].score)

    def test_external_p6_adapter_score_preferred(self):
        ext = StrategyExperienceScore("strategy_b@1.0",
            "surgical_case_review|colorectal&robotic", 0.91, 20, "p6-policy-score-22")
        report = rank_eligible_strategies((self.a, self.b), task_type="surgical_case_review",
            context_tags=("robotic", "colorectal"), external_scores=(ext,))
        self.assertEqual(report.selected_strategy_ref, "strategy_b@1.0")
        chosen = report.rankings[0]
        self.assertEqual(chosen.origin, ScoreOrigin.P6_ADAPTER)
        self.assertIn("p6-policy-score-22", chosen.source_refs)
        self.assertTrue(chosen.uncertainty_note)

    def test_external_score_requires_minimum_sample(self):
        ext = StrategyExperienceScore("strategy_b@1.0",
            "surgical_case_review|colorectal&robotic", 0.99, 2, "p6-small")
        report = rank_eligible_strategies((self.a, self.b), task_type="surgical_case_review",
            context_tags=("robotic", "colorectal"), external_scores=(ext,))
        self.assertEqual(report.status, AdaptationStatus.INSUFFICIENT_EXPERIENCE)
        self.assertEqual(report.selected_strategy_ref, "strategy_a@1.0")

    def test_require_exact_context_abstains_from_fallback(self):
        events = [event(i, "strategy_b@1.0", OutcomeLabel.VERIFIED_SUPPORTED,
                        tags=("robotic",)) for i in range(1, 7)]
        report = rank_eligible_strategies((self.a, self.b), task_type="surgical_case_review",
            context_tags=("robotic", "colorectal"), feedback=FeedbackLedger(tuple(events)),
            policy=AdaptationPolicy(5, True, True))
        self.assertEqual(report.status, AdaptationStatus.INSUFFICIENT_EXPERIENCE)
        self.assertEqual(report.selected_strategy_ref, "strategy_a@1.0")

    def test_only_caller_supplied_eligible_candidates_are_ranked(self):
        report = rank_eligible_strategies((self.b,), task_type="surgical_case_review")
        self.assertEqual([x.strategy_ref for x in report.rankings], ["strategy_b@1.0"])

    def test_catalog_helper_preserves_canonical_eligibility(self):
        needs_rules = StrategyDefinition("needs_rules", "1.0", ("surgical_case_review",),
            (StrategyOperation.APPLY_RULES,), requires_rules=True)
        catalog = StrategyCatalog((needs_rules, self.a))
        request = ReasoningRequest("req-1", "surgical_case_review", ())
        report = rank_catalog_strategies(request, catalog, has_rules=False)
        self.assertEqual([x.strategy_ref for x in report.rankings], ["strategy_a@1.0"])

    def test_validation_and_empty_candidates(self):
        with self.assertRaises(ValueError):
            StrategyExperienceScore("s", "ctx", 1.1, 10, "src")
        with self.assertRaises(ValueError):
            rank_eligible_strategies((self.a,), task_type="x", context_tags=("a", "a"))
        report = rank_eligible_strategies((), task_type="surgical_case_review")
        self.assertEqual(report.status, AdaptationStatus.NO_ELIGIBLE_STRATEGIES)

    def test_ties_are_deterministic(self):
        events = [event(i, "strategy_a@1.0", OutcomeLabel.VERIFIED_SUPPORTED) for i in range(1, 6)]
        events += [event(i + 10, "strategy_b@1.0", OutcomeLabel.VERIFIED_SUPPORTED) for i in range(1, 6)]
        report = rank_eligible_strategies((self.b, self.a), task_type="surgical_case_review",
            context_tags=("robotic", "colorectal"), feedback=FeedbackLedger(tuple(events)))
        self.assertEqual(report.selected_strategy_ref, "strategy_a@1.0")


if __name__ == "__main__":
    unittest.main()
