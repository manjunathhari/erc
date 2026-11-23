"""Stage 2, Increment 4: reading a block of conversation, with the amended word-for-word rule.

Frozen specification and test plan: claude/engram-stage2-inc4-spec-draft5-revision2.md, frozen 21 November 2026,
07:25 IST (SHA-256 16a1c876db77c448bb5cd099faa5d5f329e9bb5de07b2bd8388742579698d4db), with contract Amendment 9
(claude/engram-wr-amendment9.md, SHA-256 a677654b22a430a36ad1e5ebda54e18b8cc8d55347062b73f388b87bdeacfe3a), in force from
the freeze. Freeze record: claude/engram-stage2-inc4-freeze-record.md. Section and group numbers below are the
specification's (K1 to K12, section 7.1).

  K1  readings (B-1 to B-6)            K7  steps 3 and 4: the condition and A7 checks on the name line (Q9)
  K2  the block prompt (N7)            K8  things borrow nothing (Q13)
  K3  parsing (N8)                     K9  deletion (Q8, R4-3)
  K4  a borrowed name stored           K10 unchanged without the new arguments
  K5  steps 2a to 2e                   K11 shapes of the acceptance sentences
  K6  the Q10 qualification            K12 D2-1: what step 1 rejects stays rejected

Fixed, hand-written proposals only; no model is called. Every sentence is made up. None is LoCoMo text.

TESTS FIRST. This file is written before the build. Until Increment 4 is built, every test whose name begins with
test_new_ is expected to FAIL; every test whose name begins with test_control_ passes before and after the build.
"""
import dataclasses
import hashlib
import json

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.fact_validator import ACCEPTED, REJECTED, UNCERTAIN
from engram_knowledge.schema import SCHEMA_VERSION
from engram_knowledge.state_engine import StateEngine

SAID = "12 June, 2025"
PEOPLE = ("Asha", "Ben")

# Section 2.6: the six reason strings, exact, each with the plain apostrophe U+0027 where it has one.
R2A = "the sentence is shown for reading only"
R2B = "the name's line is the main line"
R2B2 = "the name's line is not in this chat"
R2C = "the sentence does not refer to a person"
R2D = "a relation is borrowed only from the same speaker"
R2E = "another name is as near or nearer"
NEW_REASONS = (R2A, R2B, R2B2, R2C, R2D, R2E)

# Reason texts of existing checks, unchanged.
HOLD = "the source gives someone else's words"                  # A7 (Increment 3, DQ-5)
CONDITION = "the source states a condition"                     # S3 (Increment 1)
NOT_IN_SOURCE = "'Tobias' is not in its source"                 # the resolver (D1-12.10)
NOT_COPIED = "object not copied word for word from the sentence"
ACROSS = "first person across different speakers"
HYPOTHETICAL = "the source may be hypothetical"

# Today's writer prompt, unchanged by Increment 4 (N7): SHA-256 of engram_structure.WRITER_PROMPT, at 84abfa7 until Increment 5's approved version B.
PROMPT_SHA256 = "0a7a0718248d69d2e17f728473d5e4effc5abaf669fd400b90c07424fb6fe878"   # Increment 5: approved version B (writer_B.txt); was 3d1781cb…d31c
# Section 4: the block prompt's exact text "is pinned by its own SHA-256 in the new test file once approved". Approved:
# the block prompt, Draft 2 (claude/engram-stage2-inc4-block-prompt-draft2.md), his word of 21 November 08:05, until
# Increment 5's approved version B. This is the SHA-256 of that prompt filled for the block of
# test_new_k2_the_block_prompt_is_pinned_by_its_own_sha256.
BLOCK_PROMPT_SHA256 = "5f97f1d7d898445be55cd6e59f15ff6bd801af1b11c444bef2483fd1763392fd"   # Increment 5: rendered from approved block_B.txt; was d4e398b2…cf72

# Section 4: the two instructions the block prompt adds, word for word.
READ_ONLY_RULE = "Give facts only from lines that are not marked (read only)."
BORROW_RULE = ('If a line names a person only as he, she, him, her, his or hers, you may copy that person\'s name from one '
               'other line of the chat and give that line\'s id as "subject_from". Copy the name word for word. Never copy '
               'anything else from another line.')
# P-7 of the approved block prompt, Draft 2 (N9 (b), 9A2, 9A3): the two sentences placed before BORROW_RULE.
RELATION_RULE = ('Below, a person\'s name also means a relation without a name, such as "my sister". A name may be copied from '
                 'a line of either speaker; a relation without a name may be copied only from a line said by the same speaker as '
                 'the line that states the fact.')
LIST_RULE = ('When a line lists several things, such as "tea, coffee and juice", give each thing its own entry and never put '
             'the list in one object.')

