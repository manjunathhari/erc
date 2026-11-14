"""WR-C (writing layer contract v1, sections 1.2 to 1.4 and 6.2, with Amendment 4): base 2's proposal carries a vocabulary
word, and the record carries it.

Settled points tested here:
  1.2    the proposal holds a word from the 31 or "other"; a sentence may give several proposals (WP-2)
  1.3 R1 predicate = the word (or base 2's wording for "other"); metadata.wording and metadata.vocabulary kept apart
  A1/C11 an "other" record takes the gate's type and is marked outside
  A8     the same fact said again is one record with two sources
  4A12   RM-a: a word the sentence does not support is held back; the fact is filed under its wording only
  4A13   RM-b: "my" + a thing is the speaker; "my" + a person is that person
  4A14   RM-c: a relative's name is filed under the relative, wording only, never reframed as parent_of
  L5     checked_by stays on every base 2 record, so the graph walk still finds it

Fixed proposals only. The real-model check (claude/engram-wr-real-model-check-r1.md) supplied the hard cases; no model is
called here. These tests do not depend on dates, so WR-C is assessable on its own (4A1).

Interface proposed in the tests-first package (section 2):
  StructureLayer.file(sid, subject, obj, kind="", word="")      word "" or "other" -> outside the vocabulary
  parse_proposals(...) -> [{line, subject, word, object}]
"""
import ast
import json
import os

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, UNCERTAIN, Candidate, KnowledgePipeline
from engram_knowledge.normalizer import PREDICATE_TYPES
from engram_knowledge.state_engine import StateEngine
from engram_knowledge.transition import slot_of

SAID = "2:15 pm on 12 June, 2025"


class Mem:
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.layer = S.StructureLayer(self.m.db)

    def say(self, text, said=SAID, speaker="User"):
        self.m.open_chat(said)
        sid = self.m.add(speaker, text, date=said)
        self.m.close_chat(write_note=False)
        return sid

    def file(self, text, subject, obj, word, said=SAID, sid=None):
        sid = sid or self.say(text, said)
        return self.layer.file(sid, subject, obj, S.gate("User", text, said)[1], word=word)

    def fact(self, out):
        assert out.verdict == ACCEPTED and out.fact_id, out
        return self.kb.get(out.fact_id).fact

    def who(self, f):
        return self.kb.entity(f.subject_id).canonical_name

    def records(self):
        return self.m.db.execute("SELECT predicate, metadata FROM knowledge_records ORDER BY recorded_at, fact_id").fetchall()


@pytest.fixture
def mem(tmp_path):
    w = Mem(tmp_path)
    yield w
    w.m.close()


# ---------------------------------------------------------------- 1.2: the writer's prompt and reply
def test_the_prompt_offers_every_vocabulary_word_and_other():
    p = S.writer_prompt([("D1:1", "I work at Manipal.")])
    assert '"word"' in p and '"other"' in p
    missing = [w for w in PREDICATE_TYPES if w not in p]
    assert missing == []                                    # read from the vocabulary in code, never a separate copy


def test_the_prompt_states_the_my_thing_rule():
    """4A13: the subject is no longer copied "exactly as written" for the speaker's own job, home or move."""
    p = S.WRITER_PROMPT.lower()                     # the template itself, so a line of the chat cannot satisfy it
    assert "my job" in p and '"i"' in p


def test_parse_keeps_the_word():
    reply = json.dumps({"facts": [dict(line="D1:1", subject="I", word="works_at", object="Manipal")]})
    assert S.parse_proposals(reply, {"D1:1"}) == [dict(line="D1:1", subject="I", word="works_at", object="Manipal")]


@pytest.mark.parametrize("given,kept", [(None, "other"), ("", "other"), ("other", "other"), ("employer", "other"),
                                        ("Works_At ", "works_at"), ("LIVES_IN", "lives_in")])
def test_parse_turns_a_missing_or_unknown_word_into_other(given, kept):
    row = dict(line="D1:1", subject="I", object="Manipal") | ({} if given is None else dict(word=given))
    assert S.parse_proposals(json.dumps({"facts": [row]}), {"D1:1"})[0]["word"] == kept


def test_parse_keeps_several_proposals_for_one_line_and_drops_an_exact_repeat():
    """WP-2: a sentence may state several facts. Only an identical proposal is dropped."""
    rows = [dict(line="D1:1", subject="I", word="lives_in", object="Pune"), dict(line="D1:1", subject="I", word="works_at", object="Infosys"),
            dict(line="D1:1", subject="I", word="works_at", object="Infosys")]
    got = S.parse_proposals(json.dumps({"facts": rows}), {"D1:1"})
    assert got == rows[:2]


