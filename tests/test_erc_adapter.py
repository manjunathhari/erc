"""Engram -> adapter -> ERC as one unit: acceptance test 1 of ADAPTER_REQUIREMENTS.md, plus attempts to break it.
Everything runs through a real ChatMemory and the base-2 structure layer; no model."""
import pytest
from datetime import datetime, timezone

import engram_chat as E
from engram_memory import open_memory
from engram_structure import StructureLayer
from engram_erc_adapter import Adapter, parse_as_of, relate, norm

U = timezone.utc


@pytest.fixture
def mem(tmp_path):
    m = open_memory(str(tmp_path / "m.db"), design="light", durable=False)
    L = StructureLayer(m.db)
    sids = {}

    def say(date, text, subj=None, obj=None, kind="", speaker="User", key=None):
        m.open_chat(date); sid = m.add(speaker, text, date=date); m.close_chat(write_note=False, sleep=True)
        if obj: L.file(sid, subj, obj, kind)
        sids[key or text] = sid
        return sid
    m.say, m.sids, m.L = say, sids, L
    yield m
    m.close()


def D(d, mo, y=2024): return f"9:00 am on {d} {['January','February','March','April','May','June','July','August','September','October','November','December'][mo-1]}, {y}"


def shown(text, s): return s.lower() in text.lower()


# ---------- versions, history, forget ----------
def test_three_versions_newest_only_and_history_on_request(mem):
    mem.say(D(1, 3), "Asha lives in Pune.", "Asha", "Pune"); mem.say(D(1, 6), "Asha lives in Delhi.", "Asha", "Delhi"); mem.say(D(1, 9), "Asha lives in Goa.", "Asha", "Goa")
    A = Adapter(mem)
    t, info = A.context_for("Where does Asha live?")
    assert shown(t, "Goa") and not shown(t, "Pune") and not shown(t, "Delhi")
    assert {w["sid"] for w in info["withheld"]} >= {mem.sids["Asha lives in Pune."], mem.sids["Asha lives in Delhi."]}
    t, _ = A.context_for("Where did Asha live in April 2024?")
    assert shown(t, "Pune") and not shown(t, "Delhi") and not shown(t, "Goa")
    t, _ = A.context_for("Where did Asha live in July 2024?")
    assert shown(t, "Delhi") and not shown(t, "Pune") and not shown(t, "Goa")


def test_forget_newest_restores_previous_without_adapter_state(mem):
    mem.say(D(1, 3), "Asha lives in Pune.", "Asha", "Pune"); mem.say(D(1, 6), "Asha lives in Delhi.", "Asha", "Delhi")
    A = Adapter(mem)
    assert shown(A.context_for("Where does Asha live?")[0], "Delhi")
    mem.forget_sentence(mem.sids["Asha lives in Delhi."])
    t, _ = A.context_for("Where does Asha live?")
    assert shown(t, "Pune") and not shown(t, "Delhi")   # P1 invalidated Delhi; Pune's P1 status is still 'superseded' but ERC sees no rival


def test_old_versions_are_kept_in_the_store(mem):
    mem.say(D(1, 3), "Asha lives in Pune.", "Asha", "Pune"); mem.say(D(1, 6), "Asha lives in Delhi.", "Asha", "Delhi")
    rows = mem.db.execute("SELECT object_value, status, valid_to FROM knowledge_records ORDER BY recorded_at").fetchall()
    assert rows[0][:2] == ("Pune", "superseded") and rows[0][2] == "2024-06-01" and rows[1][:2] == ("Delhi", "active")
    assert mem.db.execute("SELECT count(*) FROM sentences").fetchone()[0] == 2


# ---------- same day, undated, alias ----------
def test_same_day_conflict_newer_record_wins(mem):
    mem.say(D(5, 5), "Asha lives in Pune.", "Asha", "Pune"); mem.say(D(5, 5), "Asha lives in Delhi.", "Asha", "Delhi")
    t, _ = Adapter(mem).context_for("Where does Asha live?")
    assert shown(t, "Delhi") and not shown(t, "Pune")


