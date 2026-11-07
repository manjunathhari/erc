import unittest
from datetime import datetime, timezone, timedelta

from engram_erc.calibration import (
    CalibrationOutcome, CalibrationObservation, CalibrationLedger,
    ReliabilityStatus, CalibrationPolicy, monitor_reliability,
)


NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def obs(i, day, confidence, outcome, context="robotic_colorectal"):
    return CalibrationObservation(
        observation_id=f"obs-{i}", result_id=f"result-{i}",
        conclusion_ref=f"conclusion-{i}", confidence=confidence,
        confidence_semantics="estimated probability that this conclusion is correct",
        confidence_source_ref="calibration-model:v1",
        outcome=outcome,
        observed_at=NOW - timedelta(days=day),
        adjudication_source_ref=f"adjudication-{i}",
        context_key=context,
    )


def policy(**kwargs):
    values=dict(bin_count=5, min_observations=10,
                rolling_window_days=30, min_reference_observations=10,
                min_context_observations=5,
                max_expected_calibration_error=0.15,
                max_brier_score=0.20, max_ece_change=0.10,
                max_accuracy_decline=0.15)
    values.update(kwargs)
    return CalibrationPolicy(**values)


def good_ledger():
    items=[]
    # Previous window: 16 observations, 12 correct, confidence 0.75.
    for i in range(16):
        items.append(obs(f"ref-{i}", 40, 0.75,
            CalibrationOutcome.CORRECT if i < 12 else CalibrationOutcome.INCORRECT))
    # Current window: same empirical calibration, different IDs.
    for i in range(16):
        items.append(obs(f"cur-{i}", 5, 0.75,
            CalibrationOutcome.CORRECT if i < 12 else CalibrationOutcome.INCORRECT))
    return CalibrationLedger(tuple(items))


