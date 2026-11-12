"""Evidence-aware conclusion evaluation and explicit reporting decisions."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import heapq
from itertools import islice, product
import json
import math
from typing import Any, Iterator, Mapping

from .contracts import (
    Evidence, EvidenceLink, EvidenceRelation, InferenceStep, Proposition, PropositionKind,
    ReasoningResult, UncertaintyKind,
)
from .graph import ReasoningGraphBuilder, ReasoningGraphView
from .primitives.evidence_assessment import (
    EvidenceAssessment, EvidenceAssessmentStatus, assess_evidence,
)
from .primitives.contradiction import ContradictionCertainty, find_contradictions


class ConclusionDecision(str, Enum):
    ACCEPTED = "accepted"
    PROVISIONAL = "provisional"
    WITHHELD = "withheld"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"


class EscalationLevel(str, Enum):
    NONE = "none"
    REVIEW = "review"
    EXPERT_ADJUDICATION = "expert_adjudication"
    SOURCE_RETRIEVAL = "source_retrieval"


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """Transparent thresholds; intentionally no hidden evidence weighting."""
    min_supporting_sources_per_leaf: int = 1
    require_support_for_every_leaf: bool = True
    require_no_contradicting_evidence: bool = True
    allow_qualifying_evidence_for_acceptance: bool = False
    require_complete_premise_lineage: bool = True
    functional_predicates: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.min_supporting_sources_per_leaf < 0:
            raise ValueError("min_supporting_sources_per_leaf cannot be negative")


@dataclass(frozen=True, slots=True)
class PremiseCoverage:
    conclusion_id: str
    leaf_premise_ids: tuple[str, ...]
    covered_leaf_ids: tuple[str, ...]
    uncovered_leaf_ids: tuple[str, ...]
    unresolved_refs: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class DerivationEvaluation:
    """One way of tracing a conclusion to stated propositions, decided on its own leaves (ERC 0.8.0).

    ``step_ids`` are the inference steps chosen in this derivation, the step that produces the conclusion itself
    among them; ``leaf_premise_ids`` its stated propositions; ``decision`` and ``reasons`` its own.
    """
    step_ids: tuple[str, ...]
    decision: ConclusionDecision
    leaf_premise_ids: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConclusionEvaluation:
    conclusion_id: str
    decision: ConclusionDecision
    escalation: EscalationLevel
    premise_coverage: PremiseCoverage
    evidence_assessments: tuple[EvidenceAssessment, ...]
    supporting_source_count: int
    contradicting_source_count: int
    qualifying_source_count: int
    reasons: tuple[str, ...]
    limitations: tuple[str, ...]
    # ERC 0.8.0: empty when the conclusion has one derivation; otherwise every evaluated derivation, best first. The
    # fields above are then those of the best one.
    derivations: tuple[DerivationEvaluation, ...] = ()


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    request_id: str
    policy: DecisionPolicy
    evaluations: tuple[ConclusionEvaluation, ...]
    accepted_refs: tuple[str, ...]
    provisional_refs: tuple[str, ...]
    withheld_refs: tuple[str, ...]
    conflicted_refs: tuple[str, ...]
    rejected_refs: tuple[str, ...]
    overall_decision: ConclusionDecision
    escalation: EscalationLevel


def _make_view(result: ReasoningResult, evidence, evidence_links) -> ReasoningGraphView:
    builder = ReasoningGraphBuilder()
    for proposition in result.propositions:
        builder.add_proposition(proposition)
    for item in evidence:
        builder.add_evidence(item)
    for link in evidence_links:
        builder.link_evidence(link)
    for step in result.inference_steps:
        builder.add_inference(step)
        builder.connect_inference(
            step.id,
            premise_proposition_ids=step.input_refs,
            output_proposition_ids=step.output_proposition_refs,
        )
    graph = builder.build()
    return ReasoningGraphView(graph, result.propositions, evidence, result.inference_steps)


# ERC 0.8.0 (B5): a conclusion may be derived in several ways. Each derivation is decided on its own leaves, and the
# conclusion takes the outcome of its best one. At most this many derivations of one conclusion are evaluated.
MAX_DERIVATIONS = 64
_DECISION_RANK = {
    ConclusionDecision.ACCEPTED: 0, ConclusionDecision.PROVISIONAL: 1, ConclusionDecision.WITHHELD: 2,
    ConclusionDecision.CONFLICTED: 3, ConclusionDecision.REJECTED: 4,
}
_NEGATIVE = (ConclusionDecision.WITHHELD, ConclusionDecision.CONFLICTED, ConclusionDecision.REJECTED)
_TIME_NOT_ESTABLISHED = "CONCLUSION_TIME_NOT_ESTABLISHED"
_TRUNCATED = "ALTERNATIVE_DERIVATIONS_TRUNCATED"
_UNRESOLVED_KEY = ("2",)
_UNORDERED_KEY = ("0", "")               # a stated proposition beneath a conclusion that has no choice of derivation


def _instant(moment: datetime | None) -> str | None:
    """One spelling for one instant, whatever zone it was given in: UTC, ISO 8601, with microseconds."""
    if moment is None:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.isoformat(timespec="microseconds")


def _plain(value: Any) -> Any:
    """A JSON value with every mapping as a plain dict, at every level, so that it can be written with sorted
    member names. Lists keep their order."""
    if isinstance(value, Mapping):
        return {str(name): _plain(member) for name, member in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(member) for member in value]
    return value


def _content_key(proposition: Proposition) -> tuple[str, str]:
    """The key of a stated proposition: what it claims, in one canonical JSON text.

    Its members are subject, predicate, object, polarity, kind, valid_time, occurred and qualifiers. No identifier is
    part of it: not the proposition's id, and not its source references, which name where it came from and not what
    it claims. Two propositions equal in every listed member have equal keys.
    """
    period, event = proposition.valid_time, proposition.occurred
    members = {
        "subject": proposition.subject,
        "predicate": proposition.predicate,
        "object": _plain(proposition.object_value),
        "polarity": proposition.polarity,
        "kind": proposition.kind.value,
        "valid_time": None if period is None else {
            "start": _instant(period.start), "start_latest": _instant(period.start_latest),
            "end_earliest": _instant(period.end_earliest), "end": _instant(period.end),
            "start_unbounded": period.start_unbounded, "end_unbounded": period.end_unbounded,
            "start_is_lower_bound": period.start_is_lower_bound, "end_is_upper_bound": period.end_is_upper_bound,
        },
        "occurred": None if event is None else {"earliest": _instant(event.earliest), "latest": _instant(event.latest)},
        "qualifiers": _plain(proposition.qualifiers),
    }
    return ("0", json.dumps(members, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))


def _holds_non_finite(value: Any) -> bool:
    """Whether a JSON value holds, at any depth, a number that is not finite (NaN or an infinity)."""
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_holds_non_finite(member) for member in value.values())
    if isinstance(value, (list, tuple)):
        return any(_holds_non_finite(member) for member in value)
    return False


def _beneath(conclusion_id: str, propositions: Mapping[str, Proposition],
             producers: Mapping[str, list[InferenceStep]]) -> tuple[bool, list[Proposition]]:
    """Whether the conclusion has a choice (it, or a derived proposition beneath it, has more than one producing
    step), and the stated propositions beneath it."""
    choice, stated, seen, pending = False, [], set(), [conclusion_id]
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        seen.add(ref)
        proposition = propositions.get(ref)
        if proposition is None:
            continue
        if proposition.kind != PropositionKind.INFERENCE:
            stated.append(proposition)
            continue
        steps = producers.get(ref, [])
        choice = choice or len(steps) > 1
        for step in steps:
            pending.extend(step.input_refs)
    return choice, stated


@dataclass(frozen=True, slots=True)
class _Derivation:
    """One derivation while it is being listed. ``key`` orders derivations by content; ``step_ids`` only orders two
    derivations whose keys are equal."""
    key: tuple
    leaves: frozenset[str]
    unresolved: frozenset[str]
    step_ids: tuple[str, ...]
    time_not_established: bool

    @property
    def order(self) -> tuple:
        return (self.key, self.step_ids)


def _derivations(conclusion_id: str, result: ReasoningResult) -> tuple[list[_Derivation], bool]:
    """The derivations of a conclusion that are evaluated, in order, and whether any were left out.

    A derivation chooses exactly one producing step for the conclusion and for every derived proposition beneath it.
    A conclusion with one step at every level has exactly one derivation, with the leaves found before 0.8.0.

    The order is by content and never by an id. The key of a stated proposition is ``_content_key``; the key of a
    derivation through a step is the step's rule (id and version) followed by the keys of the derivations chosen for
    the step's premises, in input order; a reference that cannot be resolved (a proposition that is absent, a derived
    one that no step produces, or one that depends on itself) has one fixed key. Derivations with equal keys are a
    tie group: they differ only in which of several identical stated propositions they rest on.

    At most ``MAX_DERIVATIONS`` are returned, and the limit never divides a tie group: if it would, that whole group
    is left out. The one exception is a first tie group that alone exceeds the limit; its first ``MAX_DERIVATIONS``
    by step id are returned.

    Raises ``ValueError`` if the conclusion has a choice and a stated proposition beneath it holds a number that is
    not finite, in its object or its qualifiers, at any depth.
    """
    propositions = {p.id: p for p in result.propositions}
    producers: dict[str, list[InferenceStep]] = {}
    for step in result.inference_steps:
        for output_id in step.output_proposition_refs:
            producers.setdefault(output_id, []).append(step)
    wanted = MAX_DERIVATIONS + 1          # one more than is used, so that leaving some out is noticed
    # An order is worked out only for a conclusion that has a choice (Amendment 2). A conclusion with none has exactly
    # one derivation, as before 0.8.0, and is evaluated without any key being built, whatever else the result holds.
    ordered, stated = _beneath(conclusion_id, propositions, producers)
    if ordered:
        # The key is JSON without non-finite numbers, and no spelling for them is defined: refuse, deliberately.
        offending = sorted(p.id for p in stated if _holds_non_finite(p.object_value) or _holds_non_finite(p.qualifiers))
        if offending:
            raise ValueError(f"Alternative derivations of conclusion {conclusion_id} cannot be ordered: "
                             f"proposition {offending[0]} holds a number that is not finite.")
    listed: dict[str, list[_Derivation]] = {}

    def through(step: InferenceStep, visiting: frozenset[str]) -> Iterator[_Derivation]:
        record = step.parameters.get("conclusion_time") or {}
        not_established = record.get("status") == "not_established"
        parts = [expand(premise, visiting) for premise in step.input_refs]
        # Each part is in order, so their product is in order of the combined key.
        for chosen in product(*parts):
            yield _Derivation(
                key=("1", step.rule_id) + tuple(part.key for part in chosen),
                leaves=frozenset().union(*(part.leaves for part in chosen)),
                unresolved=frozenset().union(*(part.unresolved for part in chosen)),
                step_ids=(step.id,) + tuple(step_id for part in chosen for step_id in part.step_ids),
                time_not_established=not_established or any(part.time_not_established for part in chosen),
            )

    def expand(ref: str, visiting: frozenset[str]) -> list[_Derivation]:
        proposition = propositions.get(ref)
        if proposition is None or ref in visiting:
            return [_Derivation(_UNRESOLVED_KEY, frozenset(), frozenset({ref}), (), False)]
        if proposition.kind != PropositionKind.INFERENCE:
            key = _content_key(proposition) if ordered else _UNORDERED_KEY
            return [_Derivation(key, frozenset({ref}), frozenset(), (), False)]
        if ref in listed:
            return listed[ref]
        steps = producers.get(ref, [])
        if not steps:
            return [_Derivation(_UNRESOLVED_KEY, frozenset(), frozenset({ref}), (), False)]
        streams = [through(step, visiting | {ref}) for step in steps]
        listed[ref] = list(islice(heapq.merge(*streams, key=lambda derivation: derivation.order), wanted))
        return listed[ref]

    found = expand(conclusion_id, frozenset())
    truncated = len(found) > MAX_DERIVATIONS
    keep = len(found)
    if truncated:
        keep = MAX_DERIVATIONS
        if found[keep - 1].key == found[keep].key:               # the limit would divide a tie group
            first_of_group = next(n for n, derivation in enumerate(found) if derivation.key == found[keep].key)
            keep = first_of_group or MAX_DERIVATIONS             # leave the whole group out, unless it is the first
    return found[:keep], truncated


def evaluate_conclusions(
    result: ReasoningResult,
    *,
    evidence: tuple[Evidence, ...] = (),
    evidence_links: tuple[EvidenceLink, ...] = (),
    policy: DecisionPolicy = DecisionPolicy(),
) -> EvaluationReport:
    """Evaluate whether each conclusion is justified for reporting.

    This is a deterministic gate, not truth adjudication. Evidence counts are
    counts of distinct linked evidence records, not independent studies or
    statistical weight. REJECTED is reserved for explicit, complete contrary
    evidence under the configured policy; ambiguous or missing evidence is
    WITHHELD instead.
    """
    view = _make_view(result, evidence, evidence_links)
    proposition_map = {p.id: p for p in result.propositions}
    contradictions = find_contradictions(
        result.propositions, functional_predicates=policy.functional_predicates
    )
    evaluations = []

    def decide(conclusion_id, leaves, unresolved):
        assessments = tuple(assess_evidence(view, ref) for ref in leaves)
        by_id = {a.proposition_id: a for a in assessments}
        covered = tuple(sorted(
            ref for ref, assessment in by_id.items()
            if len(assessment.supporting_evidence_ids) >= policy.min_supporting_sources_per_leaf
        ))
        uncovered = tuple(sorted(set(leaves) - set(covered)))
        supporting = sum(len(a.supporting_evidence_ids) for a in assessments)
        contradicting = sum(len(a.contradicting_evidence_ids) for a in assessments)
        qualifying = sum(len(a.qualifying_evidence_ids) for a in assessments)
        definite_conflicts = tuple(
            c for c in contradictions
            if c.certainty == ContradictionCertainty.DEFINITE
            and (c.left_id == conclusion_id or c.right_id == conclusion_id
                 or c.left_id in leaves or c.right_id in leaves)
        )
        potential_conflicts = tuple(
            c for c in contradictions
            if c.certainty == ContradictionCertainty.POTENTIAL
            and (c.left_id == conclusion_id or c.right_id == conclusion_id
                 or c.left_id in leaves or c.right_id in leaves)
        )

        complete = not unresolved and (not policy.require_complete_premise_lineage or bool(leaves))
        coverage = PremiseCoverage(
            conclusion_id=conclusion_id,
            leaf_premise_ids=leaves,
            covered_leaf_ids=covered,
            uncovered_leaf_ids=uncovered,
            unresolved_refs=unresolved,
            complete=complete,
        )
        reasons: list[str] = []
        limitations: list[str] = []
        all_leaves_contradicted = bool(leaves) and all(
            by_id[ref].contradicting_evidence_ids
            and not by_id[ref].supporting_evidence_ids
            for ref in leaves
        )
        mixed_support_and_contradiction = any(
            a.supporting_evidence_ids and a.contradicting_evidence_ids
            for a in assessments
        )
        if definite_conflicts or (mixed_support_and_contradiction and policy.require_no_contradicting_evidence):
            decision = ConclusionDecision.CONFLICTED
            escalation = EscalationLevel.EXPERT_ADJUDICATION
            reasons.append("CONTRADICTORY_CLAIM_OR_MIXED_EVIDENCE_REQUIRES_ADJUDICATION")
        elif all_leaves_contradicted and policy.require_no_contradicting_evidence:
            decision = ConclusionDecision.REJECTED
            escalation = EscalationLevel.EXPERT_ADJUDICATION
            reasons.append("ALL_ROOT_PREMISES_HAVE_EXPLICIT_CONTRARY_EVIDENCE")
        elif contradicting and policy.require_no_contradicting_evidence:
            decision = ConclusionDecision.CONFLICTED
            escalation = EscalationLevel.EXPERT_ADJUDICATION
            reasons.append("CONTRADICTING_EVIDENCE_REQUIRES_ADJUDICATION")
        elif not complete:
            decision = ConclusionDecision.WITHHELD
            escalation = EscalationLevel.REVIEW
            reasons.append("PREMISE_LINEAGE_INCOMPLETE")
        elif uncovered and policy.require_support_for_every_leaf:
            decision = ConclusionDecision.WITHHELD
            escalation = EscalationLevel.SOURCE_RETRIEVAL
            reasons.append("ONE_OR_MORE_ROOT_PREMISES_LACK_REQUIRED_SUPPORT")
        elif contradicting and not policy.require_no_contradicting_evidence:
            decision = ConclusionDecision.PROVISIONAL
            escalation = EscalationLevel.REVIEW
            reasons.append("CONTRADICTING_EVIDENCE_PRESENT_BUT_POLICY_ALLOWS_PROVISIONAL_REVIEW")
        elif qualifying and not policy.allow_qualifying_evidence_for_acceptance:
            decision = ConclusionDecision.PROVISIONAL
            escalation = EscalationLevel.REVIEW
            reasons.append("QUALIFYING_EVIDENCE_REQUIRES_INTERPRETATION")
        elif potential_conflicts:
            decision = ConclusionDecision.PROVISIONAL
            escalation = EscalationLevel.REVIEW
            reasons.append("POTENTIAL_CONTRADICTION_REQUIRES_SCOPE_REVIEW")
        elif policy.require_support_for_every_leaf and supporting < policy.min_supporting_sources_per_leaf * len(leaves):
            decision = ConclusionDecision.WITHHELD
            escalation = EscalationLevel.SOURCE_RETRIEVAL
            reasons.append("MINIMUM_SUPPORT_THRESHOLD_NOT_MET")
        else:
            decision = ConclusionDecision.ACCEPTED
            escalation = EscalationLevel.NONE
            reasons.append("PREMISE_LINEAGE_COMPLETE_AND_SUPPORT_THRESHOLD_MET")

        if any(a.status == EvidenceAssessmentStatus.CONFLICT for a in assessments):
            limitations.append("CONFLICTING_EVIDENCE_RETAINED_NOT_WEIGHTED")
        if any(a.status == EvidenceAssessmentStatus.NO_LINKED_EVIDENCE for a in assessments):
            limitations.append("NO_LINKED_EVIDENCE_IS_NOT_EVIDENCE_OF_FALSEHOOD")
        if qualifying:
            limitations.append("QUALIFYING_EVIDENCE_NOT_AUTOMATICALLY_RESOLVED")
        if any(
            item.reliability_score is None
            for a in assessments
            for item in evidence
            if item.id in (
                a.supporting_evidence_ids + a.contradicting_evidence_ids
                + a.qualifying_evidence_ids
            )
        ):
            limitations.append("RELIABILITY_NOT_ASSESSED_FOR_ALL_LINKED_SOURCES")
        return decision, escalation, coverage, assessments, supporting, contradicting, qualifying, reasons, limitations

    for conclusion_id in result.conclusion_refs:
        derivations, truncated = _derivations(conclusion_id, result)
        options: list[tuple[_Derivation, ConclusionEvaluation]] = []
        for derivation in derivations:
            (decision, escalation, coverage, assessments, supporting, contradicting, qualifying, reasons,
             limitations) = decide(conclusion_id, tuple(sorted(derivation.leaves)), tuple(sorted(derivation.unresolved)))
            if derivation.time_not_established:
                # The conclusion, or a derived proposition beneath it, holds for a time that is not established.
                if decision == ConclusionDecision.ACCEPTED:
                    decision, escalation, reasons = ConclusionDecision.PROVISIONAL, EscalationLevel.REVIEW, [_TIME_NOT_ESTABLISHED]
                limitations.append(_TIME_NOT_ESTABLISHED)
            options.append((derivation, ConclusionEvaluation(
                conclusion_id=conclusion_id,
                decision=decision,
                escalation=escalation,
                premise_coverage=coverage,
                evidence_assessments=assessments,
                supporting_source_count=supporting,
                contradicting_source_count=contradicting,
                qualifying_source_count=qualifying,
                reasons=tuple(reasons),
                limitations=tuple(dict.fromkeys(limitations)),
            )))
        # Best outcome first; among equals, the earlier in the order of derivations (the sort is stable).
        options.sort(key=lambda option: _DECISION_RANK[option[1].decision])
        best = options[0][1]
        if truncated:
            # Some derivations were not examined. Nothing definite may be said against the conclusion from an
            # incomplete search, unless a definite contradiction involves the conclusion itself: that applies to
            # every derivation, examined or not.
            contradicted = any(
                conclusion_id in (c.left_id, c.right_id) and c.certainty == ContradictionCertainty.DEFINITE
                for c in contradictions
            )
            if best.decision in _NEGATIVE and not contradicted:
                best = replace(best, decision=ConclusionDecision.PROVISIONAL, escalation=EscalationLevel.REVIEW,
                               reasons=(_TRUNCATED,))
            best = replace(best, limitations=tuple(dict.fromkeys(best.limitations + (_TRUNCATED,))))
        if len(options) > 1:
            best = replace(best, derivations=tuple(
                DerivationEvaluation(derivation.step_ids, evaluation.decision,
                                     evaluation.premise_coverage.leaf_premise_ids, evaluation.reasons)
                for derivation, evaluation in options))
        evaluations.append(best)

    decisions = [item.decision for item in evaluations]
    if not decisions:
        overall = ConclusionDecision.WITHHELD
        escalation = EscalationLevel.REVIEW
    elif ConclusionDecision.CONFLICTED in decisions:
        overall = ConclusionDecision.CONFLICTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    elif all(d == ConclusionDecision.ACCEPTED for d in decisions):
        overall = ConclusionDecision.ACCEPTED
        escalation = EscalationLevel.NONE
    elif all(d == ConclusionDecision.REJECTED for d in decisions):
        overall = ConclusionDecision.REJECTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    elif ConclusionDecision.REJECTED in decisions and ConclusionDecision.ACCEPTED in decisions:
        overall = ConclusionDecision.CONFLICTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    elif ConclusionDecision.PROVISIONAL in decisions:
        overall = ConclusionDecision.PROVISIONAL
        escalation = EscalationLevel.REVIEW
    elif ConclusionDecision.REJECTED in decisions:
        overall = ConclusionDecision.REJECTED
        escalation = EscalationLevel.EXPERT_ADJUDICATION
    else:
        overall = ConclusionDecision.WITHHELD
        escalation = EscalationLevel.SOURCE_RETRIEVAL

    def refs(decision):
        return tuple(item.conclusion_id for item in evaluations if item.decision == decision)

    return EvaluationReport(
        request_id=result.request_id,
        policy=policy,
        evaluations=tuple(evaluations),
        accepted_refs=refs(ConclusionDecision.ACCEPTED),
        provisional_refs=refs(ConclusionDecision.PROVISIONAL),
        withheld_refs=refs(ConclusionDecision.WITHHELD),
        conflicted_refs=refs(ConclusionDecision.CONFLICTED),
        rejected_refs=refs(ConclusionDecision.REJECTED),
        overall_decision=overall,
        escalation=escalation,
    )