# ------------------------------------------------------------------ made-up chats used across the groups
BOAT = "Last month Tobias bought an old sailing boat."               # names Tobias, not as its first word
MARINA = "He keeps it at the marina by the bridge."                  # refers to a person, names nobody
HARBOUR = "He works at the harbour office now."
SHOP = "Last month my cousin Tobias opened a bicycle repair shop."   # a relation with a name: names Tobias
MILL = "He fixes bicycles in the old mill."
SISTER = "Last week my sister moved back to town."                   # a relation without a name (N9)
PIANO = "She teaches piano at the music school."
TOLD = "He told Tobias the shop opens at nine."                      # the borrowed name also in the main line
OTHER_BOAT = "Last month Marek bought an old sailing boat."           # names Marek only
CHAT = "I will ring you after lunch."                                # a line of the other person, no name


def _new(fn):
    """A function of section 3 that does not exist before the build: every test that reaches it fails until then."""
    return getattr(S, fn)


class Mem:
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.layer = S.StructureLayer(self.m.db)
        self.kb = self.layer.kb

    def chat(self, lines):
        """Stores one chat, its lines in order; returns their sentence ids."""
        self.m.open_chat(SAID)
        sids = [self.m.add(who, text, date=SAID) for who, text in lines]
        self.m.close_chat(write_note=False)
        return sids

    def file(self, sid, subject, obj, word="other", subject_from=None, reading=None, kind="", subject_kind=None):
        """Section 3: StructureLayer.file with its two new optional arguments; Increment 5 (P-2): subject_kind when given."""
        extra = {} if subject_kind is None else dict(subject_kind=subject_kind)
        return self.layer.file(sid, subject, obj, kind, word=word, subject_from=subject_from, reading=reading, **extra)

    def facts(self):
        return self.m.db.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0]

    def reviews(self):
        return len(self.kb.reviews())

    def roles(self, fact_id):
        return {int(e.source_id): e.evidence_role for e in self.kb.get(fact_id).evidence}

    def subject_of(self, fact_id):
        return self.kb.get(fact_id).fact.subject_id

    def review_sids(self, review_id):
        return sorted(r[0] for r in self.m.db.execute("SELECT sid FROM review_sources WHERE review_id=?", (review_id,)))

    def candidate(self, review_id):
        return json.loads(self.kb.review(review_id)["candidate"])


@pytest.fixture
def mem(tmp_path):
    m = Mem(tmp_path)
    yield m
    m.m.close()


def stored(out):
    assert out.verdict == ACCEPTED and out.fact_id, (out.verdict, out.reasons)
    return out.fact_id


def held_with(out, reason):
    assert out.verdict == UNCERTAIN and out.reasons == (reason,), (out.verdict, out.reasons)


def rejected_not_queued(mem, out, reason=None):
    assert out.verdict == REJECTED and out.review_id is None and out.fact_id is None, (out.verdict, out.reasons)
    if reason is not None: assert reason in out.reasons, out.reasons
    assert mem.facts() == 0 and mem.reviews() == 0


# ------------------------------------------------------------------ K1: readings (B-1 to B-6)
def _lines(*spoken):
    return [(f"L{i}", who, text) for i, (who, text) in enumerate(spoken, 1)]


def readings(lines, people=PEOPLE):
    return _new("readings")(lines, date=SAID, people=people)


def test_new_k1_one_reading_per_person_in_the_order_they_first_speak():
    out = readings(_lines(("Ben", CHAT), ("Asha", BOAT), ("Ben", "My brother sold his car."), ("Asha", MARINA)))
    assert [who for who, _ in out] == ["Ben", "Asha"]


def test_new_k1_a_person_and_an_assistant_give_one_reading():
    out = readings(_lines(("User", BOAT), ("Assistant", "What a lovely boat that is."), ("User", MARINA)), people=("User", "Assistant"))
    assert [who for who, _ in out] == ["User"]


def test_new_k1_assistant_system_and_tool_lines_are_not_in_the_block():
    lines = _lines(("User", BOAT), ("Assistant", "What a lovely boat that is."), ("system", "Be brief."),
                   ("tool:search", "No results."), ("User", MARINA))
    [(who, block)] = readings(lines, people=("User", "Assistant"))
    assert [b.line_id for b in block] == ["L1", "L5"]


def test_new_k1_the_block_keeps_every_person_line_in_order_with_its_id_speaker_and_text():
    lines = _lines(("Asha", BOAT), ("Ben", CHAT), ("Asha", MARINA))
    for _, block in readings(lines):
        assert [(b.line_id, b.speaker, b.text) for b in block] == lines


def test_new_k1_the_reading_speakers_passing_line_is_citable():
    out = dict(readings(_lines(("Asha", BOAT), ("Ben", CHAT), ("Asha", MARINA))))
    assert [b.citable for b in out["Asha"]] == [True, False, True]


def test_new_k1_the_other_persons_passing_line_is_read_only():
    out = dict(readings(_lines(("Asha", BOAT), ("Ben", "My brother sold his car."))))
    assert S.first_filter("Ben", "My brother sold his car.", SAID, PEOPLE).passes      # it passes the first filter
    assert [b.citable for b in out["Asha"]] == [True, False]
    assert [b.citable for b in out["Ben"]] == [False, True]


