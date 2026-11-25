"""IF-T05..IF-T29: ingest, retrieve, the audit trace, and the calls not yet built, against the stub."""
import pytest
from engram_interface import (StubMemory, Turn, Fact, E_NO_MEMORY, E_NO_MATCH, E_BUDGET, E_SPEAKER, R_EMPTY_TEXT,
                              NOT_UNTIL_B8, NOT_UNTIL_B9, NOT_UNTIL_GATE, render_context)
from engram_interface.render import count_tokens
from .helpers import memory_with_facts

Q = "Where does Alice live?"


# ---- ingest (C02 role boundary at the interface) ----
def test_t05_ingest_keeps_words_speaker_role_date_ref_verbatim():
    m = StubMemory()
    r = m.ingest(Turn("Alice", "user", "  I moved to Leeds.  ", "2026-04-10", "conv0:1"))
    assert r.reason == "" and len(r.stored) == 1
    ctx = m.retrieve("Leeds", 500).context
    e = ctx.excerpts[0]
    assert (e.speaker, e.role, e.text, e.date, e.ref) == ("Alice", "user", "  I moved to Leeds.  ", "2026-04-10", "conv0:1")


def test_t06_ingest_rejects_unknown_role():
    with pytest.raises(ValueError):
        StubMemory().ingest(Turn("Alice", "system", "hello"))


def test_t07_empty_text_is_refused_with_a_reason():
    r = StubMemory().ingest(Turn("Alice", "user", "   "))
    assert r.stored == () and r.reason == R_EMPTY_TEXT


def test_t08_ids_are_unique_and_in_order():
    m = StubMemory()
    ids = [m.ingest(Turn("Alice", "user", f"note {i}")).stored[0] for i in range(5)]
    assert len(set(ids)) == 5 and ids == sorted(ids, key=lambda s: int(s[1:]))


def test_t09_assistant_words_never_become_a_fact_source():
    m, (e1, e2, e3) = memory_with_facts()
    with pytest.raises(ValueError):
        m.seed_fact(Fact("f9", "Alice", "lives in Bristol", "2026-04-10", (e2,)))
    assert all(f.fact_id != "f9" for f in m.retrieve("Bristol Alice", 500).context.facts)


# ---- retrieve (C03) ----
def test_t10_empty_store_gives_a_reason_and_nothing_else():
    c = StubMemory().retrieve(Q, 500).context
    assert c.is_empty and c.empty_reason == E_NO_MEMORY and c.tokens == 0


def test_t11_no_match_gives_a_reason():
    m, _ = memory_with_facts()
    c = m.retrieve("favourite colour?", 500).context
    assert c.is_empty and c.empty_reason == E_NO_MATCH


def test_t12_validated_fact_is_given_with_its_date():
    m, _ = memory_with_facts()
    c = m.retrieve(Q, 500).context
    assert [f.fact_id for f in c.facts] == ["f1"] and c.facts[0].date == "2026-04-10"


def test_t13_fact_comes_with_its_original_excerpt():
    m, (e1, _, _) = memory_with_facts()
    c = m.retrieve(Q, 500).context
    src = [e for e in c.excerpts if e.excerpt_id == e1]
    assert src and src[0].text == "I moved to Leeds last spring." and src[0].date == "2026-04-10"


def test_t14_uncertain_fact_is_kept_apart_from_validated_facts():
    m, _ = memory_with_facts()
    c = m.retrieve("Is Alice's sister visiting in June?", 500).context
    assert "f2" in [f.fact_id for f in c.uncertain]
    assert "f2" not in [f.fact_id for f in c.facts]


def test_t15_exactly_one_of_context_and_reason():
    m, _ = memory_with_facts()
    for q in (Q, "favourite colour?", "sister June"):
        c = m.retrieve(q, 500).context
        assert c.is_empty == bool(c.empty_reason), q
    c = StubMemory().retrieve(Q, 500).context
    assert c.is_empty and c.empty_reason


def test_t16_budget_is_respected_and_tokens_count_the_rendered_block():
    m, _ = memory_with_facts()
    for b in (60, 90, 120, 500):
        c = m.retrieve("Alice Leeds sister June Bristol", b).context
        if not c.is_empty:
            assert c.tokens <= b and c.tokens == count_tokens(render_context(c)), b


