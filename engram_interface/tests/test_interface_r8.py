"""IF-T123..IF-T132 (revision 8): the OpenAI SDK major pin (D-A32), injected clients and the real comparison-run
readiness check (D-A31), real-run profile requirements (D-A33, D-A34).
Fake SDK modules and clients only. The tests check what the adapter gives to fake SDK constructors and clients and
whether a provider call happened; they do not check HTTP traffic or provider acceptance."""
import sys
import pytest
from engram_interface import (ClaudeAdapter, OpenAIAdapter, check_real_run, RealRunRefused,
                              profile_hash)
from .helpers import FakeAnthropicClient, FakeOpenAIClient, fake_sdk, memory_with_facts, claude_adapter, openai_adapter
from .profiles_fake import LEGACY, O_PLAIN, NONE, DEFAULT, claude_for, openai_for

PROMPT = "Excerpts:\n- Alice: I moved to Leeds.\n\nQuestion: Where does Alice live?\n"
Q = "Where does Alice live?"
SOURCE = "https://platform.example/docs/models (read 2026-11-25)"
# r9 setup (D-A35): real-run sources are provider-specific, so each REAL profile names its provider's documentation.
SOURCES = {"claude": "https://platform.claude.com/docs/en/about-claude/models (read 2026-11-25)",
           "openai": "https://developers.openai.com/api/docs/models (read 2026-11-25)"}
REAL = {"claude": claude_for("claude-real-fake", max_tokens_limit=8192, source=SOURCES["claude"]),
        "openai": openai_for("openai-real-fake", max_tokens_limit=8192, source=SOURCES["openai"])}


def install(monkeypatch, sdk, version="2.0.0"):
    client = FakeAnthropicClient() if sdk == "anthropic" else FakeOpenAIClient()
    mod = fake_sdk(sdk, "Anthropic" if sdk == "anthropic" else "OpenAI", client)
    mod.__version__ = version
    monkeypatch.setitem(sys.modules, sdk, mod)
    return mod, client


def kit(provider, pinned=2, client=None):
    cls, p = (ClaudeAdapter, REAL["claude"]) if provider == "claude" else (OpenAIAdapter, REAL["openai"])
    return cls(None, sdk_major=pinned, client=client).kit_callable(p.model, p)


def ask(fn, provider):
    return fn(PROMPT, max_tokens=60 if provider == "claude" else 16, temperature="default",
              reasoning=NONE if provider == "claude" else DEFAULT)


# ---- D-A32: the OpenAI SDK major is pinned per callable, as Anthropic's is (D-A27) ----
@pytest.mark.parametrize("installed,pinned,ok", [("2.0.0", 2, True), ("2.31.4", 2, True), ("1.99.0", 2, False),
                                                  ("3.0.0", 2, False), ("2.0.0", None, False), (None, 2, False),
                                                  ("dev", 2, False), ("", 2, False)])
def test_t123_the_openai_sdk_major_is_pinned_and_refused_before_any_client(installed, pinned, ok, monkeypatch):
    mod, client = install(monkeypatch, "openai", installed)
    fn = OpenAIAdapter(None, sdk_major=pinned).kit_callable(O_PLAIN.model, O_PLAIN)
    m, _ = memory_with_facts()
    a = openai_adapter(m, sdk_major=pinned)
    if ok:
        _, usage, _ = ask(fn, "openai")
        assert usage["sdk_version"] == installed
        assert a.answer(Q, 500).sdk_version == installed
    else:
        with pytest.raises(ValueError):
            ask(fn, "openai")
        with pytest.raises(ValueError):
            a.answer(Q, 500)
        assert mod.made == [] and client.calls == []


@pytest.mark.parametrize("provider,sdk", [("claude", "anthropic"), ("openai", "openai")])
def test_t124_the_exact_sdk_version_is_recorded_on_every_call(provider, sdk, monkeypatch):
    mod, client = install(monkeypatch, sdk, "2.4.1")
    fn = kit(provider)
    versions = [ask(fn, provider)[1]["sdk_version"] for _ in range(3)]
    m, _ = memory_with_facts()
    make = claude_adapter if provider == "claude" else openai_adapter
    a = make(m)
    versions += [a.answer(Q, 500).sdk_version for _ in range(2)]
    assert versions == ["2.4.1"] * 5 and len(client.calls) == 5


# ---- D-A31: injected clients work in tests and are refused by the real-run check ----
@pytest.mark.parametrize("provider", ["claude", "openai"])
def test_t125_an_injected_client_works_in_a_test_run_but_not_in_a_real_run(provider, monkeypatch):
    mod, _ = install(monkeypatch, "anthropic" if provider == "claude" else "openai")
    injected = FakeAnthropicClient() if provider == "claude" else FakeOpenAIClient()
    fn = kit(provider, client=injected)
    _, usage, _ = ask(fn, provider)
    assert usage["sdk_version"] is None and len(injected.calls) == 1        # honest: no SDK was loaded
    with pytest.raises(RealRunRefused):
        check_real_run(fn)
    m, _ = memory_with_facts()
    make = claude_adapter if provider == "claude" else openai_adapter
    a = make(m, client=injected, model=REAL[provider].model, profile=REAL[provider])
    assert a.answer(Q, 500).sdk_version is None
    with pytest.raises(RealRunRefused):
        check_real_run(a)
    assert len(injected.calls) == 2 and mod.made == []


