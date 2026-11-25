"""IF-T66..IF-T75 (revision 4, D-A7; revised in r5 for D-A8 to D-A14).

Each adapter is used as the test kit's answer callable and judge callable: fn(prompt, max_tokens, temperature,
reasoning) -> (text, usage, secs), with usage["effective"] = {model, max_tokens, temperature, reasoning}.
Fake clients capture the arguments each adapter passes to its SDK client. The tests read the settings back from
those captured arguments with their own reader (profiles_fake.claude_outbound / openai_outbound) and check:
  - the request matches the freeze, under each API's own parameter names;
  - usage["effective"] equals what the captured request says, not what was asked for.
They check the arguments passed to the SDK client, not the serialised HTTP body or whether the provider accepts
them. No network, no key, no SDK.
r5: every kit callable now needs the model's capability profile (D-A8); reasoning is a named mode (D-A9, D-A11);
OpenAI uses the Responses API (D-A12); per-model params may not touch controlled fields (D-A14)."""
import inspect
import pytest
from engram_interface import ClaudeAdapter, OpenAIAdapter, KitCallable
from .helpers import FakeAnthropicClient, FakeOpenAIClient, fake_sdk
from .profiles_fake import (LEGACY, ADAPTIVE, SWITCH, BOTH, O_PLAIN, O_REASON, O_NAMED, NONE, DEFAULT,
                            adaptive, manual, effort, claude_outbound, openai_outbound)

PROMPT = "Excerpts:\n- Alice: I moved to Leeds.\n\nQuestion: Where does Alice live?\n"
FIELDS = ("model", "max_tokens", "temperature", "reasoning")

# The freezes the kit would hold (fake model names; real models and profiles are fixed at the comparison-run freeze).
CLAUDE_FREEZE = dict(answer=dict(model=LEGACY.model, max_tokens=60, temperature=0, reasoning=NONE),
                     judge=dict(model=ADAPTIVE.model, max_tokens=4096, temperature="default", reasoning=adaptive("high")))
CLAUDE_PROFILE = dict(answer=LEGACY, judge=ADAPTIVE)
OPENAI_FREEZE = dict(answer=dict(model=O_PLAIN.model, max_tokens=60, temperature=0, reasoning=DEFAULT),
                     judge=dict(model=O_REASON.model, max_tokens=16, temperature="default", reasoning=effort("low")))
OPENAI_PROFILE = dict(answer=O_PLAIN, judge=O_REASON)


def differ(expected, effective):
    """The kit's rule (engram_testkit.runner.settings_differ), restated: equal values, bools not mixed with numbers."""
    if not isinstance(effective, dict):
        return ["no effective settings reported"]
    return [f for f in FIELDS if f not in effective or expected[f] != effective[f]
            or isinstance(expected[f], bool) != isinstance(effective[f], bool)]


class ServedClaude(FakeAnthropicClient):
    """Also says which model served the reply, as the real API does."""
    def _create(self, **kw):
        r = super()._create(**kw)
        r.model = kw["model"] + "-20261101"
        return r


def call_as_kit(fn, part):
    """How the kit calls a callable: keyword settings from the freeze."""
    return fn(PROMPT, max_tokens=part["max_tokens"], temperature=part["temperature"], reasoning=part["reasoning"])


@pytest.mark.parametrize("cls,fake,profile,asked", [
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, dict(max_tokens=10, temperature=0, reasoning=NONE)),
    (OpenAIAdapter, FakeOpenAIClient, O_PLAIN, dict(max_tokens=16, temperature=0, reasoning=DEFAULT))])
def test_t66_the_kit_callable_has_the_kits_shape(cls, fake, profile, asked):
    # r5: a profile is passed (D-A8); the settings asked for are profile-valid; a missing profile is refused.
    fn = cls(None, client=fake()).kit_callable(profile.model, profile)
    assert isinstance(fn, KitCallable) and fn.model == profile.model
    names = set(inspect.signature(fn).parameters)
    assert {"max_tokens", "temperature", "reasoning"} <= names
    text, usage, secs = fn(PROMPT, **asked)
    assert isinstance(text, str) and isinstance(secs, float) and secs >= 0
    assert set(usage["effective"]) == set(FIELDS)
    assert (usage["prompt_tokens"], usage["completion_tokens"]) == (10, 2)
    with pytest.raises(ValueError):
        cls(None, client=fake()).kit_callable(profile=profile)        # IF-8: no default model
    with pytest.raises(ValueError):
        cls(None, client=fake()).kit_callable(profile.model)          # D-A8: no profile, no callable