def test_case_and_alias_variants_are_one_entity(mem):
    mem.say(D(1, 3), "asha lives in Pune.", "asha", "Pune"); mem.say(D(1, 6), "ASHA lives in Delhi.", "ASHA", "Delhi")
    t, _ = Adapter(mem).context_for("Where does Asha live?")
    assert shown(t, "Delhi") and not shown(t, "Pune")


# ---------- preferences ----------
def test_two_preferences_coexist_and_repetition_ranks_first(mem):
    mem.say(D(1, 3), "I like filter coffee.", "I", "filter coffee", "preference"); mem.say(D(2, 3), "I like filter coffee.", "I", "filter coffee", "preference")
    mem.say(D(3, 3), "I like masala dosa.", "I", "masala dosa", "preference")
    t, info = Adapter(mem).context_for("Plan my weekend.")
    assert shown(t, "filter coffee") and shown(t, "masala dosa")
    assert t.lower().index("filter coffee") < t.lower().index("masala dosa")   # 2 sentences of evidence beat 1


def test_retraction_retires_a_preference_but_not_the_others(mem):
    mem.say(D(1, 3), "I like window seats.", "I", "window seats", "preference"); mem.say(D(1, 4), "I like filter coffee.", "I", "filter coffee", "preference")
    mem.say(D(1, 5), "I no longer like window seats.", "I", "window seats", "preference")
    t, _ = Adapter(mem).context_for("Book me a flight.")
    assert not shown(t, "I like window seats") and shown(t, "filter coffee")


def test_preference_then_retraction_then_same_preference_again_is_live(mem):
    mem.say(D(1, 3), "I like jazz.", "I", "jazz", "preference"); mem.say(D(1, 4), "I no longer like jazz.", "I", "jazz", "preference")
    mem.say(D(1, 6), "I like jazz.", "I", "jazz", "preference")
    t, _ = Adapter(mem).context_for("Suggest some music.")
    assert shown(t, "I like jazz")


def test_profile_appears_even_when_question_is_unrelated(mem):
    mem.say(D(1, 3), "I like filter coffee.", "I", "filter coffee", "preference")
    t, _ = Adapter(mem).context_for("What is the capital of France?")
    assert shown(t, "filter coffee")


# ---------- multi-hop ----------
def test_three_hops_follow_current_link_not_stale_one(mem):
    mem.say(D(1, 1), "My sister is Asha.", "my sister", "Asha"); mem.say(D(2, 1), "Asha works at Infosys.", "Asha", "Infosys")
    mem.say(D(3, 1), "Infosys is headquartered in Bengaluru.", "Infosys", "Bengaluru"); mem.say(D(4, 1), "Zoho is headquartered in Chennai.", "Zoho", "Chennai")
    mem.say(D(1, 6), "Asha works at Zoho.", "Asha", "Zoho")
    t, _ = Adapter(mem).context_for("In which city is the company where the user's sister works headquartered?")
    assert shown(t, "Chennai") and shown(t, "Zoho") and not shown(t, "Asha works at Infosys")


def test_walk_does_not_expand_the_hub_wholesale(mem):
    for i in range(30): mem.say(D(1 + i % 27, 1), f"I like item{i}.", "I", f"item{i}", "preference")
    mem.say(D(1, 2), "Asha lives in Pune.", "Asha", "Pune")
    t, info = Adapter(mem).context_for("Where does Asha live?")
    assert shown(t, "Pune") and info["reached"] <= 3


# ---------- the gate ----------
def test_superseded_sentence_found_by_search_is_withheld(mem):
    mem.say(D(1, 3), "Asha lives in Pune and loves the weather there.", "Asha", "Pune"); mem.say(D(1, 6), "Asha lives in Delhi.", "Asha", "Delhi")
    t, info = Adapter(mem).context_for("Does Asha love the weather in Pune?")   # search will want the Pune sentence
    assert not shown(t, "loves the weather") and any(w["sid"] == mem.sids["Asha lives in Pune and loves the weather there."] for w in info["withheld"])


