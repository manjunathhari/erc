"""The Claude (Messages API) and OpenAI (Responses API) adapters (sections 4.2, 4.6 to 4.10).

Each adapter offers two paths, built through one preflight (`kit_request`, D-A21):
- `kit_callable(model, profile)`: the P-B kit's callable form fn(prompt, max_tokens, temperature, reasoning) ->
  (text, usage, secs), where usage["effective"] is read back from the request actually passed to the client (D-A7);
- `answer(question)`: memory-backed; the rendered memory block goes in `system` (Claude) or `instructions` (OpenAI).
Every setting is checked against the model's frozen capability profile before any client is made or called.
Nothing is dropped silently: what cannot be sent raises ValueError.
The SDK is imported only when a call needs it (D-A3), its major version is pinned (D-A27, D-A32) and the exact
installed version is recorded with every call. An injected client (tests) loads no SDK and reports
sdk_version None (D-A31).
"""
import importlib
import re
import time

from .contract import AnswerResult, DEFAULT_BUDGET
from .profiles import ClaudeProfile, OpenAIProfile, profile_hash
from .render import render_context

DEFAULT_TEMPERATURE = "default"      # the kit's "not sent"
DEFAULT_EFFORT = "default"           # Claude adaptive thinking at the model's default effort
DEFAULT_MAX_TOKENS = 1024

# IF-9: the real instruction text is settled with the comparison protocol. Both adapters use this one text.
INSTRUCTION = ("TEMPLATE (instruction wording to be settled with the comparison protocol): answer the user's question. "
               "Use the memory below only where it supports the answer.")

TOKEN_LIMIT_NAMES = ("max_tokens", "max_output_tokens", "max_completion_tokens", "max_tokens_to_sample")
SDK_OVERRIDE_OPTIONS = ("extra_headers", "extra_body", "extra_query")   # they override documented parameters
CLAUDE_CONTROLLED = ("model", "messages", "system", "thinking", "output_config") + TOKEN_LIMIT_NAMES + SDK_OVERRIDE_OPTIONS
OPENAI_CONTROLLED = (("model", "input", "instructions", "messages", "reasoning", "reasoning_effort")
                     + TOKEN_LIMIT_NAMES + SDK_OVERRIDE_OPTIONS)

THINKING_TYPES = {"enabled": "manual", "adaptive": "adaptive", "disabled": "none", "between_tools": "none"}
NONE_SENT_AS = {"disabled": {"type": "disabled"}, "between_tools": {"type": "between_tools"}}


class BudgetClosed(RuntimeError):
    """The memory block is over budget (D-A19): answer() fails closed before contacting the SDK."""

    def __init__(self, context):
        super().__init__(f"the memory block needs {context.tokens} tokens but the budget is {context.budget}; "
                         "nothing was sent")
        self.context = context


def _whole(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float("inf"), float("-inf"))


def read_major(version):
    """The major number of an installed SDK version such as '2.4.1', or None when it cannot be read."""
    if not isinstance(version, str):
        return None
    m = re.match(r"(\d+)\.\d+", version)
    return int(m.group(1)) if m else None


def extra_allows(constraint, value):
    """Does a value meet one extras constraint (name, kind, *args)? (D-A20)"""
    kind, args = constraint[1], constraint[2:]
    if kind == "int":
        return _whole(value) and args[0] <= value <= args[1]
    if kind == "number":
        return _number(value) and args[0] <= value <= args[1]
    if kind == "choice":
        return any(type(value) is type(c) and value == c for c in args[0])
    if kind == "dict":
        return isinstance(value, dict)
    if kind == "str":
        return isinstance(value, str)
    return False


class KitCallable:
    """One frozen model behind the kit's callable form. `.model`, `.profile` and `.profile_hash` are fixed."""

    def __init__(self, adapter, model, profile, allow_deprecated):
        self.adapter = adapter
        self.model = model
        self.profile = profile
        self.allow_deprecated = allow_deprecated
        self.profile_hash = profile_hash(profile)

    def __call__(self, prompt, max_tokens, temperature, reasoning):
        return self.adapter._kit_call(self, prompt, max_tokens, temperature, reasoning)


