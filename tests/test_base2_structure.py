"""Engram base 2: the structure layer (engram_structure.py) and its switch in the LongMemEval runner. Offline: no model."""
import json
import os
import subprocess
import sys

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase

DAY1 = "2:15 pm on 3 March, 2023"
DAY2 = "9:00 am on 9 April, 2023"
LINES = {
    "job": ("User", "I work with Dave at the studio.", DAY1),
    "dave": ("Dave", "I live in Boston.", DAY1),
    "sis": ("User", "My sister lives in Paris.", DAY1),
    "bro": ("User", "My brother lives in Rome.", DAY1),
    "bikes3": ("User", "I have 3 bikes.", DAY1),
    "bikes4": ("User", "I have 4 bikes.", DAY2),
    "date": ("User", "I bought the console on the 17th.", DAY1),
    "full": ("User", "I bought the console on 17 August 2023.", DAY1),
    "neg": ("User", "I never adopted a parrot.", DAY1),
    "ask": ("User", "Should I adopt a hamster?", DAY1),
    "bot": ("Assistant", "You adopted a dog named Max.", DAY1),
    "party": ("User", "I went to a party.", DAY1),
    "hi": ("User", "Hello there!", DAY1),
}


@pytest.fixture
def m(tmp_path):
    mem = E.ChatMemory(str(tmp_path / "m.db"))
    mem.open_chat(DAY1)
    mem.ids = {k: mem.add(s, t, date=d) for k, (s, t, d) in LINES.items()}
    yield mem
    mem.close()


def file(m, key, subject, obj):
    return S.StructureLayer(m.db).file(m.ids[key], subject, obj)


# ---------- the writer reply ----------

def test_parse_keeps_good_proposals_and_drops_bad_ones():
    reply = json.dumps({"facts": [
        dict(line="D1:1", subject="I", object="Dave"),
        dict(line="D1:1", subject="I", object="studio"),     # second for one line: dropped
        dict(line="D9:9", subject="I", object="x"),          # unknown line: dropped
        dict(line="D1:2", subject="", object="Boston"),      # no subject: dropped
        dict(line="D1:3", subject="my sister", object="Paris"),
        "not a dict"]})
    got = S.parse_proposals("Here you go: " + reply, {"D1:1", "D1:2", "D1:3"})
    assert got == [dict(line="D1:1", subject="I", object="Dave"), dict(line="D1:3", subject="my sister", object="Paris")]


@pytest.mark.parametrize("junk", ["", "no json", "{bad json", json.dumps({"facts": "x"}), json.dumps([1, 2])])
def test_parse_never_raises(junk):
    assert S.parse_proposals(junk, {"D1:1"}) == []


def test_writer_prompt_lists_each_line_with_its_id():
    p = S.writer_prompt([("D1:1", "I work with Dave."), ("D1:2", "I have 3 bikes.")])
    assert "D1:1 I work with Dave.\nD1:2 I have 3 bikes." in p and '"facts"' in p


# ---------- the gate ----------

@pytest.mark.parametrize("text,picked", [
    ("I work with Dave at the studio.", True),
    ("My sister lives in Paris.", True),
    ("Hello there!", False),
    ("Can you recommend a good book?", False),
    ("Thanks so much!", False),
])
def test_gate_picks_statements_and_drops_small_talk_and_requests(text, picked):
    assert S.gate("User", text)[0] is picked


def test_gate_never_picks_the_assistant():
    assert S.gate("Assistant", "You adopted a dog named Max.")[0] is False


# ---------- the rules ----------

def test_a_plain_statement_is_stored_with_its_sentence_and_date(m):
    out = file(m, "job", "I", "Dave")
    assert out.verdict == "accepted" and out.fact_id
    rec = KnowledgeBase(m.db).get(out.fact_id)
    assert rec.fact.object_value == "Dave" and rec.fact.valid_from == "2023-03-03" and rec.fact.status == "active"
    assert [e.source_id for e in rec.evidence] == [str(m.ids["job"])]
    assert KnowledgeBase(m.db).entity(rec.fact.subject_id).canonical_name == "User"


@pytest.mark.parametrize("obj", ["Davey", "studios", "Dave at the office", "art"])
def test_copy_rule_rejects_an_object_not_in_the_sentence_word_for_word(m, obj):
    out = file(m, "job", "I", obj)
    assert out.verdict == "rejected" and "word for word" in out.reasons[0]


def test_copy_rule_needs_whole_words(m):
    out = file(m, "party", "I", "art")
    assert out.verdict == "rejected" and "word for word" in out.reasons[0]  # the copy rule itself, before P2
    assert file(m, "party", "I", "a party").verdict == "accepted"


