# Engram Reasoning Core (ERC) — ERC-2.5

**Milestone:** Reasoning Calibration and Reliability Monitoring  
**Version:** 0.2.5  
**Status:** Implemented; cumulative test suite passes 169/169.

## Purpose

ERC-2.5 adds a calibration and monitoring layer for confidence attached to individual reasoning conclusions. It deliberately separates:

1. **Conclusion-level confidence:** a score supplied by the producing system for one conclusion, with explicit semantics and provenance.
2. **Historical reliability:** how often conclusions with those scores were subsequently adjudicated correct or incorrect over a defined cohort and time window.

ERC does not derive confidence from evidence counts, evidence quality labels, accepted/provisional decisions, rule scores, strategy rankings or historical accuracy. Those are different quantities and must not be silently conflated.

Implementation: `engram_erc/calibration.py`.

## Public API

- `CalibrationOutcome`: `CORRECT`, `INCORRECT`, `INCONCLUSIVE`, `SUPERSEDED`.
- `CalibrationObservation`: immutable conclusion-level confidence score, score semantics, score-source reference, outcome, timestamp, adjudication reference and context.
- `CalibrationLedger`: immutable append-only, event-ID-idempotent ledger.
- `CalibrationPolicy`: bin count, minimum current/reference/context samples, rolling-window length and alert thresholds.
- `ReliabilityBin`: count, mean confidence, observed accuracy and absolute calibration gap for one confidence interval.
- `CalibrationMetrics`: observed accuracy, mean confidence, Brier score, log loss, expected calibration error (ECE), maximum calibration error and bin table.
- `ContextReliability`: separate metrics for each current-window context.
- `ReliabilityAlert`: machine-readable warning code, severity, observed value and configured threshold.
- `ReliabilityMonitoringReport`: current and preceding reference-window metrics, context metrics, drift deltas, alerts and limitations.
- `monitor_reliability(ledger, generated_at=..., policy=..., confidence_source_ref=..., confidence_semantics=...)`.

## Statistical definitions

For each explicitly adjudicated conclusion, confidence is `p` and correctness is `y` (1 for correct, 0 for incorrect).

- **Observed accuracy:** mean of `y`.
- **Mean confidence:** mean of `p`.
- **Brier score:** mean of `(p - y)^2`; lower is better.
- **Log loss:** mean binary logarithmic loss with configurable clipping epsilon.
- **ECE:** confidence-bin-weighted absolute difference between mean confidence and observed accuracy.
- **Maximum calibration error:** largest absolute confidence/accuracy gap among non-empty bins.

Inconclusive and superseded outcomes are excluded from calibration scoring but remain counted in the report. Current-window reliability is compared with the immediately preceding, non-overlapping window of equal duration. Alerts are triggered by configured ECE deterioration, accuracy decline, ECE limit or Brier limit.

A monitoring run must use one confidence source and one semantic definition. If multiple sources or meanings are present, separate reports must be requested explicitly. This prevents mixing, for example, a probability of conclusion correctness with a score of evidence sufficiency.

## Example

```python
from engram_erc.calibration import (
    CalibrationPolicy, CalibrationLedger, monitor_reliability,
)

report = monitor_reliability(
    calibration_ledger,
    generated_at=aware_datetime,
    policy=CalibrationPolicy(
        bin_count=10,
        min_observations=50,
        rolling_window_days=90,
        min_reference_observations=50,
        max_expected_calibration_error=0.08,
        max_brier_score=0.15,
        max_ece_change=0.04,
        max_accuracy_decline=0.08,
        min_context_observations=30,
    ),
    confidence_source_ref="erc-confidence:v1",
    confidence_semantics="estimated probability that this conclusion is correct",
)
print(report.status)
print(report.current.brier_score, report.current.expected_calibration_error)
for alert in report.alerts:
    print(alert.code, alert.current_value, alert.threshold)
```

These values are illustrative configuration, not clinically validated thresholds. The confidence source must document how it generates the score and whether the score is intended as a probability.

## Reliability states

- `ADEQUATE`: current and reference windows meet minimum sample requirements and no configured warning/drift threshold is breached.
- `CALIBRATION_WARNING`: adequate samples, but current ECE or Brier score exceeds a configured limit.
- `RELIABILITY_DRIFT`: adequate samples and the current-vs-reference ECE or observed-accuracy change exceeds a configured drift threshold.
- `INSUFFICIENT_DATA`: current or reference adjudicated sample is below its minimum. This takes precedence over a reassuring point estimate.

Context metrics use a separate minimum context sample. Small contexts are flagged as insufficient rather than being treated as reliable.

## Safeguards and limitations

- Confidence score, score semantics and score source are caller-supplied; ERC does not manufacture or recalibrate them.
- Adjudication outcome and source must be explicit. The caller owns adjudication independence, quality and provenance.
- Brier score, log loss and ECE are descriptive calibration metrics, not proof of clinical utility or safety.
- ECE is sensitive to bin count and boundaries. Always inspect reliability-bin counts and gaps; do not interpret ECE alone.
- Two-window monitoring is a practical drift signal, not a formal sequential hypothesis test or proof of distribution shift.
- Small subgroups produce unstable estimates. Minimums are software safeguards, not statistical power calculations.
- No automatic recalibration, confidence override, rule change, strategy update, registry write, P6 mutation or clinical release occurs.
- Calibration is not a substitute for ERC-2.4's paired validation uncertainty. ERC-2.4 quantifies uncertainty in comparative validation; ERC-2.5 monitors whether a confidence score corresponds to historical correctness.

## Cumulative milestone contents

This package includes ERC-1.1 through ERC-2.5: typed contracts, reasoning graph, primitives, bounded rule execution, orchestration, evidence-aware evaluation, outcome feedback, contextual adaptation, trace learning, human-reviewed improvement proposals, counterfactual replay, development/holdout generalisation, temporal/external validation, statistical uncertainty and conclusion-level calibration/reliability monitoring.

## Validation

```bash
python -m pytest -q
```

**Result:** 169 tests passed.

## Integration status

This is a cumulative source package. It is not a claim that ERC has been merged into the private Engram repository or connected to live registry/P6 persistence. A future thin adapter should supply confidence scores with documented semantics, source/version references, adjudicated outcomes, timestamps and context from the existing Engram systems.