class _Adapter:
    provider = ""            # the SDK module, and the provider name in readiness records
    client_class = ""
    profile_type = None
    controlled = ()

    def __init__(self, memory, model=None, profile=None, reasoning=None, max_tokens=DEFAULT_MAX_TOKENS,
                 temperature=DEFAULT_TEMPERATURE, params=None, allow_deprecated=(), client=None, sdk_major=None):
        self.memory = memory
        self.model = model                     # IF-8: never defaulted in code
        self.profile = profile
        self.reasoning = reasoning
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.params = self._checked_params(params)
        self.allow_deprecated = self._checked_allowance(allow_deprecated)
        if sdk_major is not None and not _whole(sdk_major):
            raise ValueError(f"sdk_major must be a whole number or None, not {sdk_major!r}")
        self.sdk_major = sdk_major
        self._client = client                  # an injected client: no SDK is loaded (tests)
        self._made = {}                        # clients this adapter constructed
        self._sdk = None
        self.sdk_version = None

    # ---- construction-time checks (D-A14) ----
    def _checked_params(self, params):
        if params is None:
            return {}
        if not isinstance(params, dict) or not all(isinstance(k, str) for k in params):
            raise ValueError("params must be a dict with text keys")
        bad = sorted(k for k in params if k in self.controlled)
        if bad:
            raise ValueError(f"per-model params may not set or remove controlled request fields: {bad}")
        return dict(params)

    @staticmethod
    def _checked_allowance(allow_deprecated):
        if not isinstance(allow_deprecated, (tuple, list)) or not all(isinstance(m, str) for m in allow_deprecated):
            raise ValueError("allow_deprecated must be a tuple of mode names")
        return tuple(allow_deprecated)

    # ---- the SDK: imported when needed, pinned, version recorded ----
    def import_sdk(self):
        try:
            return importlib.import_module(self.provider)
        except ImportError as e:
            raise ImportError(f"the {self.provider} SDK is not installed; {type(self).__name__} needs it to make a "
                              f"call") from e

    def check_pin(self, module):
        """The installed version if its major matches the pin; ValueError otherwise. Constructs nothing."""
        if self.sdk_major is None:
            raise ValueError(f"the {self.provider} SDK major version must be pinned in the freeze (sdk_major)")
        version = getattr(module, "__version__", None)
        major = read_major(version)
        if major is None:
            raise ValueError(f"the installed {self.provider} SDK version {version!r} cannot be read")
        if major != self.sdk_major:
            raise ValueError(f"the installed {self.provider} SDK is {version} (major {major}); the freeze pins major "
                             f"{self.sdk_major}")
        return version

    def load_sdk(self):
        """Import the SDK and apply the pin, without constructing a client or calling the provider. With an injected
        client nothing is loaded and sdk_version stays None."""
        if self._client is not None:
            return None
        if self._sdk is None:
            module = self.import_sdk()
            version = self.check_pin(module)
            self._sdk = module
            self.sdk_version = version
        return self._sdk

    def client(self, profile):
        if self._client is not None:
            return self._client
        module = self.load_sdk()
        key = self._client_key(profile)
        if key not in self._made:
            self._made[key] = self._construct(module, profile)
        return self._made[key]

    # ---- the one preflight (D-A8, D-A9, D-A11, D-A14, D-A16, D-A17, D-A20, D-A21) ----
    def _check_profile(self, model, profile):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("no model chosen: the model is named for each run at the freeze (IF-8)")
        if not isinstance(profile, self.profile_type):
            raise ValueError(f"a {self.profile_type.__name__} for {model!r} is required, not {profile!r}")
        if profile.model != model:
            raise ValueError(f"the profile is for {profile.model!r}, not for {model!r}")

    @staticmethod
    def _limit(max_tokens, least, most):
        if not _whole(max_tokens) or max_tokens < least:
            raise ValueError(f"the token limit must be a whole number of at least {least}, not {max_tokens!r}")
        if most is not None and max_tokens > most:
            raise ValueError(f"the token limit {max_tokens} is above the profile's ceiling {most}")
        return max_tokens

    def _temperature(self, profile, t, thinking_on):
        if not _number(t):
            raise ValueError(f"temperature must be {DEFAULT_TEMPERATURE!r} or a finite number, not {t!r}")
        if profile.temperature is None:
            raise ValueError(f"{profile.model} takes no temperature (profile)")
        low, high = profile.temperature
        if not low <= t <= high:
            raise ValueError(f"temperature {t} is outside {profile.model}'s range {profile.temperature}")
        if thinking_on and not self._temperature_with_thinking(profile):
            raise ValueError(f"{profile.model} takes no temperature while thinking is on")
        return t

    @staticmethod
    def _temperature_with_thinking(profile):
        return True

    def _params(self, req, profile, thinking_on):
        """Per-model params, applied last: temperature by its own rule; anything else only if listed (D-A20)."""
        listed = {c[0]: c for c in profile.extras}
        for k, v in self.params.items():
            if k == "temperature":
                if v is None:
                    req.pop("temperature", None)
                else:
                    req["temperature"] = self._temperature(profile, v, thinking_on)
                continue
            if k not in listed:
                raise ValueError(f"{k!r} is not in {profile.model}'s extras allowlist")
            if v is None:
                req.pop(k, None)
            elif extra_allows(listed[k], v):
                req[k] = v
            else:
                raise ValueError(f"{k}={v!r} is outside its constraint {listed[k]}")

    def kit_request(self, model, profile, fields, max_tokens, temperature, reasoning, allow_deprecated=()):
        """The request for one call and the warnings it records, or ValueError before any client is touched."""
        self._check_profile(model, profile)
        warnings = []
        req = {"model": model, **fields}
        self._put_limit(req, profile, max_tokens)
        thinking_on = self._put_reasoning(req, profile, reasoning, max_tokens, tuple(allow_deprecated), warnings)
        if isinstance(temperature, str) and temperature == DEFAULT_TEMPERATURE:
            pass
        else:
            req["temperature"] = self._temperature(profile, temperature, thinking_on)
        self._put_version(req, profile)
        self._params(req, profile, thinking_on)
        return req, warnings

    def _put_version(self, req, profile):
        pass

    def api_version_sent(self, req):
        return None

    # ---- the kit path (D-A7) ----
    def kit_callable(self, model=None, profile=None, allow_deprecated=()):
        self._check_profile(model, profile)
        return KitCallable(self, model, profile, self._checked_allowance(allow_deprecated))

    def _kit_call(self, fn, prompt, max_tokens, temperature, reasoning):
        if not isinstance(prompt, str):
            raise ValueError("the prompt must be text")
        req, warnings = self.kit_request(fn.model, fn.profile, self._prompt_fields(prompt), max_tokens, temperature,
                                         reasoning, fn.allow_deprecated)
        client = self.client(fn.profile)
        started = time.perf_counter()
        response = self._send(client, req)
        secs = float(time.perf_counter() - started)
        text, n_in, n_out, served = self._parse(response)
        usage = {"prompt_tokens": n_in, "completion_tokens": n_out,
                 "effective": self.effective(req, fn.profile),
                 "served_model": served, "warnings": list(warnings),
                 "api_version": self.api_version_sent(req),
                 "sdk_version": self.sdk_version,
                 "profile_hash": fn.profile_hash}
        return text, usage, secs

    # ---- the memory-backed path ----
    def system_text(self, ctx):
        return INSTRUCTION + "\n\n" + render_context(ctx)

    def request(self, ctx, question):
        return self._answer_request(ctx, question)[0]

    def _answer_request(self, ctx, question):
        if not isinstance(question, str) or not question.strip():
            raise ValueError("the question must be non-empty text")
        fields = self._memory_fields(self.system_text(ctx), question)
        return self.kit_request(self.model, self.profile, fields, self.max_tokens, self.temperature, self.reasoning,
                                self.allow_deprecated)

    def answer(self, question, budget=None, speaker=None):
        """Retrieve, then one call. The adapter stores nothing (IF-10)."""
        if self.memory is None:
            raise ValueError("this adapter has no memory to answer from")
        budget = DEFAULT_BUDGET if budget is None else budget
        if not isinstance(question, str) or not question.strip():
            raise ValueError("the question must be non-empty text")
        # The whole preflight runs before anything is retrieved (D-A21); it runs again on the real block below.
        self.kit_request(self.model, self.profile, self._memory_fields("", question), self.max_tokens,
                         self.temperature, self.reasoning, self.allow_deprecated)
        found = self.memory.retrieve(question, budget, speaker)
        if found.context.over_budget:
            raise BudgetClosed(found.context)
        req, warnings = self._answer_request(found.context, question)
        client = self.client(self.profile)
        started = time.perf_counter()
        response = self._send(client, req)
        secs = float(time.perf_counter() - started)
        text, n_in, n_out, _ = self._parse(response)
        return AnswerResult(text, found.context, found.trace, req, getattr(response, "usage", None), n_in, n_out, secs,
                            tuple(warnings), self.api_version_sent(req), self.sdk_version, profile_hash(self.profile))


