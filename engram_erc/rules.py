"""Declarative, versioned rule contracts for deterministic forward chaining."""
from __future__ import annotations

from dataclasses import dataclass, field
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

    def __post_init__(self) -> None:
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


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """Immutable rule with explicit version and ordered premise patterns."""
    rule_id: str
    version: str
    premises: tuple[PropositionPattern, ...]
    conclusion: ConclusionTemplate
    description: str = ""
    max_firings: int = 100

    def __post_init__(self) -> None:
        require_nonempty(self.rule_id, "rule_id")
        require_nonempty(self.version, "version")
        if not self.premises:
            raise ValueError("rule requires at least one premise")
        if self.max_firings < 1:
            raise ValueError("max_firings must be >= 1")
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
