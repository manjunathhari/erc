"""Fake model-capability profiles for the tests (r5). Model names are fake. Each profile copies the SHAPE of a
configuration the providers document (see the r5 document's citations), not any real model's full truth."""
from engram_interface import ClaudeProfile, OpenAIProfile

ALL = ("low", "medium", "high", "xhigh", "max")

# Legacy-only: manual (budget) thinking only; adaptive rejected; thinking off when omitted; temperature allowed
# only while thinking is off. (Shape of the "extended only" rows of the thinking support table.)
OLD_VERSION, NEW_VERSION = "2023-06-01", "2026-10-21"   # r6: every Claude profile pins its API version (D-A16)
LEGACY = ClaudeProfile("claude-legacy-fake", modes=("none", "manual"), omitted_means="none", none_sends="omit",
                       temperature=(0, 1), temperature_with_thinking=False, api_version=OLD_VERSION,
                       extras=(("top_k", "int", 1, 500), ("metadata", "dict")), source="fake")
# Adaptive-only and always on: none and manual rejected; effort at output_config.effort; no temperature.
ADAPTIVE = ClaudeProfile("claude-adaptive-fake", modes=("adaptive",), omitted_means="adaptive", none_sends=None,
                         efforts=ALL, temperature=None, api_version=NEW_VERSION, source="fake")
# Adaptive by default, with an off switch sent as between_tools, accepted at effort high or below.
SWITCH = ClaudeProfile("claude-switch-fake", modes=("none", "adaptive"), omitted_means="adaptive",
                       none_sends="between_tools", efforts=ALL, none_efforts=("low", "medium", "high"),
                       temperature=None, api_version=NEW_VERSION, source="fake")
# Both modes, manual deprecated ("deprecated-both"): off when omitted; manual refused unless the freeze allows it
# (r6, D-A17), then sent with a warning.
BOTH = ClaudeProfile("claude-both-fake", modes=("none", "manual", "adaptive"), omitted_means="none",
                     none_sends="omit", efforts=("low", "medium", "high", "max"), deprecated=("manual",),
                     temperature=(0, 1), temperature_with_thinking=False, api_version=OLD_VERSION, source="fake")
CLAUDE_PROFILES = (LEGACY, ADAPTIVE, SWITCH, BOTH)

# OpenAI: a model without reasoning; a reasoning model with a short allowlist; one that needs an effort named.
O_PLAIN = OpenAIProfile("openai-plain-fake", efforts=(), default_allowed=True, temperature=(0, 2),
                        extras=(("metadata", "dict"), ("top_p", "number", 0, 1)), source="fake")
O_REASON = OpenAIProfile("openai-reasoning-fake", efforts=("low", "medium", "high"), default_allowed=True,
                         temperature=None, source="fake")
O_NAMED = OpenAIProfile("openai-named-fake", efforts=("medium", "high", "xhigh"), default_allowed=False,
                        temperature=None, source="fake")
OPENAI_PROFILES = (O_PLAIN, O_REASON, O_NAMED)

NONE = {"mode": "none"}
DEFAULT = {"mode": "default"}


def adaptive(effort):
    return {"mode": "adaptive", "effort": effort}


def manual(n):
    return {"mode": "manual", "budget_tokens": n}


def effort(e):
    return {"mode": "effort", "effort": e}


def claude_outbound(req, profile):
    """The test's own reading of a Messages API request. With no thinking field the model does what the
    profile says it does when thinking is omitted."""
    t = req.get("thinking")
    e = (req.get("output_config") or {}).get("effort")
    kind = profile.omitted_means if t is None else {"enabled": "manual", "adaptive": "adaptive",
                                                    "disabled": "none", "between_tools": "none"}[t["type"]]
    if kind == "manual":
        r = {"mode": "manual", "budget_tokens": t["budget_tokens"]}
    elif kind == "adaptive":
        r = {"mode": "adaptive", "effort": e if e is not None else "default"}
    else:
        r = {"mode": "none"} if e is None else {"mode": "none", "effort": e}
    return dict(model=req["model"], max_tokens=req.get("max_tokens"),
                temperature=req["temperature"] if "temperature" in req else "default", reasoning=r)


def openai_outbound(req, profile=None):
    """The test's own reading of a Responses API request."""
    return dict(model=req["model"], max_tokens=req.get("max_output_tokens"),
                temperature=req["temperature"] if "temperature" in req else "default",
                reasoning={"mode": "effort", "effort": req["reasoning"]["effort"]} if "reasoning" in req
                else {"mode": "default"})


def claude_for(model, **kw):
    """A legacy-shaped profile under any model name, for the memory-backed answer() tests (r6, D-A21)."""
    base = dict(modes=("none", "manual"), omitted_means="none", none_sends="omit", temperature=(0, 1),
                api_version=OLD_VERSION, extras=(("top_k", "int", 1, 500), ("metadata", "dict")), source="fake")
    return ClaudeProfile(model, **{**base, **kw})


def openai_for(model, **kw):
    base = dict(efforts=(), default_allowed=True, temperature=(0, 2), extras=(("metadata", "dict"),), source="fake")
    return OpenAIProfile(model, **{**base, **kw})
