"""Stage 2, Increment 3: the first filter.

Frozen specification and test plan: claude/engram-stage2-inc3-spec-draft6.md, frozen 19 November 2026, 21:44 IST
(SHA-256 22012c72cd0893890ff59b3500c98d66403fc98a17a48523586cd50de5270f13). Section and group numbers below are that
document's (F1 to F11, section 7.1). Decisions: claude/engram-stage2-inc3-decisions.md.

  F1  the drop list (A3)                      F7  Increment 1 and 2 rules behind the filter (A10)
  F2  where a bare greeting ends (A4, 3.1)    F8  known limit L2: hearsay may be stored (A10)
  F3  no first person passes (S2-11)          F9  interfaces; gate and StructureLayer.file agree (DQ-4)
  F4  notes (A5, CF-2, DQ-2)                  F10 the delete cascade
  F5  still not passed (A6, DQ-1)             F11 shapes of the acceptance sentences
  F6  someone else's words held (A7, A7a)

Fixed, hand-written proposals only; no model is called. Every sentence is made up. None is LoCoMo text.

TESTS FIRST. This file is written before the build. Until Increment 3 is built, every test whose name begins with
test_new_ is expected to FAIL; every test whose name begins with test_control_ passes before and after the build.
"""
import hashlib
import json

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.fact_validator import ACCEPTED, REJECTED, UNCERTAIN
from engram_knowledge.learning import LearningDecision
from engram_knowledge.learning_queue import prepare_stored

SAID = "2:15 pm on 12 June, 2025"
PEOPLE = ("Asha", "Ben")

# The A7 hold's reason text (DQ-5, apostrophe U+0027 confirmed at 20:36).
HOLD = "the source gives someone else's words"
# The five note codes (section 3.2).
NOTES = {"unresolved_context_reference", "uncertain_or_conditional_content", "unsupported_content_kind",
         "attribution_not_confirmed", "interpreter_flagged_for_review"}
# The writer's prompt, unchanged by Increment 3 (A1): SHA-256 of engram_structure.WRITER_PROMPT at 4e7e635.
PROMPT_SHA256 = "3d1781cb36f24032fc4d2b154922162ee2545d296b02d84345018dab5e51d31c"

# Reason texts of the existing checks (Increments 1 and 2), unchanged.
CONDITION = "the source states a condition"
NEAR_MISS = "the source states a near miss"
OPINION = "an opinion about something else"
INDEFINITE = "an indefinite person is not stored"
OUR = "'our' does not say whose"


def first_filter(*args, **kw):
    """The new function of section 4.1. Before the build it does not exist, so every test that calls it fails."""
    return S.first_filter(*args, **kw)


class Mem:
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.layer = S.StructureLayer(self.m.db)
        self.kb = self.layer.kb

    def say(self, speaker, text, others=(("Ben", "I will ring you after lunch."),)):
        """Stores the sentence in a chat whose recorded speakers are the speaker and `others` (DQ-4)."""
        self.m.open_chat(SAID)
        for who, line in others:
            self.m.add(who, line, date=SAID)
        sid = self.m.add(speaker, text, date=SAID)
        self.m.close_chat(write_note=False)
        return sid

    def file(self, sid, subject, obj, word, kind=""):
        return self.layer.file(sid, subject, obj, kind, word=word)

    def facts(self):
        return self.m.db.execute("SELECT COUNT(*) FROM knowledge_records").fetchone()[0]

    def reviews(self):
        return len(self.kb.reviews())

    def note_of(self, out):
        """The filter_note on what the outcome left in the store; None when there is no key."""
        if out.verdict == ACCEPTED:
            return (self.kb.get(out.fact_id).fact.metadata or {}).get("filter_note")
        if out.verdict == UNCERTAIN:
            return json.loads(self.kb.review(out.review_id)["candidate"]).get("filter_note")
        raise AssertionError("a rejected proposal leaves nothing in the store")


@pytest.fixture
def mem(tmp_path):
    m = Mem(tmp_path)
    yield m
    m.m.close()


def passes(speaker, text, people=PEOPLE):
    return S.gate(speaker, text, SAID, people=people)[0]


