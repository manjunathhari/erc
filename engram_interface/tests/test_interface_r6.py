"""IF-T93..IF-T105 (revision 6): API version pinned (D-A16), temperature prohibition incl. answer() (D-A16, D-A22),
deprecated modes only when the freeze allows them (D-A17), the budget notice for any omitted evidence (D-A18),
fail-closed empty results (D-A19), extras allowlist (D-A20), one preflight for answer() and kit_callable() (D-A21),
manual budget with effort refused (D-A23).
The adapter tests check the arguments passed to the SDK client and the arguments its constructor receives. They do
not check the HTTP headers the SDK finally sends, nor whether the provider accepts them."""
import sys
import pytest
from engram_interface import (ClaudeAdapter, OpenAIAdapter, ClaudeProfile, OpenAIProfile, StubMemory, Turn, Fact,
                              BudgetClosed, render_context, E_BUDGET, E_NO_MATCH, E_NO_MEMORY)
from engram_interface.render import NOTICE, count_tokens
from .helpers import FakeAnthropicClient, FakeOpenAIClient, fake_sdk, memory_with_facts, claude_adapter, openai_adapter
from .profiles_fake import (LEGACY, ADAPTIVE, SWITCH, BOTH, O_PLAIN, O_REASON, NONE, DEFAULT, OLD_VERSION, NEW_VERSION,
                            adaptive, manual, effort, claude_for, openai_for)

PROMPT = "Excerpts:\n- Alice: I moved to Leeds.\n\nQuestion: Where does Alice live?\n"
Q = "Where does Alice live?"


# ---- D-A16: the API version is fixed in the freeze and used by the adapter ----
def test_t93_a_claude_profile_pins_its_api_version_and_follows_its_rules():
    with pytest.raises(ValueError):
        ClaudeProfile("m", modes=("none",), omitted_means="none", none_sends="omit")             # no version
    with pytest.raises(ValueError):
        claude_for("m", api_version=NEW_VERSION, extras=())         # 2026-10-21 removes temperature: (0, 1) refused
    with pytest.raises(ValueError):
        claude_for("m", api_version=NEW_VERSION, temperature=None)  # ... and top_k as an allowed extra
    p = claude_for("m", api_version=NEW_VERSION, temperature=None, extras=(("metadata", "dict"),))
    assert p.api_version == NEW_VERSION and p.temperature is None


@pytest.mark.parametrize("profile,reasoning", [(LEGACY, NONE), (ADAPTIVE, adaptive("high")), (SWITCH, NONE)])
def test_t94_every_claude_request_carries_the_frozen_version(profile, reasoning):
    c = FakeAnthropicClient()
    fn = ClaudeAdapter(None, client=c).kit_callable(profile.model, profile)
    _, usage, _ = fn(PROMPT, max_tokens=4096, temperature="default", reasoning=reasoning)
    assert c.calls[-1]["extra_headers"] == {"anthropic-version": profile.api_version}
    assert usage["api_version"] == c.calls[-1]["extra_headers"]["anthropic-version"] == profile.api_version
    o = FakeOpenAIClient()
    _, ou, _ = OpenAIAdapter(None, client=o).kit_callable(O_PLAIN.model, O_PLAIN)(PROMPT, max_tokens=16,
                                                                                  temperature="default", reasoning=DEFAULT)
    assert "extra_headers" not in o.calls[-1] and ou["api_version"] is None


def test_t95_the_sdk_client_is_configured_with_the_frozen_version_not_its_default(monkeypatch):
    client = FakeAnthropicClient()
    mod = fake_sdk("anthropic", "Anthropic", client)
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    a = ClaudeAdapter(None, sdk_major=2)          # r7 setup (D-A27): SDK major pinned
    a.kit_callable(LEGACY.model, LEGACY)(PROMPT, max_tokens=60, temperature="default", reasoning=NONE)
    a.kit_callable(ADAPTIVE.model, ADAPTIVE)(PROMPT, max_tokens=60, temperature="default", reasoning=adaptive("low"))
    a.kit_callable(LEGACY.model, LEGACY)(PROMPT, max_tokens=60, temperature="default", reasoning=NONE)
    assert [kw for _, kw in mod.made] == [{"default_headers": {"anthropic-version": OLD_VERSION}},
                                         {"default_headers": {"anthropic-version": NEW_VERSION}}]
    m, _ = memory_with_facts()
    mod.made.clear()
    claude_adapter(m, profile=claude_for("model-under-test")).answer(Q, 500)
    assert mod.made == [((), {"default_headers": {"anthropic-version": OLD_VERSION}})]
    assert client.calls[-1]["extra_headers"] == {"anthropic-version": OLD_VERSION}


