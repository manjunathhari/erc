"""Deterministic declarative rule matching and forward-chaining execution."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from .contracts import (
    Evidence, EvidenceLink, InferenceStep, Occurrence, Proposition, PropositionKind,
    ReasoningGraph, ReasoningResult, ReasoningStatus, TimeInterval, TraceEntry, new_id,
)
from .graph import ReasoningGraphBuilder, ReasoningGraphView
from .rules import (
    ConclusionTemplate, PropositionPattern, RuleDefinition, RuleSet, Variable,
)
from .temporal_requirements import TemporalOutcome, check_temporal_requirements
from .conclusion_time import ConclusionTimeStatus, derive_conclusion_time, time_record


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule_id: str
    rule_version: str
    premise_ids: tuple[str, ...]
    bindings: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    max_rounds: int = 10
    max_total_firings: int = 500

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        if self.max_total_firings < 1:
            raise ValueError("max_total_firings must be >= 1")


@dataclass(frozen=True, slots=True)
class RuleExecution:
    propositions: tuple[Proposition, ...]
    inference_steps: tuple[InferenceStep, ...]
    graph: ReasoningGraph
    trace: tuple[TraceEntry, ...]
    status: ReasoningStatus
    rounds_executed: int
    firings_executed: int


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _unify(term: Any, value: Any, bindings: dict[str, Any]) -> bool:
    if isinstance(term, Variable):
        if term.name in bindings:
            return bindings[term.name] == value
        bindings[term.name] = value
        return True
    return term == value


def _match_pattern(
    pattern: PropositionPattern,
    proposition: Proposition,
    initial: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    bindings = dict(initial or {})
    pairs = (
        (pattern.subject, proposition.subject),
        (pattern.predicate, proposition.predicate),
        (pattern.object_value, proposition.object_value),
        (pattern.polarity, proposition.polarity),
    )
    for term, value in pairs:
        if not _unify(term, value, bindings):
            return None
    return bindings


def match_rule(
    rule: RuleDefinition,
    propositions: Iterable[Proposition],
    *,
    allow_reusing_premise: bool = False,
) -> tuple[RuleMatch, ...]:
    """Find all deterministic matches in input order.

    Repeated use of the same proposition for two premises is prohibited by
    default. Variable bindings are shared across all premise patterns.
    """
    candidates = tuple(sorted(propositions, key=lambda item: item.id))
    matches: list[RuleMatch] = []

    def walk(index: int, bindings: dict[str, Any], selected: tuple[str, ...]):
        if index == len(rule.premises):
            matches.append(RuleMatch(
                rule.rule_id, rule.version, selected, dict(bindings)
            ))
            return
        pattern = rule.premises[index]
        for proposition in candidates:
            if not allow_reusing_premise and proposition.id in selected:
                continue
            next_bindings = _match_pattern(pattern, proposition, bindings)
            if next_bindings is not None:
                walk(index + 1, next_bindings, selected + (proposition.id,))

    walk(0, {}, ())
    # Multiple routes should not create duplicate bindings / premise tuples.
    unique: dict[str, RuleMatch] = {}
    for match in matches:
        key = _canonical({
            "rule": match.rule_id,
            "version": match.rule_version,
            "premises": match.premise_ids,
            "bindings": dict(match.bindings),
        })
        unique[key] = match
    return tuple(unique[key] for key in sorted(unique))


def _resolve(term: Any, bindings: Mapping[str, Any]) -> Any:
    if isinstance(term, Variable):
        if term.name not in bindings:
            raise ValueError(f"unbound variable at execution: {term.name}")
        return bindings[term.name]
    return term


def instantiate_conclusion(
    rule: RuleDefinition,
    bindings: Mapping[str, Any],
    *,
    proposition_id: str,
    valid_time: TimeInterval | None = None,
    occurred: Occurrence | None = None,
) -> Proposition:
    """The conclusion of one match. ``valid_time`` and ``occurred`` (ERC 0.8.0) are the time the rule's declaration
    gives it; a rule that declares nothing passes neither, and the conclusion carries no time, as before."""
    template = rule.conclusion
    return Proposition(
        valid_time=valid_time, occurred=occurred,
        id=proposition_id,
        subject=_resolve(template.subject, bindings),
        predicate=_resolve(template.predicate, bindings),
        object_value=_resolve(template.object_value, bindings),
        polarity=_resolve(template.polarity, bindings),
        kind=PropositionKind.INFERENCE,
    )


def _stable_id(prefix: str, payload: Any) -> str:
    digest = sha256(_canonical(payload).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def execute_rules(
    propositions: Iterable[Proposition],
    ruleset: RuleSet,
    *,
    evidence: Iterable[Evidence] = (),
    evidence_links: Iterable[EvidenceLink] = (),
    limits: ExecutionLimits = ExecutionLimits(),
    request_id: str = "erc-rule-execution",
) -> RuleExecution:
    """Run bounded, deterministic forward chaining over propositions.

    The function never mutates its inputs. Derived propositions are added to a
    separate result collection and can participate in later rounds.
    """
    original_props = tuple(propositions)
    evidence_items = tuple(evidence)
    links = tuple(evidence_links)
    prop_by_id = {p.id: p for p in original_props}
    if len(prop_by_id) != len(original_props):
        raise ValueError("duplicate proposition IDs")
    evidence_by_id = {e.id: e for e in evidence_items}
    if len(evidence_by_id) != len(evidence_items):
        raise ValueError("duplicate evidence IDs")
    for link in links:
        if link.proposition_id not in prop_by_id:
            raise ValueError(f"evidence link references unknown proposition: {link.proposition_id}")
        if link.evidence_id not in evidence_by_id:
            raise ValueError(f"evidence link references unknown evidence: {link.evidence_id}")

    all_props = dict(prop_by_id)
    inference_steps: list[InferenceStep] = []
    trace: list[TraceEntry] = []
    fired_keys: set[str] = set()
    # ERC 0.8.0: the temporal status of each conclusion derived in this run by a rule that declares requirements or a
    # conclusion time. Conclusions of rules that declare nothing are not in it.
    derived_status: dict[str, ConclusionTimeStatus] = {}
    per_rule_firings: dict[str, int] = {}
    rounds = 0
    firings = 0
    limit_reached = False

    ordered_rules = tuple(sorted(ruleset.rules, key=lambda r: (r.rule_id, r.version)))

    while rounds < limits.max_rounds:
        rounds += 1
        new_this_round = []
        for rule in ordered_rules:
            for match in match_rule(rule, all_props.values()):
                key_payload = {
                    "rule_id": rule.rule_id,
                    "rule_version": rule.version,
                    "premise_ids": match.premise_ids,
                    "bindings": dict(match.bindings),
                }
                firing_key = _canonical(key_payload)
                if firing_key in fired_keys:
                    continue
                # ERC 0.7.0: a rule that declares temporal requirements fires only on a match that establishes them.
                # A match that does not is recorded once, is not looked at again and counts toward no firing limit.
                temporal = None
                if rule.temporal:
                    check = check_temporal_requirements(rule, [all_props[ref] for ref in match.premise_ids])
                    temporal = [dict(item) for item in check.constraints]
                    if check.outcome is not TemporalOutcome.ESTABLISHED:
                        disproved = check.outcome is TemporalOutcome.DISPROVED
                        fired_keys.add(firing_key)
                        trace.append(TraceEntry(
                            sequence=len(trace), operation="rule_evaluation",
                            input_refs=match.premise_ids, output_refs=(),
                            status="temporal_requirement_disproved" if disproved else "temporal_requirement_indeterminate",
                            rule_id=rule.rule_id,
                            explanation_code=("TEMPORAL_REQUIREMENT_DISPROVED" if disproved
                                              else "TEMPORAL_REQUIREMENT_NOT_ESTABLISHED"),
                            details={"rule_version": rule.version, "temporal": temporal},
                        ))
                        continue
                if per_rule_firings.get(rule.rule_id, 0) >= rule.max_firings or firings >= limits.max_total_firings:
                    limit_reached = True
                    break

                conclusion_id = _stable_id("prop", key_payload)
                # ERC 0.8.0: the time of the conclusion. None for a rule that declares nothing.
                timing = derive_conclusion_time(rule, [all_props[ref] for ref in match.premise_ids])
                candidate = instantiate_conclusion(
                    rule, match.bindings, proposition_id=conclusion_id,
                    valid_time=timing.valid_time if timing else None, occurred=timing.occurred if timing else None,
                )
                if timing is None:
                    # A rule that declares nothing, exactly as in 0.7.0: if an identical proposition already exists
                    # under a different ID, do not add a duplicate derived node. Conclusions derived in this run by a
                    # rule that declares are not considered (Amendment 2): the two kinds of rule never share a
                    # conclusion, whichever rule id sorts first.
                    duplicate = next((
                        p for p in all_props.values()
                        if p.id not in derived_status
                        and (p.subject, p.predicate, p.object_value, p.polarity, p.valid_time)
                        == (candidate.subject, candidate.predicate, candidate.object_value,
                            candidate.polarity, candidate.valid_time)
                    ), None)
                    if duplicate is not None:
                        fired_keys.add(firing_key)
                        trace.append(TraceEntry(
                            sequence=len(trace), operation="rule_evaluation",
                            input_refs=match.premise_ids, output_refs=(duplicate.id,),
                            status="no_op_duplicate_conclusion", rule_id=rule.rule_id,
                            explanation_code="CONCLUSION_ALREADY_PRESENT",
                            details={"rule_version": rule.version},
                        ))
                        continue
                    same = None
                else:
                    # A rule that declares: only a conclusion derived earlier in this run with the same claim, the same
                    # time and the same status is the same conclusion, and this match is then recorded as an
                    # alternative derivation of it. A stated proposition never absorbs a derivation, and two
                    # periods of one claim are two conclusions.
                    same = next((all_props[ref] for ref, status in derived_status.items()
                                 if status is timing.status and _claim_and_time(all_props[ref]) == _claim_and_time(candidate)),
                                None)
                    if same is not None:
                        candidate = same

                step_id = _stable_id("inf", key_payload)
                step = InferenceStep(
                    id=step_id,
                    operation="forward_rule",
                    input_refs=match.premise_ids,
                    output_proposition_refs=(candidate.id,),
                    rule_id=f"{rule.rule_id}@{rule.version}",
                    parameters={
                        "ruleset_version": ruleset.version,
                        "bindings": dict(match.bindings),
                        "description": rule.description,
                        **({"temporal": temporal} if temporal is not None else {}),
                        **({"conclusion_time": time_record(timing)} if timing is not None else {}),
                    },
                )
                inference_steps.append(step)
                if timing is not None and same is None:
                    derived_status[candidate.id] = timing.status
                if same is None:
                    all_props[candidate.id] = candidate
                    new_this_round.append(candidate.id)
                fired_keys.add(firing_key)
                firings += 1
                per_rule_firings[rule.rule_id] = per_rule_firings.get(rule.rule_id, 0) + 1
                trace.append(TraceEntry(
                    sequence=len(trace), operation="rule_execution",
                    input_refs=match.premise_ids, output_refs=(candidate.id,),
                    status="derived" if same is None else "derived_alternative", rule_id=f"{rule.rule_id}@{rule.version}",
                    explanation_code="RULE_PREMISES_MATCHED" if same is None else "ALTERNATIVE_DERIVATION_RECORDED",
                    details={
                        "rule_version": rule.version,
                        "ruleset_version": ruleset.version,
                        "inference_id": step_id,
                        "bindings": dict(match.bindings),
                        **({"conclusion_time": time_record(timing)} if timing is not None else {}),
                    },
                ))
            if limit_reached:
                break
        if limit_reached or not new_this_round:
            break

    if limit_reached:
        status = ReasoningStatus.PARTIAL
        trace.append(TraceEntry(
            sequence=len(trace), operation="execution_limit",
            input_refs=(), output_refs=(), status="limit_reached",
            explanation_code="EXECUTION_LIMIT_REACHED",
            details={"max_rounds": limits.max_rounds,
                     "max_total_firings": limits.max_total_firings},
        ))
    else:
        status = ReasoningStatus.COMPLETE

    # Rebuild one graph from original inputs plus derived propositions/steps.
    builder = ReasoningGraphBuilder()
    for proposition in all_props.values():
        builder.add_proposition(proposition)
    for item in evidence_items:
        builder.add_evidence(item)
    for link in links:
        builder.link_evidence(link)
    for step in inference_steps:
        builder.add_inference(step)
        builder.connect_inference(
            step.id,
            premise_proposition_ids=step.input_refs,
            output_proposition_ids=step.output_proposition_refs,
        )
    graph = builder.build()

    # Validate the final graph and dependency order before returning.
    ReasoningGraphView(
        graph, builder.propositions, builder.evidence, builder.inference_steps
    ).inference_order()

    return RuleExecution(
        propositions=tuple(all_props.values()),
        inference_steps=tuple(inference_steps),
        graph=graph,
        trace=tuple(trace),
        status=status,
        rounds_executed=rounds,
        firings_executed=firings,
    )


def _claim_and_time(proposition: Proposition) -> tuple:
    """What a derived conclusion says and when: two conclusions equal in this and in status are one conclusion."""
    return (proposition.subject, proposition.predicate, proposition.object_value, proposition.polarity,
            proposition.valid_time, proposition.occurred)


def to_reasoning_result(
    execution: RuleExecution,
    *,
    request_id: str,
    result_id: str | None = None,
) -> ReasoningResult:
    """Wrap a rule execution in the public ERC ReasoningResult contract."""
    return ReasoningResult(
        id=result_id or new_id("result"),
        request_id=request_id,
        status=execution.status,
        conclusion_refs=tuple(
            p.id for p in execution.propositions if p.kind == PropositionKind.INFERENCE
        ),
        propositions=execution.propositions,
        inference_steps=execution.inference_steps,
        graph=execution.graph,
        trace=execution.trace,
    )