# ------------------------------------------------------------------ F1: the drop list (A3)
DROPPED = [
    ("assistant", "Assistant", "You could try the new bakery on Church Street."),
    ("bare greeting", "Asha", "Hi Ben!"),
    ("thanks", "Asha", "Thanks a ton, Ben!"),
    ("short reply", "Asha", "Sure thing."),
    ("short reply 2", "Asha", "Hmm."),
    ("question", "Asha", "Did you ever finish the marathon?"),
    ("request", "Asha", "Can you send me the recipe?"),
    ("request 2", "Asha", "Please share the photos later."),
]
DROPPED_USER = [(f"{c} (User)", "User" if s == "Asha" else s, t) for c, s, t in DROPPED]


@pytest.mark.parametrize("cid,speaker,text", DROPPED + DROPPED_USER, ids=[c[0] for c in DROPPED + DROPPED_USER])
def test_control_f1_dropped_kinds_do_not_reach_the_writer(cid, speaker, text):
    assert passes(speaker, text, people=PEOPLE if speaker != "User" else ()) is False


@pytest.mark.parametrize("cid,speaker,text", DROPPED + DROPPED_USER, ids=[c[0] for c in DROPPED + DROPPED_USER])
def test_new_f1_first_filter_drops_them_with_no_note_and_no_hold(cid, speaker, text):
    r = first_filter(speaker, text, SAID, people=PEOPLE if speaker != "User" else ())
    assert (r.passes, r.note, r.hold) == (False, "", "")


# ------------------------------------------------------------------ F2: where a bare greeting ends (A4, section 3.1)
GREETINGS = [  # sentence, words left after L-G words and the chat's names, passes
    ("Hi Ben!", 0, False),
    ("Thanks a ton, Ben!", 0, False),
    ("Hey Ben, how are you?", 3, False),
    ("Hi Ben, all well here.", 3, False),
    ("Thank you! I really needed that.", 4, True),
    ("Hey Ben, I started a pottery class last week!", 7, True),
    ("Hello Ben, we finally moved into the new flat.", 7, True),
]


@pytest.mark.parametrize("text,left,wanted", [g for g in GREETINGS if not g[2]], ids=[g[0] for g in GREETINGS if not g[2]])
def test_control_f2_a_greeting_with_fewer_than_four_words_left_is_dropped(text, left, wanted):
    assert passes("Asha", text) is False


@pytest.mark.parametrize("text,left,wanted", [g for g in GREETINGS if g[2]], ids=[g[0] for g in GREETINGS if g[2]])
def test_new_f2_a_greeting_with_four_or_more_words_left_passes_whole(text, left, wanted):
    assert passes("Asha", text) is True
    assert first_filter("Asha", text, SAID, people=PEOPLE).passes is True


def test_new_f2_the_names_stripped_are_the_chats_people():
    """Without Ben among the people, "Ben" is not stripped and counts as a word left: 3 words become 4."""
    assert first_filter("Asha", "Hi Ben, all well here.", SAID, people=PEOPLE).passes is False
    assert first_filter("Asha", "Hi Ben, all well here.", SAID, people=("Asha",)).passes is True


def test_control_f2_the_sentence_given_to_the_writer_is_never_cut(mem):
    text = "Hey Ben, I started a pottery class last week!"
    sid = mem.say("Asha", text)
    out = mem.file(sid, "I", "a pottery class", "other")
    assert out.verdict == ACCEPTED
    ev = mem.kb.get(out.fact_id).evidence
    assert [e.source_id for e in ev] == [str(sid)]
    assert mem.m.db.execute("SELECT text FROM sentences WHERE sid=?", (sid,)).fetchone()[0] == text


# ------------------------------------------------------------------ F3: no first person (S2-11)
NO_FIRST_PERSON = ["The pottery class meets every Thursday.", "Ben works at a bakery in Mysuru.",
                   "Someone at work bought a boat.", "The band nearly signed with a big label."]