# ---- D-A16, D-A22: temperature prohibited where the profile or version says so, on answer() too ----
def test_t96_no_temperature_is_sent_where_prohibited_on_either_path():
    new = claude_for("model-under-test", api_version=NEW_VERSION, temperature=None, extras=())
    m, _ = memory_with_facts()
    c = FakeAnthropicClient()
    r = claude_adapter(m, client=c, profile=new).answer(Q, 500)      # default: no temperature sent
    assert "temperature" not in c.calls[-1] and r.api_version == NEW_VERSION
    c = FakeAnthropicClient()
    with pytest.raises(ValueError):
        claude_adapter(m, client=c, profile=new, temperature=0.0).answer(Q, 500)
    assert c.calls == []
    o = FakeOpenAIClient()
    with pytest.raises(ValueError):
        openai_adapter(m, client=o, profile=openai_for("model-under-test", temperature=None), temperature=0.0).answer(Q, 500)
    assert o.calls == []
    openai_adapter(m, client=o, profile=openai_for("model-under-test", temperature=None)).answer(Q, 500)
    assert "temperature" not in o.calls[-1]
    fn = ClaudeAdapter(None, client=FakeAnthropicClient()).kit_callable(ADAPTIVE.model, ADAPTIVE)
    with pytest.raises(ValueError):
        fn(PROMPT, max_tokens=60, temperature=0, reasoning=adaptive("low"))


# ---- D-A21: answer() needs a profile and runs the same preflight ----
@pytest.mark.parametrize("cls,make", [(ClaudeAdapter, claude_adapter), (OpenAIAdapter, openai_adapter)])
def test_t97_answer_runs_the_kit_preflight_before_contacting_the_sdk(cls, make):
    m, _ = memory_with_facts()
    fake = FakeAnthropicClient if cls is ClaudeAdapter else FakeOpenAIClient
    other = openai_for("model-under-test") if cls is ClaudeAdapter else claude_for("model-under-test")
    bad = [dict(profile=None), dict(profile=other),
           dict(profile=(claude_for if cls is ClaudeAdapter else openai_for)("another-model")),
           dict(reasoning={"mode": "adaptive", "effort": "high"} if cls is ClaudeAdapter else effort("high")),
           dict(reasoning="none"), dict(params={"top_k_unlisted": 1}), dict(max_tokens=0)]
    if cls is OpenAIAdapter:
        bad.append(dict(max_tokens=15))
    for kw in bad:
        c = fake()
        with pytest.raises(ValueError):
            make(m, client=c, **kw).answer(Q, 500)
        assert c.calls == [], kw
    c = fake()
    make(m, client=c).answer(Q, 500)
    assert len(c.calls) == 1


