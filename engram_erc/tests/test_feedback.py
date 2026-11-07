import unittest
from datetime import datetime, timezone

from engram_erc import (
    OutcomeLabel, FeedbackTargetKind, OutcomeEvent, FeedbackLedger,
    summarize_feedback, make_feedback_event_id,
)


def event(event_id, outcome, when, *, rules=("rule-A",), sources=("source-X",),
          tags=("robotic",), strategy="strategy-1"):
    return OutcomeEvent(
        event_id=event_id, result_id=f"result-{event_id}",
        conclusion_ref="conclusion-1", outcome=outcome,
        observed_at=when, adjudication_source_ref="review-record-1",
        task_type="clinical_review", context_tags=tags, rule_refs=rules,
        source_refs=sources, strategy_ref=strategy,
    )


class FeedbackLedgerTests(unittest.TestCase):
    def test_append_is_idempotent_for_same_event(self):
        item = event("evt-1", OutcomeLabel.VERIFIED_SUPPORTED,
                     datetime(2026, 1, 1, tzinfo=timezone.utc))
        ledger = FeedbackLedger().append(item)
        self.assertIs(ledger.append(item), ledger)
        self.assertEqual(len(ledger.events), 1)

    def test_same_id_with_different_payload_is_rejected(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        a = event("evt-1", OutcomeLabel.VERIFIED_SUPPORTED, t)
        b = event("evt-1", OutcomeLabel.CONTRADICTED, t)
        ledger = FeedbackLedger().append(a)
        with self.assertRaises(ValueError):
            ledger.append(b)

    def test_ledger_is_immutable(self):
        ledger = FeedbackLedger()
        item = event("evt-1", OutcomeLabel.VERIFIED_SUPPORTED,
                     datetime(2026, 1, 1, tzinfo=timezone.utc))
        changed = ledger.append(item)
        self.assertEqual(len(ledger.events), 0)
        self.assertEqual(len(changed.events), 1)

    def test_naive_event_time_is_rejected(self):
        with self.assertRaises(ValueError):
            event("evt-1", OutcomeLabel.VERIFIED_SUPPORTED, datetime(2026, 1, 1))

    def test_counts_and_observed_rate(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ledger = FeedbackLedger().append_many((
            event("1", OutcomeLabel.VERIFIED_SUPPORTED, t),
            event("2", OutcomeLabel.VERIFIED_SUPPORTED, t),
            event("3", OutcomeLabel.CONTRADICTED, t),
            event("4", OutcomeLabel.INCONCLUSIVE, t),
            event("5", OutcomeLabel.SUPERSEDED, t),
        ))
        report = summarize_feedback(
            ledger, generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            include_context_tags=False,
        )
        metric = next(m for m in report.metrics
                      if m.target_kind == FeedbackTargetKind.RULE)
        self.assertEqual(metric.counts.total, 5)
        self.assertEqual(metric.counts.adjudicated, 3)
        self.assertAlmostEqual(metric.counts.observed_success_rate, 2/3)

    def test_contexts_are_kept_separate(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        a = event("1", OutcomeLabel.VERIFIED_SUPPORTED, t, tags=("robotic",))
        b = event("2", OutcomeLabel.CONTRADICTED, t, tags=("open",))
        report = summarize_feedback(
            FeedbackLedger((a,b)), generated_at=t
        )
        contexts = {m.context_key for m in report.metrics
                    if m.target_kind == FeedbackTargetKind.RULE}
        self.assertEqual(contexts, {
            "clinical_review", "clinical_review|robotic", "clinical_review|open"
        })

    def test_window_excludes_expired_and_future_events(self):
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        ledger = FeedbackLedger().append_many((
            event("old", OutcomeLabel.VERIFIED_SUPPORTED,
                  datetime(2025, 1, 1, tzinfo=timezone.utc)),
            event("current", OutcomeLabel.VERIFIED_SUPPORTED,
                  datetime(2026, 3, 1, tzinfo=timezone.utc)),
            event("future", OutcomeLabel.CONTRADICTED,
                  datetime(2026, 4, 1, tzinfo=timezone.utc)),
        ))
        report = summarize_feedback(ledger, generated_at=now, window_days=30)
        self.assertEqual(report.excluded_future_events, 1)
        self.assertEqual(report.excluded_out_of_window_events, 1)
        self.assertTrue(all("current" in m.event_refs for m in report.metrics))

    def test_source_and_strategy_metrics_are_reported(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        report = summarize_feedback(
            FeedbackLedger((event("1", OutcomeLabel.CONTRADICTED, t),)),
            generated_at=t, include_context_tags=False,
        )
        kinds = {m.target_kind for m in report.metrics}
        self.assertEqual(kinds, {
            FeedbackTargetKind.CONCLUSION, FeedbackTargetKind.RULE,
            FeedbackTargetKind.SOURCE, FeedbackTargetKind.STRATEGY,
        })

    def test_monthly_metrics_keep_temporal_periods_separate(self):
        jan = datetime(2026, 1, 15, tzinfo=timezone.utc)
        feb = datetime(2026, 2, 15, tzinfo=timezone.utc)
        ledger = FeedbackLedger().append_many((
            event("jan", OutcomeLabel.VERIFIED_SUPPORTED, jan),
            event("feb", OutcomeLabel.CONTRADICTED, feb),
        ))
        report = summarize_feedback(
            ledger, generated_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            include_context_tags=False, period_granularity="month",
        )
        rule_metrics = [m for m in report.metrics
                        if m.target_kind == FeedbackTargetKind.RULE]
        self.assertEqual(len(rule_metrics), 2)
        self.assertNotEqual(rule_metrics[0].period_start, rule_metrics[1].period_start)

    def test_stable_event_id(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertEqual(
            make_feedback_event_id("r", "c", "review", t),
            make_feedback_event_id("r", "c", "review", t),
        )


if __name__ == "__main__":
    unittest.main()
