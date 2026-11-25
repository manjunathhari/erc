"""IF-T76..IF-T92 (revision 5): protected request fields (D-A14), Claude model profiles and reasoning modes
(D-A8, D-A9), OpenAI effort allowlists and the Responses API (D-A11, D-A12), and the budget-exclusion notice
(D-A13). The adapter tests check the arguments passed to the SDK client, not the serialised HTTP body or the
provider's acceptance."""
import re
import types
import pytest
from engram_interface import ClaudeAdapter, OpenAIAdapter, ClaudeProfile, OpenAIProfile, StubMemory, Turn, Fact, ModelContext, render_context
from engram_interface.render import NOTICE, count_tokens
from .helpers import FakeAnthropicClient, FakeOpenAIClient, memory_with_facts
from .helpers import claude_adapter, openai_adapter, make
from .profiles_fake import (LEGACY, ADAPTIVE, SWITCH, BOTH, O_PLAIN, O_REASON, O_NAMED, NONE, DEFAULT,
                            adaptive, manual, effort, claude_outbound, openai_outbound)

PROMPT = "Excerpts:\n- Alice: I moved to Leeds.\n\nQuestion: Where does Alice live?\n"
CLAUDE_PROTECTED = ("model", "messages", "system", "thinking", "output_config",
                    "max_tokens", "max_output_tokens", "max_completion_tokens")
OPENAI_PROTECTED = ("model", "input", "instructions", "messages", "reasoning", "reasoning_effort",
                    "max_output_tokens", "max_tokens", "max_completion_tokens")


def kit(cls, profile, **opts):
    c = (FakeAnthropicClient if cls is ClaudeAdapter else FakeOpenAIClient)()
    return cls(None, client=c, **opts).kit_callable(profile.model, profile), c


# ---- D-A14: controlled request fields ----
@pytest.mark.parametrize("cls,key", [(ClaudeAdapter, k) for k in CLAUDE_PROTECTED] + [(OpenAIAdapter, k) for k in OPENAI_PROTECTED])
@pytest.mark.parametrize("value", ["x", 99, None])
def test_t76_params_may_not_set_or_remove_a_controlled_field(cls, key, value):
    c = (FakeAnthropicClient if cls is ClaudeAdapter else FakeOpenAIClient)()
    with pytest.raises(ValueError):
        cls(None, client=c, params={key: value})
    assert c.calls == []


def test_t77_grid_of_params_conflicting_ones_refused_others_checked_against_the_allowlist():
    # r6 (D-A20) revised: r5 asserted that any non-controlled key (temperature, metadata, top_k) was sent and
    # reported. Now only keys in the profile's allowlist, within their constraints, are sent; anything unlisted or
    # outside its constraint is refused before the call. Controlled keys are still refused at construction.
    cases = (
        (ClaudeAdapter, LEGACY, CLAUDE_PROTECTED, claude_outbound, dict(max_tokens=60, temperature=0, reasoning=NONE),
         {"top_k": (40, 0, 501, "40")}, {"metadata": ({"user_id": "u"}, "x")}, ("top_p", "service_tier")),
        (OpenAIAdapter, O_PLAIN, OPENAI_PROTECTED, openai_outbound, dict(max_tokens=60, temperature=0, reasoning=DEFAULT),
         {"top_p": (0.5, -0.1, 1.5, "0.5")}, {"metadata": ({"run": "r"}, 3)}, ("top_k", "service_tier")))
    for cls, profile, protected, reader, base, ranged, typed, unlisted in cases:
        fake = FakeAnthropicClient if cls is ClaudeAdapter else FakeOpenAIClient
        for key in protected:
            for value in (99, None):
                with pytest.raises(ValueError):
                    cls(None, client=fake(), params={key: value})
        for key, values in {**ranged, **typed}.items():
            good, *bad = values
            fn, c = kit(cls, profile, params={key: good})
            _, usage, _ = fn(PROMPT, **base)
            assert c.calls[-1][key] == good and usage["effective"] == reader(c.calls[-1], profile)
            for v in bad:
                fn, c = kit(cls, profile, params={key: v})
                with pytest.raises(ValueError):
                    fn(PROMPT, **base)
                assert c.calls == [], (key, v)
            fn, c = kit(cls, profile, params={key: None})      # removing a listed key is allowed
            fn(PROMPT, **base)
            assert key not in c.calls[-1]
        for key in unlisted:
            fn, c = kit(cls, profile, params={key: 1})
            with pytest.raises(ValueError):
                fn(PROMPT, **base)
            assert c.calls == [], key
        fn, c = kit(cls, profile, params={"temperature": 1})       # temperature: checked by the temperature rule
        _, usage, _ = fn(PROMPT, **base)
        assert c.calls[-1]["temperature"] == 1 and usage["effective"]["temperature"] == 1


