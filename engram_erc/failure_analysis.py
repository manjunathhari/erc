"""Evidence-grounded failure analysis and human-governed root-cause attribution.

The module separates observed failure symptoms from causal hypotheses. It does
not infer blame from rule co-occurrence, mutate rules, or write to registries.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .contracts import ReasoningResult
from .feedback import FeedbackLedger, OutcomeLabel


class FailureCategory(str, Enum):
    MISSING_KNOWLEDGE_OR_EVIDENCE = "missing_knowledge_or_evidence"
    PREMISE_EXTRACTION_ERROR = "premise_extraction_error"
    RULE_APPLICATION_ERROR = "rule_application_error"
    INFERENCE_DEPENDENCY_ERROR = "inference_dependency_error"
    MISSED_CONTRADICTION = "missed_contradiction"
    TEMPORAL_REASONING_ERROR = "temporal_reasoning_error"
    CONTEXT_MISMATCH = "context_mismatch"
    CONFIDENCE_MISCALIBRATION = "confidence_miscalibration"
    OTHER = "other"


class FailureSymptom(str, Enum):
    INCORRECT_CONCLUSION = "incorrect_conclusion"
    UNSUPPORTED_CONCLUSION = "unsupported_conclusion"
    INCOMPLETE_CONCLUSION = "incomplete_conclusion"
    CONTRADICTION_UNRESOLVED = "contradiction_unresolved"
    OVERCONFIDENT_CONCLUSION = "overconfident_conclusion"
    UNDERCONFIDENT_CONCLUSION = "underconfident_conclusion"
    OTHER = "other"


class AttributionStatus(str, Enum):
    CONFIRMED_BY_ADJUDICATOR = "confirmed_by_adjudicator"
    SUPPORTED_HYPOTHESIS = "supported_hypothesis"
    UNRESOLVED = "unresolved"
    INSUFFICIENT_TRACE = "insufficient_trace"


class SignalKind(str, Enum):
    OBSERVED = "observed"
    HYPOTHESIZED = "hypothesized"


@dataclass(frozen=True, slots=True)
class FailureSignal:
    """A single attributed signal; its origin must be explicit.

    OBSERVED means the signal itself was directly observed in the supplied
    trace/record. HYPOTHESIZED means it is an explanatory candidate, not fact.
    Only an adjudicator may mark a category confirmed.
    """
    category: FailureCategory
    kind: SignalKind
    basis_refs: tuple[str, ...]
    rationale: str
    adjudicator_confirmed: bool = False
    adjudication_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.rationale.strip():
            raise ValueError("rationale must be non-empty")
        if len(set(self.basis_refs)) != len(self.basis_refs):
            raise ValueError("basis_refs must not contain duplicates")
        if self.adjudicator_confirmed and not self.adjudication_ref:
            raise ValueError("adjudication_ref is required for confirmed attribution")
        if not self.adjudicator_confirmed and self.adjudication_ref:
            raise ValueError("adjudication_ref is only valid for confirmed attribution")


@dataclass(frozen=True, slots=True)
class FailureCase:
    case_id: str
    result_id: str
    conclusion_ref: str
    outcome_event_ref: str
    symptom: FailureSymptom
    symptom_basis_refs: tuple[str, ...]
    signals: tuple[FailureSignal, ...] = ()
    context_key: str = ""

    def __post_init__(self) -> None:
        for name in ("case_id", "result_id", "conclusion_ref", "outcome_event_ref"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if len(set(self.symptom_basis_refs)) != len(self.symptom_basis_refs):
            raise ValueError("symptom_basis_refs must not contain duplicates")


@dataclass(frozen=True, slots=True)
class FailureAnalysisPolicy:
    require_adjudicated_contradiction: bool = True
    min_basis_refs_for_supported_hypothesis: int = 1
    include_non_contradicted_outcomes: bool = False

    def __post_init__(self) -> None:
        if self.min_basis_refs_for_supported_hypothesis < 1:
            raise ValueError("min_basis_refs_for_supported_hypothesis must be at least 1")


@dataclass(frozen=True, slots=True)
class RootCauseAttribution:
    category: FailureCategory
    status: AttributionStatus
    signal_count: int
    observed_signal_count: int
    hypothesized_signal_count: int
    basis_refs: tuple[str, ...]
    adjudication_refs: tuple[str, ...]
    rationales: tuple[str, ...]
    limitation: str


@dataclass(frozen=True, slots=True)
class FailureCaseAnalysis:
    case_id: str
    result_id: str
    conclusion_ref: str
    outcome_event_ref: str
    symptom: FailureSymptom
    symptom_basis_refs: tuple[str, ...]
    attributions: tuple[RootCauseAttribution, ...]
    unresolved: bool
    limitations: tuple[str, ...]
    context_key: str = ""


@dataclass(frozen=True, slots=True)
class FailureAnalysisReport:
    analyzed_cases: tuple[FailureCaseAnalysis, ...]
    excluded_cases: tuple[tuple[str, str], ...]
    category_counts: tuple[tuple[FailureCategory, int], ...]
    limitations: tuple[str, ...]


def _available_refs(result: ReasoningResult) -> set[str]:
    refs = {p.id for p in result.propositions}
    refs.update(s.id for s in result.inference_steps)
    refs.update(f"trace:{e.sequence}" for e in result.trace)
    refs.update(n.id for n in result.graph.nodes)
    refs.update(e.id for e in result.graph.edges)
    refs.update(u.id for u in result.uncertainty)
    return refs


def _analyze_case(case: FailureCase, result: ReasoningResult,
                  policy: FailureAnalysisPolicy) -> FailureCaseAnalysis:
    available = _available_refs(result)
    missing_symptom_refs = set(case.symptom_basis_refs) - available
    merged: dict[FailureCategory, list[FailureSignal]] = {}
    for signal in case.signals:
        merged.setdefault(signal.category, []).append(signal)

    attributions: list[RootCauseAttribution] = []
    for category, signals in sorted(merged.items(), key=lambda item: item[0].value):
        valid = [s for s in signals if set(s.basis_refs).issubset(available) and s.basis_refs]
        confirmed = [s for s in valid if s.adjudicator_confirmed]
        observed = [s for s in valid if s.kind == SignalKind.OBSERVED]
        hypothesized = [s for s in valid if s.kind == SignalKind.HYPOTHESIZED]
        basis = tuple(sorted({ref for s in valid for ref in s.basis_refs}))
        adjudication_refs = tuple(sorted({s.adjudication_ref for s in confirmed if s.adjudication_ref}))
        rationales = tuple(sorted({s.rationale for s in valid}))
        if confirmed:
            status = AttributionStatus.CONFIRMED_BY_ADJUDICATOR
            limitation = "Confirmed by the supplied adjudicator reference; ERC does not independently establish causality."
        elif len(basis) >= policy.min_basis_refs_for_supported_hypothesis and (observed or hypothesized):
            status = AttributionStatus.SUPPORTED_HYPOTHESIS
            limitation = "Evidence-supported candidate only; causal responsibility remains unconfirmed."
        elif not valid:
            status = AttributionStatus.INSUFFICIENT_TRACE
            limitation = "No supplied basis reference could be verified against this reasoning result."
        else:
            status = AttributionStatus.UNRESOLVED
            limitation = "Available signal is insufficient to support or confirm attribution."
        attributions.append(RootCauseAttribution(category, status, len(signals), len(observed),
            len(hypothesized), basis, adjudication_refs, rationales, limitation))

    return FailureCaseAnalysis(case.case_id, case.result_id, case.conclusion_ref,
        case.outcome_event_ref, case.symptom, case.symptom_basis_refs,
        tuple(attributions), not any(a.status == AttributionStatus.CONFIRMED_BY_ADJUDICATOR for a in attributions),
        tuple(x for x in (
            "A symptom is not itself a root cause.",
            "Multiple contributing causes are retained; no single-cause ranking is fabricated.",
            "Missing trace/provenance prevents attribution rather than proving a category absent.",
            ("Some symptom basis references are not present in the supplied result: " + ", ".join(sorted(missing_symptom_refs))) if missing_symptom_refs else "",
            "No automatic rule, strategy, confidence, evidence, registry, or P6 change is performed.",
        ) if x), case.context_key)


def analyze_reasoning_failures(
    cases: Iterable[FailureCase],
    results: Iterable[ReasoningResult],
    ledger: FeedbackLedger,
    *,
    policy: FailureAnalysisPolicy = FailureAnalysisPolicy(),
) -> FailureAnalysisReport:
    """Analyze failure cases against recorded results and adjudicated outcomes.

    Each case must map to an existing contradicted feedback event by default.
    Category signals are explicit structured annotations; ERC validates their
    trace references and separates observed signals from causal hypotheses.
    """
    result_map = {r.id: r for r in results}
    event_map = {e.event_id: e for e in ledger.events}
    analyzed: list[FailureCaseAnalysis] = []
    excluded: list[tuple[str, str]] = []
    for case in cases:
        result = result_map.get(case.result_id)
        event = event_map.get(case.outcome_event_ref)
        if result is None:
            excluded.append((case.case_id, "RESULT_NOT_SUPPLIED")); continue
        if case.conclusion_ref not in result.conclusion_refs:
            excluded.append((case.case_id, "CONCLUSION_NOT_IN_RESULT")); continue
        if event is None:
            excluded.append((case.case_id, "OUTCOME_EVENT_NOT_FOUND")); continue
        if event.result_id != case.result_id or event.conclusion_ref != case.conclusion_ref:
            excluded.append((case.case_id, "OUTCOME_EVENT_LINK_MISMATCH")); continue
        if policy.require_adjudicated_contradiction and event.outcome != OutcomeLabel.CONTRADICTED:
            excluded.append((case.case_id, "OUTCOME_NOT_CONTRADICTED")); continue
        if not policy.include_non_contradicted_outcomes and event.outcome in {OutcomeLabel.INCONCLUSIVE, OutcomeLabel.SUPERSEDED}:
            excluded.append((case.case_id, "OUTCOME_NOT_ADJUDICATED")); continue
        analyzed.append(_analyze_case(case, result, policy))

    counts: dict[FailureCategory, int] = {category: 0 for category in FailureCategory}
    for item in analyzed:
        for attribution in item.attributions:
            counts[attribution.category] += 1
    return FailureAnalysisReport(tuple(analyzed), tuple(excluded),
        tuple((category, counts[category]) for category in FailureCategory if counts[category]),
        ("Root-cause signals are caller-supplied and provenance-checked; ERC does not infer them from rule co-occurrence.",
         "Confirmed attribution requires an explicit adjudicator reference.",
         "Supported hypotheses are not causal findings; multiple contributing categories may coexist.",
         "Cases excluded for missing or mismatched provenance are not silently repaired.",
         "No automatic learning, ruleset rewrite, registry write, P6 mutation, or practice release occurs."))
