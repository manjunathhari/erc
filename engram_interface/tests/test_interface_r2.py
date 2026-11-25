"""IF-T43..IF-T65 (revisions 2 and 3): R2-A tests (trace completeness, stable ids, evidence links), second catching
tests for X01, X06, X08, X09 and X13, and tests for decisions IF-5, IF-7, IF-11, IF-19 and IF-20."""
from collections import Counter
import pytest
from engram_interface import (StubMemory, Turn, Fact, ModelContext, ClaudeAdapter, OpenAIAdapter, render_context, DEFAULT_BUDGET,
                              E_NO_MATCH, E_BUDGET, E_NO_SPEAKER, NOT_UNTIL_B9, NOT_UNTIL_GATE)
from engram_interface.render import count_tokens
from .helpers import memory_with_facts, FakeAnthropicClient, FakeOpenAIClient
from .helpers import claude_adapter, openai_adapter, make

Q = "Where does Alice live?"
QUESTIONS = (Q, "Alice Leeds sister June Bristol", "Is Alice's sister visiting in June?", "Bristol", "favourite colour?")
BUDGETS = tuple(range(5, 200, 3)) + (500,)


def sweep(m):
    for q in QUESTIONS:
        for b in BUDGETS:
            yield q, b, m.retrieve(q, b)


def given(ctx):
    return {("fact", f.fact_id) for f in ctx.facts + ctx.uncertain} | {("excerpt", e.excerpt_id) for e in ctx.excerpts}


# ---- R2-A (1): audit-trace completeness ----
def test_t43_each_memory_considered_appears_once():
    m, _ = memory_with_facts()
    for q, b, r in sweep(m):
        counts = Counter((e.kind, e.memory_id) for e in r.trace.entries)
        assert all(n == 1 for n in counts.values()), (q, b, counts)


def test_t44_every_entry_says_given_or_dropped_with_a_reason():
    m, _ = memory_with_facts()
    for q, b, r in sweep(m):
        for e in r.trace.entries:
            assert e.why, (q, b, e)
            assert (e.dropped_because == "") if e.included else bool(e.dropped_because), (q, b, e)


def test_t45_nothing_given_that_is_not_traced_and_nothing_traced_given_that_is_not():
    m, _ = memory_with_facts()
    for q, b, r in sweep(m):
        included = {(e.kind, e.memory_id) for e in r.trace.entries if e.included}
        assert given(r.context) == included, (q, b)


def test_t46_what_is_considered_does_not_depend_on_the_budget():
    m, _ = memory_with_facts()
    for q in QUESTIONS:
        wide = {(e.kind, e.memory_id) for e in m.retrieve(q, 500).trace.entries}
        for b in BUDGETS:
            here = {(e.kind, e.memory_id) for e in m.retrieve(q, b).trace.entries}
            assert here == wide, (q, b)


def test_t47_empty_traces_are_honest():
    m, _ = memory_with_facts()
    r = m.retrieve("favourite colour?", 500)
    assert r.trace.empty_reason == E_NO_MATCH and r.trace.entries == ()
    r = m.retrieve(Q, 5)
    assert r.trace.empty_reason == E_BUDGET and r.trace.entries and not any(e.included for e in r.trace.entries)


# ---- R2-A (2): stable memory ids ----
def test_t48_same_memory_same_kind_and_id_across_calls():
    m, (e1, _, e3) = memory_with_facts()
    a = {e.memory_id: e.kind for e in m.retrieve(Q, 500).trace.entries}
    b = {e.memory_id: e.kind for e in m.retrieve("Alice Leeds sister June", 40).trace.entries}
    c = {e.memory_id: e.kind for e in m.retrieve("Leeds spring", 500).trace.entries}
    for d in (a, b, c):
        assert d.get("f1", "fact") == "fact" and d.get(e1, "excerpt") == "excerpt"
    assert "f1" in a and e1 in a and e1 in c


def test_t49_ids_survive_a_reopen(tmp_path):
    path = str(tmp_path / "stub.json")
    m = StubMemory(path)
    e1 = m.ingest(Turn("Alice", "user", "I moved to Leeds last spring.", "2026-04-10")).stored[0]
    e2 = m.ingest(Turn("Alice", "user", "I work at the library.", "2026-04-11")).stored[0]
    m.seed_fact(Fact("f1", "Alice", "lives in Leeds", "2026-04-10", (e1,)))
    before = m.retrieve(Q, 500).context
    again = StubMemory(path)
    after = again.retrieve(Q, 500).context
    assert [f.fact_id for f in after.facts] == [f.fact_id for f in before.facts] == ["f1"]
    assert [x.excerpt_id for x in after.excerpts] == [x.excerpt_id for x in before.excerpts]
    assert again.retrieve("library", 500).context.excerpts[0].excerpt_id == e2
    assert again.retrieve("library", 500).context.excerpts[0].text == "I work at the library."