def test_new_k1_the_reading_speakers_line_the_filter_drops_is_read_only():
    question = "Did you ever meet Tobias?"
    assert not S.first_filter("Asha", question, SAID, PEOPLE).passes
    out = dict(readings(_lines(("Asha", question), ("Asha", MARINA))))
    assert [b.citable for b in out["Asha"]] == [False, True]


def test_new_k1_a_person_whose_lines_all_drop_still_has_a_reading():
    out = dict(readings(_lines(("Asha", BOAT), ("Ben", "Thanks, Asha!"))))
    assert set(out) == {"Asha", "Ben"} and [b.citable for b in out["Ben"]] == [False, False]


def test_new_k1_a_citable_lines_kind_is_the_first_filters():
    out = dict(readings(_lines(("Asha", BOAT), ("Asha", "I think Tobias is the best sailor in town."))))
    assert [b.kind for b in out["Asha"]] == [S.first_filter("Asha", t, SAID, PEOPLE).kind for t in
                                             (BOAT, "I think Tobias is the best sailor in town.")]


def test_new_k1_blockline_is_a_frozen_dataclass_with_the_five_fields():
    B = _new("BlockLine")
    assert [f.name for f in dataclasses.fields(B)] == ["line_id", "speaker", "text", "citable", "kind"]
    b = B("L1", "Asha", BOAT, True, "claim")
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.citable = False


AGREE = [  # chats whose stored speakers are the people (DQ-4)
    ("two people", [("Asha", BOAT), ("Ben", "My brother sold his car."), ("Asha", "Did you ever meet Tobias?"), ("Asha", MARINA)]),
    ("person and assistant", [("User", BOAT), ("Assistant", "What a lovely boat that is."), ("User", "Thanks!"), ("User", MARINA)]),
    ("one person only", [("Asha", BOAT), ("Asha", "Hi Ben!"), ("Asha", MARINA)]),
]


@pytest.mark.parametrize("cid,spoken", AGREE, ids=[a[0] for a in AGREE])
def test_new_k1_readings_and_filter_of_agree_on_identical_inputs(mem, cid, spoken):
    sids = mem.chat(spoken)
    people = tuple(dict.fromkeys(who for who, _ in spoken))           # the recorded speakers, in recorded order
    lines = [(str(s), who, text) for s, (who, text) in zip(sids, spoken)]
    for who, block in readings(lines, people=people):
        for b in block:
            want = b.speaker == who and mem.layer.filter_of(int(b.line_id)).passes
            assert b.citable == want, (who, b.text)


# ------------------------------------------------------------------ K2: the block prompt (N7)
def _block(lines, reading="Asha"):
    return dict(readings(lines))[reading]


def block_prompt(block):
    return _new("block_prompt")(block)


def test_new_k2_a_citable_line_is_shown_with_its_id_and_speaker():
    p = block_prompt(_block(_lines(("Asha", BOAT), ("Ben", CHAT))))
    assert f"L1 Asha: {BOAT}" in p.splitlines()


def test_new_k2_a_read_only_line_is_marked_after_its_id():
    p = block_prompt(_block(_lines(("Asha", BOAT), ("Ben", CHAT))))
    assert f"L2 (read only) Ben: {CHAT}" in p.splitlines()
    assert f"L1 (read only) Asha: {BOAT}" not in p


def test_new_k2_the_two_new_instructions_are_given_word_for_word():
    p = block_prompt(_block(_lines(("Asha", BOAT), ("Ben", CHAT))))
    assert READ_ONLY_RULE in p and BORROW_RULE in p


def test_new_k2_the_relation_instruction_p7_is_given_word_for_word_before_the_borrow_rule():
    p = block_prompt(_block(_lines(("Asha", BOAT), ("Ben", CHAT))))
    assert RELATION_RULE + " " + BORROW_RULE in p


def test_new_k2_the_json_shape_gains_subject_from():
    assert '"subject_from": "<line id>"' in block_prompt(_block(_lines(("Asha", BOAT))))


def test_new_k2_todays_rules_are_kept_the_list_sentence_included():
    p = block_prompt(_block(_lines(("Asha", BOAT))))
    assert LIST_RULE in p and S.VOCABULARY_WORDS in p and "Never use words that are not in the line." in p


def test_new_k2_the_block_prompt_is_pinned_by_its_own_sha256():
    p = block_prompt(_block(_lines(("Asha", BOAT), ("Ben", CHAT), ("Asha", MARINA))))
    assert BLOCK_PROMPT_SHA256 is not None
    assert hashlib.sha256(p.encode("utf-8")).hexdigest() == BLOCK_PROMPT_SHA256


def test_control_k2_todays_writer_prompt_is_unchanged_byte_for_byte():
    assert hashlib.sha256(S.WRITER_PROMPT.encode("utf-8")).hexdigest() == PROMPT_SHA256
    assert S.writer_prompt([("L1", BOAT)]) == S.WRITER_PROMPT.format(words=S.VOCABULARY_WORDS, lines=f"L1 {BOAT}")


# ------------------------------------------------------------------ K3: parsing (N8)
CITABLE, BLOCK = {"L1", "L3"}, {"L1", "L2", "L3"}       # L2 is read-only in this reading