def test_t98_answer_refuses_a_deprecated_mode_unless_allowed_then_records_the_warning():
    m, _ = memory_with_facts()
    both = claude_for("model-under-test", modes=("none", "manual", "adaptive"), efforts=("low",), deprecated=("manual",))
    c = FakeAnthropicClient()
    with pytest.raises(ValueError):
        claude_adapter(m, client=c, profile=both, reasoning=manual(1024), max_tokens=4096).answer(Q, 500)
    assert c.calls == []
    r = claude_adapter(m, client=c, profile=both, reasoning=manual(1024), allow_deprecated=("manual",),
                       max_tokens=4096).answer(Q, 500)
    assert c.calls[-1]["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert r.warnings and "deprecated" in r.warnings[0]


# ---- D-A18: the notice covers any matching evidence left out for budget ----
def excerpt_memory():
    """One fact and several standalone excerpts that all match 'leeds'."""
    m = StubMemory()
    e1 = m.ingest(Turn("Alice", "user", "I moved to Leeds.", "2026-04-10")).stored[0]
    m.seed_fact(Fact("f1", "Alice", "lives in Leeds", "2026-04-10", (e1,)))
    for i, t in enumerate(["Leeds was rainy today.", "The Leeds market is busy on Saturdays near the station.",
                           "I found a quiet cafe in Leeds with good tea and a long reading table by the window."]):
        m.ingest(Turn("Alice", "user", t, f"2026-04-1{i + 1}"))
    return m


def test_t99_a_standalone_excerpt_left_out_triggers_the_notice_and_is_recorded_not_disclosed():
    m = excerpt_memory()
    hits = []
    for b in range(5, 400):
        r = m.retrieve("Leeds", b)
        c = r.context
        dropped = tuple(e.memory_id for e in r.trace.entries
                        if e.kind == "excerpt" and not e.included and e.why == "excerpt matched the question")
        assert set(c.omitted_excerpts) == set(dropped), b
        assert c.omitted_for_budget == {"fact": len(c.excluded_facts), "excerpt": len(c.omitted_excerpts)}
        if c.omitted_excerpts and not c.excluded_facts and not c.is_empty:
            hits.append(r)
    assert hits, "no budget left out only standalone excerpts"
    for r in hits:
        text = render_context(r.context)
        assert text.splitlines()[-1] == NOTICE and r.context.tokens == count_tokens(text) <= r.context.budget
        for eid in r.context.omitted_excerpts:
            assert m._excerpts[eid].text not in text and f"[{eid}]" not in text


def test_t100_notice_space_is_reserved_for_omitted_excerpts_too():
    m = excerpt_memory()
    proofs = 0
    for b in range(5, 400):
        c = m.retrieve("Leeds", b).context
        if c.is_empty or not c.omitted_excerpts:
            continue
        for eid in c.omitted_excerpts:
            more = c.__class__(c.trace_id, c.question, c.facts, c.excerpts + (m._excerpts[eid],), c.uncertain,
                               c.profile, 0, b)
            if count_tokens(render_context(more, notice=False)) <= b < count_tokens(render_context(more, notice=True)):
                proofs += 1
    assert proofs, "no case where the reservation decided an excerpt's outcome"


# ---- D-A19: empty E_BUDGET results ----
def test_t101_empty_budget_result_counts_the_notice_and_fails_closed_at_the_exact_boundary():
    m, _ = memory_with_facts()
    empties = [m.retrieve(Q, b).context for b in range(5, 200)]
    empties = [c for c in empties if c.is_empty]
    assert empties and all(c.empty_reason == E_BUDGET for c in empties)
    size = count_tokens(render_context(empties[0]))
    assert NOTICE in render_context(empties[0])
    at, below = m.retrieve(Q, size).context, m.retrieve(Q, size - 1).context
    assert at.is_empty and not at.over_budget and at.tokens == size
    assert below.is_empty and below.over_budget and below.tokens == size > below.budget
    for c in empties:
        assert c.over_budget == (c.tokens > c.budget) and c.tokens == count_tokens(render_context(c))
    for make, fake in ((claude_adapter, FakeAnthropicClient), (openai_adapter, FakeOpenAIClient)):
        f = fake()
        with pytest.raises(BudgetClosed):
            make(m, client=f).answer(Q, size - 1)
        assert f.calls == []
        make(m, client=f).answer(Q, size)
        assert len(f.calls) == 1 and NOTICE in (f.calls[0].get("system") or f.calls[0].get("instructions"))


def test_t102_empty_results_from_no_memory_or_no_match_get_no_notice():
    for c in (StubMemory().retrieve(Q, 5).context, memory_with_facts()[0].retrieve("favourite colour?", 5).context):
        assert c.empty_reason in (E_NO_MEMORY, E_NO_MATCH)
        assert NOTICE not in render_context(c) and c.tokens == 0 and not c.over_budget
        assert c.omitted_for_budget == {"fact": 0, "excerpt": 0}


# ---- D-A23: manual budget with effort is not supported in this shell ----
@pytest.mark.parametrize("profile,allow", [(LEGACY, ()), (BOTH, ("manual",))])
def test_t103_manual_budget_with_effort_is_refused(profile, allow):
    c = FakeAnthropicClient()
    fn = ClaudeAdapter(None, client=c).kit_callable(profile.model, profile, allow_deprecated=allow)
    for e in ("low", "high", "default"):
        with pytest.raises(ValueError):
            fn(PROMPT, max_tokens=4096, temperature="default", reasoning={"mode": "manual", "budget_tokens": 2048, "effort": e})
    assert c.calls == []
    fn(PROMPT, max_tokens=4096, temperature="default", reasoning=manual(2048))
    assert "output_config" not in c.calls[-1]


# ---- D-A14 extended: the SDK's extra_* options would override controlled fields ----
@pytest.mark.parametrize("cls", [ClaudeAdapter, OpenAIAdapter])
@pytest.mark.parametrize("key", ["extra_headers", "extra_body", "extra_query"])
def test_t104_params_may_not_use_the_sdks_extra_options(cls, key):
    with pytest.raises(ValueError):
        cls(None, params={key: {"anthropic-version": "2023-01-01", "temperature": 1}})


# ---- D-A20: the allowlist applies on answer() too ----
def test_t105_answer_checks_extras_against_the_allowlist():
    m, _ = memory_with_facts()
    c = FakeAnthropicClient()
    claude_adapter(m, client=c, params={"top_k": 40}).answer(Q, 500)
    assert c.calls[-1]["top_k"] == 40
    for params in ({"top_k": 0}, {"top_k": "40"}, {"top_p": 0.9}, {"metadata": "x"}):
        c = FakeAnthropicClient()
        with pytest.raises(ValueError):
            claude_adapter(m, client=c, params=params).answer(Q, 500)
        assert c.calls == [], params


# ---- IF-8 restated for r6: with a profile required, a code default model must still not exist ----
@pytest.mark.parametrize("cls", [ClaudeAdapter, OpenAIAdapter])
def test_t106_no_default_model_even_with_a_profile(cls):
    a = cls(None, client=FakeAnthropicClient())
    assert a.model is None
    profile = LEGACY if cls is ClaudeAdapter else O_PLAIN
    with pytest.raises(ValueError, match="no model chosen"):
        a.kit_callable(profile=profile)