def test_t67_claude_answer_and_judge_send_what_the_freeze_says():
    # r5: answer on a legacy-only profile (mode none, temperature 0); judge on an adaptive-only profile
    # (adaptive, effort high at output_config.effort, temperature not sent). r4 used thinking 1024 and temperature 1.
    c = FakeAnthropicClient()
    a = ClaudeAdapter(None, client=c)
    for kind in ("answer", "judge"):
        part, profile = CLAUDE_FREEZE[kind], CLAUDE_PROFILE[kind]
        fn = a.kit_callable(part["model"], profile)
        _, usage, _ = call_as_kit(fn, part)
        req = c.calls[-1]
        assert req["model"] == part["model"] and req["max_tokens"] == part["max_tokens"]
        assert req["messages"] == [{"role": "user", "content": PROMPT}] and "system" not in req
        if kind == "answer":
            assert req["temperature"] == 0 and "thinking" not in req and "output_config" not in req
        else:
            assert "temperature" not in req
            assert req["thinking"] == {"type": "adaptive"} and req["output_config"] == {"effort": "high"}
        assert claude_outbound(req, profile) == {f: part[f] for f in FIELDS}
        assert differ(part, usage["effective"]) == [], kind
    assert len(c.calls) == 2


def test_t68_openai_answer_and_judge_send_what_the_freeze_says_in_responses_form():
    # r5 (D-A12): Responses API. Was Chat Completions with max_tokens / max_completion_tokens and reasoning_effort.
    c = FakeOpenAIClient()
    answer = OpenAIAdapter(None, client=c).kit_callable(O_PLAIN.model, O_PLAIN)
    judge = OpenAIAdapter(None, client=c).kit_callable(O_REASON.model, O_REASON)
    _, ua, _ = call_as_kit(answer, OPENAI_FREEZE["answer"])
    ra = c.calls[-1]
    assert ra["max_output_tokens"] == 60 and ra["temperature"] == 0 and "reasoning" not in ra
    _, uj, _ = call_as_kit(judge, OPENAI_FREEZE["judge"])
    rj = c.calls[-1]
    assert rj["model"] == O_REASON.model and rj["max_output_tokens"] == 16
    assert "temperature" not in rj and rj["reasoning"] == {"effort": "low"}
    for req in (ra, rj):
        assert req["input"] == PROMPT and "messages" not in req and "instructions" not in req
        assert not {"max_tokens", "max_completion_tokens", "reasoning_effort"} & set(req)
    for kind, req, usage in (("answer", ra, ua), ("judge", rj, uj)):
        part = OPENAI_FREEZE[kind]
        assert openai_outbound(req) == {f: part[f] for f in FIELDS}, kind
        assert differ(part, usage["effective"]) == [], kind


CASES = [  # (adapter class, fake, profile, adapter options, settings asked for)
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, {}, dict(max_tokens=60, temperature=0, reasoning=NONE)),
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, {}, dict(max_tokens=4096, temperature="default", reasoning=manual(1024))),
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, dict(params={"temperature": None}), dict(max_tokens=60, temperature=0, reasoning=NONE)),
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, dict(params={"temperature": 1}), dict(max_tokens=60, temperature=0, reasoning=NONE)),
    (ClaudeAdapter, FakeAnthropicClient, ADAPTIVE, {}, dict(max_tokens=4096, temperature="default", reasoning=adaptive("max"))),
    (ClaudeAdapter, FakeAnthropicClient, SWITCH, {}, dict(max_tokens=60, temperature="default", reasoning=NONE)),
    (OpenAIAdapter, FakeOpenAIClient, O_PLAIN, {}, dict(max_tokens=60, temperature=0, reasoning=DEFAULT)),
    (OpenAIAdapter, FakeOpenAIClient, O_REASON, {}, dict(max_tokens=16, temperature="default", reasoning=effort("low"))),
    (OpenAIAdapter, FakeOpenAIClient, O_PLAIN, dict(params={"temperature": 1}), dict(max_tokens=60, temperature=0, reasoning=DEFAULT)),
    (OpenAIAdapter, FakeOpenAIClient, O_PLAIN, dict(params={"temperature": None}), dict(max_tokens=60, temperature=0.5, reasoning=DEFAULT)),
]