@pytest.mark.parametrize("junk", ["", "no json", "{bad json", json.dumps({"facts": "x"}), json.dumps([1, 2])])
def test_parse_still_never_raises(junk):
    assert S.parse_proposals(junk, {"D1:1"}) == []


def test_oq3_the_prompt_does_not_ask_for_dates():
    """4A16: dates come only from the fixed rules, so the writer is never asked for them."""
    p = S.WRITER_PROMPT.lower()
    for asked in ('"dates"', '"date"', '"start"', '"end"', '"role"'):
        assert asked not in p


def test_oq3_dates_in_the_writers_reply_are_dropped_by_the_parser():
    reply = json.dumps({"facts": [dict(line="D1:1", subject="I", word="works_at", object="Apollo", date="1999",
                                       dates=[dict(value="1999", role="start")], start="1999", end="2001")]})
    [row] = S.parse_proposals(reply, {"D1:1"})
    assert set(row) == {"line", "subject", "word", "object"}


# ---------------------------------------------------------------- 1.3 R1, C14: the record carries the word
def test_a_vocabulary_record_has_the_word_as_predicate_and_keeps_its_wording(mem):
    text = "I work at Manipal."
    f = mem.fact(mem.file(text, "I", "Manipal", "works_at"))
    assert f.predicate == "works_at" and f.fact_type == PREDICATE_TYPES["works_at"]
    assert f.metadata["vocabulary"] == "in" and f.metadata["wording"] == S.version_key(text, "Manipal")
    assert f.metadata["checked_by"] == "rules " + S.RULES_VERSION and f.metadata["said_on"] == SAID     # L5; WP-7


@pytest.mark.parametrize("word", ["other", ""])
def test_an_other_record_keeps_the_wording_as_predicate_and_the_gates_type(mem, word):
    text = "I speak Kannada and Tamil."
    f = mem.fact(mem.file(text, "I", "Kannada and Tamil", word))
    assert f.predicate == S.version_key(text, "Kannada and Tamil") == f.metadata["wording"]
    assert f.metadata["vocabulary"] == "outside"
    assert f.fact_type == S.FACT_TYPE[S.gate("User", text, SAID)[1]]                                    # A1


def test_no_predicate_carries_a_marker(mem):
    mem.file("I speak Kannada and Tamil.", "I", "Kannada and Tamil", "other")
    mem.file("I work at Manipal.", "I", "Manipal", "works_at")
    for predicate, _ in mem.records():
        assert "other" not in predicate and ":" not in predicate


def test_every_record_carries_both_new_keys(mem):
    """C14 over a mixed set, including a held word (RM-a) and a person's fact."""
    mem.file("I work at Manipal.", "I", "Manipal", "works_at")
    mem.file("I speak Kannada and Tamil.", "I", "Kannada and Tamil", "other")
    mem.file("I was diagnosed with asthma in 2015.", "I", "asthma", "status")
    mem.file("My sister lives in Paris.", "my sister", "Paris", "lives_in")
    rows = mem.records()
    assert len(rows) == 4
    for _, meta in rows:
        meta = json.loads(meta)
        assert meta["vocabulary"] in ("in", "outside") and meta["wording"] and meta["checked_by"] == "rules " + S.RULES_VERSION


def test_c11_an_outside_record_gets_no_state_slot(mem):
    f = mem.fact(mem.file("I speak Kannada and Tamil.", "I", "Kannada and Tamil", "other"))
    assert slot_of(f.predicate) is None


# ---------------------------------------------------------------- WP-2: several proposals from one sentence
def test_several_proposals_from_one_sentence_make_several_records(mem):
    text = "I live in Pune and work at Infosys."
    sid = mem.say(text)
    a = mem.fact(mem.file(text, "I", "Pune", "lives_in", sid=sid))
    b = mem.fact(mem.file(text, "I", "Infosys", "works_at", sid=sid))
    assert (a.predicate, b.predicate) == ("lives_in", "works_at") and a.fact_id != b.fact_id


# ---------------------------------------------------------------- A8: the same fact said again
def test_a8_the_same_fact_said_twice_is_one_record_with_two_sources(mem):
    first = mem.file("I work at Manipal.", "I", "Manipal", "works_at")
    again = mem.file("I work at Manipal.", "I", "Manipal", "works_at", said="9:00 am on 1 July, 2025")
    assert again.fact_id == first.fact_id and len(mem.kb.get(first.fact_id).evidence) == 2