@pytest.mark.parametrize("obj,partial", [
    ("the 17th", True), ("17th", True), ("on the 3rd", True), ("last week", True), ("Tuesday", True), ("yesterday", True),
    ("two weeks ago", True), ("next month", True), ("17 August 2023", False), ("Boston", False), ("3 bikes", False),
])
def test_date_rule_spots_bare_and_relative_dates(obj, partial):
    assert S.is_partial_date(obj) is partial


def test_date_rule_rejects_a_bare_day_and_keeps_a_full_date(m):
    bad = file(m, "date", "I", "the 17th")
    assert bad.verdict == "rejected" and "date" in bad.reasons[0]
    assert file(m, "full", "I", "17 August 2023").verdict == "accepted"


def test_who_rule_accepts_someone_named_in_the_sentence(m):
    out = file(m, "sis", "my sister", "Paris")
    assert out.verdict == "accepted"
    assert KnowledgeBase(m.db).entity(KnowledgeBase(m.db).get(out.fact_id).fact.subject_id).canonical_name == "my sister"


def test_who_rule_rejects_a_subject_who_neither_speaks_nor_is_named(m):
    file(m, "sis", "my sister", "Paris")                       # 'my sister' is now a known entity
    out = file(m, "job", "my sister", "Dave")                   # but this sentence is the user's, about the user
    assert out.verdict == "rejected"


def test_a_second_relative_is_not_blocked_by_the_first(m):
    assert file(m, "sis", "my sister", "Paris").verdict == "accepted"
    assert file(m, "bro", "my brother", "Rome").verdict == "accepted"


@pytest.mark.parametrize("key,subject,obj,why", [
    ("neg", "I", "a parrot", "negate"),
    ("ask", "I", "a hamster", "question"),
])
def test_doubtful_sentences_go_to_review_never_to_the_facts(m, key, subject, obj, why):
    out = file(m, key, subject, obj)
    assert out.verdict == "uncertain" and any(why in r for r in out.reasons) and out.fact_id is None
    assert KnowledgeBase(m.db).review(out.review_id) is not None
    assert S.StructureLayer(m.db).graph().facts == {}


def test_the_assistant_cannot_file_a_fact_about_the_user(m):
    out = file(m, "bot", "User", "Max")
    assert out.verdict != "accepted" and out.fact_id is None


def test_a_missing_sentence_is_rejected(m):
    assert S.StructureLayer(m.db).file(99999, "I", "Dave").verdict == "rejected"


# ---------- versions and repeats ----------

def test_a_newer_version_replaces_the_older_one_and_both_are_kept(m):
    old = file(m, "bikes3", "I", "3 bikes")
    new = file(m, "bikes4", "I", "4 bikes")
    kb = KnowledgeBase(m.db)
    o, n = kb.get(old.fact_id).fact, kb.get(new.fact_id).fact
    assert o.status == "superseded" and o.valid_to == "2023-04-09" and n.status == "active" and n.valid_from == "2023-04-09"
    g = S.StructureLayer(m.db).graph()
    assert [g.facts[f]["object"] for f in g.by_subject["user"]] == ["3 bikes", "4 bikes"]  # every version, oldest first


def test_the_same_fact_said_twice_is_two_statements_linked_not_merged(m):
    """Base 3: every statement is its own record with its own date; a restatement points at the earlier record."""
    first = file(m, "job", "I", "Dave")
    sid = m.add("User", "I work with Dave at the studio.", date=DAY2)
    again = S.StructureLayer(m.db).file(sid, "I", "Dave")
    assert again.fact_id != first.fact_id
    kb = KnowledgeBase(m.db)
    assert kb.get(again.fact_id).fact.metadata["same_claim_as"] == first.fact_id
    assert kb.get(first.fact_id).fact.status == "active" and kb.get(again.fact_id).fact.status == "active"   # same value: no conflict


# ---------- the walk ----------

@pytest.fixture
def chain(m):
    L = S.StructureLayer(m.db)
    L.file(m.ids["job"], "I", "Dave")       # User -> Dave
    L.file(m.ids["dave"], "I", "Boston")    # Dave -> Boston (Dave speaking)
    L.file(m.ids["sis"], "my sister", "Paris")
    return L.graph()


def test_walk_follows_two_links_from_a_search_hit(m, chain):
    fids = S.walk(chain, "Where does the person I work with live?", seed_sids=[m.ids["job"]], hubs=["User"])
    assert [(chain.facts[f]["subject"], chain.facts[f]["object"]) for f in fids] == [("user", "dave"), ("dave", "boston")]