def test_t50_traces_are_kept_on_disk_and_trace_ids_never_reused(tmp_path):
    path = str(tmp_path / "stub.json")
    m = StubMemory(path)
    m.ingest(Turn("Alice", "user", "I moved to Leeds."))
    old = [m.retrieve("Leeds", 500).trace for _ in range(3)]
    again = StubMemory(path)
    for t in old:
        assert again.trace(t.trace_id) == t
    new = again.retrieve("Leeds", 500).trace.trace_id
    assert new not in {t.trace_id for t in old}


def test_t51_forget_reservation_neither_frees_nor_reuses_an_id(tmp_path):
    path = str(tmp_path / "stub.json")
    m, (e1, e2, e3) = memory_with_facts()
    for mid in ("f1", e1, e2):
        assert m.forget(mid).reason == NOT_UNTIL_GATE
    new = m.ingest(Turn("Alice", "user", "A new note.")).stored[0]
    assert new not in {e1, e2, e3}
    r = m.retrieve(Q, 500)
    assert "f1" in [f.fact_id for f in r.context.facts]
    assert next(e for e in r.context.excerpts if e.excerpt_id == e1).text == "I moved to Leeds last spring."
    p = StubMemory(path)
    a = p.ingest(Turn("Bob", "user", "one")).stored[0]
    p.forget(a)
    b = StubMemory(path).ingest(Turn("Bob", "user", "two")).stored[0]
    assert a != b


def test_t52_a_fact_id_cannot_be_reused():
    m, (e1, _, e3) = memory_with_facts()
    with pytest.raises(ValueError):
        m.seed_fact(Fact("f1", "Alice", "lives in York", "2026-06-01", (e3,)))
    assert m.retrieve(Q, 500).context.facts[0].statement == "lives in Leeds"


# ---- R2-A (3): link from each fact to its original evidence ----
def test_t53_every_fact_given_names_its_sources_and_each_is_present():
    # r3: "or s in c.cut_sources" removed. 25 Nov 2026: a fact is never given without its supporting sentence.
    m, _ = memory_with_facts()
    for q, b, r in sweep(m):
        c = r.context
        present = {e.excerpt_id for e in c.excerpts}
        for f in c.facts + c.uncertain:
            assert f.sources, (q, b, f)
            for s in f.sources:
                assert s in present, (q, b, f.fact_id, s)


def _alone(m, ctx, fact):
    """Tokens the block would take with this fact added but its sentence left out (what the rule forbids)."""
    return count_tokens(render_context(ModelContext(ctx.trace_id, ctx.question, ctx.facts + (fact,), ctx.excerpts,
                                                    ctx.uncertain, ctx.profile, 0, ctx.budget)))


def test_t54_a_fact_whose_sentence_does_not_fit_is_left_out_and_recorded():
    # r3: rewritten. r2 checked that a cut source was marked; the 25 Nov 2026 rule forbids giving the fact at all.
    m, (e1, _, _) = memory_with_facts()
    f1 = next(f for f in m._facts.values() if f.fact_id == "f1")
    bites = []
    for b in range(5, 200):
        r = m.retrieve(Q, b)
        c = r.context
        if "f1" in {f.fact_id for f in c.facts}:
            assert e1 in {e.excerpt_id for e in c.excerpts} and "f1" not in c.excluded_facts, b
            continue
        assert "f1" in c.excluded_facts, b
        entry = next(e for e in r.trace.entries if (e.kind, e.memory_id) == ("fact", "f1"))
        assert not entry.included and entry.dropped_because == "over budget", b
        assert "supporting sentence" in entry.why and "did not fit" in entry.why, b
        assert e1 not in {e.excerpt_id for e in c.excerpts}, b
        if _alone(m, c, f1) <= b:
            bites.append(b)
    assert bites, "no budget reached the case where the fact alone would fit but not with its sentence"
    assert "[cut for budget]" not in render_context(m.retrieve(Q, bites[0]).context)


def test_t55_source_excerpts_given_are_the_users_original_words():
    m, (e1, _, e3) = memory_with_facts()
    original = {e1: "I moved to Leeds last spring.", e3: "My sister may be visiting in June, not sure."}
    for q, b, r in sweep(m):
        byid = {e.excerpt_id: e for e in r.context.excerpts}
        for f in r.context.facts + r.context.uncertain:
            for s in f.sources:
                if s in byid:
                    assert byid[s].role == "user" and byid[s].text == original[s], (q, b, s)


def test_t56_excluded_facts_are_matching_facts_that_were_not_given():
    # r3: replaces r2's test on cut sources (that field no longer exists).
    m, _ = memory_with_facts()
    for q, b, r in sweep(m):
        c = r.context
        dropped = {e.memory_id for e in r.trace.entries if e.kind == "fact" and not e.included}
        assert set(c.excluded_facts) == dropped, (q, b)
        assert not set(c.excluded_facts) & {f.fact_id for f in c.facts + c.uncertain}, (q, b)