@pytest.mark.parametrize("text", NO_FIRST_PERSON)
def test_new_f3_a_sentence_with_no_first_person_reaches_the_writer_with_no_note(text):
    assert passes("Asha", text) is True
    r = first_filter("Asha", text, SAID, people=PEOPLE)
    assert (r.passes, r.note, r.hold, r.reason) == (True, "", "", "not_about_the_speaker")


# ------------------------------------------------------------------ F4: notes (A5, CF-2, DQ-2)
NOTED = [  # id, sentence, subject, object, word, note, outcome (stored or held)
    ("unresolved it 1", "I am keen on teaching these days.", "I", "teaching", "likes", "unresolved_context_reference", ACCEPTED),
    ("unresolved it 2", "That trip changed my whole outlook.", "I", "my whole outlook", "other", "unresolved_context_reference", ACCEPTED),
    ("condition", "If I get the job, I will move to Pune.", "I", "Pune", "moved_to", "uncertain_or_conditional_content", UNCERTAIN),
    ("uncertain", "Maybe I will take up rowing again.", "I", "rowing", "hobby", "uncertain_or_conditional_content", UNCERTAIN),
    ("emotion", "I'm excited to start my new class.", "I", "my new class", "other", "unsupported_content_kind", ACCEPTED),
]


@pytest.mark.parametrize("cid,text,subject,obj,word,note,outcome", NOTED, ids=[n[0] for n in NOTED])
def test_new_f4_a_doubtful_sentence_reaches_the_writer_with_its_note(cid, text, subject, obj, word, note, outcome):
    assert passes("Asha", text) is True
    r = first_filter("Asha", text, SAID, people=PEOPLE)
    assert (r.passes, r.note, r.hold) == (True, note, "")


@pytest.mark.parametrize("cid,text,subject,obj,word,note,outcome", NOTED, ids=[n[0] for n in NOTED])
def test_new_f4_what_is_made_from_it_carries_filter_note(mem, cid, text, subject, obj, word, note, outcome):
    out = mem.file(mem.say("Asha", text), subject, obj, word)
    assert out.verdict == outcome
    assert mem.note_of(out) == note


@pytest.mark.parametrize("cid,text,subject,obj,word,note,outcome", NOTED, ids=[n[0] for n in NOTED])
def test_control_f4_the_note_holds_nothing_by_itself(mem, cid, text, subject, obj, word, note, outcome):
    """The outcome is the existing checks' outcome, before and after the build."""
    assert mem.file(mem.say("Asha", text), subject, obj, word).verdict == outcome


def _decision(decision, code, kind="claim"):
    return LearningDecision(decision, (code,), kind, "none", "none", "uncertain", False, True, 0.3)


@pytest.mark.parametrize("code", ["attribution_not_confirmed", "interpreter_flagged_for_review"])
def test_new_f4_the_two_unreached_held_reasons_pass_with_a_note(monkeypatch, code):
    """DQ-2 (a). No made-up sentence reaches these reasons through today's interpreter (none in conversations 0 to 4
    either), so today's evaluate is replaced, inside engram_structure only, by one that returns the reason."""
    monkeypatch.setattr(S, "evaluate", lambda *a, **k: _decision("review", code))
    r = first_filter("Asha", "I work at a bakery in Mysuru.", SAID, people=PEOPLE)
    assert (r.passes, r.note, r.hold, r.reason) == (True, code, "", code)


def test_control_f4_an_unclear_act_or_unknown_kind_stays_dropped():
    """DQ-2 (a): an empty sentence is today's only way to an "unclear" act and "unknown" kind."""
    assert passes("Asha", "") is False


def test_new_f4_an_unclear_act_or_unknown_kind_is_dropped_by_first_filter():
    r = first_filter("Asha", "", SAID, people=PEOPLE)
    assert (r.passes, r.note, r.hold) == (False, "", "")


def test_control_f4_the_writers_prompt_is_unchanged():
    assert hashlib.sha256(S.WRITER_PROMPT.encode("utf-8")).hexdigest() == PROMPT_SHA256


def test_control_f4_the_note_never_reaches_the_writers_prompt():
    p = S.writer_prompt([("D1:1", "I am keen on teaching these days.")])
    assert not any(code in p for code in NOTES) and "filter_note" not in p