def test_a8_a_different_object_is_a_second_record(mem):
    a = mem.file("I work at Manipal.", "I", "Manipal", "works_at")
    b = mem.file("I work at Apollo.", "I", "Apollo", "works_at", said="9:00 am on 1 July, 2025")
    assert a.fact_id != b.fact_id


def test_a8_two_wordings_of_one_fact_share_the_record(mem):
    """C11's shape without dates: the word, not the wording, decides that it is the same fact."""
    a = mem.file("I work at Manipal.", "I", "Manipal", "works_at")
    b = mem.file("I am working at Manipal.", "I", "Manipal", "works_at", said="9:00 am on 1 July, 2025")
    assert a.fact_id == b.fact_id


# ---------------------------------------------------------------- 4A12 (RM-a): an unsupported word is held back
def test_rm_a_a_word_the_sentence_does_not_support_is_held_and_the_fact_filed_by_its_wording(mem):
    text = "I was diagnosed with asthma in 2015."
    out = mem.file(text, "I", "asthma", "status")
    f = mem.fact(out)
    assert f.predicate == S.version_key(text, "asthma") and f.metadata["vocabulary"] == "outside"
    assert any(r.startswith("word held") and "status" in r for r in out.reasons)


def test_rm_a_a_held_word_never_reaches_the_state_engine(mem):
    out = mem.file("I was diagnosed with asthma in 2015.", "I", "asthma", "status")
    who = mem.fact(out).subject_id
    assert StateEngine(mem.kb).get_history(who, "status")["periods"] == []


# OQ-1 (decided 22:53): a fixed, status-specific support rule in the shared checker. "am", "im" and "is" alone no longer
# support status; only status's own state words do (single, married, divorced, retired, student, pregnant).
STATUS = [("I am single now.", "single", True), ("I am married.", "married", True), ("I am a student.", "student", True),
          ("I am retired.", "retired", True), ("I am divorced.", "divorced", True), ("I am pregnant.", "pregnant", True),
          ("I am allergic to penicillin.", "penicillin", False),
          ("I was diagnosed with asthma.", "asthma", False)]


@pytest.mark.parametrize("text,obj,supported", STATUS, ids=[t for t, _, _ in STATUS])
def test_oq1_base2_status_is_kept_only_when_a_state_word_supports_it(mem, text, obj, supported):
    out = mem.file(text, "I", obj, "status")
    f = mem.fact(out)
    if supported:
        assert f.predicate == "status" and f.metadata["vocabulary"] == "in"
    else:                                                    # word held; the fact is kept by its wording only (RM-a)
        assert f.predicate == S.version_key(text, obj) and f.metadata["vocabulary"] == "outside"
        assert StateEngine(mem.kb).get_history(f.subject_id, "status")["periods"] == []


@pytest.mark.parametrize("text,obj,supported", STATUS, ids=[t for t, _, _ in STATUS])
def test_oq1_classic_status_enters_the_slot_only_when_a_state_word_supports_it(mem, text, obj, supported):
    """The same shared rule on the classic back end. It has no wording-only fallback, so an unsupported status is held
    for review, as an unsupported word always was there, and nothing enters the status slot."""
    sid = mem.say(text)
    d, ref = KnowledgePipeline(mem.m.db).process(Candidate("I", "status", obj, (sid,), "", "test", "1"))
    if supported:
        assert d.verdict == ACCEPTED and mem.kb.get(ref).fact.predicate == "status"
    else:
        assert d.verdict == UNCERTAIN and "nothing in the source says status" in d.reasons
        assert mem.m.db.execute("SELECT count(*) FROM knowledge_records WHERE predicate='status'").fetchone()[0] == 0


def test_oq1_the_rule_is_restricted_to_status(mem):
    """attended is the only other word with a linking verb ("was") among its cue words; it must be untouched by OQ-1."""
    text = "I was there for the Pune meetup."
    f = mem.fact(mem.file(text, "I", "Pune meetup", "attended"))
    assert f.predicate == "attended" and f.metadata["vocabulary"] == "in"
    sid = mem.say(text, said="9:00 am on 1 July, 2025")
    d, _ = KnowledgePipeline(mem.m.db).process(Candidate("I", "attended", "Pune meetup", (sid,), "", "test", "1"))
    assert d.verdict == ACCEPTED


def test_rm_a_other_doubts_still_send_the_proposal_to_review(mem):
    """Holding the word never lets a doubtful sentence through: a negated fact is still uncertain and not stored."""
    out = mem.file("I do not work at Apollo.", "I", "Apollo", "works_at")
    assert out.verdict == UNCERTAIN and out.fact_id is None