def test_sentence_with_no_fact_passes_the_gate(mem):
    mem.say(D(1, 3), "Nice weather today in Pune.")
    t, _ = Adapter(mem).context_for("How was the weather in Pune?")
    assert shown(t, "Nice weather today")


def test_review_queue_items_are_never_shown_as_facts(mem):
    mem.say(D(1, 3), "Should I move to Pune?", "I", "Pune")   # question -> review, not a fact
    t, info = Adapter(mem).context_for("Where does the user live?")
    assert not info["shown"] and not info["profile"]


# ---------- determinism, no writes ----------
def test_same_memory_same_question_same_bytes_and_no_writes(mem):
    mem.say(D(1, 3), "Asha lives in Pune.", "Asha", "Pune"); mem.say(D(1, 6), "Asha lives in Delhi.", "Asha", "Delhi")
    before = mem.db.execute("SELECT count(*), max(recorded_at) FROM knowledge_records").fetchone()
    A = Adapter(mem); as_of = datetime(2025, 1, 1, tzinfo=U)
    a = A.context_for("Where does Asha live?", as_of=as_of)[0]; b = A.context_for("Where does Asha live?", as_of=as_of)[0]
    assert a == b and mem.db.execute("SELECT count(*), max(recorded_at) FROM knowledge_records").fetchone() == before
    assert mem.db.execute("SELECT count(*) FROM sentences").fetchone()[0] == 2


# ---------- trying to break it ----------
def test_unparsed_sentence_falls_back_to_base2_key_and_still_resolves(mem):
    mem.say(D(1, 3), "Asha reports to Ravi.", "Asha", "Ravi"); mem.say(D(1, 6), "Asha reports to Meera.", "Asha", "Meera")   # no relation pattern for 'reports to'
    t, _ = Adapter(mem).context_for("Who does Asha report to?")
    assert shown(t, "Meera") and not shown(t, "Ravi")


def test_unicode_and_punctuation_in_values(mem):
    mem.say(D(1, 3), "Asha lives in Bengalūru.", "Asha", "Bengalūru"); mem.say(D(1, 6), "Asha lives in Bengaluru.", "Asha", "Bengaluru")
    t, info = Adapter(mem).context_for("Where does Asha live?")
    assert t.lower().count("asha lives in") == 1   # normalised to one value, one version shown


def test_question_about_the_future_shows_nothing_as_current(mem):
    mem.say(D(1, 3), "Asha lives in Pune.", "Asha", "Pune")
    t, _ = Adapter(mem).context_for("Where did Asha live in 2020?")
    assert not shown(t, "Pune")


def test_two_speakers_do_not_merge_preferences(mem):
    mem.say(D(1, 3), "I like jazz.", "I", "jazz", "preference", speaker="User"); mem.say(D(1, 4), "I like techno.", "I", "techno", "preference", speaker="Ravi")
    A = Adapter(mem, hubs=("user", "ravi")); st = A.load()
    assert ("user", "likes") in st.groups and ("ravi", "likes") in st.groups


def test_many_versions_scale(mem):
    for i in range(60): mem.say(D(1 + i % 27, 1 + i % 12, 2024 + i // 27), f"Asha lives in City{i}.", "Asha", f"City{i}", key=i)
    import time; t0 = time.time(); t, _ = Adapter(mem).context_for("Where does Asha live?"); dt = time.time() - t0
    assert dt < 5 and t.lower().count("asha lives in") == 1


def test_relate_and_as_of_helpers():
    assert relate("I no longer like jazz.", "User") == ("user", "likes", "jazz", False)
    assert relate("The capital of Italy is Rome.", "User") == ("italy", "capital", "rome", True)
    assert relate("Asha's manager is Ravi.", "User") == ("asha", "poss:manager", "ravi", True)
    assert parse_as_of("Where did Asha live in March 2024?").month == 3 and parse_as_of("Where does Asha live?") is None
    assert norm("the country of Italy") == "italy" and norm("Bengalūru") == "bengaluru"
