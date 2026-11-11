"""Rule temporal requirements (ERC 0.7.0, increment B4).

A rule may declare the temporal relationship it needs between named premises (`rules.TemporalConstraint`). For one
match of such a rule this module answers, per constraint and overall, one of three things:

    established     the relationship holds in every history consistent with what is stated
    disproved       it holds in none
    indeterminate   anything else

Only an established match lets the rule fire (`inference.execute_rules`). The answer may be more cautious than those
definitions (indeterminate where a longer argument would settle it), never bolder.

What is read: `Proposition.valid_time` (a state) or `Proposition.occurred` (an event), and nothing else. No qualifier,
no evidence date and no `as_of` is read. `overlaps` is B3's comparison itself (`primitives.comparison._temporal_relation`),
called and not copied, so the contradiction check and a rule cannot come to disagree about two states.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .contracts import Occurrence, Proposition, PropositionKind, TimeInterval
from .primitives.comparison import (
    TemporalRelation, _ALWAYS, _NEVER, _earliest_possible_end, _latest_possible_start, _temporal_relation,
)
from .rules import RuleDefinition, TemporalRequirementKind


class TemporalOutcome(str, Enum):
    ESTABLISHED = "established"
    DISPROVED = "disproved"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True, slots=True)
class TemporalCheck:
    """What one match of a rule gives for the rule's temporal requirements.

    `outcome` is the overall answer: disproved if any constraint is disproved, otherwise indeterminate if any is
    indeterminate, otherwise established. `constraints` has one mapping per declared constraint, in declared order:
    `relation`, `left`, `right`, `outcome`, and `reason` when the constraint is indeterminate.
    """
    outcome: TemporalOutcome
    constraints: tuple[Mapping[str, Any], ...]


_ESTABLISHED, _DISPROVED, _INDETERMINATE = TemporalOutcome.ESTABLISHED, TemporalOutcome.DISPROVED, TemporalOutcome.INDETERMINATE

# Reasons for an indeterminate constraint, in the order in which they are looked for.
DERIVED_PREMISE = "derived_premise"
NO_TEMPORAL_STATEMENT = "no_temporal_statement"
WRONG_KIND = "wrong_kind"
BOUNDS_DO_NOT_SETTLE = "bounds_do_not_settle"


# --------------------------------------------------------------------------
# The quantities, read exactly as B3 reads them
# --------------------------------------------------------------------------

def _is_instant(value: Any) -> bool:
    """A stated instant: not absent, and neither "always" nor "never"."""
    return value is not None and value is not _ALWAYS and value is not _NEVER


def _begins(time: TimeInterval | Occurrence) -> tuple[Any, Any]:
    """The earliest and the latest instant at which a state or an event begins."""
    if isinstance(time, Occurrence):
        return time.earliest, time.latest
    return (_ALWAYS if time.start_unbounded else time.start), _latest_possible_start(time)


def _is_over(time: TimeInterval | Occurrence) -> tuple[Any, Any]:
    """The earliest and the latest instant at which a state or an event is over."""
    if isinstance(time, Occurrence):
        return time.earliest, time.latest
    return _earliest_possible_end(time), (_NEVER if time.end_unbounded else time.end)


# --------------------------------------------------------------------------
# The three relations
# --------------------------------------------------------------------------

def _overlaps(left: TimeInterval, right: TimeInterval) -> TemporalOutcome:
    """Two states hold at one and the same time: B3's comparison, unchanged."""
    return {TemporalRelation.OVERLAP: _ESTABLISHED, TemporalRelation.DISJOINT: _DISPROVED,
            TemporalRelation.UNKNOWN: _INDETERMINATE}[_temporal_relation(left, right)]


def _before(left: TimeInterval | Occurrence, right: TimeInterval | Occurrence) -> TemporalOutcome:
    """`left` is over before `right` begins.

    A state is over at its end instant, so a state that ends at X is before something that begins at X. An event must
    be strictly earlier than what follows it.
    """
    event = isinstance(left, Occurrence)
    over_earliest, over_latest = _is_over(left)
    begins_earliest, begins_latest = _begins(right)
    if _is_instant(over_latest) and _is_instant(begins_earliest):
        if (over_latest < begins_earliest) if event else (over_latest <= begins_earliest):
            return _ESTABLISHED
    if begins_latest is _ALWAYS or over_earliest is _NEVER:
        return _DISPROVED            # `right` has no beginning, or `left` never ends
    if _is_instant(over_earliest) and _is_instant(begins_latest):
        if (over_earliest >= begins_latest) if event else (over_earliest > begins_latest):
            return _DISPROVED
    return _INDETERMINATE


def _during(event: Occurrence, state: TimeInterval) -> TemporalOutcome:
    """The event happens while the state holds: start <= instant < end."""
    begins_earliest, begins_latest = _begins(state)
    over_earliest, over_latest = _is_over(state)
    if _is_instant(event.latest) and _is_instant(begins_earliest) and event.latest < begins_earliest:
        return _DISPROVED            # the window ends before the state could begin
    if _is_instant(event.earliest) and _is_instant(over_latest) and event.earliest >= over_latest:
        return _DISPROVED            # the window begins at or after the state must have ended
    had_begun = begins_latest is _ALWAYS or (
        _is_instant(begins_latest) and event.earliest is not None and begins_latest <= event.earliest)
    still_held = over_earliest is _NEVER or (
        _is_instant(over_earliest) and event.latest is not None and event.latest < over_earliest)
    return _ESTABLISHED if had_begun and still_held else _INDETERMINATE


