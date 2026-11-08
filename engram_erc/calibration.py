"""Conclusion-level confidence calibration and historical reliability monitoring.

Confidence is an externally supplied, semantically defined score for an
individual conclusion. Historical correctness is separately supplied through
explicit adjudication. ERC does not infer confidence from evidence counts,
decision labels, rule scores, or prior success rates.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from math import log
from typing import Iterable


class CalibrationOutcome(str, Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    INCONCLUSIVE = "inconclusive"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    observation_id: str
    result_id: str
    conclusion_ref: str
    confidence: float
    confidence_semantics: str
    confidence_source_ref: str
    outcome: CalibrationOutcome
    observed_at: datetime
    adjudication_source_ref: str
    context_key: str

    def __post_init__(self) -> None:
        for name in ("observation_id", "result_id", "conclusion_ref",
                     "confidence_semantics", "confidence_source_ref",
                     "adjudication_source_ref", "context_key"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)) or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be a finite numeric value between 0 and 1")
        if not isinstance(self.outcome, CalibrationOutcome):
            raise ValueError("outcome must be a CalibrationOutcome")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CalibrationLedger:
    observations: tuple[CalibrationObservation, ...] = ()

    def __post_init__(self) -> None:
        ids = [x.observation_id for x in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate observation_id")

    def append(self, observation: CalibrationObservation) -> "CalibrationLedger":
        existing = {x.observation_id: x for x in self.observations}
        if observation.observation_id in existing:
            if existing[observation.observation_id] != observation:
                raise ValueError("observation_id already exists with different content")
            return self
        return CalibrationLedger(self.observations + (observation,))

    def append_many(self, observations: Iterable[CalibrationObservation]) -> "CalibrationLedger":
        ledger = self
        for observation in observations:
            ledger = ledger.append(observation)
        return ledger


class ReliabilityStatus(str, Enum):
    ADEQUATE = "adequate"
    INSUFFICIENT_DATA = "insufficient_data"
    CALIBRATION_WARNING = "calibration_warning"
    RELIABILITY_DRIFT = "reliability_drift"


@dataclass(frozen=True, slots=True)
class CalibrationPolicy:
    bin_count: int = 10
    min_observations: int = 30
    rolling_window_days: int = 90
    min_reference_observations: int = 30
    max_expected_calibration_error: float = 0.10
    max_brier_score: float = 0.20
    max_ece_change: float = 0.05
    max_accuracy_decline: float = 0.10
    min_context_observations: int = 20
    log_loss_epsilon: float = 1e-6

    def __post_init__(self) -> None:
        for name in ("bin_count", "min_observations", "rolling_window_days",
                     "min_reference_observations", "min_context_observations"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        for name in ("max_expected_calibration_error", "max_brier_score",
                     "max_ece_change", "max_accuracy_decline"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not 0.0 < self.log_loss_epsilon < 0.5:
            raise ValueError("log_loss_epsilon must be between 0 and 0.5")


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    lower_bound: float
    upper_bound: float
    count: int
    mean_confidence: float | None
    observed_accuracy: float | None
    calibration_gap: float | None


@dataclass(frozen=True, slots=True)
class CalibrationMetrics:
    observation_count: int
    adjudicated_count: int
    correct_count: int
    incorrect_count: int
    inconclusive_count: int
    superseded_count: int
    observed_accuracy: float | None
    mean_confidence: float | None
    brier_score: float | None
    log_loss: float | None
    expected_calibration_error: float | None
    maximum_calibration_error: float | None
    bins: tuple[ReliabilityBin, ...]
    status: ReliabilityStatus
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextReliability:
    context_key: str
    metrics: CalibrationMetrics


@dataclass(frozen=True, slots=True)
class ReliabilityAlert:
    code: str
    severity: str
    message: str
    current_value: float | None
    threshold: float | None


@dataclass(frozen=True, slots=True)
class ReliabilityMonitoringReport:
    generated_at: datetime
    window_start: datetime
    window_end: datetime
    confidence_source_ref: str
    confidence_semantics: str
    current: CalibrationMetrics
    reference: CalibrationMetrics
    contexts: tuple[ContextReliability, ...]
    ece_change: float | None
    accuracy_change: float | None
    alerts: tuple[ReliabilityAlert, ...]
    status: ReliabilityStatus
    excluded_future_observations: int
    limitations: tuple[str, ...]


def _adjudicated(items: Iterable[CalibrationObservation]):
    return [x for x in items if x.outcome in
            (CalibrationOutcome.CORRECT, CalibrationOutcome.INCORRECT)]


def _metrics(items: Iterable[CalibrationObservation], policy: CalibrationPolicy) -> CalibrationMetrics:
    rows = tuple(items)
    adjudicated = _adjudicated(rows)
    correct = sum(x.outcome == CalibrationOutcome.CORRECT for x in adjudicated)
    incorrect = len(adjudicated) - correct
    inconclusive = sum(x.outcome == CalibrationOutcome.INCONCLUSIVE for x in rows)
    superseded = sum(x.outcome == CalibrationOutcome.SUPERSEDED for x in rows)
    if not adjudicated:
        return CalibrationMetrics(len(rows), 0, 0, 0, inconclusive, superseded,
            None, None, None, None, None, None, (), ReliabilityStatus.INSUFFICIENT_DATA,
            ("NO_ADJUDICATED_OUTCOMES",))
    confidences = [float(x.confidence) for x in adjudicated]
    labels = [1.0 if x.outcome == CalibrationOutcome.CORRECT else 0.0 for x in adjudicated]
    n = len(adjudicated)
    accuracy = sum(labels) / n
    mean_conf = sum(confidences) / n
    brier = sum((p-y)**2 for p,y in zip(confidences,labels)) / n
    eps = policy.log_loss_epsilon
    logloss = -sum(y*log(max(eps,min(1-eps,p))) +
                   (1-y)*log(max(eps,min(1-eps,1-p)))
                   for p,y in zip(confidences,labels)) / n
    bins=[]
    weighted_gap=0.0
    max_gap=0.0
    for i in range(policy.bin_count):
        lo=i/policy.bin_count
        hi=(i+1)/policy.bin_count
        selected=[(p,y) for p,y in zip(confidences,labels)
                  if (lo <= p < hi) or (i == policy.bin_count-1 and p == 1.0)]
        if selected:
            mp=sum(p for p,_ in selected)/len(selected)
            acc=sum(y for _,y in selected)/len(selected)
            gap=abs(mp-acc)
            weighted_gap += len(selected)/n*gap
            max_gap=max(max_gap,gap)
        else:
            mp=acc=gap=None
        bins.append(ReliabilityBin(lo,hi,len(selected),mp,acc,gap))
    status = (ReliabilityStatus.ADEQUATE if n >= policy.min_observations
              else ReliabilityStatus.INSUFFICIENT_DATA)
    limitations=[]
    if n < policy.min_observations:
        limitations.append("SMALL_ADJUDICATED_SAMPLE")
    if inconclusive or superseded:
        limitations.append("INCONCLUSIVE_AND_SUPERSEDED_EXCLUDED_FROM_CALIBRATION_METRICS")
    limitations.append("ECE_DEPENDS_ON_BIN_COUNT_AND_BIN_BOUNDARIES")
    return CalibrationMetrics(len(rows),n,correct,incorrect,inconclusive,superseded,
        accuracy,mean_conf,brier,logloss,weighted_gap,max_gap,tuple(bins),status,
        tuple(limitations))


def monitor_reliability(
    ledger: CalibrationLedger,
    *,
    generated_at: datetime | None = None,
    policy: CalibrationPolicy = CalibrationPolicy(),
    confidence_source_ref: str | None = None,
    confidence_semantics: str | None = None,
) -> ReliabilityMonitoringReport:
    """Compare the latest rolling window with its immediately preceding window.

    All confidence scores and outcomes are conclusion-level. The caller is
    responsible for score semantics, adjudication quality and cohort governance.
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    window_start = generated_at - timedelta(days=policy.rolling_window_days)
    reference_start = window_start - timedelta(days=policy.rolling_window_days)
    eligible = [x for x in ledger.observations if x.observed_at <= generated_at]
    sources = {x.confidence_source_ref for x in eligible}
    semantics_set = {x.confidence_semantics for x in eligible}
    if confidence_source_ref is None:
        if len(sources) > 1:
            raise ValueError("multiple confidence sources present; select confidence_source_ref")
        confidence_source_ref = next(iter(sources), "unspecified")
    if confidence_semantics is None:
        if len(semantics_set) > 1:
            raise ValueError("multiple confidence semantics present; select confidence_semantics")
        confidence_semantics = next(iter(semantics_set), "unspecified")
    current_rows=[]
    reference_rows=[]
    future=0
    for item in ledger.observations:
        if item.observed_at > generated_at:
            future += 1
        elif item.confidence_source_ref != confidence_source_ref or item.confidence_semantics != confidence_semantics:
            continue
        elif window_start <= item.observed_at <= generated_at:
            current_rows.append(item)
        elif reference_start <= item.observed_at < window_start:
            reference_rows.append(item)
    current=_metrics(current_rows,policy)
    reference=_metrics(reference_rows,policy)
    contexts=[]
    context_policy = replace(policy, min_observations=policy.min_context_observations)
    for key in sorted({x.context_key for x in current_rows}):
        ctx=_metrics((x for x in current_rows if x.context_key==key),context_policy)
        contexts.append(ContextReliability(key,ctx))
    ece_change=(current.expected_calibration_error-reference.expected_calibration_error
                if current.expected_calibration_error is not None and
                   reference.expected_calibration_error is not None else None)
    accuracy_change=(current.observed_accuracy-reference.observed_accuracy
                     if current.observed_accuracy is not None and
                        reference.observed_accuracy is not None else None)
    alerts=[]
    if current.adjudicated_count < policy.min_observations:
        alerts.append(ReliabilityAlert("CURRENT_WINDOW_INSUFFICIENT","warning",
            "Too few adjudicated observations to assess current-window calibration.",
            float(current.adjudicated_count),float(policy.min_observations)))
    if reference.adjudicated_count < policy.min_reference_observations:
        alerts.append(ReliabilityAlert("REFERENCE_WINDOW_INSUFFICIENT","warning",
            "Too few adjudicated observations in the preceding reference window.",
            float(reference.adjudicated_count),float(policy.min_reference_observations)))
    if current.expected_calibration_error is not None and current.expected_calibration_error > policy.max_expected_calibration_error:
        alerts.append(ReliabilityAlert("ECE_ABOVE_LIMIT","warning",
            "Current expected calibration error exceeds the configured limit.",
            current.expected_calibration_error,policy.max_expected_calibration_error))
    if current.brier_score is not None and current.brier_score > policy.max_brier_score:
        alerts.append(ReliabilityAlert("BRIER_ABOVE_LIMIT","warning",
            "Current Brier score exceeds the configured limit.",
            current.brier_score,policy.max_brier_score))
    drift=False
    if ece_change is not None and ece_change > policy.max_ece_change:
        drift=True
        alerts.append(ReliabilityAlert("CALIBRATION_ERROR_DRIFT","warning",
            "Expected calibration error has worsened beyond the configured reference-window threshold.",
            ece_change,policy.max_ece_change))
    if accuracy_change is not None and accuracy_change < -policy.max_accuracy_decline:
        drift=True
        alerts.append(ReliabilityAlert("OBSERVED_ACCURACY_DECLINE","warning",
            "Observed adjudicated accuracy has declined beyond the configured threshold.",
            accuracy_change,-policy.max_accuracy_decline))
    if current.adjudicated_count < policy.min_observations or reference.adjudicated_count < policy.min_reference_observations:
        status=ReliabilityStatus.INSUFFICIENT_DATA
    elif drift:
        status=ReliabilityStatus.RELIABILITY_DRIFT
    elif (current.expected_calibration_error is not None and current.expected_calibration_error > policy.max_expected_calibration_error) or (current.brier_score is not None and current.brier_score > policy.max_brier_score):
        status=ReliabilityStatus.CALIBRATION_WARNING
    else:
        status=ReliabilityStatus.ADEQUATE
    return ReliabilityMonitoringReport(generated_at,window_start,generated_at,
        confidence_source_ref,confidence_semantics,current,
        reference,tuple(contexts),ece_change,accuracy_change,tuple(alerts),status,future,
        ("Confidence is a caller-supplied score for an individual conclusion; it is not inferred from evidence counts, ERC decision labels or historical accuracy.",
         "Calibration metrics compare supplied confidence scores with later adjudicated correctness; they do not establish truth or real-world utility.",
         "Inconclusive and superseded observations are excluded from Brier, log-loss, ECE and observed accuracy, but are counted and reported.",
         "ECE is sensitive to bin count and boundaries; report bin-level reliability and sample counts, not ECE alone.",
         "The two-window comparison is a monitoring signal, not a formal sequential hypothesis test or proof of distribution shift.",
         "No automatic confidence recalibration, ruleset update, registry write, P6 mutation or practice release is performed."))