def test_t17_budget_too_small_gives_the_budget_reason():
    m, _ = memory_with_facts()
    r = m.retrieve(Q, 5)
    assert r.context.is_empty and r.context.empty_reason == E_BUDGET
    assert r.trace.entries and not any(e.included for e in r.trace.entries)


@pytest.mark.parametrize("bad", [0, -1, 1.5, None])
def test_t18_bad_budget_raises(bad):
    with pytest.raises(ValueError):
        StubMemory().retrieve(Q, bad)


def test_t19_same_question_same_order():
    m, _ = memory_with_facts()
    a = m.retrieve("Alice Leeds sister", 500).context
    b = m.retrieve("Alice Leeds sister", 500).context
    assert [x.fact_id for x in a.facts] == [x.fact_id for x in b.facts]
    assert [x.excerpt_id for x in a.excerpts] == [x.excerpt_id for x in b.excerpts]


def test_t20_speaker_limits_to_that_speaker():
    # r2: questions reworded to first person, because under IF-11 speaker decides who "I" and "my" are.
    m, _ = memory_with_facts()
    m.ingest(Turn("Bob", "user", "I live in Leeds too."))
    c = m.retrieve("Do I live in Leeds?", 500, speaker="Bob").context
    assert c.excerpts and all(e.speaker == "Bob" for e in c.excerpts) and not c.facts
    assert m.retrieve("Do I live in Leeds?", 500, speaker="Carol").context.empty_reason == E_SPEAKER


def test_t21_context_carries_the_profile_result():
    m, _ = memory_with_facts()
    p = m.retrieve(Q, 500).context.profile
    assert p.available is False and p.reason == NOT_UNTIL_B8


# ---- audit trace (C06) ----
def test_t22_every_item_given_has_an_included_trace_entry_with_a_reason():
    m, _ = memory_with_facts()
    r = m.retrieve("Alice Leeds sister June", 500)
    given = {("fact", f.fact_id) for f in r.context.facts + r.context.uncertain} | \
            {("excerpt", e.excerpt_id) for e in r.context.excerpts}
    included = {(e.kind, e.memory_id) for e in r.trace.entries if e.included}
    assert given == included
    assert all(e.why for e in r.trace.entries)


def test_t23_dropped_items_are_traced_with_why():
    m, _ = memory_with_facts()
    r = m.retrieve("Alice Leeds sister June Bristol", 90)
    dropped = [e for e in r.trace.entries if not e.included]
    assert dropped and all(e.dropped_because == "over budget" for e in dropped)


def test_t24_trace_is_kept_and_matches_the_context():
    m, _ = memory_with_facts()
    r = m.retrieve(Q, 500)
    assert r.trace.trace_id == r.context.trace_id and r.trace.question == Q
    assert m.trace(r.context.trace_id) == r.trace
    assert m.retrieve(Q, 500).context.trace_id != r.context.trace_id


def test_t25_trace_names_the_matched_words_and_source_links():
    m, (e1, _, _) = memory_with_facts()
    r = m.retrieve(Q, 500)
    f = next(e for e in r.trace.entries if e.memory_id == "f1")
    assert "leeds" in f.matched or "alice" in f.matched
    assert any(e.memory_id == e1 and "f1" in e.why for e in r.trace.entries)


# ---- not built yet: structured, never raised silently, never fabricated ----
def test_t26_profile_is_not_available_until_b8():
    m, _ = memory_with_facts()
    p = m.profile("Alice")
    assert (p.available, p.stable, p.recent, p.reason) == (False, (), (), NOT_UNTIL_B8)


def test_t27_feedback_is_not_collected_until_b9():
    m, _ = memory_with_facts()
    r = m.retrieve(Q, 500)
    fb = m.feedback(r.context.trace_id, "f1", True)
    assert (fb.accepted, fb.reason) == (False, NOT_UNTIL_B9)
    with pytest.raises(ValueError):
        m.feedback(r.context.trace_id, "f1", "yes")


def test_t28_forget_is_reserved_and_deletes_nothing():
    m, _ = memory_with_facts()
    u = m.forget("f1")
    assert (u.call, u.done, u.reason) == ("forget", False, NOT_UNTIL_GATE)
    assert [f.fact_id for f in m.retrieve(Q, 500).context.facts] == ["f1"]


def test_t29_access_control_is_reserved():
    m, _ = memory_with_facts()
    u = m.access("someone", "f1")
    assert (u.call, u.done, u.reason) == ("access", False, NOT_UNTIL_GATE)