def reply(*rows):
    return json.dumps({"facts": list(rows)})


def row(line="L3", subject="Tobias", obj="the marina by the bridge", word="other", **more):
    return dict(line=line, subject=subject, word=word, object=obj, **more)


def parse(text):
    return S.parse_proposals(text, CITABLE, block_lines=BLOCK)


@pytest.mark.parametrize("text", ["not json at all", "", None, '{"facts": "none"}', "[1, 2, 3]"],
                         ids=["prose", "empty", "none", "facts not a list", "a bare list"])
def test_new_k3_an_unreadable_reply_gives_nothing(text):
    assert parse(text) == []


def test_new_k3_an_empty_subject_or_object_is_dropped():
    assert parse(reply(row(subject=""), row(obj="  "))) == []


def test_new_k3_a_line_not_in_the_block_is_dropped():
    assert parse(reply(row(line="L9"))) == []


def test_new_k3_a_read_only_main_line_is_kept():
    [r] = parse(reply(row(line="L2", subject="I", obj=CHAT)))
    assert r["line"] == "L2"


@pytest.mark.parametrize("given", ["L1", "L3", "L9", "sid-404"], ids=["a block line", "equal to line", "unknown", "outside"])
def test_new_k3_subject_from_is_kept_as_given_whatever_it_is(given):
    [r] = parse(reply(row(subject_from=given)))
    assert r["subject_from"] == given and r["line"] == "L3"


def test_new_k3_never_raises_on_odd_rows():
    out = parse('{"facts": [1, "x", null, {"line": 3}, {"line": "L3", "subject": 5, "object": 6}]}')
    assert [{k: r[k] for k in ("line", "subject", "word", "object")} for r in out] == [
        dict(line="L3", subject="5", word="other", object="6")]


TODAY = [  # (reply, today's result with valid lines {"L1", "L3"}), measured at 84abfa7
    (reply(row(), row(line="L2")), [dict(line="L3", subject="Tobias", word="other", object="the marina by the bridge")]),
    (reply(row(subject_from="L1")), [dict(line="L3", subject="Tobias", word="other", object="the marina by the bridge")]),
    (reply(row(word="Works_At "), row(word="Works_At ")), [dict(line="L3", subject="Tobias", word="works_at", object="the marina by the bridge")]),
    ("nothing", []),
]


@pytest.mark.parametrize("text,want", TODAY, ids=["read-only dropped", "subject_from ignored", "repeat dropped", "unreadable"])
def test_control_k3_without_block_lines_parsing_is_exactly_todays(text, want):
    assert S.parse_proposals(text, CITABLE) == want


# ------------------------------------------------------------------ K4: a borrowed name stored (Q4, Q5, Q6, Q7, N9)
def test_new_k4_a_name_borrowed_from_the_speakers_line_before_is_stored_under_that_name(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", MARINA)])
    fid = stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))
    assert mem.kb.entity(mem.subject_of(fid)).canonical_name == "Tobias"


def test_new_k4_the_main_line_supports_and_the_name_line_qualifies(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", MARINA)])
    fid = stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))
    assert mem.roles(fid) == {b: "supports", a: "qualifies"}


def test_new_k4_a_relation_with_a_name_keeps_its_alias_on_the_name_line(mem):
    a, b = mem.chat([("Asha", SHOP), ("Asha", MILL)])
    fid = stored(mem.file(b, "my cousin Tobias", "bicycles", subject_from=a, reading="Asha"))
    who = mem.subject_of(fid)
    assert [(x.alias, x.source_id) for x in mem.kb.aliases(who)] == [("Tobias", str(a))]
    assert mem.kb.entity(who).metadata.get("relation") == "cousin"


def test_new_k4_the_who_rule_reads_the_name_line(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", MARINA)])
    out = mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person")
    assert "the speaker of the source is someone else" not in out.reasons and out.verdict == ACCEPTED


def test_control_k4_without_a_name_line_the_same_proposal_is_rejected_as_today(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", MARINA)])
    out = mem.layer.file(b, "Tobias", "the marina by the bridge", word="other")
    rejected_not_queued(mem, out, NOT_IN_SOURCE)


def test_new_k4_a_name_from_the_other_persons_line_is_stored(mem):
    a, b = mem.chat([("Asha", BOAT), ("Ben", MARINA)])
    fid = stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Ben", subject_kind="person"))
    assert mem.kb.entity(mem.subject_of(fid)).canonical_name == "Tobias" and mem.roles(fid) == {b: "supports", a: "qualifies"}


def test_new_k4_a_name_from_a_line_after_is_stored(mem):
    b, a = mem.chat([("Asha", MARINA), ("Asha", BOAT)])
    fid = stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))
    assert mem.roles(fid) == {b: "supports", a: "qualifies"}


def test_new_k4_a_same_speaker_relation_without_a_name_is_stored(mem):
    a, b = mem.chat([("Asha", SISTER), ("Asha", PIANO)])
    fid = stored(mem.file(b, "my sister", "piano", subject_from=a, reading="Asha"))
    assert mem.kb.entity(mem.subject_of(fid)).metadata.get("relation") == "sister"