# ------------------------------------------------------------------ F5: still not passed (A6, DQ-1)
CORRECTIONS = ["Actually, I meant Chennai, not Pune."]
UNTOLD = ["I work at a bakery in Mysuru.", "If I get the job, I will move to Pune.", "The pottery class meets every Thursday."]


@pytest.mark.parametrize("text", CORRECTIONS)
def test_control_f5_a_correction_is_not_passed(text):
    assert passes("Asha", text) is False and passes("User", text, people=()) is False


@pytest.mark.parametrize("text", CORRECTIONS)
def test_new_f5_first_filter_gives_the_correction_reason(text):
    r = first_filter("Asha", text, SAID, people=PEOPLE)
    assert (r.passes, r.note, r.hold, r.reason) == (False, "", "", "correction_requires_target_resolution")


@pytest.mark.parametrize("text", UNTOLD)
def test_control_f5_a_named_speaker_the_gate_is_not_told_is_a_person_is_not_passed(text):
    assert passes("Asha", text, people=()) is False and passes("Asha", text, people=("Ravi",)) is False


@pytest.mark.parametrize("text", UNTOLD)
def test_new_f5_first_filter_gives_the_unknown_speaker_reason(text):
    r = first_filter("Asha", text, SAID, people=())
    assert (r.passes, r.note, r.hold, r.reason) == (False, "", "", "speaker_role_unknown")


# ------------------------------------------------------------------ F6: someone else's words (A7, A7a)
OTHERS_WORDS = [  # id, sentence, subject, object, word. Measured today: the first and third are accepted, the second is held
    # for another doubt ("this may be about someone else the speaker mentions"); after the build all three carry the A7 hold
    ("quoted words", 'Ravi said "I love hiking".', "I", "hiking", "likes"),
    ("quoted words 2", 'My boss told me "you will lead the Pune team".', "I", "the Pune team", "other"),
    ("quoted title", 'I just finished reading "Quiet Rivers" last night.', "I", "Quiet Rivers", "other"),
]


@pytest.mark.parametrize("cid,text,subject,obj,word", OTHERS_WORDS, ids=[o[0] for o in OTHERS_WORDS])
def test_new_f6_someone_elses_words_reach_the_writer_with_a_hold_and_no_note(cid, text, subject, obj, word):
    assert passes("Asha", text) is True
    r = first_filter("Asha", text, SAID, people=PEOPLE)
    assert (r.passes, r.note, r.hold, r.reason) == (True, "", HOLD, "externally_attributed_statement")


@pytest.mark.parametrize("cid,text,subject,obj,word", OTHERS_WORDS, ids=[o[0] for o in OTHERS_WORDS])
def test_new_f6_a_proposal_from_them_is_held_never_stored_and_carries_no_filter_note(mem, cid, text, subject, obj, word):
    out = mem.file(mem.say("Asha", text), subject, obj, word)
    assert out.verdict == UNCERTAIN and HOLD in out.reasons
    assert mem.facts() == 0
    assert HOLD in mem.kb.review(out.review_id)["reasons"]
    assert mem.note_of(out) is None


def test_new_f6_the_hold_reason_uses_the_plain_apostrophe():
    assert "'" in HOLD and "’" not in HOLD
    r = first_filter("Asha", 'Ravi said "I love hiking".', SAID, people=PEOPLE)
    assert r.hold == HOLD


def test_control_f6_a_rejected_proposal_from_them_stays_rejected_and_is_not_queued(mem):
    sid = mem.say("Asha", 'Ravi said "I love hiking".')
    out = mem.file(sid, "I", "mountain biking", "likes")
    assert out.verdict == REJECTED and out.review_id is None
    assert mem.reviews() == 0 and mem.facts() == 0