def test_walk_starts_at_a_subject_named_in_the_question(m, chain):
    fids = S.walk(chain, "Where does Dave live?", hubs=["User"])
    assert [chain.facts[f]["object"] for f in fids] == ["boston"]


def test_walk_never_expands_the_speaker_wholesale(m, chain):
    assert S.walk(chain, "What does the user like?", hubs=["User"]) == []


def test_walk_respects_the_hop_limit(m, chain):
    # As in arm B, the facts found first (named or seeded) are the first step; each further step follows one link.
    one = S.walk(chain, "x", seed_sids=[m.ids["job"]], hops=1, hubs=["User"])
    two = S.walk(chain, "x", seed_sids=[m.ids["job"]], hops=2, hubs=["User"])
    assert [chain.facts[f]["object"] for f in one] == ["dave"]
    assert [chain.facts[f]["object"] for f in two] == ["dave", "boston"]
    assert S.walk(chain, "Where does my sister live?", hops=1, hubs=["User"]) != []


def test_facts_are_shown_as_their_original_sentences_with_dates(m, chain):
    fids = S.walk(chain, "Where does the person I work with live?", seed_sids=[m.ids["job"]], hubs=["User"])
    text, used = S.facts_section(m, chain, fids, 500)
    assert "[2:15 pm on 3 March, 2023] User: I work with Dave at the studio." in text
    assert "[2:15 pm on 3 March, 2023] Dave: I live in Boston." in text
    assert used == E.count_tokens(text)


def test_facts_section_keeps_to_its_budget_and_is_empty_when_nothing_fits(m, chain):
    fids = list(chain.facts)
    assert S.facts_section(m, chain, fids, 5) == ("", 0)
    text, used = S.facts_section(m, chain, fids, 45)
    assert 0 < used <= 45 and text.count("\n") == 1


# ---------- deletion ----------

def test_deleting_a_sentence_removes_its_facts_from_the_walk(m, chain):
    m.forget_sentence(m.ids["dave"])
    g = S.StructureLayer(m.db).graph()
    assert ("dave", "boston") not in {(f["subject"], f["object"]) for f in g.facts.values()}
    assert S.walk(g, "Where does Dave live?", hubs=["User"]) == []
    assert KnowledgeBase(m.db).integrity_check() == []


def test_forgetting_one_statement_of_a_claim_leaves_the_other_standing(m):
    """Base 3: each statement is its own record, so deleting one sentence invalidates that statement only."""
    first = file(m, "job", "I", "Dave")
    sid = m.add("User", "I work with Dave at the studio.", date=DAY2)
    again = S.StructureLayer(m.db).file(sid, "I", "Dave")
    m.forget_sentence(sid)
    kb = KnowledgeBase(m.db)
    assert kb.get(again.fact_id).fact.status == "invalidated" and kb.get(first.fact_id).fact.status == "active"
    assert first.fact_id in S.StructureLayer(m.db).graph().facts and again.fact_id not in S.StructureLayer(m.db).graph().facts


def test_forgetting_the_newer_version_reinstates_the_older_one(m):
    """Base 3: a supersession rests on the sentence that caused it (finding F9)."""
    old = file(m, "bikes3", "I", "3 bikes"); new = file(m, "bikes4", "I", "4 bikes")
    kb = KnowledgeBase(m.db)
    assert kb.get(old.fact_id).fact.status == "superseded"
    m.forget_sentence(m.ids["bikes4"])
    assert kb.get(old.fact_id).fact.status == "active" and kb.get(old.fact_id).fact.valid_to is None


def test_a_retraction_is_a_statement_and_retires_the_claim(m):
    """Base 3: 'I no longer like X' is filed with polarity false (finding F7); ERC's polarity check retires 'I like X'."""
    m.ids["like"] = m.add("User", "I like jazz.", date=DAY1); m.ids["unlike"] = m.add("User", "I no longer like jazz.", date=DAY2)
    a = S.StructureLayer(m.db).file(m.ids["like"], "I", "jazz", "preference"); b = S.StructureLayer(m.db).file(m.ids["unlike"], "I", "jazz", "preference")
    assert a.verdict == b.verdict == "accepted"
    kb = KnowledgeBase(m.db)
    assert kb.get(b.fact_id).fact.metadata["polarity"] is False
    assert kb.get(a.fact_id).fact.status == "superseded" and "OPPOSITE_POLARITY" in kb.get(a.fact_id).fact.note