_RELATIONS = {TemporalRequirementKind.OVERLAPS: _overlaps, TemporalRequirementKind.BEFORE: _before,
              TemporalRequirementKind.DURING: _during}


# --------------------------------------------------------------------------
# Reasons that lie in a premise, not in its dates
# --------------------------------------------------------------------------

def _time_of(premise: Proposition) -> TimeInterval | Occurrence | None:
    return premise.occurred if premise.occurred is not None else premise.valid_time


def _kind_needed(relation: TemporalRequirementKind, side: int) -> type | None:
    """The kind of time the left (0) or right (1) premise must carry; None when either will do."""
    if relation is TemporalRequirementKind.OVERLAPS:
        return TimeInterval
    if relation is TemporalRequirementKind.DURING:
        return Occurrence if side == 0 else TimeInterval
    return None


def _premise_reasons(relation: TemporalRequirementKind, sides: Sequence[Proposition]) -> dict[str, list[tuple[int, str]]]:
    """For each reason that lies in a premise: the premises it applies to (0 left, 1 right) and the phrase for each.

    The one place that says to which premise a reason applies. The check takes the first reason that applies to either
    premise; the uncertainty wording names every premise the reported reason applies to, left then right.
    """
    untimed = [side for side, premise in enumerate(sides) if _time_of(premise) is None]
    wrong = []
    for side, premise in enumerate(sides):
        needed, time = _kind_needed(relation, side), _time_of(premise)
        if needed is not None and time is not None and not isinstance(time, needed):
            wrong.append((side, "is an event where a state is needed" if needed is TimeInterval
                          else "is a state where an event is needed"))
    return {
        DERIVED_PREMISE: [(side, "is a derived conclusion and carries no time yet") for side in untimed
                          if sides[side].kind == PropositionKind.INFERENCE],
        NO_TEMPORAL_STATEMENT: [(side, "carries no time") for side in untimed],
        WRONG_KIND: wrong,
    }


def _check_constraint(relation: TemporalRequirementKind, left: Proposition, right: Proposition) -> tuple[TemporalOutcome, str | None]:
    """The outcome of one constraint over its two premises and, when indeterminate, the single reason for it."""
    for reason, applies_to in _premise_reasons(relation, (left, right)).items():
        if applies_to:
            return _INDETERMINATE, reason
    outcome = _RELATIONS[relation](_time_of(left), _time_of(right))
    return outcome, (BOUNDS_DO_NOT_SETTLE if outcome is _INDETERMINATE else None)


def _premises_by_name(rule: RuleDefinition, premises: Sequence[Proposition]) -> dict[str, Proposition]:
    return {pattern.name: premise for pattern, premise in zip(rule.premises, premises) if pattern.name is not None}


def check_temporal_requirements(rule: RuleDefinition, premises: Sequence[Proposition]) -> TemporalCheck:
    """Does this match establish every temporal relationship the rule declares?

    `premises` are the matched propositions, one per premise pattern of the rule and in the patterns' order. A rule
    that declares nothing (`temporal` None or empty) is established with no constraints.
    """
    by_name = _premises_by_name(rule, premises)
    items: list[dict[str, Any]] = []
    for constraint in rule.temporal or ():
        outcome, reason = _check_constraint(constraint.relation, by_name[constraint.left], by_name[constraint.right])
        item: dict[str, Any] = {"relation": constraint.relation.value, "left": constraint.left,
                                "right": constraint.right, "outcome": outcome.value}
        if reason is not None:
            item["reason"] = reason
        items.append(item)
    outcomes = {item["outcome"] for item in items}
    overall = (_DISPROVED if _DISPROVED.value in outcomes
               else _INDETERMINATE if _INDETERMINATE.value in outcomes else _ESTABLISHED)
    return TemporalCheck(overall, tuple(items))


# --------------------------------------------------------------------------
# The wording of an uncertainty (used by orchestration, from a verified result)
# --------------------------------------------------------------------------

_CLAUSES = {
    TemporalRequirementKind.OVERLAPS: "whether {left} and {right} hold at the same time cannot be established",
    TemporalRequirementKind.BEFORE: "whether {left} is over before {right} begins cannot be established",
    TemporalRequirementKind.DURING: "whether {left} happens while {right} holds cannot be established",
}
_NO_PREMISE_NAMED = "the known dates do not settle it"
RESOLUTION_HINT = "Supply the missing or more precise times for the named premises."


def _describe_not_applied(rule: RuleDefinition, premises: Sequence[Proposition],
                          constraints: Sequence[Mapping[str, Any]]) -> str:
    """The description of the uncertainty item for one indeterminate match.

    Built from `constraints`, a per-constraint result (in orchestration: the second run of the check, after it has been
    compared with the trace entry) and from nothing else that decides an outcome: one clause for each constraint that
    result leaves indeterminate, in its order, worded for its relation, its two names and its reason code. The
    premises are read only to say which premise the reason applies to and, for a wrong kind, in which direction.
    """
    by_name = _premises_by_name(rule, premises)
    clauses = []
    for item in constraints:
        if item["outcome"] != _INDETERMINATE.value:
            continue
        relation, names = TemporalRequirementKind(item["relation"]), (item["left"], item["right"])
        applies_to = _premise_reasons(relation, (by_name[names[0]], by_name[names[1]])).get(item["reason"], [])
        reason_text = " and ".join(f"{names[side]} {phrase}" for side, phrase in applies_to) or _NO_PREMISE_NAMED
        clauses.append(_CLAUSES[relation].format(left=names[0], right=names[1]) + f" ({reason_text})")
    return f"Rule {rule.rule_id}@{rule.version} not applied: " + "; ".join(clauses) + "."