# ---- D-A8, D-A9: Claude profiles ----
def test_t78_legacy_only_model():
    fn, c = kit(ClaudeAdapter, LEGACY)
    for bad in (dict(reasoning=adaptive("high")), dict(reasoning=manual(1023)), dict(reasoning=manual(4096)),
                dict(reasoning=manual(2048), temperature=0.5), dict(reasoning={"mode": "manual", "budget_tokens": 2048, "effort": "low"})):
        with pytest.raises(ValueError):
            fn(PROMPT, **{**dict(max_tokens=4096, temperature="default", reasoning=NONE), **bad})
    assert c.calls == []
    fn(PROMPT, max_tokens=4096, temperature="default", reasoning=manual(2048))
    assert c.calls[-1]["thinking"] == {"type": "enabled", "budget_tokens": 2048} and "output_config" not in c.calls[-1]
    fn(PROMPT, max_tokens=60, temperature=0.5, reasoning=NONE)
    assert "thinking" not in c.calls[-1] and c.calls[-1]["temperature"] == 0.5


def test_t79_adaptive_only_model():
    fn, c = kit(ClaudeAdapter, ADAPTIVE)
    for bad in (dict(reasoning=NONE), dict(reasoning=manual(2048)), dict(reasoning=adaptive("extreme")),
                dict(reasoning=adaptive("high"), temperature=0), dict(reasoning=adaptive("high"), temperature=1),
                dict(reasoning={"mode": "adaptive"})):
        with pytest.raises(ValueError):
            fn(PROMPT, **{**dict(max_tokens=4096, temperature="default", reasoning=adaptive("high")), **bad})
    assert c.calls == []
    _, usage, _ = fn(PROMPT, max_tokens=4096, temperature="default", reasoning=adaptive("xhigh"))
    req = c.calls[-1]
    assert req["thinking"] == {"type": "adaptive"} and req["output_config"] == {"effort": "xhigh"}
    assert "effort" not in req["thinking"] and "temperature" not in req
    assert usage["effective"]["reasoning"] == adaptive("xhigh")
    _, usage, _ = fn(PROMPT, max_tokens=4096, temperature="default", reasoning=adaptive("default"))
    assert "output_config" not in c.calls[-1] and usage["effective"]["reasoning"] == adaptive("default")


def test_t80_adaptive_by_default_with_an_off_switch():
    fn, c = kit(ClaudeAdapter, SWITCH)
    _, usage, _ = fn(PROMPT, max_tokens=60, temperature="default", reasoning=NONE)
    assert c.calls[-1]["thinking"] == {"type": "between_tools"} and usage["effective"]["reasoning"] == NONE
    _, usage, _ = fn(PROMPT, max_tokens=60, temperature="default", reasoning={"mode": "none", "effort": "high"})
    assert c.calls[-1]["output_config"] == {"effort": "high"}
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=60, temperature="default", reasoning={"mode": "none", "effort": "xhigh"})
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=4096, temperature="default", reasoning=manual(2048))
    assert len(c.calls) == 2


def test_t81_deprecated_mode_refused_unless_the_freeze_allows_it_then_sent_with_a_warning():
    # r6 (D-A17) revised: r5 sent the deprecated mode with a warning by default. Now it is refused unless the freeze
    # explicitly allows that mode; when allowed it is sent, reported truthfully and the warning recorded.
    fn, c = kit(ClaudeAdapter, BOTH)
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=4096, temperature="default", reasoning=manual(1024))
    assert c.calls == []
    c = FakeAnthropicClient()
    fn = ClaudeAdapter(None, client=c).kit_callable(BOTH.model, BOTH, allow_deprecated=("manual",))
    _, usage, _ = fn(PROMPT, max_tokens=4096, temperature="default", reasoning=manual(1024))
    assert usage["warnings"] and "deprecated" in usage["warnings"][0] and "allowed by the freeze" in usage["warnings"][0]
    assert usage["effective"]["reasoning"] == manual(1024)
    _, usage, _ = fn(PROMPT, max_tokens=4096, temperature="default", reasoning=adaptive("max"))
    assert usage["warnings"] == [] and c.calls[-1]["thinking"] == {"type": "adaptive"}
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=4096, temperature="default", reasoning=adaptive("xhigh"))   # not in this model's list