def _usage_counts(response):
    usage = getattr(response, "usage", None)
    return getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)


class ClaudeAdapter(_Adapter):
    provider = "anthropic"
    client_class = "Anthropic"
    profile_type = ClaudeProfile
    controlled = CLAUDE_CONTROLLED

    def _client_key(self, profile):
        return profile.api_version             # one client per API version (D-A16)

    def _construct(self, module, profile):
        return module.Anthropic(default_headers={"anthropic-version": profile.api_version})

    @staticmethod
    def _send(client, req):
        return client.messages.create(**req)

    @staticmethod
    def _prompt_fields(prompt):
        return {"messages": [{"role": "user", "content": prompt}]}

    @staticmethod
    def _memory_fields(system, question):
        return {"system": system, "messages": [{"role": "user", "content": question}]}

    def _put_limit(self, req, profile, max_tokens):
        req["max_tokens"] = self._limit(max_tokens, 1, profile.max_tokens_limit)

    @staticmethod
    def _temperature_with_thinking(profile):
        return profile.temperature_with_thinking

    def _put_reasoning(self, req, profile, reasoning, max_tokens, allow_deprecated, warnings):
        """Section 4.7. Returns whether thinking is on."""
        if not isinstance(reasoning, dict) or not isinstance(reasoning.get("mode"), str):
            raise ValueError(f"reasoning must name its mode, for example {{'mode': 'none'}}, not {reasoning!r}")
        mode = reasoning["mode"]
        if mode not in profile.modes:
            raise ValueError(f"{profile.model} does not support reasoning mode {mode!r} (profile modes "
                             f"{profile.modes})")
        keys = set(reasoning)
        if mode == "none":
            if not keys <= {"mode", "effort"}:
                raise ValueError(f"unknown reasoning keys {sorted(keys - {'mode', 'effort'})}")
            if profile.none_sends in NONE_SENT_AS:
                req["thinking"] = dict(NONE_SENT_AS[profile.none_sends])
            if "effort" in reasoning:
                if reasoning["effort"] not in profile.none_efforts:
                    raise ValueError(f"{profile.model} takes effort {reasoning['effort']!r} with thinking off only "
                                     f"from {profile.none_efforts}")
                req["output_config"] = {"effort": reasoning["effort"]}
            thinking_on = False
        elif mode == "manual":
            if "effort" in reasoning:
                raise ValueError("a manual thinking budget with an effort is not supported in this shell (D-A23)")
            if keys != {"mode", "budget_tokens"}:
                raise ValueError("manual thinking is {'mode': 'manual', 'budget_tokens': N}")
            n = reasoning["budget_tokens"]
            if not _whole(n) or n < profile.min_budget or n >= max_tokens:
                raise ValueError(f"the thinking budget must be a whole number from {profile.min_budget} and below "
                                 f"max_tokens {max_tokens}, not {n!r}")
            req["thinking"] = {"type": "enabled", "budget_tokens": n}
            thinking_on = True
        else:
            if keys != {"mode", "effort"}:
                raise ValueError("adaptive thinking is {'mode': 'adaptive', 'effort': E or 'default'}")
            effort = reasoning["effort"]
            if effort != DEFAULT_EFFORT and effort not in profile.efforts:
                raise ValueError(f"{profile.model} takes effort only from {profile.efforts}, not {effort!r}")
            req["thinking"] = {"type": "adaptive"}
            if effort != DEFAULT_EFFORT:
                req["output_config"] = {"effort": effort}      # never inside thinking
            thinking_on = True
        if mode in profile.deprecated:
            if mode not in allow_deprecated:
                raise ValueError(f"reasoning mode {mode!r} is deprecated for {profile.model}; the freeze must allow "
                                 f"it (allow_deprecated)")
            warnings.append(f"reasoning mode {mode!r} is deprecated for {profile.model}; sent because it is allowed "
                            f"by the freeze")
        return thinking_on

    def _put_version(self, req, profile):
        req["extra_headers"] = {"anthropic-version": profile.api_version}      # never the SDK's default (D-A16)

    def api_version_sent(self, req):
        return (req.get("extra_headers") or {}).get("anthropic-version")

    def effective(self, req, profile):
        """The settings the request carries, read back from it (D-A7)."""
        thinking = req.get("thinking")
        effort = (req.get("output_config") or {}).get("effort")
        kind = profile.omitted_means if thinking is None else THINKING_TYPES[thinking["type"]]
        if kind == "manual":
            reasoning = {"mode": "manual", "budget_tokens": thinking["budget_tokens"]}
        elif kind == "adaptive":
            reasoning = {"mode": "adaptive", "effort": DEFAULT_EFFORT if effort is None else effort}
        elif effort is None:
            reasoning = {"mode": "none"}
        else:
            reasoning = {"mode": "none", "effort": effort}
        return {"model": req["model"], "max_tokens": req.get("max_tokens"),
                "temperature": req["temperature"] if "temperature" in req else DEFAULT_TEMPERATURE,
                "reasoning": reasoning}

    @staticmethod
    def _parse(response):
        blocks = getattr(response, "content", None) or []
        text = "".join(b.text for b in blocks if getattr(b, "type", None) == "text")
        n_in, n_out = _usage_counts(response)
        return text, n_in, n_out, getattr(response, "model", None)