# ------------------------------------------------------------------ F7: Increment 1 and 2 rules behind the filter (A10)
BEHIND = [  # id, sentence, subject, object, word, wanted, reason the existing check gives
    ("S3 condition", "If I get the job, I will move to Pune.", "I", "Pune", "moved_to", UNCERTAIN, CONDITION),
    ("S4 near miss", "The band nearly signed with a big label.", "the band", "a big label", "other", UNCERTAIN, NEAR_MISS),
    ("S7 opinion", "I guess it might rain at the fair.", "it", "rain at the fair", "other", UNCERTAIN, OPINION),
    ("S2-6 indefinite", "A colleague adopted a kitten.", "A colleague", "a kitten", "adopted", UNCERTAIN, INDEFINITE),
    ("our + person", "Maybe our neighbour moved to Mysuru.", "our neighbour", "Mysuru", "moved_to", UNCERTAIN, OUR),
    ("plain fact", "Ben works at a bakery in Mysuru.", "Ben", "a bakery in Mysuru", "works_at", ACCEPTED, None),
]


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted,reason", BEHIND, ids=[b[0] for b in BEHIND])
def test_new_f7_the_sentence_now_reaches_the_writer(cid, text, subject, obj, word, wanted, reason):
    assert passes("Asha", text) is True


@pytest.mark.parametrize("cid,text,subject,obj,word,wanted,reason", BEHIND, ids=[b[0] for b in BEHIND])
def test_control_f7_the_existing_rules_decide_its_proposal(mem, cid, text, subject, obj, word, wanted, reason):
    out = mem.file(mem.say("Asha", text), subject, obj, word)
    assert out.verdict == wanted
    if reason:
        assert any(reason in r for r in out.reasons)


def test_control_f7_a_plain_fact_is_stored_with_its_sentence_and_date(mem):
    sid = mem.say("Asha", "Ben works at a bakery in Mysuru.")
    out = mem.file(sid, "Ben", "a bakery in Mysuru", "works_at")
    stored = mem.kb.get(out.fact_id)
    assert [e.source_id for e in stored.evidence] == [str(sid)] and stored.fact.metadata["said_on"] == SAID


# ------------------------------------------------------------------ F8: known limit L2 (A10)
HEARSAY = ("People say the lake is lovely in winter.", "the lake", "lovely", "other")


def test_new_f8_hearsay_now_reaches_the_writer():
    assert passes("Asha", HEARSAY[0]) is True


def test_control_f8_known_limit_hearsay_without_first_person_is_stored(mem):
    """Recorded limit L2 (A10, his words): addressing it needs a later, separately specified change."""
    out = mem.file(mem.say("Asha", HEARSAY[0]), *HEARSAY[1:])
    assert out.verdict == ACCEPTED


# ------------------------------------------------------------------ F9: interfaces and agreement (DQ-4)
# Every sentence above that has a proposal: (speaker, sentence, subject, object, word)
AGREE = ([("Asha", t, s, o, w) for _, t, s, o, w, _, _ in NOTED] + [("Asha", t, s, o, w) for _, t, s, o, w in OTHERS_WORDS]
         + [("Asha", t, s, o, w) for _, t, s, o, w, _, _ in BEHIND] + [("Asha",) + HEARSAY]
         + [("Asha", "Hey Ben, I started a pottery class last week!", "I", "a pottery class", "other"),
            ("Asha", "I work at a bakery in Mysuru.", "I", "a bakery in Mysuru", "works_at"),
            ("Asha", "Actually, I meant Chennai, not Pune.", "I", "Chennai", "lives_in")])
AGREE_USER = [("User",) + a[1:] for a in AGREE]
AGREE_BEN = [("Ben",) + a[1:] for a in AGREE[:6]]
REJECTED_WITH_HOLD = [("Asha", 'Ravi said "I love hiking".', "I", "mountain biking", "likes"),
                      ("Asha", 'I just finished reading "Quiet Rivers" last night.', "I", "Silent Lakes", "other")]