# ---------------------------------------------------------------- 4A13 (RM-b): "my" + a thing is the speaker
@pytest.mark.parametrize("text,subject,obj,word", [
    ("My job is at Manipal.", "My job", "Manipal", "works_at"),
    ("My home has been in Mysore since 2019.", "My home", "Mysore", "lives_in"),
    ("My move to Chennai was in March 2023.", "My move", "Chennai", "moved_to"),
])
def test_rm_b_my_thing_is_filed_under_the_speaker(mem, text, subject, obj, word):
    f = mem.fact(mem.file(text, subject, obj, word))
    assert mem.who(f) == "User" and f.predicate == word


@pytest.mark.parametrize("text,subject,obj,word", [
    ("My sister lives in Paris.", "my sister", "Paris", "lives_in"),
    ("My husband works at Infosys.", "My husband", "Infosys", "works_at"),
    ("My daughter works at Infosys.", "My daughter", "Infosys", "works_at"),     # "daughter" is a cue word of parent_of, not of works_at
])
def test_rm_b_my_person_is_filed_under_that_person(mem, text, subject, obj, word):
    f = mem.fact(mem.file(text, subject, obj, word))
    assert mem.who(f) != "User" and f.predicate == word


def test_rm_b_holds_whatever_the_model_wrote_as_subject(mem):
    """The rule is enforced after the writer, so "My job" and "I" give the same record."""
    a = mem.fact(mem.file("My job is at Manipal.", "My job", "Manipal", "works_at"))
    b = mem.fact(mem.file("My job is at Manipal.", "I", "Manipal", "works_at", said="9:00 am on 1 July, 2025"))
    assert a.fact_id == b.fact_id


def test_oq2_with_other_the_subject_is_left_as_written(mem):
    """OQ-2 (22:55): the "my" + thing rule applies only with a vocabulary word. With "other" nothing changes from today."""
    f = mem.fact(mem.file("My job is at Manipal.", "My job", "Manipal", "other"))
    assert mem.who(f).lower() == "my job" and f.metadata["vocabulary"] == "outside"


# ---------------------------------------------------------------- 4A14 (RM-c): a relative's name
def test_rm_c_a_relatives_name_is_filed_under_the_relative_by_its_wording(mem):
    text = "My daughter is called Meera."
    f = mem.fact(mem.file(text, "My daughter", "Meera", "other"))
    assert mem.who(f) != "User"
    assert f.predicate == S.version_key(text, "Meera") and f.metadata["vocabulary"] == "outside"
    assert not [p for p, _ in mem.records() if p == "parent_of"]


# ---------------------------------------------------------------- L5: the graph walk still finds base 2's records
def test_l5_the_walk_finds_vocabulary_and_outside_records(mem):
    a = mem.fact(mem.file("I work at Manipal.", "I", "Manipal", "works_at"))
    b = mem.fact(mem.file("I speak Kannada and Tamil.", "I", "Kannada and Tamil", "other"))
    g = mem.layer.graph()
    assert a.fact_id in g.facts and b.fact_id in g.facts



# ---------------------------------------------------------------- OQ-5 (23:00): the benchmark runner passes the word
RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit_tools", "lme_gpt4o.py")


def _runner_file_call():
    """The runner's own layer.file(...) call, read from its source, so this tests the line the runner runs."""
    src = open(RUNNER, encoding="utf-8").read()
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "file" and isinstance(n.func.value, ast.Name) and n.func.value.id == "layer"]
    assert len(calls) == 1, "the runner should file proposals in exactly one place"
    return compile(ast.Expression(calls[0]), RUNNER, "eval")


def _file_as_the_runner_does(mem, text, proposal):
    sid = mem.say(text)
    p = dict(line="D1:1", kind=S.gate("User", text, SAID)[1]) | proposal
    return eval(_runner_file_call(), {}, dict(layer=mem.layer, sid_of={"D1:1": sid}, p=p))


def test_oq5_the_runner_passes_the_writers_word(mem):
    f = mem.fact(_file_as_the_runner_does(mem, "I work at Manipal.", dict(subject="I", object="Manipal", word="works_at")))
    assert f.predicate == "works_at" and f.metadata["vocabulary"] == "in"


def test_oq5_a_saved_proposal_without_a_word_is_filed_as_other(mem):
    """Proposals cached by earlier runs have no word: they must still file, outside the vocabulary."""
    text = "I work at Manipal."
    f = mem.fact(_file_as_the_runner_does(mem, text, dict(subject="I", object="Manipal")))
    assert f.predicate == S.version_key(text, "Manipal") and f.metadata["vocabulary"] == "outside"