class OpenAIAdapter(_Adapter):
    provider = "openai"
    client_class = "OpenAI"
    profile_type = OpenAIProfile
    controlled = OPENAI_CONTROLLED

    def _client_key(self, profile):
        return None

    def _construct(self, module, profile):
        return module.OpenAI()

    @staticmethod
    def _send(client, req):
        return client.responses.create(**req)

    @staticmethod
    def _prompt_fields(prompt):
        return {"input": prompt}

    @staticmethod
    def _memory_fields(system, question):
        return {"instructions": system, "input": question}

    def _put_limit(self, req, profile, max_tokens):
        req["max_output_tokens"] = self._limit(max_tokens, profile.min_output_tokens, profile.max_tokens_limit)

    def _put_reasoning(self, req, profile, reasoning, max_tokens, allow_deprecated, warnings):
        """Section 4.8. Returns False: OpenAI profiles carry no with-reasoning temperature rule."""
        if not isinstance(reasoning, dict) or not isinstance(reasoning.get("mode"), str):
            raise ValueError(f"reasoning must name its mode, for example {{'mode': 'default'}}, not {reasoning!r}")
        mode = reasoning["mode"]
        if mode == "default" and set(reasoning) == {"mode"}:
            if not profile.default_allowed:
                raise ValueError(f"{profile.model} needs its effort named (profile)")
        elif mode == "effort" and set(reasoning) == {"mode", "effort"}:
            if reasoning["effort"] not in profile.efforts:
                raise ValueError(f"{profile.model} takes effort only from {profile.efforts}, not "
                                 f"{reasoning['effort']!r}")
            req["reasoning"] = {"effort": reasoning["effort"]}
        else:
            raise ValueError(f"OpenAI reasoning is {{'mode': 'default'}} or {{'mode': 'effort', 'effort': E}}, not "
                             f"{reasoning!r}")
        return False

    def effective(self, req, profile=None):
        reasoning = ({"mode": "effort", "effort": req["reasoning"]["effort"]} if "reasoning" in req
                     else {"mode": "default"})
        return {"model": req["model"], "max_tokens": req.get("max_output_tokens"),
                "temperature": req["temperature"] if "temperature" in req else DEFAULT_TEMPERATURE,
                "reasoning": reasoning}

    @staticmethod
    def _parse(response):
        text = getattr(response, "output_text", None)
        if not isinstance(text, str):
            parts = []
            for item in getattr(response, "output", None) or []:
                for part in getattr(item, "content", None) or []:
                    if getattr(part, "type", None) == "output_text":
                        parts.append(part.text)
            text = "".join(parts)
        n_in, n_out = _usage_counts(response)
        return text, n_in, n_out, getattr(response, "model", None)
