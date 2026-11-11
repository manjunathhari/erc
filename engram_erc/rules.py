"""Declarative, versioned rule contracts for deterministic forward chaining."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, TypeAlias

from .contracts import JSONValue, Proposition, require_nonempty


@dataclass(frozen=True, slots=True)
class Variable:
    """A named unification variable in a rule pattern."""
    name: str

    def __post_init__(self) -> None:
        require_nonempty(self.name, "variable name")


@dataclass(frozen=True, slots=True)
class PropositionPattern:
    """A partial proposition pattern. Variable terms bind consistently."""
    subject: str | Variable
    predicate: str | Variable
    object_value: JSONValue | Variable
    polarity: bool | Variable = True
    # ERC 0.7.0: an optional name by which a rule's temporal constraints refer to this premise. It plays no part in
    # matching: a named pattern matches exactly the propositions it matched unnamed.
    name: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        if self.name is not None and (not isinstance(self.name, str) or not self.name.strip()):
            raise ValueError("pattern name must be a non-empty string")
        if not isinstance(self.polarity, (bool, Variable)):
            raise ValueError("pattern polarity must be bool or Variable")
        for name in ("subject", "predicate"):
            value = getattr(self, name)
            if not isinstance(value, (str, Variable)):
                raise ValueError(f"pattern {name} must be str or Variable")


@dataclass(frozen=True, slots=True)
class ConclusionTemplate:
    subject: str | Variable
    predicate: str | Variable
    object_value: JSONValue | Variable
    polarity: bool | Variable = True

    def __post_init__(self) -> None:
        if not isinstance(self.polarity, (bool, Variable)):
            raise ValueError("conclusion polarity must be bool or Variable")


class TemporalRequirementKind(str, Enum):
    """The temporal relationship a rule may require between two of its premises (ERC 0.7.0)."""
    OVERLAPS = "overlaps"   # two states hold at one and the same time; the order of the two names carries no meaning
    BEFORE = "before"       # left is over before right begins
    DURING = "during"       # left, an event, happens while right, a state, holds


@dataclass(frozen=True, slots=True)
class TemporalConstraint:
    """`relation` must hold between the premises named `left` and `right` for the rule to fire."""
    relation: TemporalRequirementKind | str
    left: str
    right: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "relation", TemporalRequirementKind(self.relation))
        except ValueError:
            raise ValueError(f"unknown temporal relation: {self.relation!r}") from None
        for side in (self.left, self.right):
            if not isinstance(side, str) or not side.strip():
                raise ValueError("a temporal constraint names two premises")
        if self.left == self.right:
            raise ValueError("a temporal constraint relates two different premises")


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Immutable rule with explicit version and ordered premise patterns."""
    rule_id: str
    version: str
    premises: tuple[PropositionPattern, ...]
    conclusion: ConclusionTemplate
    description: str = ""
    max_firings: int = 100
    # ERC 0.7.0: the temporal relationships the rule needs between its named premises; all must be established for a
    # match to fire. None: the rule declares nothing. (): the rule states that it needs none. In 0.7.0 both fire as a
    # rule always did. A rule whose declaration is changed must be given a new version.
    temporal: tuple[TemporalConstraint, ...] | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        require_nonempty(self.rule_id, "rule_id")
        require_nonempty(self.version, "version")
        if not self.premises:
            raise ValueError("rule requires at least one premise")
        if self.max_firings < 1:
            raise ValueError("max_firings must be >= 1")
        names = [pattern.name for pattern in self.premises if pattern.name is not None]
        if len(names) != len(set(names)):
            raise ValueError("two premises carry the same name")
        if self.temporal is not None:
            if not isinstance(self.temporal, tuple) or not all(isinstance(c, TemporalConstraint) for c in self.temporal):
                raise ValueError("temporal must be None or a tuple of TemporalConstraint")
            declared = set()
            for constraint in self.temporal:
                sides = (constraint.left, constraint.right)
                for side in sides:
                    if side not in names:
                        raise ValueError(f"temporal constraint names an unknown premise: {side!r}")
                # `overlaps` means the same with its two names exchanged
                key = (constraint.relation, frozenset(sides) if constraint.relation is TemporalRequirementKind.OVERLAPS else sides)
                if key in declared:
                    raise ValueError("the same temporal constraint is declared twice")
                declared.add(key)
        # Every variable used in the conclusion must be bound by a premise.
        bound = set()
        for pattern in self.premises:
            for term in (pattern.subject, pattern.predicate, pattern.object_value, pattern.polarity):
                if isinstance(term, Variable):
                    bound.add(term.name)
        used = set()
        for term in (
            self.conclusion.subject, self.conclusion.predicate,
            self.conclusion.object_value, self.conclusion.polarity
        ):
            if isinstance(term, Variable):
                used.add(term.name)
        missing = used - bound
        if missing:
            raise ValueError(f"conclusion contains unbound variables: {sorted(missing)}")


@dataclass(frozen=True, slots=True)
class RuleSet:
    rules: tuple[RuleDefinition, ...]
    version: str = "1"

    def __post_init__(self) -> None:
        require_nonempty(self.version, "ruleset version")
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule_id in RuleSet")
