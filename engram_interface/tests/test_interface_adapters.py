"""IF-T30..IF-T42: rendering and the Claude and OpenAI adapters, with fake clients only."""
import sys
import pytest
from engram_interface import ClaudeAdapter, OpenAIAdapter, StubMemory, render_context, E_NO_MEMORY
from .helpers import memory_with_facts, FakeAnthropicClient, FakeOpenAIClient, fake_sdk
from .helpers import claude_adapter, openai_adapter, make

Q = "Where does Alice live?"


def test_t30_rendered_block_is_labelled_and_dated():
    m, _ = memory_with_facts()
    text = render_context(m.retrieve("Alice Leeds sister June", 500).context)
    for label in ("Validated facts:", "Original excerpts:", "Uncertain:", "Profile:"):
        assert label in text
    assert "2026-04-10" in text and "2026-05-02" in text
    assert '"I moved to Leeds last spring."' in text and "Alice was not sure" in text
    lines = text.splitlines()
    assert "(2026-04-10)" in next(l for l in lines if l.startswith("- [f1]"))
    assert "(2026-05-02)" in next(l for l in lines if l.startswith("- [f2]"))


def test_t31_empty_block_states_the_reason_and_nothing_else():
    text = render_context(StubMemory().retrieve(Q, 500).context)
    assert E_NO_MEMORY in text and "Validated facts" not in text


def test_t32_assistant_excerpt_is_labelled_as_the_assistants():
    m, _ = memory_with_facts()
    text = render_context(m.retrieve("Bristol", 500).context)
    assert "Assistant (assistant)" in text and "Validated facts:\n- none" in text


def test_t33_claude_request_puts_memory_in_system():
    m, _ = memory_with_facts()
    a = claude_adapter(m, model="model-under-test", client=FakeAnthropicClient(), max_tokens=200)
    req = a.request(m.retrieve(Q, 500).context, Q)
    assert "Validated facts:" in req["system"] and "lives in Leeds" in req["system"]
    assert req["messages"] == [{"role": "user", "content": Q}]
    assert req["model"] == "model-under-test" and req["max_tokens"] == 200


def test_t34_claude_answer_uses_the_client_once_and_returns_trace():
    m, _ = memory_with_facts()
    c = FakeAnthropicClient("Alice lives in Leeds.")
    r = claude_adapter(m, model="model-under-test", client=c).answer(Q, 500)
    assert len(c.calls) == 1 and c.calls[0] == r.request
    assert r.text == "Alice lives in Leeds." and r.trace.trace_id == r.context.trace_id
    assert r.usage.output_tokens == 2


def test_t35_openai_request_puts_memory_in_instructions():
    # r5 (D-A12, Responses API): was "system not in req; messages are system then user; memory in messages[0]".
    m, _ = memory_with_facts()
    a = openai_adapter(m, model="model-under-test", client=FakeOpenAIClient())
    req = a.request(m.retrieve(Q, 500).context, Q)
    assert "system" not in req and "messages" not in req
    assert "lives in Leeds" in req["instructions"] and req["input"] == Q


def test_t36_openai_answer_parses_the_first_choice():
    m, _ = memory_with_facts()
    c = FakeOpenAIClient("Leeds.")
    r = openai_adapter(m, model="model-under-test", client=c).answer(Q, 500)
    assert len(c.calls) == 1 and r.text == "Leeds." and r.context.facts[0].fact_id == "f1"


@pytest.mark.parametrize("cls,fake", [(ClaudeAdapter, FakeAnthropicClient), (OpenAIAdapter, FakeOpenAIClient)])
def test_t37_no_model_means_no_call(cls, fake):
    m, _ = memory_with_facts()
    c = fake()
    with pytest.raises(ValueError):
        make(cls, m, model=None, client=c).answer(Q, 500)   # r6: helper adds a profile when a model is named
    assert c.calls == []


@pytest.mark.parametrize("cls,sdk", [(ClaudeAdapter, "anthropic"), (OpenAIAdapter, "openai")])
def test_t38_missing_sdk_gives_a_clear_error_only_when_used(cls, sdk, monkeypatch):
    monkeypatch.setitem(sys.modules, sdk, None)        # makes `import sdk` fail
    m, _ = memory_with_facts()
    a = make(cls, m, model="model-under-test")               # construction must not import
    with pytest.raises(ImportError, match=sdk):
        a.answer(Q, 500)


@pytest.mark.parametrize("cls,sdk,cname,fake", [(ClaudeAdapter, "anthropic", "Anthropic", FakeAnthropicClient),
                                                (OpenAIAdapter, "openai", "OpenAI", FakeOpenAIClient)])
def test_t39_sdk_client_is_made_lazily_and_once(cls, sdk, cname, fake, monkeypatch):
    client = fake()
    mod = fake_sdk(sdk, cname, client)
    monkeypatch.setitem(sys.modules, sdk, mod)
    m, _ = memory_with_facts()
    a = make(cls, m, model="model-under-test")
    assert mod.made == []
    a.answer(Q, 500); a.answer(Q, 500)
    assert len(mod.made) == 1 and len(client.calls) == 2


def test_t40_both_adapters_give_the_model_the_same_memory():
    m, _ = memory_with_facts()
    ctx = m.retrieve(Q, 500).context
    c = claude_adapter(m, model="x").request(ctx, Q)["system"]
    o = openai_adapter(m, model="x").request(ctx, Q)["instructions"]   # r5 (D-A12): was ["messages"][0]["content"]
    assert c == o and render_context(ctx) in c


def test_t41_adapter_does_not_store_the_question_or_answer():
    m, _ = memory_with_facts()
    before = len(m._excerpts)
    claude_adapter(m, model="x", client=FakeAnthropicClient()).answer(Q, 500)
    openai_adapter(m, model="x", client=FakeOpenAIClient()).answer(Q, 500)
    assert len(m._excerpts) == before


def test_t42_empty_memory_still_reaches_the_model_with_the_reason():
    c = FakeAnthropicClient("I have no memory of that.")
    r = claude_adapter(StubMemory(), model="x", client=c).answer(Q, 500)
    assert E_NO_MEMORY in c.calls[0]["system"] and r.context.is_empty