def test_t82_absent_thinking_is_read_as_the_profile_says_and_none_is_never_sent_by_omission_on_adaptive_models():
    req = {"model": "m", "max_tokens": 10, "messages": []}
    assert claude_outbound(req, LEGACY)["reasoning"] == NONE
    assert ClaudeAdapter(None).effective(req, LEGACY)["reasoning"] == NONE
    assert ClaudeAdapter(None).effective(req, ADAPTIVE)["reasoning"] == adaptive("default")
    with pytest.raises(ValueError):
        ClaudeProfile("m", modes=("none", "adaptive"), omitted_means="adaptive", none_sends="omit")
    for p in (SWITCH,):
        fn, c = kit(ClaudeAdapter, p)
        fn(PROMPT, max_tokens=60, temperature="default", reasoning=NONE)
        assert "thinking" in c.calls[-1]


def test_t83_the_profile_must_match_the_model_and_the_api():
    with pytest.raises(ValueError):
        ClaudeAdapter(None, client=FakeAnthropicClient()).kit_callable("another-model", LEGACY)
    with pytest.raises(ValueError):
        ClaudeAdapter(None, client=FakeAnthropicClient()).kit_callable(O_PLAIN.model, O_PLAIN)
    with pytest.raises(ValueError):
        OpenAIAdapter(None, client=FakeOpenAIClient()).kit_callable(LEGACY.model, LEGACY)


@pytest.mark.parametrize("cls,profile,base", [
    (ClaudeAdapter, ADAPTIVE, dict(max_tokens=4096, temperature="default", reasoning=adaptive("high"))),
    (ClaudeAdapter, LEGACY, dict(max_tokens=4096, temperature="default", reasoning=manual(1024))),
    (OpenAIAdapter, O_REASON, dict(max_tokens=60, temperature="default", reasoning=effort("low")))])
def test_t84_a_params_temperature_is_checked_against_the_profile_before_the_call(cls, profile, base):
    fn, c = kit(cls, profile, params={"temperature": 0.3})
    with pytest.raises(ValueError):
        fn(PROMPT, **base)
    assert c.calls == []


# ---- D-A11, D-A12: OpenAI ----
def test_t85_openai_effort_allowlist_is_the_models():
    for profile in (O_PLAIN, O_REASON, O_NAMED):
        fn, c = kit(OpenAIAdapter, profile)
        for e in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
            if e in profile.efforts:
                fn(PROMPT, max_tokens=60, temperature="default", reasoning=effort(e))
                assert c.calls[-1]["reasoning"] == {"effort": e} and "reasoning_effort" not in c.calls[-1]
            else:
                n = len(c.calls)
                with pytest.raises(ValueError):
                    fn(PROMPT, max_tokens=60, temperature="default", reasoning=effort(e))
                assert len(c.calls) == n
    fn, c = kit(OpenAIAdapter, O_NAMED)
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=60, temperature="default", reasoning=DEFAULT)
    assert c.calls == []


def test_t86_openai_output_limit_has_the_models_minimum():
    fn, c = kit(OpenAIAdapter, O_PLAIN)
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=15, temperature="default", reasoning=DEFAULT)
    assert c.calls == []
    fn(PROMPT, max_tokens=16, temperature="default", reasoning=DEFAULT)
    assert c.calls[-1]["max_output_tokens"] == 16
    p = OpenAIProfile("openai-big-min-fake", min_output_tokens=64)
    fn, c = kit(OpenAIAdapter, p)
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=63, temperature="default", reasoning=DEFAULT)