@pytest.mark.parametrize("cls,fake,profile,opts,asked", CASES)
def test_t69_effective_is_read_from_the_request_actually_sent(cls, fake, profile, opts, asked):
    # r5: cases rebuilt for profiles and Responses; r4's params cases on token and reasoning fields are now
    # refused (D-A14, tested in T76 and T77), so the changing params here touch temperature only.
    c = fake()
    fn = cls(None, client=c, **opts).kit_callable(profile.model, profile)
    _, usage, _ = fn(PROMPT, **asked)
    read = (claude_outbound if cls is ClaudeAdapter else openai_outbound)(c.calls[-1], profile)
    assert usage["effective"] == read


@pytest.mark.parametrize("cls,fake,profile,opts,asked", [x for x in CASES if x[3].get("params")])
def test_t70_a_changed_outbound_setting_is_reported_and_the_kit_would_refuse_it(cls, fake, profile, opts, asked):
    c = fake()
    fn = cls(None, client=c, **opts).kit_callable(profile.model, profile)
    _, usage, _ = fn(PROMPT, **asked)
    freeze = dict(model=profile.model, **asked)
    assert differ(freeze, usage["effective"]) != []          # truthful report: it does not match what was asked
    assert usage["effective"] != freeze


@pytest.mark.parametrize("cls,fake,profile,bad", [
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, dict(reasoning="high")),
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, dict(reasoning=True)),
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, dict(temperature="warm")),
    (ClaudeAdapter, FakeAnthropicClient, LEGACY, dict(reasoning=1024)),
    (OpenAIAdapter, FakeOpenAIClient, O_REASON, dict(reasoning=1024)),
    (OpenAIAdapter, FakeOpenAIClient, O_REASON, dict(reasoning=effort("extreme"))),
    (OpenAIAdapter, FakeOpenAIClient, O_REASON, dict(max_tokens=0)),
])
def test_t71_a_setting_that_cannot_be_sent_is_refused_before_any_call(cls, fake, profile, bad):
    # r5: values rewritten as named modes; a bare number or string is now refused for both APIs (D-A9).
    c = fake()
    fn = cls(None, client=c).kit_callable(profile.model, profile)
    base = dict(max_tokens=60, temperature="default", reasoning=NONE if cls is ClaudeAdapter else DEFAULT)
    with pytest.raises(ValueError):
        fn(PROMPT, **{**base, **bad})
    assert c.calls == []


@pytest.mark.parametrize("cls,fake,profile,part", [
    (ClaudeAdapter, None, LEGACY, CLAUDE_FREEZE["answer"]),
    (OpenAIAdapter, FakeOpenAIClient, O_PLAIN, OPENAI_FREEZE["answer"])])
def test_t72_served_model_is_kept_apart_from_the_model_sent(cls, fake, profile, part):
    # r5: also for OpenAI (Responses returns the served model in response.model).
    c = ServedClaude() if fake is None else fake()
    if fake is not None:
        orig = c._create
        def dated(**kw):
            r = orig(**kw); r.model = kw["model"] + "-2026-11-01"; return r
        c.responses.create = dated
    fn = cls(None, client=c).kit_callable(profile.model, profile)
    _, usage, _ = call_as_kit(fn, part)
    assert usage["effective"]["model"] == profile.model == c.calls[-1]["model"]
    assert usage["served_model"] not in (None, profile.model) and usage["served_model"].startswith(profile.model)


@pytest.mark.parametrize("cls,sdk,cname,fake,profile,reasoning", [
    (ClaudeAdapter, "anthropic", "Anthropic", FakeAnthropicClient, LEGACY, NONE),
    (OpenAIAdapter, "openai", "OpenAI", FakeOpenAIClient, O_PLAIN, DEFAULT)])
