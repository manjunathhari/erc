"""Stage 2, Increment 6: retriever and router attached. Tests written first (the four-part standard, Q11).
Specification: Increment 6 Specification Draft 6 (engram-stage2-inc6-spec-draft6.md, SHA-256
a3ab719523894b6fc35573d64da015e107a8cab37ae183ce160595b63db53941), frozen 24 Nov 2026 08:43 (freeze record
7facb6c54029ee17d7911e93ba611171967facf4be9a34e0e2caa036591a761a); decisions record r28. As amended by Amendment 1
(engram-stage2-inc6-amendment1.md, SHA-256 b905b5a2391b7457103697cfd37e282c2f7d9f6d37949f4a55d55b7fe4a114d7), approved
24 Nov 09:55 (decisions record r32): T5 extended to R11; T22 (G-1) and T23 (G-2) added. And by Amendment 2
(engram-stage2-inc6-amendment2.md, SHA-256 e003eba656837394bcae03cd92f06813995beaf3381f105a2be3669739ac7c25), approved
24 Nov 10:10 (decisions record r34): the module is engram_knowledge/knowledge_text.py (G-3); T18 follows.

`knowledge_section(memory, question, budget, speaker=None) -> (text, tokens, reason)` in engram_knowledge/knowledge_text.py,
and `KnowledgeRetriever.find_entity(question, report=False)`. Group names T1 to T21 follow Draft 6, section 7; T22 and T23 follow Amendment 1, A4.
Tests marked CONTROL pin behaviour that exists at 69da9fc and must keep passing; every other test fails at 69da9fc
because the module, or find_entity's `report`, does not exist yet.
Facts are filed through StructureLayer.file with fixed, hand-written proposals; no model is called. Every sentence and
name is made up; none is LoCoMo text.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, UNCERTAIN
from engram_knowledge.knowledge_retriever import KnowledgeRetriever
from engram_knowledge.models import Entity, FactEvidence

ROOT = Path(__file__).resolve().parents[1]
D1, D2 = "2:15 pm on 12 June, 2025", "10:00 am on 3 July, 2025"
HEAD = "[Records from the knowledge store: each fact with the original sentences behind it]"
BIG = 10_000

R1 = "the question is not about a stored kind of fact"
R2 = "a name in the question belongs to more than one known entity"
R3 = "the question names more than one known entity"
R4 = "the question names both the supplied speaker and another known entity"
R5 = "no known entity is named"
R6 = "the kind of fact asked about is not one the router knows"
R7_CURRENT = "no current record"                                   # R7: the retriever's own note, as it is
R8 = "the supplied speaker is not one known entity"
R9 = "the records did not fit the budget"
R10 = "the question is in the first person and names another known entity"
R11 = "no record has a supporting sentence to show"                    # Amendment 1, A3


def knowledge_section(*args, **kwargs):
    from engram_knowledge.knowledge_text import knowledge_section as ks       # absent at 69da9fc: the intended failure
    return ks(*args, **kwargs)


class Mem:
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.layer = S.StructureLayer(self.m.db)
        self.kb = KnowledgeBase(self.m.db)

    def chat(self, date, lines):
        self.m.open_chat(date)
        self.m.add("Asha", "Morning Ben, the tea is ready.", date=date)
        self.m.add("Ben", "Hi Asha, likewise.", date=date)
        sids = [self.m.add(who, text, date=date) for who, text in lines]
        self.m.close_chat(write_note=False)
        return sids

    def file(self, sid, subject, obj, word, **kw):
        return self.layer.file(sid, subject, obj, "claim", word=word, **kw)

    def stored(self, sid, subject, obj, word, **kw):
        out = self.file(sid, subject, obj, word, **kw)
        assert out.verdict == ACCEPTED and out.fact_id, (out.verdict, out.reasons)
        return out.fact_id

    def person(self, name):
        return self.kb.add_entity(Entity.create(name, "person")).entity_id

    def dump(self):
        return "\n".join(self.m.db.iterdump())


@pytest.fixture
def mem(tmp_path):
    m = Mem(tmp_path)
    yield m
    m.m.close()


def ask(mem, question, budget=BIG, speaker=None):
    """Runs the function and checks the contract every answer must keep (section 5.1): exactly one of text and reason."""
    text, tokens, reason = knowledge_section(mem.m, question, budget, speaker=speaker)
    assert bool(text) != bool(reason), (text, reason)
    assert tokens == (E.count_tokens(text) if text else 0)
    assert tokens <= budget
    return text, reason


def block(*lines):
    return "\n".join((HEAD,) + lines)


def fact(n, name, kind, label, value, period):
    return f"[{n}] {name} ({kind}) — {label}: {value} ({period})"


def said(date, speaker, words, tail=""):
    return f"  said {date}, {speaker}: {words}" + (f" {tail}" if tail else "")


def name_line(date, speaker, words, tail=""):
    return f"  name line, {date}, {speaker}: {words}" + (f" {tail}" if tail else "")


OPEN_D1 = "start not stated; first said 2025-06-12; still held"
OPEN_D2 = "start not stated; first said 2025-07-03; still held"


# ---------------------------------------------------------------- shared stores
def work_store(mem):
    """Asha works at Riverside Clinic, said by Asha and by Ben."""
    a, b = mem.chat(D1, [("Asha", "I work at Riverside Clinic."), ("Ben", "Asha works at Riverside Clinic, she told me.")])
    mem.stored(a, "I", "Riverside Clinic", "works_at")
    mem.stored(b, "Asha", "Riverside Clinic", "works_at")
    return block(fact(1, "Asha", "person", "Works at", "Riverside Clinic", OPEN_D1),
                 said(D1, "Asha", "I work at Riverside Clinic."),
                 said(D1, "Ben", "Asha works at Riverside Clinic, she told me."))


def job_change_store(mem):
    """Asha at Hill Bank from March 2024 (stated), then Riverside Clinic (said 3 July 2025, start not stated)."""
    a, = mem.chat(D1, [("Asha", "I work at Hill Bank since March 2024.")])
    b, = mem.chat(D2, [("Asha", "I work at Riverside Clinic now.")])
    mem.stored(a, "I", "Hill Bank", "works_at")
    mem.stored(b, "I", "Riverside Clinic", "works_at")
    hill = (fact(1, "Asha", "person", "Works at", "Hill Bank", "from 2024-03; to 2025-07-02"),
            said(D1, "Asha", "I work at Hill Bank since March 2024."))
    river = lambda n: (fact(n, "Asha", "person", "Works at", "Riverside Clinic", OPEN_D2),
                       said(D2, "Asha", "I work at Riverside Clinic now."))
    return hill, river


def lose_support(mem, fact_id):
    """Constructed edge (as T12's): the fact's supporting link points at a sentence that does not exist. Base 2 never
    writes this."""
    mem.m.db.execute("UPDATE record_evidence SET source_id='999999' WHERE fact_id=? AND evidence_role='supports'", (fact_id,))
    mem.m.db.commit()


def world(mem):
    """Asha (works at Riverside Clinic), Ben (lives in Pune), Lee, two different people called Sam, and Rob, whose one
    fact has lost its supporting sentence (for R11)."""
    expected = work_store(mem)
    c, = mem.chat(D1, [("Ben", "I live in Pune.")])
    mem.stored(c, "I", "Pune", "lives_in")
    mem.person("Lee")
    mem.person("Sam")
    mem.person("Sam")
    mem.person("Rob")
    r, = mem.chat(D1, [("Asha", "Rob works at Hill Bank.")])
    lose_support(mem, mem.stored(r, "Rob", "Hill Bank", "works_at"))
    return expected


# ---------------------------------------------------------------- T1
def test_t1_a_base2_fact_is_shown_for_a_question_naming_its_subject(mem):
    expected = work_store(mem)
    assert ask(mem, "Where does Asha work now?") == (expected, "")


# ---------------------------------------------------------------- T2
def test_t2_unslotted_and_outside_facts_are_never_shown(mem):
    a, b, c = mem.chat(D1, [("Asha", "I work at Riverside Clinic."), ("Asha", "I visited Goa last year."),
                             ("Asha", "I play chess every Sunday.")])
    mem.stored(a, "I", "Riverside Clinic", "works_at")
    mem.stored(b, "I", "Goa", "visited")
    mem.stored(c, "I", "chess", "other")
    kinds = {r[0] for r in mem.m.db.execute("SELECT json_extract(metadata, '$.vocabulary') FROM knowledge_records")}
    assert kinds == {"in", "outside"}                                           # the setup holds both groups
    for q in ("Where does Asha work now?", "Where has Asha worked over time?", "Asha's job?"):
        text, _ = ask(mem, q)
        assert "Goa" not in text and "chess" not in text


# ---------------------------------------------------------------- T3 (Q8)
def test_t3_current_state_shows_only_the_new_value(mem):
    hill, river = job_change_store(mem)
    assert ask(mem, "Where does Asha work now?") == (block(*river(1)), "")


def test_t3_history_shows_both_values_with_their_periods(mem):
    hill, river = job_change_store(mem)
    assert ask(mem, "Where has Asha worked over time?") == (block(*hill, *river(2)), "")


# ---------------------------------------------------------------- T4
def test_t4_two_speakers_disagreeing_are_both_shown_marked(mem):
    a, b = mem.chat(D1, [("Asha", "I work at Riverside Clinic."), ("Ben", "Asha works at Hill Bank.")])
    mem.stored(a, "I", "Riverside Clinic", "works_at")
    mem.stored(b, "Asha", "Hill Bank", "works_at")
    text, reason = ask(mem, "Where does Asha work now?")
    lines = text.split("\n")
    assert reason == "" and lines[0] == HEAD and len(lines) == 5
    blocks = {(lines[1][4:], lines[2]), (lines[3][4:], lines[4])}            # order of two facts said together is not fixed
    assert {lines[1][:4], lines[3][:4]} == {"[1] ", "[2] "} and lines[1].startswith("[1] ")
    assert blocks == {
        (fact(1, "Asha", "person", "Works at", "Riverside Clinic", OPEN_D1 + "; sources disagree")[4:], said(D1, "Asha", "I work at Riverside Clinic.")),
        (fact(1, "Asha", "person", "Works at", "Hill Bank", OPEN_D1 + "; sources disagree")[4:], said(D1, "Ben", "Asha works at Hill Bank."))}


# ---------------------------------------------------------------- T5 (Q4, Q10, Q3b, Q4b, P3)
REASON_CASES = [
    ("R1", "Tell a joke please.", None, BIG, R1),
    ("R2", "Where does Sam work now?", None, BIG, R2),
    ("R3", "Where do Asha and Ben work now?", None, BIG, R3),
    ("R4", "Do I work with Ben?", "Asha", BIG, R4),
    ("R5", "Where does the boss work now?", None, BIG, R5),
    ("R6", "Is Asha single now?", None, BIG, R6),
    ("R7", "Where does Ben work now?", None, BIG, R7_CURRENT),
    ("R8", "Where do I work now?", "Zed", BIG, R8),
    ("R9", "Where does Asha work now?", None, 5, R9),
    ("R10", "Do I work with Ben?", None, BIG, R10),
    ("R11", "Where does Rob work now?", None, BIG, R11),                        # Amendment 1, A3
]


@pytest.mark.parametrize("case,question,speaker,budget,reason", REASON_CASES, ids=[c[0] for c in REASON_CASES])
def test_t5_each_no_answer_case_gives_its_own_reason_and_no_text(mem, case, question, speaker, budget, reason):
    world(mem)
    assert ask(mem, question, budget, speaker) == ("", reason)


def test_t5_the_reasons_are_all_different():
    """A check on this file's own table (Q5a: the reasons stay distinct); it calls no code, so it passes at 69da9fc."""
    assert len({c[4] for c in REASON_CASES}) == len(REASON_CASES) == 11


# ---------------------------------------------------------------- T6, T17 (Q5a, Q5b)
def shared_store(mem):
    long = "I love green tea, especially the fresh leaves my aunt sends from the hills near her old farm every spring."
    e, = mem.chat(D1, [("Asha", long)])
    s, = mem.chat(D2, [("Asha", "I love green tea and chess.")])
    mem.stored(e, "I", "green tea", "likes")
    mem.stored(s, "I", "green tea", "likes")                                  # the same fact said again: more evidence
    mem.stored(s, "I", "chess", "likes")
    return long


def test_t17_a_shared_sentence_is_shown_once_with_back_references(mem):
    long = shared_store(mem)
    expected = block(fact(1, "Asha", "person", "Likes", "green tea", OPEN_D1),
                     said(D1, "Asha", long),
                     said(D2, "Asha", "I love green tea and chess.", "(also supports [2])"),
                     fact(2, "Asha", "person", "Likes", "chess", OPEN_D2),
                     "  said: see [1]")
    assert ask(mem, "What does Asha like now?") == (expected, "")


def test_t6_a_dropped_first_fact_moves_the_shared_sentence_to_the_first_fact_shown(mem):
    long = shared_store(mem)
    small = block(fact(1, "Asha", "person", "Likes", "chess", OPEN_D2), said(D2, "Asha", "I love green tea and chess."))
    tea_alone = block(fact(1, "Asha", "person", "Likes", "green tea", OPEN_D1), said(D1, "Asha", long),
                      said(D2, "Asha", "I love green tea and chess."))
    budget = E.count_tokens(small)
    assert E.count_tokens(tea_alone) > budget                                 # the setup: the first fact cannot fit
    assert ask(mem, "What does Asha like now?", budget) == (small, "")


def test_t6_the_budget_is_kept_and_each_sentence_appears_once(mem):
    shared_store(mem)
    text, _ = ask(mem, "What does Asha like now?")
    assert text.count("I love green tea and chess.") == 1
    for budget in range(1, E.count_tokens(text) + 2):
        t, r = ask(mem, "What does Asha like now?", budget)                   # ask() checks tokens <= budget
        assert t or r == R9


# ---------------------------------------------------------------- T7 (controls through the new function)
def test_t7_facts_section_and_the_retriever_are_unchanged_by_the_new_function(mem):
    work_store(mem)
    g = mem.layer.graph()
    fids = S.walk(g, "Where does Asha work now?")
    before = (S.facts_section(mem.m, g, fids, 500), KnowledgeRetriever(mem.m).retrieve("Where does Asha work now?"))
    ask(mem, "Where does Asha work now?")
    after = (S.facts_section(mem.m, g, fids, 500), KnowledgeRetriever(mem.m).retrieve("Where does Asha work now?"))
    assert before == after


# ---------------------------------------------------------------- T8 (Q12, K-6 P-A)
def test_t8_the_stored_kind_is_shown_unknown_included(mem):
    a, = mem.chat(D1, [("Asha", "Rob works at Hill Bank.")])
    mem.kb.add_entity(Entity.create("Rob", "unknown"))                       # an entity as base 2 wrote it before Increment 5
    mem.stored(a, "Rob", "Hill Bank", "works_at")
    assert ask(mem, "Where does Rob work now?") == (
        block(fact(1, "Rob", "unknown", "Works at", "Hill Bank", OPEN_D1), said(D1, "Asha", "Rob works at Hill Bank.")), "")
    assert mem.kb.entity(mem.kb.resolve("Rob")).entity_type == "unknown"     # read, never derived or changed


# ---------------------------------------------------------------- T9 (P6, B8)
ALL_KINDS = ["Tell a joke please.", "Where does Asha work now?", "Asha's job?", "Where has Asha worked over time?",
             "Where did Asha first work?", "Where did Asha work in 2024?", "Are there conflicting records about where Asha works?",
             "What is the evidence for where Asha works?", "When did Asha start at her job?", "Where does Ben work now?",
             "Is Asha single now?", "Where does the boss work now?", "Where does Sam work now?", "Do I work with Ben?"]


def test_t9_no_ordinary_memory_search_is_performed_and_nothing_is_written(mem, monkeypatch):
    world(mem)
    calls = []

    def spy(*args, **kwargs):
        calls.append(args)
        raise AssertionError("ordinary-memory search was called")

    monkeypatch.setattr(mem.m, "find", spy)
    before = mem.dump()
    for q in ALL_KINDS:
        for speaker in (None, "Asha"):
            ask(mem, q, speaker=speaker)
    assert calls == []
    assert mem.dump() == before


# ---------------------------------------------------------------- T10 (Q4)
def test_t10_a_combined_question_gives_the_record_only(mem):
    expected = work_store(mem)
    assert ask(mem, "Asha's job?") == (expected, "")


# ---------------------------------------------------------------- T11 (B5)
def test_t11_a_historical_question_uses_the_stated_dates(mem):
    hill, _ = job_change_store(mem)
    assert ask(mem, "Where did Asha work in 2024?") == (block(*hill), "")


def test_t11_an_original_value_question_uses_the_stated_dates(mem):
    hill, _ = job_change_store(mem)
    assert ask(mem, "Where did Asha first work?") == (block(*hill), "")


def test_t11_a_first_said_day_is_never_shown_as_a_start(mem):
    job_change_store(mem)
    text, _ = ask(mem, "Where has Asha worked over time?")
    assert "from 2025" not in text and "first said 2025-07-03" in text


# ---------------------------------------------------------------- T12 (Q14, Q5a)
def test_t12_a_name_line_is_marked_and_never_shown_as_said(mem):
    a, b = mem.chat(D1, [("Asha", "My neighbour Ravi is very kind."), ("Asha", "He works at Hill Bank.")])
    mem.stored(b, "Ravi", "Hill Bank", "works_at", subject_from=a, reading="Asha", subject_kind="person")
    assert ask(mem, "Where does Ravi work now?") == (
        block(fact(1, "Ravi", "person", "Works at", "Hill Bank", OPEN_D1),
              said(D1, "Asha", "He works at Hill Bank."),
              name_line(D1, "Asha", "My neighbour Ravi is very kind.")), "")


def test_t12_a_fact_whose_only_sentence_in_the_text_would_be_a_name_line_is_not_shown(mem):
    """Constructed edge: the supporting link of one fact is pointed at a sentence that does not exist, so its trace holds
    only its name line. Base 2 never writes this; the test pins that a name line never counts as support."""
    a, b = mem.chat(D1, [("Asha", "My neighbour Ravi is very kind."), ("Asha", "He loves green tea.")])
    c, = mem.chat(D1, [("Ben", "Ravi likes chess.")])                         # its own chat, so it is not a nearer name
    tea = mem.stored(b, "Ravi", "green tea", "likes", subject_from=a, reading="Asha", subject_kind="person")
    mem.stored(c, "Ravi", "chess", "likes")
    mem.m.db.execute("UPDATE record_evidence SET source_id='999999' WHERE fact_id=? AND evidence_role='supports'", (tea,))
    mem.m.db.commit()
    assert ask(mem, "What does Ravi like now?") == (
        block(fact(1, "Ravi", "person", "Likes", "chess", OPEN_D1), said(D1, "Ben", "Ravi likes chess.")), "")


def test_t17_a_shared_name_line_is_shown_once_with_back_references(mem):
    """One borrowed sentence states two facts, so both its supporting sentence and its name line are shared."""
    a, b = mem.chat(D1, [("Asha", "My neighbour Ravi is very kind."), ("Asha", "He loves green tea and chess.")])
    mem.stored(b, "Ravi", "green tea", "likes", subject_from=a, reading="Asha", subject_kind="person")
    mem.stored(b, "Ravi", "chess", "likes", subject_from=a, reading="Asha")
    text, reason = ask(mem, "What does Ravi like now?")
    first = "green tea" if "green tea" in text.split("\n")[1] else "chess"      # two facts said together: order not fixed
    second = "chess" if first == "green tea" else "green tea"
    assert (text, reason) == (block(
        fact(1, "Ravi", "person", "Likes", first, OPEN_D1),
        said(D1, "Asha", "He loves green tea and chess.", "(also supports [2])"),
        name_line(D1, "Asha", "My neighbour Ravi is very kind.", "(also the name line for [2])"),
        fact(2, "Ravi", "person", "Likes", second, OPEN_D1),
        "  said: see [1]",
        "  name line: see [1]"), "")


# ---------------------------------------------------------------- T13 (Q3, Q3a, Q3b, Q4a, Q4b, P3)
@pytest.mark.parametrize("question,speaker", [
    ("Where do I work now?", "Asha"),
    ("Which company employs me now?", "Asha"),
    ("Do Asha and I work together now?", "Asha"),                               # the entity named is the speaker's own
], ids=["I", "me", "named-is-speaker"])
def test_t13_i_and_me_map_to_the_supplied_speaker(mem, question, speaker):
    expected = world(mem)
    assert ask(mem, question, speaker=speaker) == (expected, "")


@pytest.mark.parametrize("question,speaker,reason", [
    ("Where is my office now?", "Asha", R5),                                    # "my" is not mapped (Q3a)
    ("Which office is mine now?", "Asha", R5),                                  # "mine" is not mapped (Q3a)
    ("Where do I work now?", None, R5),                                         # no speaker (Q4a)
    ("Do I work with Ben?", "Asha", R4),                                        # Q3b
    ("Do I work with Ben?", None, R10),                                         # Q4b
    ("Where do I work now?", "Zed", R8),                                        # P3
    ("Where does Ben work now?", "Asha", R7_CURRENT),                           # not first person: the speaker plays no part
], ids=["my", "mine", "no-speaker", "speaker-and-other", "no-speaker-and-other", "unknown-speaker", "third-person"])
def test_t13_first_person_cases_without_a_mapping(mem, question, speaker, reason):
    world(mem)
    assert ask(mem, question, speaker=speaker) == ("", reason)


# ---------------------------------------------------------------- T14 (Q7, B4)
def test_t14_needs_review_and_disputed_facts_are_shown(mem):
    e, = mem.chat(D1, [("Asha", "I love green tea.")])
    s, = mem.chat(D2, [("Asha", "I love chess.")])
    tea = mem.stored(e, "I", "green tea", "likes")
    chess = mem.stored(s, "I", "chess", "likes")
    mem.m.db.execute("UPDATE knowledge_records SET status='needs_review' WHERE fact_id=?", (tea,))   # as after a deletion
    mem.m.db.commit()
    mem.kb.set_status(chess, "disputed")
    assert ask(mem, "What does Asha like now?") == (block(
        fact(1, "Asha", "person", "Likes", "green tea", OPEN_D1), said(D1, "Asha", "I love green tea."),
        fact(2, "Asha", "person", "Likes", "chess", OPEN_D2), said(D2, "Asha", "I love chess.")), "")


def test_t14_a_held_proposal_is_not_shown(mem):
    a, = mem.chat(D1, [("Asha", "Zara works at Hill Bank.")])
    assert mem.file(a, "Zara", "Hill Bank", "works_at").verdict == UNCERTAIN    # a new entity with no kind (K-10)
    assert ask(mem, "Where does Zara work now?") == ("", R5)


def test_t14_waiting_reviews_are_said_on_the_fact_line(mem):
    work_store(mem)
    s, = mem.chat(D2, [("Ben", "Asha may be moving to Hill Bank.")])
    mem.kb.add_review(json.dumps(dict(subject="Asha", predicate="works_at", object="Hill Bank")), ["not settled"], [s])
    text, _ = ask(mem, "Where does Asha work now?")
    assert text.split("\n")[1] == fact(1, "Asha", "person", "Works at", "Riverside Clinic",
                                       OPEN_D1 + "; newer statements may be waiting for review")


# ---------------------------------------------------------------- T15 (Q2)
@pytest.mark.parametrize("question", ["Is Asha single now?", "Who is Asha's friend now?"])
def test_t15_slots_the_router_does_not_know_give_the_no_slot_reason_even_when_stored(mem, question):
    a, b = mem.chat(D1, [("Asha", "I am single."), ("Asha", "Ben is my friend.")])
    mem.stored(a, "I", "single", "status")
    mem.stored(b, "I", "Ben", "friend_of")
    assert ask(mem, question) == ("", R6)


# ---------------------------------------------------------------- T16, T21 (Q10a, P1, P2)
FIND_CASES = [
    ("Where does Asha work now?", "one"),
    ("Where does the boss work now?", "none"),
    ("Where does Sam work now?", "shared_name"),
    ("Where do Asha and Ben work now?", "several_named"),
    ("Where do Sam and Ben work now?", "shared_name"),                          # P1: the rest resolve to at most one entity
    ("Where do Sam, Ben and Lee work now?", "several_named"),                  # T21, P2: several_named takes precedence
]


@pytest.mark.parametrize("question,case", FIND_CASES, ids=[c[1] + str(i) for i, c in enumerate(FIND_CASES)])
def test_t16_control_find_entity_default_return_is_unchanged(mem, question, case):
    """CONTROL: passes at 69da9fc and must keep passing (report=False is today's behaviour)."""
    world(mem)
    found = KnowledgeRetriever(mem.m).find_entity(question)
    assert found == (mem.kb.resolve("Asha") if case == "one" else None)


@pytest.mark.parametrize("question,case", FIND_CASES, ids=[c[1] + str(i) for i, c in enumerate(FIND_CASES)])
def test_t16_t21_find_entity_reports_the_case(mem, question, case):
    world(mem)
    found = KnowledgeRetriever(mem.m).find_entity(question, report=True)
    assert found == ((mem.kb.resolve("Asha") if case == "one" else None), case)


# ---------------------------------------------------------------- T18 (Q15, P7)
def _fresh(code):
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True)