def test_new_f9_filter_result_is_a_frozen_dataclass_with_the_five_fields():
    import dataclasses
    assert dataclasses.is_dataclass(S.FilterResult)
    assert [f.name for f in dataclasses.fields(S.FilterResult)] == ["passes", "kind", "note", "hold", "reason"]
    r = first_filter("Asha", "I work at a bakery in Mysuru.", SAID, people=PEOPLE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.passes = False


def _others(speaker):
    return () if speaker == "User" else (("Ben" if speaker == "Asha" else "Asha", "I will ring you after lunch."),)


def _recorded(speaker, others):
    """The chat's recorded speakers, in the order they were recorded: the other lines first, then the sentence (DQ-4)."""
    return tuple(dict.fromkeys([who for who, _ in others] + [speaker]))


@pytest.mark.parametrize("speaker,text,subject,obj,word", AGREE + AGREE_USER)
def test_new_f9_gate_keeps_its_shape_and_agrees_with_first_filter(speaker, text, subject, obj, word):
    people = _recorded(speaker, _others(speaker))                           # ("Ben", "Asha") for Asha; ("User",) for User
    g = S.gate(speaker, text, SAID, people=people)
    r = first_filter(speaker, text, SAID, people=people)
    assert isinstance(g, tuple) and len(g) == 2 and g == (r.passes, r.kind)


def _agrees(mem, speaker, text, subject, obj, word, others, kind=""):
    # gate, first_filter and file are all given exactly the people the stored chat supplies to file (DQ-4).
    people = _recorded(speaker, others)
    r = first_filter(speaker, text, SAID, people=people)
    assert S.gate(speaker, text, SAID, people=people) == (r.passes, r.kind)  # gate agrees on the same recorded speakers
    before = mem.reviews()
    out = mem.file(mem.say(speaker, text, others=others), subject, obj, word, kind=kind)
    if out.verdict == REJECTED:                                             # (ii): rejected stays rejected, never queued
        assert out.review_id is None and mem.reviews() == before
        return out
    assert (HOLD in out.reasons) == bool(r.hold)                            # (i): the A7 hold, exactly when there is one
    if r.hold:
        assert out.verdict == UNCERTAIN
    assert mem.note_of(out) == (r.note or None)                             # (iii): only on what reaches the store
    return out


@pytest.mark.parametrize("speaker,text,subject,obj,word", AGREE + AGREE_BEN)
def test_new_f9_file_derives_the_same_hold_and_note_as_first_filter(mem, speaker, text, subject, obj, word):
    _agrees(mem, speaker, text, subject, obj, word, _others(speaker))


@pytest.mark.parametrize("speaker,text,subject,obj,word", AGREE_USER)
def test_new_f9_file_agrees_for_user(mem, speaker, text, subject, obj, word):
    _agrees(mem, speaker, text, subject, obj, word, ())


@pytest.mark.parametrize("speaker,text,subject,obj,word", AGREE[:9])
def test_new_f9_file_agrees_in_a_chat_where_only_one_person_has_spoken(mem, speaker, text, subject, obj, word):
    _agrees(mem, speaker, text, subject, obj, word, ())


@pytest.mark.parametrize("speaker,text,subject,obj,word", REJECTED_WITH_HOLD)
def test_new_f9_a_rejected_proposal_stays_rejected_even_when_the_sentence_has_a_hold(mem, speaker, text, subject, obj, word):
    assert first_filter(speaker, text, SAID, people=PEOPLE).hold == HOLD
    out = _agrees(mem, speaker, text, subject, obj, word, _others(speaker))
    assert out.verdict == REJECTED and mem.facts() == 0


@pytest.mark.parametrize("kind", ["", "claim", "plan", "preference", "nonsense"])
def test_new_f9_the_hold_and_the_note_do_not_depend_on_the_callers_kind(tmp_path, kind):
    for i, (speaker, text, subject, obj, word) in enumerate([AGREE[0], AGREE[2], AGREE[5]]):
        d = tmp_path / f"{kind or 'empty'}-{i}"
        d.mkdir()
        m = Mem(d)
        try:
            _agrees(m, speaker, text, subject, obj, word, _others(speaker), kind=kind)
        finally:
            m.m.close()


REVIEW_PATH = [  # sentence, today's status and first reason on the review-queue path (measured at 4e7e635)
    ("Hey Ben, I started a pottery class last week!", "ignored", "social_or_acknowledgement"),
    ("The pottery class meets every Thursday.", "ignored", "not_about_the_speaker"),
    ("It was the longest drive of my life.", "created", "unresolved_context_reference"),
    ("If I get the job, I will move to Pune.", "created", "uncertain_or_conditional_content"),
    ("I'm excited to start my new class.", "created", "unsupported_content_kind"),
    ('Ravi said "I love hiking".', "created", "externally_attributed_statement"),
    ("Actually, I meant Chennai, not Pune.", "created", "correction_requires_target_resolution"),
    ("Hi Ben!", "ignored", "social_or_acknowledgement"),
    ("Did you ever finish the marathon?", "ignored", "interaction_not_memory_content"),
    ("I work at a bakery in Mysuru.", "created", "user_authored_explicit_content"),
]


@pytest.mark.parametrize("text,status,reason", REVIEW_PATH)
def test_control_f9_the_review_queue_path_is_unchanged(mem, text, status, reason):
    """A2: Increment 3 changes the writer's path only."""
    got = prepare_stored(mem.m.db, mem.say("Asha", text), people=PEOPLE)
    assert [(g.status, g.reason_codes[0]) for g in got] == [(status, reason)]


# ------------------------------------------------------------------ F10: the delete cascade
# Today's cascade (guarantee C1): forgetting a sentence marks each fact resting on it "invalidated", removes its
# evidence (the walk no longer reaches it) and deletes the review items tied to it. Increment 3 keeps this.
def _gone(mem, sid, out):
    mem.m.forget_sentence(sid)
    if out.verdict == ACCEPTED:
        f = mem.kb.get(out.fact_id)
        assert f.fact.status == "invalidated" and not f.evidence and out.fact_id not in mem.layer.graph().facts
    assert mem.reviews() == 0


def test_new_f10_a_noted_fact_is_invalidated_with_its_sentence(mem):
    sid = mem.say("Asha", "I am keen on teaching these days.")
    out = mem.file(sid, "I", "teaching", "likes")
    assert mem.note_of(out) == "unresolved_context_reference"
    _gone(mem, sid, out)


def test_control_f10_a_fact_from_a_noted_sentence_is_invalidated_with_its_sentence(mem):
    sid = mem.say("Asha", "I am keen on teaching these days.")
    _gone(mem, sid, mem.file(sid, "I", "teaching", "likes"))


def test_control_f10_a_held_proposal_is_removed_with_its_sentence(mem):
    sid = mem.say("Asha", "Maybe I will take up rowing again.")
    out = mem.file(sid, "I", "rowing", "hobby")
    assert out.verdict == UNCERTAIN
    _gone(mem, sid, out)


def test_new_f10_an_a7_held_proposal_is_removed_with_its_sentence(mem):
    sid = mem.say("Asha", 'Ravi said "I love hiking".')
    out = mem.file(sid, "I", "hiking", "likes")
    assert out.verdict == UNCERTAIN and HOLD in out.reasons
    _gone(mem, sid, out)


# ------------------------------------------------------------------ F11: the shapes of the acceptance sentences
SHAPES = [  # acceptance sentence, made-up sentence of its shape, today's first reason, note, hold
    ("D18:1.1", "Hey Ben, I started a pottery class last week!", "social_or_acknowledgement", "", ""),
    ("D3:13.2", "It was the longest drive of my life.", "unresolved_context_reference", "unresolved_context_reference", ""),
    ("D17:25.3", "That trip changed my whole outlook.", "unresolved_context_reference", "unresolved_context_reference", ""),
    ("D17:10.3", "The pottery class meets every Thursday.", "not_about_the_speaker", "", ""),
    ("D15:28.1", 'My boss told me "you will lead the Pune team".', "externally_attributed_statement", "", HOLD),
]


@pytest.mark.parametrize("sid,text,reason,note,hold", SHAPES, ids=[s[0] for s in SHAPES])
def test_new_f11_each_shape_now_reaches_the_writer_as_decided(sid, text, reason, note, hold):
    assert passes("Asha", text) is True
    r = first_filter("Asha", text, SAID, people=PEOPLE)
    assert (r.passes, r.reason, r.note, r.hold) == (True, reason, note, hold)
