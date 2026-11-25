"""Model-capability profiles (D-A8, D-A9, D-A11), their integrity rules (R7-A, D-A30, section 4.12) and the canonical
profile hash (D-A28, section 4.13).

A profile is data chosen and frozen with each run. The adapters hold no model names and no per-model rules. An
invalid profile raises ValueError when it is constructed, so no adapter call or SDK client is ever reached with it.
"""
import dataclasses
import datetime
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Optional

CANON_SCHEMA = "engram-profile-canon/1"

CLAUDE_MODES = ("none", "manual", "adaptive")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
OPENAI_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
OMITTED_MEANS = ("none", "adaptive")
NONE_SENDS = ("omit", "disabled", "between_tools")
EXTRA_KINDS = ("int", "number", "dict", "choice", "str")
NO_SAMPLING_FROM = "2026-10-21"                     # D-A16: this API version removes temperature, top_p and top_k
NO_SAMPLING_EXTRAS = ("temperature", "top_p", "top_k")
API_VERSION_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _whole(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _plain_choice(x):
    return isinstance(x, (str, bool)) or _whole(x) or (isinstance(x, float) and math.isfinite(x))


def _check_text(name, value, non_empty):
    if not isinstance(value, str):
        raise ValueError(f"profile {name} must be text, not {value!r}")
    if non_empty and not value.strip():
        raise ValueError(f"profile {name} must not be empty")


def _choices(profile, name, allowed):
    """A field the specification describes only as values "drawn from" a set (section 4.12): a tuple or a list is
    accepted, and the field is stored as a tuple, so later changes to the caller's list reach neither the profile
    nor its hash (build r2, point B)."""
    value = getattr(profile, name)
    if not isinstance(value, (tuple, list)) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"profile {name} must be a tuple or list of text, not {value!r}")
    unknown = [v for v in value if v not in allowed]
    if unknown:
        raise ValueError(f"profile {name} has unknown values {unknown}; allowed: {allowed}")
    object.__setattr__(profile, name, tuple(value))


def _check_temperature(t):
    """Section 4.12: None, or a tuple (low, high). A list is refused (T110)."""
    if t is None:
        return
    if not isinstance(t, tuple) or len(t) != 2:
        raise ValueError(f"temperature must be None or a (low, high) tuple, not {t!r}")
    low, high = t
    if not (_finite(low) and _finite(high)):
        raise ValueError(f"temperature bounds must be finite numbers, not {t!r}")
    if low < 0 or high < 0:
        raise ValueError(f"temperature bounds must not be negative: {t!r}")
    if low > high:
        raise ValueError(f"temperature low is above high: {t!r}")


def _check_limits(least_name, least, most):
    if not _whole(least) or least <= 0:
        raise ValueError(f"{least_name} must be a whole number above 0, not {least!r}")
    if most is None:
        return
    if not _whole(most) or most <= 0:
        raise ValueError(f"max_tokens_limit must be None or a whole number above 0, not {most!r}")
    if least > most:
        raise ValueError(f"{least_name} {least} is above max_tokens_limit {most}")


def _check_extras(extras):
    """Section 4.12: a tuple of (name, kind, *args) constraints, each itself a tuple; a choice takes one tuple of
    values. Lists are refused here because the specification states tuples. Only the five kinds exist (D-A30)."""
    if not isinstance(extras, tuple):
        raise ValueError(f"extras must be a tuple of constraints, not {extras!r}")
    names = set()
    for c in extras:
        if not isinstance(c, tuple) or len(c) < 2:
            raise ValueError(f"an extra constraint is (name, kind, *args), not {c!r}")
        name, kind, args = c[0], c[1], c[2:]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"an extra needs a non-empty name, not {name!r}")
        if name in names:
            raise ValueError(f"extra {name!r} is listed twice")
        names.add(name)
        if not isinstance(kind, str) or kind not in EXTRA_KINDS:
            raise ValueError(f"extra {name!r} has kind {kind!r}; only {EXTRA_KINDS} are supported")
        if kind in ("int", "number"):
            bound = _whole if kind == "int" else _finite
            if len(args) != 2:
                raise ValueError(f"extra {name!r} of kind {kind} takes exactly (low, high)")
            if not (bound(args[0]) and bound(args[1])):
                raise ValueError(f"extra {name!r}: bounds must be {kind} values, not {args!r}")
            if args[0] > args[1]:
                raise ValueError(f"extra {name!r}: low is above high")
        elif kind == "choice":
            if len(args) != 1 or not isinstance(args[0], tuple) or not args[0]:
                raise ValueError(f"extra {name!r} of kind choice takes one non-empty tuple of values")
            if not all(_plain_choice(v) for v in args[0]):
                raise ValueError(f"extra {name!r}: choice values must be plain text, numbers or booleans")
        elif args:
            raise ValueError(f"extra {name!r} of kind {kind} takes no arguments")