def test_t18_control_importing_engram_chat_does_not_import_the_new_module():
    """CONTROL: passes at 69da9fc and must keep passing (no import from engram_chat to the new module)."""
    r = _fresh("import sys, engram_chat; print('engram_knowledge.knowledge_text' in sys.modules)")
    assert (r.returncode, r.stdout.strip()) == (0, "False"), r.stderr


@pytest.mark.parametrize("code", [
    "import engram_knowledge.knowledge_text as m; from engram_knowledge import knowledge_section as f",   # submodule first
    "from engram_knowledge import knowledge_section as f; import engram_knowledge.knowledge_text as m",   # package first
], ids=["submodule-first", "package-first"])
def test_t18_the_new_module_imports_in_a_fresh_interpreter_and_is_exported(code):
    """Amendment 2, B3: the package's `knowledge_section` is the function in knowledge_text, in either import order."""
    r = _fresh(code + "; assert f is m.knowledge_section and callable(f); print('ok')")
    assert (r.returncode, r.stdout.strip()) == (0, "ok"), r.stderr


# ---------------------------------------------------------------- T19 (P5)
def test_t19_contradicting_sentences_are_not_shown(mem):
    a, = mem.chat(D1, [("Asha", "I work at Riverside Clinic.")])
    fid = mem.stored(a, "I", "Riverside Clinic", "works_at")
    c, = mem.chat(D1, [("Ben", "Asha does not work at Riverside Clinic.")])
    mem.kb.add_evidence(FactEvidence.create(fid, c, evidence_role="contradicts"))
    assert ask(mem, "Where does Asha work now?") == (
        block(fact(1, "Asha", "person", "Works at", "Riverside Clinic", OPEN_D1), said(D1, "Asha", "I work at Riverside Clinic.")), "")