def test_new_k4_the_object_and_the_wording_come_from_the_main_line(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", MARINA)])
    fact = mem.kb.get(stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))).fact
    assert fact.object_value == "the marina by the bridge"
    assert fact.metadata["wording"] == S.version_key(MARINA, "the marina by the bridge")


def test_new_k4_a_later_repeat_adds_a_supporting_sentence(mem):
    a, b, c = mem.chat([("Asha", BOAT), ("Asha", MARINA), ("Asha", MARINA)])
    first = stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))
    again = stored(mem.file(c, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))
    assert again == first and mem.roles(first)[b] == "supports" and mem.roles(first)[c] == "supports"


# ------------------------------------------------------------------ K5: steps 2a to 2e (section 2.6, exact strings)
def test_new_k5_2a_the_other_persons_line_as_main_line_is_held(mem):
    a, b = mem.chat([("Asha", BOAT), ("Ben", "My brother sold his car.")])
    held_with(mem.file(b, "my brother", "his car", reading="Asha"), R2A)


def test_new_k5_2a_the_reading_speakers_dropped_line_as_main_line_is_held(mem):
    a2 = mem.chat([("Asha", "Thanks, got the job!"), ("Ben", CHAT)])[0]
    assert not mem.layer.filter_of(a2).passes
    held_with(mem.file(a2, "I", "the job", reading="Asha"), R2A)


def test_new_k5_2b_the_name_line_is_the_main_line_itself(mem):
    [b] = mem.chat([("Asha", TOLD)])
    held_with(mem.file(b, "Tobias", "the shop opens at nine", subject_from=b, reading="Asha"), R2B)


@pytest.mark.parametrize("where", ["unknown", "another chat"])
def test_new_k5_2b_prime_the_name_line_is_not_in_this_chat(mem, where):
    other = mem.chat([("Asha", BOAT)])[0]
    [b] = mem.chat([("Asha", TOLD)])
    given = "L99" if where == "unknown" else other
    held_with(mem.file(b, "Tobias", "the shop opens at nine", subject_from=given, reading="Asha"), R2B2)