def test_t65_an_empty_budget_result_still_records_what_was_left_out():
    m, _ = memory_with_facts()
    c = m.retrieve(Q, 5).context
    assert c.is_empty and c.empty_reason == E_BUDGET and set(c.excluded_facts) == {"f1", "f2"}
    assert m.retrieve(Q, 500).context.excluded_facts == ()


# ---- second catching tests for X01, X06, X08, X13 (X09 is caught also by T51) ----
def test_t64_a_matching_fact_not_given_is_named_in_the_trace_as_dropped():
    m, _ = memory_with_facts()
    for b in BUDGETS:
        r = m.retrieve("Alice Leeds sister June", b)
        for fid in ("f1", "f2"):
            if fid not in {f.fact_id for f in r.context.facts + r.context.uncertain}:
                e = [x for x in r.trace.entries if (x.kind, x.memory_id) == ("fact", fid)]
                assert e and not e[0].included and e[0].dropped_because == "over budget", (b, fid)



def test_t57_a_fact_resting_partly_on_the_assistants_words_is_refused():
    m, (e1, e2, _) = memory_with_facts()
    with pytest.raises(ValueError):
        m.seed_fact(Fact("f7", "Alice", "lives in Leeds or Bristol", "2026-04-10", (e1, e2)))
    for q, b, r in sweep(m):
        assert "f7" not in {f.fact_id for f in r.context.facts + r.context.uncertain}


def test_t58_feedback_answers_for_any_trace_or_memory_without_raising():
    m, _ = memory_with_facts()
    tid = m.retrieve(Q, 500).context.trace_id
    for t, mid, useful in ((tid, "f1", True), (tid, "f1", False), ("t-unknown", "f1", True), (tid, "nope", False)):
        fb = m.feedback(t, mid, useful)
        assert fb.accepted is False and fb.reason == NOT_UNTIL_B9


def test_t60_every_fact_line_carries_its_own_date():
    m, _ = memory_with_facts()
    for q, b, r in sweep(m):
        lines = render_context(r.context).splitlines()
        for f in r.context.facts + r.context.uncertain:
            line = next(l for l in lines if l.startswith(f"- [{f.fact_id}]"))
            assert f"({f.date})" in line, (q, b, line)


# ---- decisions carried into tests ----
def test_t59_budget_default_and_token_count_follow_the_engine():
    import engram_chat
    assert DEFAULT_BUDGET == engram_chat.Settings().retrieved_tokens
    for t in ("", "a", "abcd", "abcde", "x" * 401, "Validated facts:\n- none"):
        assert count_tokens(t) == engram_chat.count_tokens(t)
    m, _ = memory_with_facts()
    r = claude_adapter(m, model="x", client=FakeAnthropicClient()).answer(Q)
    assert r.context.budget == DEFAULT_BUDGET


def test_t61_speaker_decides_who_i_and_my_are():
    m, _ = memory_with_facts()
    m.ingest(Turn("Bob", "user", "I live in Leeds too."))
    assert m.retrieve("Do I live in Leeds?", 500).context.empty_reason == E_NO_SPEAKER
    c = m.retrieve("Does Alice live in Leeds?", 500, speaker="Bob").context
    assert {e.speaker for e in c.excerpts} >= {"Alice"} and "f1" in {f.fact_id for f in c.facts}
    c = m.retrieve("Where do I live? Leeds?", 500, speaker="Alice").context
    assert c.facts and all(f.subject == "Alice" for f in c.facts) and all(e.speaker == "Alice" for e in c.excerpts)


def test_t62_per_model_settings_come_from_the_run_settings():
    # r5 (D-A12, D-A14): the OpenAI part changed. r2 set the token limit through params (max_tokens None,
    # max_completion_tokens 300); the Responses API has one limit field, max_output_tokens, and params may no
    # longer set or remove a token-limit field. A params temperature of None still drops the temperature.
    m, _ = memory_with_facts()
    c = FakeOpenAIClient()
    openai_adapter(m, model="x", client=c, max_tokens=300, params={"temperature": None}).answer(Q, 500)
    req = c.calls[0]
    assert req["max_output_tokens"] == 300 and "max_tokens" not in req and "temperature" not in req
    with pytest.raises(ValueError):
        openai_adapter(m, model="x", client=FakeOpenAIClient(), params={"max_completion_tokens": 300})
    c2 = FakeAnthropicClient()
    claude_adapter(m, model="x", client=c2, params={"temperature": None}).answer(Q, 500)
    assert "temperature" not in c2.calls[0] and c2.calls[0]["max_tokens"] == 1024


@pytest.mark.parametrize("cls,fake", [(ClaudeAdapter, FakeAnthropicClient), (OpenAIAdapter, FakeOpenAIClient)])
def test_t63_each_answer_records_tokens_and_time(cls, fake):
    m, _ = memory_with_facts()
    r = make(cls, m, model="x", client=fake()).answer(Q, 500)
    assert (r.input_tokens, r.output_tokens) == (10, 2)
    assert isinstance(r.seconds, float) and r.seconds >= 0