# ---------------------------------------------------------------- T20 (P4)
def test_t20_a_contraction_is_not_taken_as_i(mem):
    world(mem)
    assert ask(mem, "I'm working where now?", speaker="Asha") == ("", R5)


# ---------------------------------------------------------------- T22 (Amendment 1: G-1, A-P1, A-P3)
def test_t22_a_sentence_with_two_roles_is_shown_once_in_its_role_for_the_first_fact(mem):
    """"My neighbour Ravi loves chess." supports Likes chess and is the name line of Likes green tea. Two facts said
    together: either may come first, so both of Amendment 1's A2 examples are accepted, and nothing else."""
    a, b = mem.chat(D1, [("Asha", "My neighbour Ravi loves chess."), ("Asha", "He loves green tea.")])
    mem.stored(a, "Ravi", "chess", "likes", subject_kind="person")
    mem.stored(b, "Ravi", "green tea", "likes", subject_from=a, reading="Asha")
    chess_first = block(
        fact(1, "Ravi", "person", "Likes", "chess", OPEN_D1),
        said(D1, "Asha", "My neighbour Ravi loves chess.", "(also the name line for [2])"),
        fact(2, "Ravi", "person", "Likes", "green tea", OPEN_D1),
        said(D1, "Asha", "He loves green tea."),
        "  name line: see [1]")
    tea_first = block(
        fact(1, "Ravi", "person", "Likes", "green tea", OPEN_D1),
        said(D1, "Asha", "He loves green tea."),
        name_line(D1, "Asha", "My neighbour Ravi loves chess.", "(also supports [2])"),
        fact(2, "Ravi", "person", "Likes", "chess", OPEN_D1),
        "  said: see [1]")
    text, reason = ask(mem, "What does Ravi like now?")
    assert reason == "" and text in (chess_first, tea_first), text
    assert text.count("My neighbour Ravi loves chess.") == 1


# ---------------------------------------------------------------- T23 (Amendment 1: G-2, A-P2)
@pytest.mark.parametrize("budget", [BIG, 1], ids=["large-budget", "budget-1"])
def test_t23_with_no_supporting_sentence_to_show_the_reason_is_r11_whatever_the_budget(mem, budget):
    """Every returned fact has lost its supporting sentence; one keeps its name line, which never counts (Q5a)."""
    a, b = mem.chat(D1, [("Asha", "My neighbour Ravi is very kind."), ("Asha", "He loves green tea.")])
    c, = mem.chat(D1, [("Ben", "Ravi likes chess.")])
    lose_support(mem, mem.stored(b, "Ravi", "green tea", "likes", subject_from=a, reading="Asha", subject_kind="person"))
    lose_support(mem, mem.stored(c, "Ravi", "chess", "likes"))
    assert ask(mem, "What does Ravi like now?", budget) == ("", R11)