class CalibrationTests(unittest.TestCase):
    def test_calibration_metrics_and_reliability_bins(self):
        report=monitor_reliability(good_ledger(),generated_at=NOW,policy=policy())
        self.assertEqual(report.current.adjudicated_count,16)
        self.assertAlmostEqual(report.current.observed_accuracy,0.75)
        self.assertAlmostEqual(report.current.mean_confidence,0.75)
        self.assertAlmostEqual(report.current.brier_score,0.1875)
        self.assertAlmostEqual(report.current.expected_calibration_error,0.0)
        self.assertEqual(report.current.status,ReliabilityStatus.ADEQUATE)

    def test_monitoring_passes_when_stable(self):
        report=monitor_reliability(good_ledger(),generated_at=NOW,policy=policy())
        self.assertEqual(report.status,ReliabilityStatus.ADEQUATE)
        self.assertEqual(report.alerts,())

    def test_detects_calibration_drift(self):
        items=[]
        for i in range(20):
            items.append(obs(f"r-{i}",40,0.5,
                CalibrationOutcome.CORRECT if i < 10 else CalibrationOutcome.INCORRECT))
            items.append(obs(f"c-{i}",5,0.9,
                CalibrationOutcome.CORRECT if i < 10 else CalibrationOutcome.INCORRECT))
        report=monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,
            policy=policy(max_ece_change=0.05))
        self.assertEqual(report.status,ReliabilityStatus.RELIABILITY_DRIFT)
        self.assertTrue(any(x.code=="CALIBRATION_ERROR_DRIFT" for x in report.alerts))

    def test_detects_accuracy_decline(self):
        items=[]
        for i in range(20):
            items.append(obs(f"r-{i}",40,0.8,
                CalibrationOutcome.CORRECT if i < 16 else CalibrationOutcome.INCORRECT))
            items.append(obs(f"c-{i}",5,0.8,
                CalibrationOutcome.CORRECT if i < 8 else CalibrationOutcome.INCORRECT))
        report=monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,
            policy=policy(max_accuracy_decline=0.1))
        self.assertTrue(any(x.code=="OBSERVED_ACCURACY_DECLINE" for x in report.alerts))

    def test_insufficient_reference_window_abstains(self):
        items=[obs(f"c-{i}",5,0.8,CalibrationOutcome.CORRECT) for i in range(20)]
        report=monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,policy=policy())
        self.assertEqual(report.status,ReliabilityStatus.INSUFFICIENT_DATA)
        self.assertTrue(any(x.code=="REFERENCE_WINDOW_INSUFFICIENT" for x in report.alerts))

    def test_context_metrics_and_context_minimum(self):
        items=[]
        for i in range(12):
            items.append(obs(f"a-{i}",5,0.8,CalibrationOutcome.CORRECT if i<10 else CalibrationOutcome.INCORRECT,"robotic_colorectal"))
        for i in range(4):
            items.append(obs(f"b-{i}",5,0.8,CalibrationOutcome.CORRECT,"upper_gi"))
        report=monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,
            policy=policy(min_context_observations=8))
        contexts={x.context_key:x.metrics for x in report.contexts}
        self.assertEqual(contexts["robotic_colorectal"].status,ReliabilityStatus.ADEQUATE)
        self.assertEqual(contexts["upper_gi"].status,ReliabilityStatus.INSUFFICIENT_DATA)

    def test_inconclusive_and_superseded_excluded_but_counted(self):
        items=[obs(f"good-{i}",5,0.8,CalibrationOutcome.CORRECT) for i in range(12)]
        items += [obs("inc",5,0.9,CalibrationOutcome.INCONCLUSIVE),
                  obs("sup",5,0.9,CalibrationOutcome.SUPERSEDED)]
        report=monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,
            policy=policy(min_reference_observations=1))
        self.assertEqual(report.current.observation_count,14)
        self.assertEqual(report.current.adjudicated_count,12)
        self.assertEqual(report.current.inconclusive_count,1)
        self.assertEqual(report.current.superseded_count,1)

    def test_future_observations_excluded(self):
        future=CalibrationObservation("future","r","c",0.8,"probability correctness",
            "model:v1",CalibrationOutcome.CORRECT,NOW+timedelta(days=1),"adj","context")
        report=monitor_reliability(CalibrationLedger((future,)),generated_at=NOW,policy=policy())
        self.assertEqual(report.excluded_future_observations,1)
        self.assertEqual(report.current.observation_count,0)

    def test_ledger_idempotency_and_collision(self):
        x=obs("same",5,0.8,CalibrationOutcome.CORRECT)
        ledger=CalibrationLedger().append(x)
        self.assertIs(ledger.append(x),ledger)
        changed=CalibrationObservation("obs-same","other","c",0.2,"semantics","model",
            CalibrationOutcome.INCORRECT,NOW-timedelta(days=5),"adj","ctx")
        with self.assertRaisesRegex(ValueError,"different content"):
            ledger.append(changed)

    def test_duplicate_ids_rejected(self):
        x=obs("same",5,0.8,CalibrationOutcome.CORRECT)
        with self.assertRaisesRegex(ValueError,"duplicate observation_id"):
            CalibrationLedger((x,x))

    def test_naive_datetime_rejected(self):
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            CalibrationObservation("x","r","c",0.5,"semantics","model",
                CalibrationOutcome.CORRECT,datetime(2026,1,1),"adj","ctx")

    def test_confidence_range_and_semantics_validated(self):
        with self.assertRaisesRegex(ValueError,"between 0 and 1"):
            CalibrationObservation("x","r","c",1.2,"semantics","model",
                CalibrationOutcome.CORRECT,NOW,"adj","ctx")
        with self.assertRaisesRegex(ValueError,"finite numeric"):
            CalibrationObservation("bool","r","c",True,"semantics","model",
                CalibrationOutcome.CORRECT,NOW,"adj","ctx")
        with self.assertRaisesRegex(ValueError,"confidence_semantics"):
            CalibrationObservation("x","r","c",0.5," ","model",
                CalibrationOutcome.CORRECT,NOW,"adj","ctx")

    def test_future_generated_at_rejected_if_naive(self):
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            monitor_reliability(CalibrationLedger(),generated_at=datetime(2026,1,1),policy=policy())

    def test_policy_validation(self):
        with self.assertRaises(ValueError):
            CalibrationPolicy(bin_count=0)
        with self.assertRaises(ValueError):
            CalibrationPolicy(max_brier_score=1.5)

    def test_no_confidence_inference_from_erc_decisions(self):
        # Observation requires explicit confidence and provenance; no API accepts an ERC decision as a score.
        with self.assertRaises(TypeError):
            CalibrationObservation("x","r","c", outcome=CalibrationOutcome.CORRECT,
                observed_at=NOW, adjudication_source_ref="adj", context_key="ctx")

    def test_reference_and_current_windows_are_non_overlapping(self):
        report=monitor_reliability(good_ledger(),generated_at=NOW,policy=policy())
        self.assertLess(report.reference.observation_count, 100)
        self.assertEqual(report.current.observation_count,16)

    def test_mixed_confidence_sources_require_separate_reports(self):
        items=list(good_ledger().observations)
        x=items[-1]
        items[-1]=CalibrationObservation(x.observation_id,x.result_id,x.conclusion_ref,
            x.confidence,x.confidence_semantics,"calibration-model:v2",x.outcome,
            x.observed_at,x.adjudication_source_ref,x.context_key)
        with self.assertRaisesRegex(ValueError,"multiple confidence sources"):
            monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,policy=policy())

    def test_source_filter_prevents_mixing(self):
        items=list(good_ledger().observations)
        x=items[-1]
        items[-1]=CalibrationObservation(x.observation_id,x.result_id,x.conclusion_ref,
            x.confidence,x.confidence_semantics,"calibration-model:v2",x.outcome,
            x.observed_at,x.adjudication_source_ref,x.context_key)
        report=monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,
            policy=policy(),confidence_source_ref="calibration-model:v1")
        self.assertEqual(report.current.adjudicated_count,15)
        self.assertEqual(report.confidence_source_ref,"calibration-model:v1")

    def test_mixed_semantics_require_separate_reports(self):
        items=list(good_ledger().observations)
        x=items[-1]
        items[-1]=CalibrationObservation(x.observation_id,x.result_id,x.conclusion_ref,
            x.confidence,"score of evidence sufficiency",x.confidence_source_ref,x.outcome,
            x.observed_at,x.adjudication_source_ref,x.context_key)
        with self.assertRaisesRegex(ValueError,"multiple confidence semantics"):
            monitor_reliability(CalibrationLedger(tuple(items)),generated_at=NOW,policy=policy())


if __name__=="__main__":
    unittest.main()