def test_new_k5_2c_a_main_line_with_none_of_the_six_words_is_held(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", "The bakery opens at seven now.")])
    held_with(mem.file(b, "Tobias", "seven", subject_from=a, reading="Asha"), R2C)


def test_new_k5_2c_they_alone_borrows_nothing(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", "They moved to the coast last year.")])
    held_with(mem.file(b, "Tobias", "the coast", subject_from=a, reading="Asha"), R2C)


def test_new_k5_2d_a_relation_from_the_other_persons_line_is_held_at_step_1(mem):
    # T-1, his decision (b) of 21 November 07:41: the frozen specification is unchanged and this one test is corrected.
    # The resolver reads the name line as well as the main line (Q7), so with two speakers it holds "my sister" at step 1
    # ("first person across different speakers") before step 2d is reached, and Q10 keeps step 1's reason. The proposal
    # is held and nothing is stored; 2d's own reason is not given.
    a, b = mem.chat([("Ben", "Last week my sister moved back to town."), ("Asha", PIANO)])
    out = mem.file(b, "my sister", "piano", subject_from=a, reading="Asha")
    assert out.verdict == UNCERTAIN and ACROSS in out.reasons and R2D not in out.reasons
    assert mem.facts() == 0 and mem.reviews() == 1


NEAR = [  # (case, the chat, index of the name line, index of the main line)
    ("a tie", [("Asha", BOAT), ("Asha", MARINA), ("Asha", "Last week Marek painted the hull blue.")], 0, 1),
    ("two names in the nearest line", [("Asha", "Last month Tobias and Marek bought an old sailing boat."), ("Asha", MARINA)], 0, 1),
    ("a nearer place", [("Asha", BOAT), ("Asha", "Then we sailed it to Brighton."), ("Asha", MARINA)], 0, 2),
    ("the other persons relation nearer (D2-3)", [("Asha", BOAT), ("Ben", "Funny, my brother wants one too."), ("Asha", MARINA)], 0, 2),
]


@pytest.mark.parametrize("cid,spoken,name,main", NEAR, ids=[n[0] for n in NEAR])
def test_new_k5_2e_another_name_as_near_or_nearer_is_held(mem, cid, spoken, name, main):
    sids = mem.chat(spoken)
    held_with(mem.file(sids[main], "Tobias", "the marina by the bridge", subject_from=sids[name], reading="Asha"), R2E)


def test_control_k5_no_reason_string_has_a_curly_apostrophe():
    assert all("\u2019" not in r for r in NEW_REASONS) and R2B.count("'") == R2B2.count("'") == 1


# ------------------------------------------------------------------ K6: the Q10 qualification
def test_new_k6_a_borrowed_proposal_whose_object_is_not_in_the_main_line_stays_rejected(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", MARINA)])
    rejected_not_queued(mem, mem.file(b, "Tobias", "an old sailing boat", subject_from=a, reading="Asha"), NOT_COPIED)


def test_new_k6_a_rejection_on_a_read_only_main_line_is_not_turned_into_a_hold(mem):
    a, b = mem.chat([("Asha", BOAT), ("Ben", MARINA)])
    rejected_not_queued(mem, mem.file(b, "Tobias", "an old sailing boat", subject_from=a, reading="Asha"), NOT_COPIED)


def test_new_k6_a_proposal_held_at_step_1_keeps_its_step_1_reason(mem):
    a, b, c = mem.chat([("Asha", BOAT), ("Asha", "Maybe he will sell the boat in spring."), ("Asha", OTHER_BOAT)])
    out = mem.file(b, "Tobias", "the boat", subject_from=a, reading="Asha")          # 2e would hold it too (a tie)
    assert out.verdict == UNCERTAIN and HYPOTHETICAL in out.reasons
    assert not set(out.reasons) & set(NEW_REASONS)


def test_new_k6_no_step_turns_a_hold_into_a_store(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", "Maybe he will sell the boat in spring.")])
    out = mem.file(b, "Tobias", "the boat", subject_from=a, reading="Asha")
    assert out.verdict == UNCERTAIN and mem.facts() == 0 and mem.reviews() == 1


FIRST = [  # (case, the chat, name line, main line, proposal subject, object, the first failing step's reason)
    ("2a before 2c", [("Asha", BOAT), ("Ben", "The bakery opens at seven now.")], 0, 1, "Tobias", "seven", R2A),
    ("2c before 2e", [("Asha", BOAT), ("Asha", "The bakery opens at seven now."), ("Asha", OTHER_BOAT)], 0, 1, "Tobias", "seven", R2C),
    ("2e before step 3", [("Asha", "If the weather holds, Tobias will race on Sunday."), ("Asha", MARINA), ("Asha", OTHER_BOAT)], 0, 1,
     "Tobias", "the marina by the bridge", R2E),
    ("2a before step 4", [("Asha", BOAT), ("Ben", 'He says "I will win it this year".')], 0, 1, "Tobias", "win it", R2A),
]


@pytest.mark.parametrize("cid,spoken,name,main,subject,obj,reason", FIRST, ids=[f[0] for f in FIRST])
def test_new_k6_the_first_failing_step_in_table_order_gives_the_reason(mem, cid, spoken, name, main, subject, obj, reason):
    sids = mem.chat(spoken)
    held_with(mem.file(sids[main], subject, obj, subject_from=sids[name], reading="Asha"), reason)


# ------------------------------------------------------------------ K7: steps 3 and 4 on the name line (Q9 (i), (ii))
def test_new_k7_a_condition_in_the_name_line_holds(mem):
    a, b = mem.chat([("Asha", "If the weather holds, Tobias will race on Sunday."), ("Asha", MARINA)])
    held_with(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha"), CONDITION)


def test_new_k7_a_condition_in_the_main_line_holds_as_today(mem):
    a, b = mem.chat([("Asha", BOAT), ("Asha", "If it rains, he keeps the boat in the shed.")])
    out = mem.file(b, "Tobias", "the shed", subject_from=a, reading="Asha")
    assert out.verdict == UNCERTAIN and CONDITION in out.reasons


OTHER_MARKERS = [  # Increment 1 markers other than the condition: not read on the name line (Q9 (i))
    ("near miss", "Last summer Tobias almost won the regatta."),
    ("opinion", "I think Tobias is the best sailor in town."),
    ("passing state", "Today Tobias is exhausted from the trip."),
]


@pytest.mark.parametrize("cid,name_line", OTHER_MARKERS, ids=[o[0] for o in OTHER_MARKERS])
def test_new_k7_other_increment_1_markers_in_the_name_line_do_not_hold(mem, cid, name_line):
    a, b = mem.chat([("Asha", name_line), ("Asha", MARINA)])
    stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))


def test_new_k7_someone_elses_words_in_the_name_line_hold_with_the_a7_reason_and_no_filter_note(mem):
    a, b = mem.chat([("Asha", 'The paper said "Tobias runs the ferry".'), ("Asha", MARINA)])
    out = mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha")
    held_with(out, HOLD)
    assert "filter_note" not in mem.candidate(out.review_id) and mem.facts() == 0


def test_new_k7_the_note_comes_from_the_main_line_only(mem):
    a, b = mem.chat([("Asha", "Maybe Tobias will open a bakery."), ("Asha", MARINA)])
    assert mem.layer.filter_of(a).note == "uncertain_or_conditional_content"
    assert mem.layer.filter_of(b).note == "unresolved_context_reference"
    fid = stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha", subject_kind="person"))
    assert mem.kb.get(fid).fact.metadata.get("filter_note") == "unresolved_context_reference"


# ------------------------------------------------------------------ K8: things borrow nothing (Q13)
NAMED = "He named it Spoke and Chain."
CORNER = "It is on the corner near the old mill."


def test_new_k8_a_things_name_borrowed_for_a_line_about_it_is_held(mem):
    a, b = mem.chat([("Asha", NAMED), ("Asha", CORNER)])
    held_with(mem.file(b, "Spoke and Chain", "the corner near the old mill", subject_from=a, reading="Asha"), R2C)


def test_control_k8_a_subject_it_is_held_as_today(mem):
    a, b = mem.chat([("Asha", NAMED), ("Asha", CORNER)])
    out = mem.layer.file(b, "It", "the corner near the old mill", word="other")
    assert out.verdict == UNCERTAIN and "'It' does not say who" in out.reasons


def test_new_k8_a_subject_it_with_a_name_line_is_held_as_today_at_step_1(mem):
    a, b = mem.chat([("Asha", NAMED), ("Asha", CORNER)])
    out = mem.file(b, "It", "the corner near the old mill", subject_from=a, reading="Asha")
    assert out.verdict == UNCERTAIN and "'It' does not say who" in out.reasons and mem.facts() == 0


# ------------------------------------------------------------------ K9: deletion (Q8 (a), R4-3)
def _cousin(mem):
    a, b = mem.chat([("Asha", SHOP), ("Asha", MILL)])
    fid = stored(mem.file(b, "my cousin Tobias", "bicycles", subject_from=a, reading="Asha"))
    return a, b, fid


def test_new_k9_deleting_the_main_line_invalidates_the_fact_and_erases_its_subject(mem):
    a, b, fid = _cousin(mem)
    mem.m.forget_sentence(b)
    fact = mem.kb.get(fid).fact
    assert (fact.status, fact.subject_id, fact.object_value) == ("invalidated", None, None)


def test_new_k9_deleting_the_name_line_sends_the_fact_to_review(mem):
    a, b, fid = _cousin(mem)
    mem.m.forget_sentence(a)
    fact = mem.kb.get(fid).fact
    assert (fact.status, fact.note) == ("needs_review", "A linked sentence was deleted")


def test_new_k9_deleting_the_name_line_keeps_the_facts_subject_unchanged(mem):
    a, b, fid = _cousin(mem)
    who = mem.subject_of(fid)
    mem.m.forget_sentence(a)
    assert mem.subject_of(fid) == who and mem.kb.get(fid).fact.object_value == "bicycles"


def test_new_k9_deleting_the_name_line_removes_the_alias_and_keeps_the_entity(mem):
    a, b, fid = _cousin(mem)
    who = mem.subject_of(fid)
    mem.m.forget_sentence(a)
    assert mem.kb.aliases(who) == [] and mem.kb.entity(who) is not None


def _held_with_both(mem):
    a, b, c = mem.chat([("Asha", BOAT), ("Asha", MARINA), ("Asha", OTHER_BOAT)])
    out = mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha")       # a tie: 2e
    held_with(out, R2E)
    assert mem.review_sids(out.review_id) == sorted((a, b))
    return a, b, out


def test_new_k9_a_held_proposal_cites_both_lines(mem):
    _held_with_both(mem)


@pytest.mark.parametrize("which", ["name line", "main line"])
def test_new_k9_a_held_proposal_is_removed_whole_when_either_line_goes(mem, which):
    a, b, out = _held_with_both(mem)
    mem.m.forget_sentence(a if which == "name line" else b)
    assert mem.kb.review(out.review_id) is None and mem.reviews() == 0


# ------------------------------------------------------------------ K10: unchanged without the new arguments
UNCHANGED = [  # (speaker, sentence, subject, object, word, today's verdict and reasons), measured at 84abfa7; "a name" changed by Increment 5 (K-10, his R-4)
    ("Asha", "I work at the harbour office.", "I", "the harbour office", "works_at", (ACCEPTED, ())),
    ("Asha", BOAT, "Tobias", "an old sailing boat", "other", (UNCERTAIN, ("the kind of 'Tobias' is not known",))),  # Increment 5, K-10
    ("Asha", MARINA, "He", "the marina by the bridge", "other", (UNCERTAIN, ("'He' does not say who",))),
    ("Asha", MARINA, "Tobias", "the marina by the bridge", "other", (REJECTED, (NOT_IN_SOURCE,))),
]


@pytest.mark.parametrize("speaker,text,subject,obj,word,want", UNCHANGED, ids=["works_at", "a name", "a pronoun", "absent name"])
def test_control_k10_a_proposal_without_the_new_arguments_files_exactly_as_today(mem, speaker, text, subject, obj, word, want):
    [sid] = mem.chat([(speaker, text)])
    out = mem.layer.file(sid, subject, obj, word=word)
    assert (out.verdict, out.reasons) == want


@pytest.mark.parametrize("speaker,text,subject,obj,word,want", UNCHANGED[:3], ids=["works_at", "a name", "a pronoun"])
def test_new_k10_a_citable_proposal_with_reading_and_no_name_line_files_as_today(mem, speaker, text, subject, obj, word, want):
    [sid] = mem.chat([(speaker, text)])
    out = mem.file(sid, subject, obj, word=word, reading=speaker)
    assert (out.verdict, out.reasons) == want


def test_new_inc5_k10_a_name_with_a_kind_is_stored(mem):
    """Increment 5 (his R-4, 22 November 22:16): the "a name" case of UNCHANGED, with subject_kind given, is stored."""
    [sid] = mem.chat([("Asha", BOAT)])
    out = mem.file(sid, "Tobias", "an old sailing boat", subject_kind="person")
    assert (out.verdict, out.reasons) == (ACCEPTED, ())


def test_control_k10_the_schema_version_is_4():
    assert SCHEMA_VERSION == 4


def test_new_k10_the_state_engine_counts_only_the_main_lines_speaker(mem):
    a, b = mem.chat([("Asha", BOAT), ("Ben", MARINA)])
    fid = stored(mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Ben", subject_kind="person"))
    assert StateEngine(mem.kb)._speakers(mem.kb.get(fid)) == {"ben"}


# ------------------------------------------------------------------ K11: shapes of the acceptance sentences (D3:13.2, D17:25.3)
SHAPES = [  # acceptance sentence, the line before (names a thing), made-up sentence of its shape, its object, its own subject,
           # and today's verdict and reasons for that subject without a name line (measured at 84abfa7; known limit L1); D17:25.3 changed by Increment 5 (K-10, his R-4)
    ("D3:13.2", "Last spring we drove the coast road to Porto.", "It was the longest drive of my life.", "the longest drive",
     "It", (UNCERTAIN, ("'It' does not say who",))),
    ("D17:25.3", "In May we spent a week walking in Galicia.", "That trip changed my whole outlook.", "my whole outlook",
     "That trip", (UNCERTAIN, ("the kind of 'That trip' is not known",))),  # Increment 5, K-10 ("trip" is on no list)
]


@pytest.mark.parametrize("sid,before,text,obj,own,today", SHAPES, ids=[s[0] for s in SHAPES])
def test_new_k11_a_things_name_from_the_line_before_is_not_borrowed(mem, sid, before, text, obj, own, today):
    a, b = mem.chat([("Asha", before), ("Asha", text)])
    held_with(mem.file(b, "Porto" if sid == "D3:13.2" else "Galicia", obj, subject_from=a, reading="Asha"), R2C)


@pytest.mark.parametrize("sid,before,text,obj,own,today", SHAPES, ids=[s[0] for s in SHAPES])
def test_control_k11_without_a_name_line_it_files_as_today_with_its_note(mem, sid, before, text, obj, own, today):
    a, b = mem.chat([("Asha", before), ("Asha", text)])
    assert mem.layer.filter_of(b).note == "unresolved_context_reference"
    out = mem.layer.file(b, own, obj, word="other")
    assert (out.verdict, out.reasons) == today


def test_new_inc5_k11_that_trip_with_a_kind_is_stored(mem):
    """Increment 5 (his R-4, 22 November 22:16): SHAPES' D17:25.3, its own subject with subject_kind given, is stored."""
    _, before, text, obj, own, _ = SHAPES[1]
    a, b = mem.chat([("Asha", before), ("Asha", text)])
    out = mem.file(b, own, obj, subject_kind="thing")
    assert (out.verdict, out.reasons) == (ACCEPTED, ())


# ------------------------------------------------------------------ K12: D2-1, what step 1 rejects stays rejected
def test_new_k12_a_name_not_in_its_name_line_nor_the_main_line_is_rejected_and_not_queued(mem):
    a, b = mem.chat([("Asha", OTHER_BOAT), ("Asha", MARINA)])
    rejected_not_queued(mem, mem.file(b, "Tobias", "the marina by the bridge", subject_from=a, reading="Asha"), NOT_IN_SOURCE)


BAD = ["unknown", "equal to line", "another chat"]


def _bad(mem, where, main_text):
    other = mem.chat([("Asha", BOAT)])[0]
    [b] = mem.chat([("Asha", main_text)])
    return b, {"unknown": "L99", "equal to line": b, "another chat": other}[where]


@pytest.mark.parametrize("where", BAD)
def test_new_k12_a_bad_name_line_with_the_name_not_in_the_main_line_is_rejected_and_not_queued(mem, where):
    b, given = _bad(mem, where, MARINA)
    out = mem.file(b, "Tobias", "the marina by the bridge", subject_from=given, reading="Asha")
    assert out.verdict == REJECTED and NOT_IN_SOURCE in out.reasons and out.review_id is None
    assert mem.reviews() == 0 and mem.facts() == 0


@pytest.mark.parametrize("where,reason", [("unknown", R2B2), ("equal to line", R2B), ("another chat", R2B2)], ids=BAD)
def test_new_k12_the_same_with_the_name_also_in_the_main_line_is_held(mem, where, reason):
    b, given = _bad(mem, where, TOLD)
    held_with(mem.file(b, "Tobias", "the shop opens at nine", subject_from=given, reading="Asha"), reason)


def test_new_k12_the_parser_keeps_every_one_of_these(mem):
    rows = [row(subject_from=g) for g in ("L99", "L3", "sid-404")] + [row(line="L1", subject="Tobias", obj="x", subject_from="L3")]
    assert [r["subject_from"] for r in parse(reply(*rows))] == ["L99", "L3", "sid-404", "L3"]
