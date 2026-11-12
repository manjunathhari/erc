"""The time of a derived conclusion (ERC 0.8.0, B5).

A rule may declare the time its conclusion takes (``RuleDefinition.conclusion_time``). For each firing match the
engine asks this module what that time is and records the answer on the inference step: the conclusion's temporal
status is derivation metadata, never a field of ``Proposition``.

Three statuses: ``timed`` (the conclusion carries ``valid_time`` or ``occurred``), ``timeless`` (the rule says the
conclusion has no temporal limit) and ``not_established`` (it has a time and that time could not be stated).

Only ``ConclusionTimeStatus`` is public. How a time is worked out is internal and may change. Nothing here reads a
qualifier, an evidence date or ``as_of``: only ``valid_time`` and ``occurred`` of the named premises.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .contracts import Occurrence, Proposition, TimeInterval
from .primitives.comparison import _ALWAYS, _NEVER, _earliest_possible_end, _latest_possible_start
from .rules import ConclusionTimeKind, RuleDefinition


class ConclusionTimeStatus(str, Enum):
    """What is known of the time for which a derived conclusion holds."""
    TIMED = "timed"
    TIMELESS = "timeless"
    NOT_ESTABLISHED = "not_established"


# Why a time is not established: a closed list.
NO_CONCLUSION_TIME_DECLARED = "no_conclusion_time_declared"   # the rule declares requirements and no conclusion time
PREMISE_CARRIES_NO_TIME = "premise_carries_no_time"           # as_premise: the premise has neither valid_time nor occurred
PREMISE_TIME_UNKNOWN = "premise_time_unknown"                 # as_premise: the premise has a time of which nothing is known

_REASON_TEXT = {
    NO_CONCLUSION_TIME_DECLARED: "the rule declares temporal requirements but not the time of its conclusion",
    PREMISE_CARRIES_NO_TIME: "{} carries no time",
    PREMISE_TIME_UNKNOWN: "the time of {} is not known",
}
RESOLUTION_HINT = "Declare how the conclusion's time follows from its premises, or supply the missing times."
_INTERVAL_FIELDS = ("start", "start_latest", "end_earliest", "end", "start_unbounded", "end_unbounded",
                    "start_is_lower_bound", "end_is_upper_bound")


@dataclass(frozen=True, slots=True)
class ConclusionTimeResult:
    """The outcome for one firing match. ``mode`` is the declared kind, or None for a rule that declares requirements
    and no conclusion time; ``premises`` are the declared names, in declared order."""
    status: ConclusionTimeStatus
    mode: str | None = None
    premises: tuple[str, ...] = ()
    reason: str | None = None
    valid_time: TimeInterval | None = None
    occurred: Occurrence | None = None


def shared_period(intervals: Sequence[TimeInterval]) -> TimeInterval | None:
    """The period in which every one of the given states holds, as far as their stated bounds settle it.

    Each state stands for every concrete history consistent with its bounds; the result's bounds admit the shared
    period of every combination of such histories and nothing wider:

    - earliest possible start: the latest of the stated earliest starts (absent if no state gives one);
    - latest possible start: the latest of the latest possible starts ("always" if every start is unbounded);
    - earliest possible end: the earliest of the earliest possible ends ("never" if every end is unbounded);
    - latest possible end: the earliest of the stated latest ends (absent if no state gives one).

    None when a certain shared part cannot be shown: a latest start or an earliest end is not known, or the latest
    possible start does not come before the earliest possible end. After B4 has established that the states overlap
    this cannot happen.
    """
    latest_starts = [_latest_possible_start(interval) for interval in intervals]
    earliest_ends = [_earliest_possible_end(interval) for interval in intervals]
    if not intervals or None in latest_starts or None in earliest_ends:
        return None
    bounded_starts = [moment for moment in latest_starts if moment is not _ALWAYS]
    bounded_ends = [moment for moment in earliest_ends if moment is not _NEVER]
    if bounded_starts and bounded_ends and not max(bounded_starts) < min(bounded_ends):
        return None

    fields: dict[str, Any] = {}
    if not bounded_starts:
        fields["start_unbounded"] = True
    else:
        stated = [interval.start for interval in intervals if interval.start is not None]
        latest, earliest = max(bounded_starts), (max(stated) if stated else None)
        if earliest is None:
            fields["start_latest"] = latest                       # no later than
        elif earliest == latest:
            fields["start"] = earliest                            # exact
        else:
            fields["start"], fields["start_latest"] = earliest, latest   # within
    if not bounded_ends:
        fields["end_unbounded"] = True
    else:
        stated = [interval.end for interval in intervals if interval.end is not None]
        earliest, latest = min(bounded_ends), (min(stated) if stated else None)
        if latest is None:
            fields["end_earliest"] = earliest                     # no earlier than
        elif earliest == latest:
            fields["end"] = latest                                # exact
        else:
            fields["end_earliest"], fields["end"] = earliest, latest     # within
    return TimeInterval(**fields)


def derive_conclusion_time(rule: RuleDefinition, premises: Sequence[Proposition]) -> ConclusionTimeResult | None:
    """The time of the conclusion of one firing match. ``premises`` are the matched propositions in the order of the
    rule's premise patterns.

    None for a rule that declares nothing (neither temporal requirements nor a conclusion time): such a rule runs
    exactly as it did in 0.7.0 and records no status.
    """
    declared = rule.conclusion_time
    if declared is None:
        if not rule.temporal:
            return None
        return ConclusionTimeResult(ConclusionTimeStatus.NOT_ESTABLISHED, reason=NO_CONCLUSION_TIME_DECLARED)

    mode, names = declared.kind.value, tuple(declared.premises)
    if declared.kind is ConclusionTimeKind.TIMELESS:
        return ConclusionTimeResult(ConclusionTimeStatus.TIMELESS, mode=mode)

    by_name = {pattern.name: matched for pattern, matched in zip(rule.premises, premises) if pattern.name is not None}
    chosen = [by_name[name] for name in names]

    if declared.kind is ConclusionTimeKind.AS_PREMISE:
        premise = chosen[0]
        if premise.valid_time is None and premise.occurred is None:
            return ConclusionTimeResult(ConclusionTimeStatus.NOT_ESTABLISHED, mode, names, PREMISE_CARRIES_NO_TIME)
        if premise.valid_time == TimeInterval() or premise.occurred == Occurrence():
            return ConclusionTimeResult(ConclusionTimeStatus.NOT_ESTABLISHED, mode, names, PREMISE_TIME_UNKNOWN)
        return ConclusionTimeResult(ConclusionTimeStatus.TIMED, mode, names,
                                    valid_time=premise.valid_time, occurred=premise.occurred)

    # while_all: every named premise is a state whose overlap with the others B4 has established, so the shared period
    # certainly exists. If it does not, that is a fault in ERC and not a property of the data.
    period = None
    if all(premise.valid_time is not None for premise in chosen):
        period = shared_period([premise.valid_time for premise in chosen])
    if period is None:
        raise RuntimeError(f"Conclusion time for rule {rule.rule_id}@{rule.version}: "
                           "the shared period of an established overlap is not certain.")
    return ConclusionTimeResult(ConclusionTimeStatus.TIMED, mode, names, valid_time=period)


def time_record(result: ConclusionTimeResult) -> dict[str, Any]:
    """The ``conclusion_time`` mapping kept on the inference step and in its trace entry. Only stated fields are
    written: instants as ISO text, flags as true; an event's unstated side is left out."""
    record: dict[str, Any] = {"status": result.status.value, "mode": result.mode, "premises": list(result.premises)}
    if result.reason is not None:
        record["reason"] = result.reason
    period, event = result.valid_time, result.occurred
    if period is not None:
        record["valid_time"] = {name: (True if getattr(period, name) is True else getattr(period, name).isoformat())
                                for name in _INTERVAL_FIELDS if getattr(period, name)}
    if event is not None:
        record["occurred"] = {name: moment.isoformat()
                              for name, moment in (("earliest", event.earliest), ("latest", event.latest))
                              if moment is not None}
    return record


def reason_text(record: Mapping[str, Any]) -> str:
    """The words for why a recorded time is not established, naming the premise where the reason is about one."""
    return _REASON_TEXT[record["reason"]].format(*record["premises"])
