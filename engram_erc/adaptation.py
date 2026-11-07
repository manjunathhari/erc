"""Context-aware, advisory strategy ranking from adjudicated experience.

This module ranks only strategies already declared eligible by the caller.
It never changes strategy definitions, rule priority, evidence, or P6 state.
External experience scores (for example, an adapter over P6.3) can be supplied
without importing or duplicating the P6 scorer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .feedback import FeedbackLedger, OutcomeLabel
from .orchestration import StrategyDefinition


class AdaptationStatus(str, Enum):
    RANKED = "ranked"
    INSUFFICIENT_EXPERIENCE = "insufficient_experience"
    NO_ELIGIBLE_STRATEGIES = "no_eligible_strategies"


class ScoreOrigin(str, Enum):
    P6_ADAPTER = "external_experience_adapter"
    ERC_FEEDBACK = "erc_adjudicated_feedback"
    BASELINE = "catalog_priority_baseline"


@dataclass(frozen=True, slots=True)
class StrategyExperienceScore:
    """Normalized score supplied by an external experience system.

    `score` must be in [0, 1]. `sample_size` is the effective adjudicated
    support count supplied by the adapter. ERC treats it as opaque metadata;
    it does not reconstruct or reimplement the upstream scoring algorithm.
    """
    strategy_ref: str
    context_key: str
    score: float
    sample_size: int
    source_ref: str
    uncertainty_note: str = ""

    def __post_init__(self) -> None:
        if not self.strategy_ref.strip() or not self.context_key.strip() or not self.source_ref.strip():
            raise ValueError("strategy_ref, context_key and source_ref must be non-empty")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")
        if self.sample_size < 0:
            raise ValueError("sample_size must be non-negative")


@dataclass(frozen=True, slots=True)
class AdaptationPolicy:
    min_adjudicated_events: int = 5
    allow_task_level_fallback: bool = True
    require_context_match: bool = False

    def __post_init__(self) -> None:
        if self.min_adjudicated_events < 1:
            raise ValueError("min_adjudicated_events must be at least 1")


@dataclass(frozen=True, slots=True)
class StrategyRanking:
    strategy_ref: str
    rank: int
    eligible: bool
    score: float | None
    sample_size: int
    origin: ScoreOrigin
    context_used: str
    context_fallback: bool
    explanation: str
    source_refs: tuple[str, ...] = ()
    uncertainty_note: str = ""


@dataclass(frozen=True, slots=True)
class AdaptationReport:
    status: AdaptationStatus
    task_type: str
    requested_context_tags: tuple[str, ...]
    selected_strategy_ref: str | None
    rankings: tuple[StrategyRanking, ...]
    minimum_sample_size: int
    abstention_reason: str | None = None


def strategy_ref(strategy: StrategyDefinition) -> str:
    return f"{strategy.strategy_id}@{strategy.version}"


def rank_eligible_strategies(
    eligible_strategies: Iterable[StrategyDefinition],
    *,
    task_type: str,
    context_tags: tuple[str, ...] = (),
    feedback: FeedbackLedger | None = None,
    external_scores: Iterable[StrategyExperienceScore] = (),
    policy: AdaptationPolicy = AdaptationPolicy(),
) -> AdaptationReport:
    """Rank eligible strategies using exact-context experience when possible.

    Context policy is deliberately conservative: first use events whose tag
    set exactly matches the requested tag set; if that lacks support, optionally
    fall back to task-level events. No partial-tag blending is performed.
    External adapter scores take precedence when an exact strategy/context
    score with sufficient support is available. If no candidate has sufficient
    experience, preserve catalog priority and explicitly abstain from adaptation.
    """
    if not task_type or not task_type.strip():
        raise ValueError("task_type must be non-empty")
    if len(context_tags) != len(set(context_tags)):
        raise ValueError("context_tags must not contain duplicates")
    strategies = tuple(eligible_strategies)
    if not strategies:
        return AdaptationReport(
            AdaptationStatus.NO_ELIGIBLE_STRATEGIES, task_type, context_tags,
            None, (), policy.min_adjudicated_events, "No strategies passed catalog eligibility.",
        )

    wanted = frozenset(context_tags)
    feedback_events = tuple(feedback.events) if feedback else ()
    external = tuple(external_scores)
    candidates: list[dict] = []

    for strategy in strategies:
        ref = strategy_ref(strategy)
        ext = [s for s in external if s.strategy_ref == ref and s.context_key == _context_key(task_type, context_tags)]
        ext = [s for s in ext if s.sample_size >= policy.min_adjudicated_events]
        if ext:
            # Multiple adapter records for the same key are not silently blended.
            chosen = sorted(ext, key=lambda s: (-s.sample_size, s.source_ref))[0]
            candidates.append(dict(strategy=strategy, ref=ref, score=chosen.score,
                n=chosen.sample_size, origin=ScoreOrigin.P6_ADAPTER,
                context=_context_key(task_type, context_tags), fallback=False,
                explanation="Used the supplied external experience score; upstream scoring and uncertainty remain owned by the adapter.",
                sources=(chosen.source_ref,), uncertainty=chosen.uncertainty_note or "Uncertainty semantics are supplied by the external adapter.",))
            continue

        relevant = [e for e in feedback_events
                    if e.strategy_ref == ref and e.task_type == task_type
                    and e.outcome in (OutcomeLabel.VERIFIED_SUPPORTED, OutcomeLabel.CONTRADICTED)
                    and (not wanted or frozenset(e.context_tags) == wanted)]
        fallback = False
        context_used = _context_key(task_type, context_tags)
        if len(relevant) < policy.min_adjudicated_events and policy.allow_task_level_fallback and wanted:
            relevant = [e for e in feedback_events
                        if e.strategy_ref == ref and e.task_type == task_type
                        and e.outcome in (OutcomeLabel.VERIFIED_SUPPORTED, OutcomeLabel.CONTRADICTED)]
            fallback = True
            context_used = task_type
        n = len(relevant)
        if n >= policy.min_adjudicated_events:
            wins = sum(e.outcome == OutcomeLabel.VERIFIED_SUPPORTED for e in relevant)
            candidates.append(dict(strategy=strategy, ref=ref, score=wins/n, n=n,
                origin=ScoreOrigin.ERC_FEEDBACK, context=context_used, fallback=fallback,
                explanation=("Descriptive observed adjudication rate; not a calibrated prediction or causal estimate."),
                sources=tuple(sorted(e.event_id for e in relevant)),
                uncertainty=f"Descriptive rate from {n} adjudicated events; no calibrated predictive interval is computed."))
        else:
            candidates.append(dict(strategy=strategy, ref=ref, score=None, n=n,
                origin=ScoreOrigin.BASELINE, context=context_used, fallback=fallback,
                explanation=f"Insufficient adjudicated experience ({n}/{policy.min_adjudicated_events}); retained catalog priority.",
                sources=(), uncertainty="Insufficient adjudicated observations; adaptation abstains."))

    has_experience = any(item["score"] is not None for item in candidates)
    if policy.require_context_match and wanted:
        has_experience = any(item["score"] is not None and not item["fallback"] for item in candidates)
    if not has_experience:
        ordered = sorted(candidates, key=lambda x: (-x["strategy"].priority, x["strategy"].strategy_id, x["strategy"].version))
        status = AdaptationStatus.INSUFFICIENT_EXPERIENCE
        selected = ordered[0]["ref"]
        abstention = "No strategy met the minimum experience threshold in the permitted context; catalog priority was preserved."
        ranked_items = [(item, None) for item in ordered]
    else:
        # Experienced strategies sort by score then support; inexperienced ones
        # follow, preserving their catalog priority rather than fabricating a score.
        ordered = sorted(candidates, key=lambda x: (
            x["score"] is None,
            -(x["score"] if x["score"] is not None else 0.0),
            -x["n"], -x["strategy"].priority,
            x["strategy"].strategy_id, x["strategy"].version,
        ))
        status = AdaptationStatus.RANKED
        selected = ordered[0]["ref"]
        abstention = None
        ranked_items = [(item, i + 1) for i, item in enumerate(ordered)]

    rankings = tuple(StrategyRanking(
        strategy_ref=item["ref"], rank=rank or i + 1, eligible=True,
        score=item["score"], sample_size=item["n"], origin=item["origin"],
        context_used=item["context"], context_fallback=item["fallback"],
        explanation=item["explanation"], source_refs=item["sources"],
        uncertainty_note=item.get("uncertainty", ""),
    ) for i, (item, rank) in enumerate(ranked_items))
    return AdaptationReport(status, task_type, context_tags, selected, rankings,
                            policy.min_adjudicated_events, abstention)


def _context_key(task_type: str, context_tags: tuple[str, ...]) -> str:
    return task_type if not context_tags else task_type + "|" + "&".join(sorted(context_tags))


def rank_catalog_strategies(
    request,
    catalog,
    *,
    has_rules: bool,
    context_tags: tuple[str, ...] = (),
    feedback: FeedbackLedger | None = None,
    external_scores: Iterable[StrategyExperienceScore] = (),
    policy: AdaptationPolicy = AdaptationPolicy(),
) -> AdaptationReport:
    """Apply adaptive ranking only after the catalog's canonical eligibility gates."""
    eligible = catalog.eligible(request, has_rules=has_rules)
    return rank_eligible_strategies(
        eligible, task_type=request.task_type, context_tags=context_tags,
        feedback=feedback, external_scores=external_scores, policy=policy,
    )