def test_t73_the_kit_callable_loads_its_sdk_only_when_called(cls, sdk, cname, fake, profile, reasoning, monkeypatch):
    client = fake()
    mod = fake_sdk(sdk, cname, client)
    monkeypatch.setitem(__import__("sys").modules, sdk, mod)
    fn = cls(None, sdk_major=2).kit_callable(profile.model, profile)   # r7 setup (D-A27): SDK major pinned
    assert mod.made == []
    fn(PROMPT, max_tokens=16, temperature="default", reasoning=reasoning)
    assert len(mod.made) == 1 and len(client.calls) == 1


def test_t74_the_answer_and_judge_callables_stay_separate():
    c = FakeOpenAIClient()
    a = OpenAIAdapter(None, client=c)
    answer, judge = a.kit_callable(O_PLAIN.model, O_PLAIN), a.kit_callable(O_REASON.model, O_REASON)
    _, ua, _ = answer(PROMPT, max_tokens=60, temperature=0, reasoning=DEFAULT)
    _, uj, _ = judge(PROMPT, max_tokens=16, temperature="default", reasoning=effort("medium"))
    assert (ua["effective"]["model"], uj["effective"]["model"]) == (O_PLAIN.model, O_REASON.model)
    assert [r["model"] for r in c.calls] == [O_PLAIN.model, O_REASON.model]
    assert (ua["effective"]["max_tokens"], uj["effective"]["max_tokens"]) == (60, 16)


def _claude_grid():
    for p in (LEGACY, ADAPTIVE, SWITCH, BOTH):
        reasonings = []
        if "none" in p.modes:
            reasonings += [NONE] + [{"mode": "none", "effort": e} for e in p.none_efforts]
        if "manual" in p.modes:
            reasonings += [manual(1024), manual(2048)]
        if "adaptive" in p.modes:
            reasonings += [adaptive("default")] + [adaptive(e) for e in p.efforts]
        temps = ["default"] + ([0, 0.7, 1] if p.temperature else [])
        for m in (4096, 8192):
            for r in reasonings:
                for t in temps:
                    if t != "default" and r["mode"] != "none" and not p.temperature_with_thinking:
                        continue
                    yield p, dict(max_tokens=m, temperature=t, reasoning=r)


def _openai_grid():
    for p in (O_PLAIN, O_REASON, O_NAMED):
        reasonings = ([DEFAULT] if p.default_allowed else []) + [effort(e) for e in p.efforts]
        temps = ["default"] + ([0, 0.7, 2] if p.temperature else [])
        for m in (16, 60, 4096):
            for r in reasonings:
                for t in temps:
                    yield p, dict(max_tokens=m, temperature=t, reasoning=r)


def profile_deprecated(p):
    return getattr(p, "deprecated", ())


def test_t75_over_a_grid_of_freezes_what_is_sent_and_reported_is_what_was_asked():
    # r5: the grid now runs over the fake profiles' valid configurations (Claude modes and efforts; OpenAI
    # allowlists) instead of fixed value lists; the conflicting-params extension is T77.
    n = 0
    for cls, fake, grid, reader in ((ClaudeAdapter, FakeAnthropicClient, _claude_grid(), claude_outbound),
                                    (OpenAIAdapter, FakeOpenAIClient, _openai_grid(), openai_outbound)):
        for profile, asked in grid:
            c = fake()
            # r6 (D-A17): the deprecated-both profile's manual mode is refused unless the freeze allows it,
            # so the grid's freeze allows each profile's deprecated modes.
            fn = cls(None, client=c).kit_callable(profile.model, profile, allow_deprecated=profile_deprecated(profile))
            _, usage, _ = fn(PROMPT, **asked)
            want = dict(model=profile.model, **asked)
            read = reader(c.calls[-1], profile)
            assert read == want, (profile.model, asked, read)
            assert differ(want, usage["effective"]) == [], (profile.model, asked)
            n += 1
    assert n >= 90    # 99 freezes with the fake profiles