def test_two_values_of_a_multi_valued_relation_both_stand(m):
    """Base 3: 'I like X' then 'I like Y' are two preferences, not two versions of one (finding F6)."""
    m.ids["c"] = m.add("User", "I like coffee.", date=DAY1); m.ids["t"] = m.add("User", "I like tea.", date=DAY2)
    a = S.StructureLayer(m.db).file(m.ids["c"], "I", "coffee", "preference"); b = S.StructureLayer(m.db).file(m.ids["t"], "I", "tea", "preference")
    kb = KnowledgeBase(m.db)
    assert kb.get(a.fact_id).fact.status == "active" and kb.get(b.fact_id).fact.status == "active"
    assert kb.get(a.fact_id).fact.predicate == "likes"


def test_deleting_a_sentence_also_drops_its_review_item(m):
    out = file(m, "neg", "I", "a parrot")
    m.forget_sentence(m.ids["neg"])
    assert KnowledgeBase(m.db).review(out.review_id) is None


def test_iso_day_reads_engram_dates():
    assert S.iso_day(DAY1) == "2023-03-03" and S.iso_day("9:00 am on 9 April, 2023") == "2023-04-09"
    assert S.iso_day("") is None and S.iso_day("someday") is None


# ---------- the switch in the LongMemEval runner (dry run, no model) ----------
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _session(*turns):
    return [dict(role=r, content=c, has_answer=False) for r, c in turns]


def _question(n, chatty):
    talk = _session(("user", "I work with Dave at the studio. I have 3 bikes."), ("assistant", "That sounds fun."))
    smalltalk = _session(("user", "Hello there! Can you help me with the garden?"), ("assistant", "Of course, the garden it is."))
    s1, s2 = (talk, _session(("user", "I live near the river."), ("assistant", "Nice."))) if chatty else (smalltalk, smalltalk)
    return dict(question_id=f"q{n}", question_type="multi-session", question=("Who do I work with at the studio?" if chatty else "Can you help me with the garden?"),
                answer="3", question_date="2023/06/01 (Thu) 10:00", answer_session_ids=[f"s{n}a"],
                haystack_session_ids=[f"s{n}a", f"s{n}b"], haystack_sessions=[s1, s2],
                haystack_dates=["2023/05/01 (Mon) 09:00", "2023/05/02 (Tue) 09:00"])


def _run(tmp_path, out, *extra):
    data = tmp_path / "lme.json"
    if not data.exists():
        data.write_text(json.dumps([_question(n, n % 2 == 0) for n in range(40)]))
    cmd = [sys.executable, os.path.join(HERE, "kit_tools", "lme_gpt4o.py"), "--data", str(data), "--save", str(tmp_path / out),
           "--n", "0", "--fake", "--design", "light", "--prompt", "v2", "--context-tokens", "4000", "--threads", "1", *extra]
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    rows = {}
    for f in os.listdir(tmp_path / out):
        if f.startswith("lme_gpt4o_answers"):
            arm = "b2" if "_v2b2" in f else "v2"
            rows[arm] = {x["question_id"]: x for x in map(json.loads, open(tmp_path / out / f))}
    return rows


@pytest.mark.slow
def test_runner_base1_arm_is_unchanged_by_the_switch_and_base2_differs_only_where_facts_are_reached(tmp_path):
    off = _run(tmp_path, "off")
    on = _run(tmp_path, "on", "--base2")
    assert set(off) == {"v2"} and set(on) == {"v2", "b2"}
    drop = lambda r: {k: v for k, v in r.items() if not k.startswith("b2_") and k != "retrieval_secs"}
    assert {q: drop(r) for q, r in off["v2"].items()} == {q: drop(r) for q, r in on["v2"].items()}  # base 1 arm identical
    chatty = [q for q in on["b2"] if int(q[1:]) % 2 == 0]
    quiet = [q for q in on["b2"] if int(q[1:]) % 2 == 1]
    assert chatty and quiet
    for q in quiet:  # nothing picked by the gate, nothing reached: base 2 shows exactly what base 1 shows
        assert on["v2"][q]["context_tokens"] > 0  # the search found text, so equality below means something
        assert on["b2"][q]["b2_walked"] == 0 and on["b2"][q]["context_tokens"] == on["v2"][q]["context_tokens"]
    for q in chatty:  # the stand-in writer's facts are reached through the search hits and shown first
        assert on["b2"][q]["b2_accepted"] >= 1 and on["b2"][q]["b2_walked"] >= 1 and on["b2"][q]["b2_facts_tokens"] > 0
        assert on["b2"][q]["context_tokens"] <= 4000
