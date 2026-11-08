"""Validated experience consolidation into reusable, provenance-preserving knowledge candidates.

This module aggregates only explicitly adjudicated outcomes and caller-supplied
experience annotations. It does not create or promote authoritative facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Iterable

from .contracts import ReasoningResult, require_aware_datetime
from .failure_analysis import FailureAnalysisReport, FailureCaseAnalysis, AttributionStatus
from .feedback import FeedbackLedger, OutcomeLabel
from .trace_learning import TraceLearningReport


class ExperienceOutcome(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INCONCLUSIVE = "inconclusive"
    SUPERSEDED = "superseded"


class ConsolidationStatus(str, Enum):
    CANDIDATE = "candidate"
    INSUFFICIENT_EXPERIENCE = "insufficient_experience"
    CONFLICTED = "conflicted"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class ConsolidationDisposition(str, Enum):
    ACCEPT_FOR_KNOWLEDGE_REVIEW = "accept_for_knowledge_review"
    REJECT = "reject"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    """One case-linked experience observation; refs point to authoritative stores."""
    experience_id: str
    result_id: str
    conclusion_ref: str
    outcome_event_ref: str
    context_key: str
    task_type: str
    site_ref: str
    activity_ref: str
    experience_kind: str
    learning_statement: str
    source_refs: tuple[str, ...]
    recorded_at: datetime
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("experience_id", "result_id", "conclusion_ref",
                     "outcome_event_ref", "context_key", "task_type",
                     "site_ref", "activity_ref", "experience_kind",
                     "learning_statement"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        require_aware_datetime(self.recorded_at, "recorded_at")
        for name in ("source_refs", "tags"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must not contain duplicates")
        if not self.source_refs:
            raise ValueError("at least one source_ref is required")


@dataclass(frozen=True, slots=True)
class ConsolidationPolicy:
    min_adjudicated_cases: int = 5
    min_distinct_sites: int = 2
    min_distinct_activities: int = 1
    allow_single_site_candidate: bool = False
    require_all_cases_adjudicated: bool = False
    max_candidate_statement_chars: int = 1000

    def __post_init__(self) -> None:
        for name in ("min_adjudicated_cases", "min_distinct_sites",
                     "min_distinct_activities", "max_candidate_statement_chars"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1")


@dataclass(frozen=True, slots=True)
class ExperienceCounts:
    supported: int = 0
    contradicted: int = 0
    inconclusive: int = 0
    superseded: int = 0

    @property
    def adjudicated(self) -> int:
        return self.supported + self.contradicted


@dataclass(frozen=True, slots=True)
class ExperienceCandidate:
    candidate_id: str
    context_key: str
    task_type: str
    activity_ref: str
    experience_kind: str
    learning_statement: str
    counts: ExperienceCounts
    distinct_sites: tuple[str, ...]
    distinct_activities: tuple[str, ...]
    experience_refs: tuple[str, ...]
    outcome_refs: tuple[str, ...]
    source_refs: tuple[str, ...]
    failure_category_refs: tuple[str, ...]
    trace_pattern_refs: tuple[str, ...]
    confidence_label: str
    status: ConsolidationStatus
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsolidationReport:
    generated_at: datetime
    candidates: tuple[ExperienceCandidate, ...]
    excluded_experiences: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConsolidationReview:
    candidate_id: str
    disposition: ConsolidationDisposition
    reviewer_ref: str
    adjudication_ref: str
    reviewed_at: datetime
    rationale: str

    def __post_init__(self) -> None:
        for name in ("candidate_id", "reviewer_ref", "adjudication_ref", "rationale"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        require_aware_datetime(self.reviewed_at, "reviewed_at")


@dataclass(frozen=True, slots=True)
class ConsolidationReviewLedger:
    reviews: tuple[ConsolidationReview, ...] = ()

    def __post_init__(self) -> None:
        keys = [(r.candidate_id, r.reviewer_ref, r.adjudication_ref) for r in self.reviews]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate consolidation review")

    def append(self, review: ConsolidationReview) -> "ConsolidationReviewLedger":
        existing = {(r.candidate_id, r.reviewer_ref, r.adjudication_ref): r for r in self.reviews}
        key = (review.candidate_id, review.reviewer_ref, review.adjudication_ref)
        if key in existing:
            if existing[key] != review:
                raise ValueError("review identity already exists with different content")
            return self
        return ConsolidationReviewLedger(self.reviews + (review,))


def _candidate_id(key: tuple[str, ...], refs: tuple[str, ...]) -> str:
    raw = "|".join((*key, *refs))
    return "erc-experience-" + sha256(raw.encode()).hexdigest()[:24]


def _failure_categories(
    history: FailureAnalysisReport | Iterable[FailureCaseAnalysis] | None,
    outcome_refs: set[str],
) -> tuple[str, ...]:
    if history is None:
        return ()
    cases = history.analyzed_cases if isinstance(history, FailureAnalysisReport) else tuple(history)
    values = set()
    for case in cases:
        if case.outcome_event_ref not in outcome_refs:
            continue
        for attr in case.attributions:
            if attr.status in (AttributionStatus.CONFIRMED_BY_ADJUDICATOR,
                               AttributionStatus.SUPPORTED_HYPOTHESIS):
                values.add(attr.category.value)
    return tuple(sorted(values))


def consolidate_experience(
    experiences: Iterable[ExperienceRecord],
    ledger: FeedbackLedger,
    *,
    results: Iterable[ReasoningResult] = (),
    trace_report: TraceLearningReport | None = None,
    failure_history: FailureAnalysisReport | Iterable[FailureCaseAnalysis] | None = None,
    policy: ConsolidationPolicy = ConsolidationPolicy(),
    generated_at: datetime | None = None,
) -> ConsolidationReport:
    """Aggregate compatible experience records into reviewable candidates.

    Outcome labels and references are read from the existing append-only
    feedback ledger. Result/conclusion links are validated when results are
    supplied; if supplied, every record must resolve to its exact result and
    conclusion. Trace report is a supporting reference only, never an outcome
    substitute. No candidate is an authoritative knowledge fact.
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    require_aware_datetime(generated_at, "generated_at")
    records = tuple(experiences)
    ids = [r.experience_id for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate experience_id")
    event_map = {e.event_id: e for e in ledger.events}
    result_map = {r.id: r for r in results}
    check_results = bool(result_map)
    excluded: list[tuple[str, str]] = []
    eligible: list[tuple[ExperienceRecord, ExperienceOutcome]] = []
    mapping = {
        OutcomeLabel.VERIFIED_SUPPORTED: ExperienceOutcome.SUPPORTED,
        OutcomeLabel.CONTRADICTED: ExperienceOutcome.CONTRADICTED,
        OutcomeLabel.INCONCLUSIVE: ExperienceOutcome.INCONCLUSIVE,
        OutcomeLabel.SUPERSEDED: ExperienceOutcome.SUPERSEDED,
    }
    for record in records:
        if len(record.learning_statement.strip()) > policy.max_candidate_statement_chars:
            excluded.append((record.experience_id, "LEARNING_STATEMENT_TOO_LONG")); continue
        event = event_map.get(record.outcome_event_ref)
        if event is None:
            excluded.append((record.experience_id, "OUTCOME_EVENT_NOT_FOUND")); continue
        if event.result_id != record.result_id or event.conclusion_ref != record.conclusion_ref:
            excluded.append((record.experience_id, "OUTCOME_LINK_MISMATCH")); continue
        if event.observed_at > generated_at or record.recorded_at > generated_at:
            excluded.append((record.experience_id, "FUTURE_DATED")); continue
        if check_results:
            result = result_map.get(record.result_id)
            if result is None:
                excluded.append((record.experience_id, "RESULT_NOT_SUPPLIED")); continue
            if record.conclusion_ref not in result.conclusion_refs:
                excluded.append((record.experience_id, "CONCLUSION_NOT_IN_RESULT")); continue
        eligible.append((record, mapping[event.outcome]))

    buckets: dict[tuple[str, ...], list[tuple[ExperienceRecord, ExperienceOutcome]]] = {}
    for record, outcome in eligible:
        key = (record.context_key, record.task_type, record.activity_ref,
               record.experience_kind, record.learning_statement.strip())
        buckets.setdefault(key, []).append((record, outcome))

    candidates: list[ExperienceCandidate] = []
    for key, rows in sorted(buckets.items()):
        records_here = [r for r, _ in rows]
        # Count each adjudicated outcome event once within a candidate. Multiple
        # experience annotations from one case must not inflate its sample size.
        outcome_by_event: dict[str, ExperienceOutcome] = {}
        record_by_event: dict[str, ExperienceRecord] = {}
        for record_item, outcome_item in rows:
            previous = outcome_by_event.get(record_item.outcome_event_ref)
            if previous is not None and previous != outcome_item:
                raise ValueError("one outcome event maps to conflicting labels")
            outcome_by_event[record_item.outcome_event_ref] = outcome_item
            record_by_event.setdefault(record_item.outcome_event_ref, record_item)
        outcomes = list(outcome_by_event.values())
        independent_records = list(record_by_event.values())
        counts = ExperienceCounts(
            sum(o == ExperienceOutcome.SUPPORTED for o in outcomes),
            sum(o == ExperienceOutcome.CONTRADICTED for o in outcomes),
            sum(o == ExperienceOutcome.INCONCLUSIVE for o in outcomes),
            sum(o == ExperienceOutcome.SUPERSEDED for o in outcomes),
        )
        sites = tuple(sorted({r.site_ref for r in independent_records}))
        activities = tuple(sorted({r.activity_ref for r in independent_records}))
        exp_refs = tuple(sorted(r.experience_id for r in records_here))
        outcome_refs = tuple(sorted(r.outcome_event_ref for r in records_here))
        source_refs = tuple(sorted({s for r in records_here for s in r.source_refs}))
        failure_refs = _failure_categories(failure_history, set(outcome_refs))
        trace_refs = ()
        if trace_report is not None:
            trace_refs = tuple(sorted({
                "trace-pattern:" + str(index)
                for index, pattern in enumerate(trace_report.patterns)
                if set(pattern.event_refs) & set(outcome_refs)
            }))
        limitations = [
            "Aggregated statement is caller-supplied and grouped by exact context/task/activity/kind/text; semantic equivalence is not inferred.",
            "Outcomes are externally adjudicated; repeated records from one case are not independent cases.",
            "Site count is a diversity descriptor, not proof of external validity.",
            "Each adjudicated outcome event is counted once per candidate; multiple annotations from one case do not increase the case count.",
            "Experience is not automatically promoted to an evidence-backed fact or practice recommendation.",
        ]
        if counts.adjudicated < policy.min_adjudicated_cases:
            status = ConsolidationStatus.INSUFFICIENT_EXPERIENCE
            limitations.append(f"Insufficient adjudicated cases ({counts.adjudicated}/{policy.min_adjudicated_cases}).")
        elif len(sites) < policy.min_distinct_sites and not policy.allow_single_site_candidate:
            status = ConsolidationStatus.INSUFFICIENT_EXPERIENCE
            limitations.append(f"Insufficient site diversity ({len(sites)}/{policy.min_distinct_sites}).")
        elif len(activities) < policy.min_distinct_activities:
            status = ConsolidationStatus.INSUFFICIENT_EXPERIENCE
            limitations.append(f"Insufficient activity diversity ({len(activities)}/{policy.min_distinct_activities}).")
        elif counts.contradicted and counts.supported:
            status = ConsolidationStatus.CONFLICTED
            limitations.append("Both supported and contradicted adjudications exist; retain the conflict for review.")
        elif policy.require_all_cases_adjudicated and (counts.inconclusive or counts.superseded):
            status = ConsolidationStatus.INSUFFICIENT_EXPERIENCE
            limitations.append("Policy requires every included case to be adjudicated as supported or contradicted.")
        else:
            status = ConsolidationStatus.CANDIDATE
        confidence = (
            "NOT_ESTIMATED: insufficient adjudicated experience" if status == ConsolidationStatus.INSUFFICIENT_EXPERIENCE else
            "NOT_ESTIMATED: conflicting adjudications" if status == ConsolidationStatus.CONFLICTED else
            "NOT_A_PROBABILITY: reviewable experience candidate"
        )
        cid = _candidate_id(key, exp_refs)
        candidates.append(ExperienceCandidate(
            cid, key[0], key[1], key[2], key[3], key[4], counts, sites,
            activities, exp_refs, outcome_refs, source_refs, failure_refs,
            trace_refs, confidence, status, tuple(limitations),
        ))

    return ConsolidationReport(
        generated_at, tuple(candidates), tuple(excluded),
        (
            "Only exact-grouped caller-authored experience statements are consolidated; ERC does not generate new domain knowledge from raw narratives.",
            "The feedback ledger is the authoritative adjudication source; inconclusive and superseded outcomes remain visible but are not counted as support.",
            "No source text is copied; source_refs remain pointers to authoritative stores.",
            "No registry, evidence store, knowledge base, P6 scorer, ruleset, strategy, or confidence value is modified.",
            "Review and explicit downstream knowledge-base promotion are separate future integration steps.",
        ),
    )


def apply_consolidation_reviews(
    report: ConsolidationReport,
    reviews: ConsolidationReviewLedger,
) -> ConsolidationReport:
    """Return a reviewed view; acceptance authorizes review handoff, not promotion."""
    review_map = {r.candidate_id: r for r in reviews.reviews}
    known = {c.candidate_id for c in report.candidates}
    unknown = set(review_map) - known
    if unknown:
        raise ValueError(f"reviews reference unknown candidates: {sorted(unknown)}")
    updated = []
    for candidate in report.candidates:
        review = review_map.get(candidate.candidate_id)
        if review is None:
            updated.append(candidate)
            continue
        if review.disposition == ConsolidationDisposition.ACCEPT_FOR_KNOWLEDGE_REVIEW:
            status = ConsolidationStatus.REVIEWED
        elif review.disposition == ConsolidationDisposition.REJECT:
            status = ConsolidationStatus.REJECTED
        else:
            status = candidate.status
        updated.append(ExperienceCandidate(
            candidate.candidate_id, candidate.context_key, candidate.task_type,
            candidate.activity_ref, candidate.experience_kind,
            candidate.learning_statement, candidate.counts, candidate.distinct_sites,
            candidate.distinct_activities, candidate.experience_refs,
            candidate.outcome_refs, candidate.source_refs, candidate.failure_category_refs,
            candidate.trace_pattern_refs, candidate.confidence_label, status,
            candidate.limitations + (
                f"Review disposition: {review.disposition.value}; reviewer={review.reviewer_ref}; "
                f"adjudication_ref={review.adjudication_ref}. Acceptance does not promote this candidate to authoritative knowledge.",
            ),
        ))
    return ConsolidationReport(report.generated_at, tuple(updated),
        report.excluded_experiences, report.limitations)