@pytest.mark.parametrize("provider,sdk", [("claude", "anthropic"), ("openai", "openai")])
def test_t126_a_ready_callable_passes_without_any_client_or_provider_call(provider, sdk, monkeypatch):
    mod, client = install(monkeypatch, sdk, "2.0.3")
    fn = kit(provider)
    record = check_real_run(fn)
    assert record["sdk_version"] == "2.0.3" and record["sdk_major"] == 2 and record["provider"] == sdk
    assert record["profile_hash"] == profile_hash(REAL[provider]) and record["model"] == REAL[provider].model
    assert mod.made == [] and client.calls == []                             # no client made, nothing sent
    ask(fn, provider)
    assert len(mod.made) == 1 and len(client.calls) == 1                     # the run then proceeds


@pytest.mark.parametrize("provider,sdk", [("claude", "anthropic"), ("openai", "openai")])
@pytest.mark.parametrize("installed,pinned", [("3.0.0", 2), ("x.y", 2), (None, 2), ("2.0.0", None)])
def test_t127_the_real_run_check_applies_the_pin_before_any_call(provider, sdk, installed, pinned, monkeypatch):
    mod, client = install(monkeypatch, sdk, installed)
    with pytest.raises(ValueError):
        check_real_run(kit(provider, pinned=pinned))
    assert mod.made == [] and client.calls == []


# ---- D-A33, D-A34: real-run profiles ----
@pytest.mark.parametrize("provider,sdk", [("claude", "anthropic"), ("openai", "openai")])
def test_t128_a_real_run_profile_must_state_max_tokens_limit(provider, sdk, monkeypatch):
    mod, client = install(monkeypatch, sdk)
    p = (claude_for if provider == "claude" else openai_for)("m", source=SOURCE)          # max_tokens_limit None
    cls = ClaudeAdapter if provider == "claude" else OpenAIAdapter
    fn = cls(None, sdk_major=2).kit_callable("m", p)
    with pytest.raises(RealRunRefused, match="max_tokens_limit"):
        check_real_run(fn)
    assert mod.made == [] and client.calls == []
    ask(fn, provider)                                    # a generic profile without a ceiling still works in tests
    assert len(client.calls) == 1


GOOD = ["https://platform.claude.com/docs/en/build-with-claude/thinking 2026-11-25",
        "Read 2026-11-25 at https://developers.openai.com/api/docs/guides/reasoning",
        "https://a.example/x, https://b.example/y; read 2024-02-29"]
BAD = ["", "   ", "fake", "https://platform.claude.com/docs (no date)", "read 2026-11-25, no link",
       "http://platform.claude.com/docs 2026-11-25", "https://localhost 2026-11-25",
       "https://platform.claude.com/docs 2026-02-30", "https://platform.claude.com/docs 2026-11-25x1",
       "https://platform.claude.com/docs 20261125", "https://platform.claude.com/docs 12026-11-25",
       "https://localhost/docs.html 2026-11-25", "https://.example.com 2026-11-25"]


@pytest.mark.parametrize("provider,sdk", [("claude", "anthropic"), ("openai", "openai")])
@pytest.mark.parametrize("source", BAD)
def test_t131_a_real_run_profile_needs_a_documentation_source_and_test_profiles_do_not(provider, sdk, source, monkeypatch):
    mod, client = install(monkeypatch, sdk)
    p = (claude_for if provider == "claude" else openai_for)("m", source=source, max_tokens_limit=8192)
    cls = ClaudeAdapter if provider == "claude" else OpenAIAdapter
    fn = cls(None, sdk_major=2).kit_callable("m", p)
    with pytest.raises(RealRunRefused, match="source"):
        check_real_run(fn)
    assert mod.made == [] and client.calls == []
    ask(fn, provider)                                    # the same profile is fine for a test run
    assert len(client.calls) == 1


@pytest.mark.parametrize("provider,sdk", [("claude", "anthropic"), ("openai", "openai")])
def test_t132_the_check_works_on_an_answer_adapter_and_needs_its_profile(provider, sdk, monkeypatch):
    mod, client = install(monkeypatch, sdk)
    m, _ = memory_with_facts()
    make = claude_adapter if provider == "claude" else openai_adapter
    a = make(m, model=REAL[provider].model, profile=REAL[provider])
    assert check_real_run(a)["profile_hash"] == profile_hash(REAL[provider])
    assert mod.made == [] and client.calls == []
    with pytest.raises(ValueError):
        check_real_run(make(m, model=REAL[provider].model, profile=None))
    a.answer(Q, 500)
    assert len(client.calls) == 1