def _check_api_version(v):
    if not isinstance(v, str) or not API_VERSION_SHAPE.fullmatch(v):
        raise ValueError(f"api_version must be YYYY-MM-DD, not {v!r}")
    try:
        datetime.date(int(v[:4]), int(v[5:7]), int(v[8:]))
    except ValueError:
        raise ValueError(f"api_version {v!r} is not a real date") from None


@dataclass(frozen=True)
class ClaudeProfile:
    """What one Claude model accepts, from its documentation at the freeze (sections 4.7, 4.9, 4.12)."""
    model: str
    modes: tuple = ()
    omitted_means: str = "none"
    none_sends: Optional[str] = None
    efforts: tuple = ()
    none_efforts: tuple = ()
    temperature: Optional[tuple] = None
    temperature_with_thinking: bool = False
    api_version: Optional[str] = None
    deprecated: tuple = ()
    extras: tuple = ()
    source: str = ""
    min_budget: int = 1024
    max_tokens_limit: Optional[int] = None

    def __post_init__(self):
        _check_text("model", self.model, non_empty=True)
        _check_text("source", self.source, non_empty=False)
        _check_api_version(self.api_version)
        _choices(self, "modes", CLAUDE_MODES)
        if self.omitted_means not in OMITTED_MEANS or not isinstance(self.omitted_means, str):
            raise ValueError(f"omitted_means must be one of {OMITTED_MEANS}, not {self.omitted_means!r}")
        if self.none_sends is not None and (not isinstance(self.none_sends, str) or self.none_sends not in NONE_SENDS):
            raise ValueError(f"none_sends must be one of {NONE_SENDS} or None, not {self.none_sends!r}")
        if ("none" in self.modes) != (self.none_sends is not None):
            raise ValueError("none_sends is set if and only if 'none' is a mode")
        if self.none_sends == "omit" and self.omitted_means != "none":
            raise ValueError("'none' cannot be sent by omission on a model whose omitted thinking means adaptive")
        _choices(self, "efforts", CLAUDE_EFFORTS)
        _choices(self, "none_efforts", CLAUDE_EFFORTS)
        _choices(self, "deprecated", CLAUDE_MODES)
        if not set(self.deprecated) <= set(self.modes):
            raise ValueError(f"deprecated modes {self.deprecated} must be among the supported modes {self.modes}")
        _check_temperature(self.temperature)
        if not isinstance(self.temperature_with_thinking, bool):
            raise ValueError("temperature_with_thinking must be True or False")
        _check_limits("min_budget", self.min_budget, self.max_tokens_limit)
        _check_extras(self.extras)
        if self.api_version >= NO_SAMPLING_FROM:
            if self.temperature is not None:
                raise ValueError(f"API version {self.api_version} removes temperature: the profile may not allow it")
            listed = [c[0] for c in self.extras if c[0] in NO_SAMPLING_EXTRAS]
            if listed:
                raise ValueError(f"API version {self.api_version} removes {listed}: they may not be extras")


@dataclass(frozen=True)
class OpenAIProfile:
    """What one OpenAI model accepts on the Responses API, from its documentation at the freeze (section 4.8)."""
    model: str
    efforts: tuple = ()
    default_allowed: bool = True
    temperature: Optional[tuple] = None
    extras: tuple = ()
    source: str = ""
    min_output_tokens: int = 16
    max_tokens_limit: Optional[int] = None

    def __post_init__(self):
        _check_text("model", self.model, non_empty=True)
        _check_text("source", self.source, non_empty=False)
        _choices(self, "efforts", OPENAI_EFFORTS)
        if not isinstance(self.default_allowed, bool):
            raise ValueError("default_allowed must be True or False")
        _check_temperature(self.temperature)
        _check_limits("min_output_tokens", self.min_output_tokens, self.max_tokens_limit)
        _check_extras(self.extras)


# ---- the canonical profile hash (D-A28) ----
def _canon_value(x):
    if isinstance(x, (tuple, list)):
        return [_canon_value(v) for v in x]
    if isinstance(x, dict):
        return {k: _canon_value(v) for k, v in x.items()}
    if isinstance(x, float) and not math.isfinite(x):
        raise ValueError("a non-finite number cannot be put in canonical JSON")
    return x


def profile_canon(profile, schema=CANON_SCHEMA):
    """The canonical object: schema version, profile kind and every field, source included."""
    if not isinstance(profile, (ClaudeProfile, OpenAIProfile)):
        raise ValueError(f"not a profile: {profile!r}")
    values = {f.name: _canon_value(getattr(profile, f.name)) for f in dataclasses.fields(profile)}
    return {"schema": schema, "kind": type(profile).__name__, "fields": values}


def canonical_json(obj):
    """Sorted keys, fixed separators, non-ASCII kept, non-finite numbers refused; tuples become arrays."""
    return json.dumps(_canon_value(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def profile_hash(profile, schema=CANON_SCHEMA):
    """SHA-256, lower-case hexadecimal, of the canonical JSON encoded as UTF-8."""
    text = canonical_json(profile_canon(profile, schema))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