def test_t87_responses_request_and_response_shapes():
    fn, c = kit(OpenAIAdapter, O_REASON)
    text, usage, _ = fn(PROMPT, max_tokens=60, temperature="default", reasoning=effort("high"))
    req = c.calls[-1]
    assert set(req) == {"model", "input", "max_output_tokens", "reasoning"}
    assert req["input"] == PROMPT and text == "Leeds."
    assert (usage["prompt_tokens"], usage["completion_tokens"]) == (10, 2) and usage["served_model"] == O_REASON.model
    # Without the SDK's output_text convenience, the text is read from output[].content[] of type output_text.
    part = types.SimpleNamespace(type="output_text", text="From output.")
    resp = types.SimpleNamespace(output=[types.SimpleNamespace(type="message", content=[part])], usage=None, model="m")
    assert OpenAIAdapter(None)._parse(resp)[0] == "From output."
    # The memory-backed answer() path uses the same API: instructions and input, no messages.
    m, _ = memory_with_facts()
    c2 = FakeOpenAIClient()
    openai_adapter(m, model="x", client=c2).answer("Where does Alice live?", 500)
    # r6 (D-A22, D-A16): "temperature" removed from the expected keys; the answer path no longer sends a default
    # temperature of 0.0, only a temperature the freeze sets and the profile allows.
    assert set(c2.calls[-1]) == {"model", "instructions", "input", "max_output_tokens"}


# ---- D-A13: the budget-exclusion notice ----
QUESTIONS = ("Where does Alice live?", "Alice Leeds sister June Bristol", "Is Alice's sister visiting in June?",
             "Bristol", "favourite colour?")


def sweep(m):
    for q in QUESTIONS:
        for b in range(5, 260, 2):
            yield q, b, m.retrieve(q, b)


def test_t88_notice_present_if_and_only_if_facts_were_left_out():
    m, _ = memory_with_facts()
    seen = {True: 0, False: 0}
    for q, b, r in sweep(m):
        text = render_context(r.context)
        # r6 (D-A18): was "== bool(excluded_facts)"; the notice now covers standalone excerpts left out too.
        assert (NOTICE in text) == bool(r.context.excluded_facts or r.context.omitted_excerpts), (q, b)
        assert text.count(NOTICE) <= 1
        if NOTICE in text:
            assert text.splitlines()[-1] == NOTICE, (q, b)      # exactly the notice, as its own last line
        seen[bool(r.context.excluded_facts or r.context.omitted_excerpts)] += 1
    assert seen[True] and seen[False]
    assert NOTICE == ("Some matching memories were omitted to fit the memory budget. The supplied evidence may "
                      "therefore be incomplete; do not infer the omitted content.")


def test_t89_with_the_notice_the_block_stays_within_budget():
    m, _ = memory_with_facts()
    for q, b, r in sweep(m):
        c = r.context
        if not c.is_empty:
            assert c.tokens == count_tokens(render_context(c)) <= b, (q, b)


def test_t90_space_for_the_notice_is_reserved_before_facts_are_chosen():
    m, _ = memory_with_facts()
    proofs = 0
    for q, b, r in sweep(m):
        c = r.context
        if c.is_empty or not c.excluded_facts:
            continue
        for fid in c.excluded_facts:
            f = m._facts[fid]
            srcs = tuple(m._excerpts[s] for s in f.sources if s not in {e.excerpt_id for e in c.excerpts})
            more = ModelContext(c.trace_id, c.question, c.facts + ((f,) if f.status == "validated" else ()),
                                c.excerpts + srcs, c.uncertain + (() if f.status == "validated" else (f,)), c.profile, 0, b)
            without = count_tokens(render_context(more, notice=False))
            withn = count_tokens(render_context(more, notice=True))
            if without <= b < withn:
                proofs += 1          # it would have fitted without the reserved notice, and it was left out
    assert proofs, "no case reached where the reservation decided the outcome"


def test_t91_the_notice_never_discloses_what_was_left_out():
    m, (e1, e2, e3) = memory_with_facts()
    for q, b, r in sweep(m):
        c = r.context
        text = render_context(c)
        given = {e.excerpt_id for e in c.excerpts}
        for fid in c.excluded_facts:
            f = m._facts[fid]
            assert f.statement not in text and not re.search(rf"\b{fid}\b", text), (q, b, fid)
            for s in f.sources:
                if s not in given:
                    assert m._excerpts[s].text not in text, (q, b, s)
    for word in ("f1", "f2", "Leeds", "sister", "Alice"):
        assert word not in NOTICE


def test_t92_the_adapters_pass_the_notice_to_the_model_unchanged():
    m, _ = memory_with_facts()
    hit = next(r for b in range(5, 260) for r in [m.retrieve("Alice Leeds sister June", b)]
               if r.context.excluded_facts and not r.context.is_empty)
    ca = claude_adapter(m, model="x").request(hit.context, "q")["system"]
    oa = openai_adapter(m, model="x").request(hit.context, "q")["instructions"]
    assert NOTICE in ca and ca == oa
