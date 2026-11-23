"""Stage 2, Increment 5 (entity kinds), with contract Amendment 10 (10A1 to 10A5).
Frozen specification: claude/engram-stage2-inc5-spec-draft5.md, frozen 22 November 2026 at 12:18
(SHA-256 8f412ee09161b5334858badaca2d081f6f2eb2dba335c5727de30775cc4f7988), with claude/engram-wr-amendment10.md
(SHA-256 19b13eebdb6a26b0d1c1174c2cf061086a60bbaefebb9ce27579e41b61207ca0). Section numbers below are the specification's.
Points settled after the freeze, recorded in claude/engram-stage2-inc5-decisions-part2.md and -part3.md:
  P-1 (S)  the K-10 hold is checked only when a fact would create a new entity, after every other refusal and hold
  P-2 (a)  StructureLayer.file takes an optional subject_kind; left out means no kind
  P-3 (a)  kinds and K-10 apply on base 2's path and on the classic path (KnowledgePipeline) alike
  P-4 (a)  the classic path's Candidate takes an optional subject_kind, same rules
  P-5 (a)  KnowledgePipeline.approve takes an optional subject_kind; a new entity with no kind is refused on approval
  P-6 (b)  on approval the writer's kind kept with the fact wins over the kind given on approval
  P-7 (a)  the runner passes the parsed subject_kind to file (one stated exception to section 8)
Fixed, hand-written proposals only; no model is called. Every sentence is made up. None is LoCoMo text.
TESTS FIRST. This file is written before the build. Tests whose names begin test_control_ pass today and must pass after
the build. Every other test is expected to FAIL until Increment 5 is built (most at once, because file(), Candidate and
approve() do not yet take subject_kind), except four whose wanted result is already today's: test_kn_an_existing_unknown_
entity_needs_no_kind, test_gp_the_group_is_separate_from_a_single_one, test_bb_biz_and_business_are_separate_with_no_alias_
between and test_vc_the_same_speakers_newer_fact_replaces. The run is reported in the tests-first package.
"""
import hashlib
import inspect
import json
import pytest
import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, REJECTED, UNCERTAIN, Candidate, KnowledgePipeline
from engram_knowledge.models import Entity, RecordError

SAID = "2:15 pm on 12 June, 2025"
A, B = "Asha", "Ben"
KINDS = ("person", "animal", "place", "organisation", "thing")

# ------------------------------------------------------------------ the reason texts (section 5), exact
def NO_KIND(subject):                                                   # 3.5, K-10
    return f"the kind of '{subject}' is not known"
BORROWED = "a borrowed name must be a person's"                         # section 7
def ANOTHER(word):                                                      # step 10a, a later unnamed one
    return f"may be another {word}: no name links it to the one already stored"
def ALREADY(word):                                                      # step 10a, a new name when unnamed are stored
    return f"may be the {word} already stored: no name links them"
OUR = "'our' does not say whose"                                        # step 1'
DIFFERENT_NAME = "a different name from the one stored for this relation"   # step 10b (O-6), Increment 2's step 7 text
OTHER_SPEAKERS = "the name belongs to another speaker's relation"       # Increment 2, section 3.1
R2B = "the name's line is the main line"                                # Increment 4, unchanged
HE = "'He' does not say who"                                            # Increment 2, unchanged (the subject as written)
_UNSET = object()


class Mem:
    """One store. chat() stores a chat's lines in order and returns their sentence ids; Asha and Ben are its speakers."""
    def __init__(self, tmp_path):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.layer = S.StructureLayer(self.m.db)
        self.kb = KnowledgeBase(self.m.db)

    def chat(self, lines):
        self.m.open_chat(SAID)
        self.m.add(A, "Morning Ben, the tea is ready.", date=SAID)
        self.m.add(B, "Hi Asha, likewise.", date=SAID)
        sids = [self.m.add(who, text, date=SAID) for who, text in lines]
        self.m.close_chat(write_note=False)
        return sids

    def file(self, sid, subject, obj, word="other", subject_kind=_UNSET, **block):
        """Base 2's path. subject_kind is passed only when the case gives one (P-2: left out means no kind)."""
        extra = {} if subject_kind is _UNSET else dict(subject_kind=subject_kind)
        return self.layer.file(sid, subject, obj, "claim", word=word, **block, **extra)

    def classic(self, sid, subject, obj, word="likes", subject_kind=_UNSET):
        """The classic path (P-3, P-4)."""
        extra = {} if subject_kind is _UNSET else dict(subject_kind=subject_kind)
        d, rid = KnowledgePipeline(self.m.db).process(Candidate(subject, word, obj, (sid,), "", "test", "1", **extra))
        return S.Outcome(d.verdict, d.reasons, rid if d.verdict == ACCEPTED else None, rid if d.verdict == UNCERTAIN else None)

    def entity(self, out):
        return self.kb.entity(self.kb.get(out.fact_id).fact.subject_id)

    def count(self, table):
        return self.m.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def state(self):
        return tuple(self.count(t) for t in ("entities", "entity_aliases", "knowledge_records"))

    def status(self, out):
        return self.kb.get(out.fact_id).fact.status

    def speaker_entity(self, label):
        rows = [self.kb.entity(r[0]) for r in self.m.db.execute("SELECT entity_id FROM entities WHERE normalized_name=?", (label.casefold(),))]
        rows = [e for e in rows if "relation_of" not in (e.metadata or {})]
        return rows[0] if len(rows) == 1 else None

    def aliases(self, entity_id):
        return [a.normalized_alias for a in self.kb.aliases(entity_id)]


@pytest.fixture
def mem(tmp_path):
    m = Mem(tmp_path)
    yield m
    m.m.close()


def stored(out):
    assert out.verdict == ACCEPTED and out.fact_id, (out.verdict, out.reasons)
    return out


def held(mem, out, reason, before=None):
    """Held for review with the reason; when `before` is given, nothing was stored: no entity, no alias, no fact (3.5)."""
    assert out.verdict == UNCERTAIN and reason in out.reasons, (out.verdict, out.reasons)
    if before is not None:
        assert mem.state() == before


def kind_name(mem, out):
    e = mem.entity(stored(out))
    return e.entity_type, e.canonical_name


# ------------------------------------------------------------------ RB, RB2: RM-b first (4.0)
def test_rb_rm_b_makes_the_subject_the_speaker_before_any_kind_rule(mem):
    [s] = mem.chat([(A, "My home is in Pune.")])
    e = mem.entity(stored(mem.file(s, "my home", "Pune", "lives_in")))
    assert e.entity_id == mem.speaker_entity(A).entity_id and e.entity_type == "person"
    assert not any("home" in r[0].lower() for r in mem.m.db.execute("SELECT canonical_name FROM entities"))


def test_rb2_without_rm_b_my_home_is_the_speakers_own_thing(mem):
    [s] = mem.chat([(A, "My home is near the park.")])
    e = mem.entity(stored(mem.file(s, "my home", "the park")))
    assert (e.entity_type, e.canonical_name) == ("thing", "Asha's home")
    assert e.metadata["relation_of"] == mem.speaker_entity(A).entity_id and e.metadata["relation"] == "home"


# ------------------------------------------------------------------ KL: a kind from a list (3.3)
@pytest.mark.parametrize("sentence,subject,obj,want", [
    ("The hospital opens at nine.", "The hospital", "nine", "place"),
    ("The bank closes at four.", "The bank", "four", "organisation"),
    ("The piano needs tuning.", "The piano", "tuning", "thing"),
    ("The pony eats apples.", "The pony", "apples", "animal"),
], ids=["place", "organisation", "thing", "animal"])
def test_kl_a_new_entity_takes_its_lists_kind(mem, sentence, subject, obj, want):
    [s] = mem.chat([(A, sentence)])
    assert kind_name(mem, mem.file(s, subject, obj))[0] == want


def test_kl_the_head_word_is_the_last_word_after_describing_words(mem):
    [s] = mem.chat([(A, "The old museum reopens in May.")])
    assert kind_name(mem, mem.file(s, "The old museum", "May"))[0] == "place"


# ------------------------------------------------------------------ KR: kinds fixed by rule (3.2)
@pytest.mark.parametrize("sentence,subject,obj", [
    ("I live in Pune.", "I", "Pune"),
    ("My sister lives in Pune.", "my sister", "Pune"),
    ("My family lives in Mysore.", "my family", "Mysore"),
], ids=["speaker", "relation", "family group"])
def test_kr_speakers_relations_and_family_groups_are_persons(mem, sentence, subject, obj):
    [s] = mem.chat([(A, sentence)])
    assert kind_name(mem, mem.file(s, subject, obj, "lives_in"))[0] == "person"


def test_kr_the_owner_made_for_a_relation_is_a_person(mem):
    [s] = mem.chat([(A, "My sister lives in Pune.")])
    stored(mem.file(s, "my sister", "Pune", "lives_in"))
    assert mem.speaker_entity(A).entity_type == "person"


# ------------------------------------------------------------------ KW, KX, KN: the writer's kind (3.4) and none (3.5)
@pytest.mark.parametrize("given", KINDS)
def test_kw_a_bare_name_takes_the_writers_kind(mem, given):
    [s] = mem.chat([(A, "Rob plays chess.")])
    assert kind_name(mem, mem.file(s, "Rob", "chess", subject_kind=given)) == (given, "Rob")


@pytest.mark.parametrize("given", ["robot", "Person", "", " person"])
def test_kx_a_value_not_exactly_one_of_the_five_counts_as_no_kind(mem, given):
    [s] = mem.chat([(A, "Rob plays chess.")])
    before = mem.state()
    held(mem, mem.file(s, "Rob", "chess", subject_kind=given), NO_KIND("Rob"), before)


def test_kn_no_kind_is_held_and_nothing_is_stored(mem):
    [s] = mem.chat([(A, "Rob plays chess.")])
    before = mem.state()
    out = mem.file(s, "Rob", "chess")
    held(mem, out, NO_KIND("Rob"), before)
    assert mem.kb.review(out.review_id) is not None


def test_kn_none_given_explicitly_is_no_kind(mem):
    [s] = mem.chat([(A, "Rob plays chess.")])
    before = mem.state()
    held(mem, mem.file(s, "Rob", "chess", subject_kind=None), NO_KIND("Rob"), before)


def test_kn_an_existing_entity_needs_no_kind(mem):
    a, b = mem.chat([(A, "Rob plays chess."), (A, "Rob plays tennis.")])
    first = mem.entity(stored(mem.file(a, "Rob", "chess", subject_kind="person")))
    assert mem.entity(stored(mem.file(b, "Rob", "tennis"))).entity_id == first.entity_id


def test_kn_an_existing_unknown_entity_needs_no_kind(mem):
    [s] = mem.chat([(A, "Rob plays chess.")])
    old = mem.kb.add_entity(Entity.create("Rob", "unknown"))
    e = mem.entity(stored(mem.file(s, "Rob", "chess")))
    assert e.entity_id == old.entity_id and e.entity_type == "unknown"


# ------------------------------------------------------------------ KS: a speaker's name is a person (3.4, check 2)
def test_ks_a_speakers_name_is_a_person_whatever_was_proposed(mem):
    [s] = mem.chat([(B, "Asha plays chess.")])
    assert kind_name(mem, mem.file(s, "Asha", "chess", subject_kind="animal"))[0] == "person"


# ------------------------------------------------------------------ KD: the list wins (D-9)
def test_kd_the_lists_kind_wins_silently_over_the_writers(mem):
    [s] = mem.chat([(A, "My dog barks at night.")])
    out = mem.file(s, "my dog", "night", subject_kind="person")
    assert kind_name(mem, out)[0] == "animal" and out.review_id is None and mem.count("review_queue") == 0


# ------------------------------------------------------------------ AB: an abstract word (D-5)
def test_ab_a_word_on_no_list_with_no_kind_is_held(mem):
    [s] = mem.chat([(A, "My dreams are vivid.")])
    before = mem.state()
    held(mem, mem.file(s, "my dreams", "vivid"), NO_KIND("my dreams"), before)


# ------------------------------------------------------------------ SC, SV, SN, SB: step 10a (K-3, D-1, K-5)
def test_sc_each_speakers_my_dog_is_their_own(mem):
    a, b = mem.chat([(A, "My dog is called Max."), (B, "My dog is called Max.")])
    ea, eb = mem.entity(stored(mem.file(a, "my dog", "Max"))), mem.entity(stored(mem.file(b, "my dog", "Max")))
    assert ea.entity_id != eb.entity_id
    assert (ea.canonical_name, eb.canonical_name) == ("Asha's dog", "Ben's dog")
    assert ea.metadata["relation_of"] == mem.speaker_entity(A).entity_id and ea.metadata["relation"] == "dog"
    assert eb.metadata["relation_of"] == mem.speaker_entity(B).entity_id
    assert ea.entity_type == eb.entity_type == "animal"


def test_sv_a_later_unnamed_one_of_the_same_word_is_held(mem):
    a, b = mem.chat([(A, "My dog barks at night."), (A, "My dog sleeps all day.")])
    stored(mem.file(a, "my dog", "night"))
    held(mem, mem.file(b, "my dog", "all day"), ANOTHER("dog"))


def test_sv_a_new_name_when_only_unnamed_are_stored_is_held(mem):
    a, b = mem.chat([(A, "My dog barks at night."), (A, "My dog Rex sleeps all day.")])
    stored(mem.file(a, "my dog", "night"))
    held(mem, mem.file(b, "my dog Rex", "all day"), ALREADY("dog"))


def test_sn_a_name_at_first_mention_is_in_the_display_name_and_a_scoped_alias(mem):
    a, b = mem.chat([(A, "My dog Max barks at night."), (A, "Max sleeps all day.")])
    first = mem.entity(stored(mem.file(a, "my dog Max", "night")))
    assert first.canonical_name == "Asha's dog Max" and "max" in mem.aliases(first.entity_id)
    assert mem.entity(stored(mem.file(b, "Max", "all day"))).entity_id == first.entity_id


def test_sb_another_speaker_does_not_reach_a_scoped_name(mem):
    a, b = mem.chat([(A, "My dog Max barks at night."), (B, "Max sleeps all day.")])
    stored(mem.file(a, "my dog Max", "night"))
    held(mem, mem.file(b, "Max", "all day"), OTHER_SPEAKERS)


def test_sn_a_describing_word_does_not_change_the_head_word(mem):
    [s] = mem.chat([(A, "My old car needs new tyres.")])
    assert kind_name(mem, mem.file(s, "my old car", "new tyres")) == ("thing", "Asha's car")


# ------------------------------------------------------------------ GP, PL, BZ, BB, NG: groups, plurals, biz (10b)
def test_gp_a_plural_is_one_group_per_speaker_found_again(mem):
    a, b = mem.chat([(A, "My turtles love the sun."), (A, "My turtles eat lettuce.")])
    first = mem.entity(stored(mem.file(a, "my turtles", "the sun")))
    assert (first.entity_type, first.canonical_name) == ("animal", "Asha's turtles")
    assert mem.entity(stored(mem.file(b, "my turtles", "lettuce"))).entity_id == first.entity_id


def test_gp_the_group_is_separate_from_a_single_one(mem):
    a, b = mem.chat([(A, "My turtle sleeps all day."), (A, "My turtles eat lettuce.")])
    one = mem.entity(stored(mem.file(a, "my turtle", "all day")))
    assert mem.entity(stored(mem.file(b, "my turtles", "lettuce"))).entity_id != one.entity_id


@pytest.mark.parametrize("sentence,subject,obj,name", [
    ("My mice sleep all day.", "my mice", "all day", "Asha's mice"),
    ("My guinea pigs eat hay.", "my guinea pigs", "hay", "Asha's guinea pigs"),
    ("My sheep graze by the river.", "my sheep", "the river", "Asha's sheep"),
], ids=["mice", "guinea pigs", "sheep"])
def test_pl_plurals_made_by_hand_are_groups(mem, sentence, subject, obj, name):
    [s] = mem.chat([(A, sentence)])
    e = mem.entity(stored(mem.file(s, subject, obj)))
    assert (e.entity_type, e.canonical_name) == ("animal", name)
    assert e.metadata["relation_of"] == mem.speaker_entity(A).entity_id


def test_pl_my_goldfish_is_one_speaker_scoped_animal_entity(mem):
    """E-4, his words: "goldfish is invariant. The test should verify one speaker-scoped entity of kind animal, while
    recording that the word form alone cannot distinguish one goldfish from several. Do not claim the system has resolved
    the actual number of animals." This test checks the entity only; it says nothing about how many fish there are."""
    a, b = mem.chat([(A, "My goldfish swim in circles."), (B, "My goldfish swim in circles.")])
    ea, eb = mem.entity(stored(mem.file(a, "my goldfish", "circles"))), mem.entity(stored(mem.file(b, "my goldfish", "circles")))
    assert ea.entity_type == "animal" and ea.metadata["relation_of"] == mem.speaker_entity(A).entity_id
    assert ea.entity_id != eb.entity_id


def test_pl_a_two_word_entry_is_matched_as_a_pair_first(mem):
    [s] = mem.chat([(A, "My guinea pig eats hay.")])
    e = mem.entity(stored(mem.file(s, "my guinea pig", "hay")))
    assert (e.entity_type, e.canonical_name, e.metadata["relation"]) == ("animal", "Asha's guinea pig", "guinea pig")


def test_bz_biz_is_a_thing_and_has_no_plural(mem):
    a, b = mem.chat([(A, "My biz is growing fast."), (A, "My bizzes are growing fast.")])
    assert kind_name(mem, mem.file(a, "my biz", "fast")) == ("thing", "Asha's biz")
    before = mem.state()
    held(mem, mem.file(b, "my bizzes", "fast"), NO_KIND("my bizzes"), before)


def test_bb_biz_and_business_are_separate_with_no_alias_between(mem):
    a, b = mem.chat([(A, "My business sells tea."), (A, "My biz is growing fast.")])
    e1, e2 = mem.entity(stored(mem.file(a, "my business", "tea"))), mem.entity(stored(mem.file(b, "my biz", "fast")))
    assert e1.entity_id != e2.entity_id
    assert not any("biz" in x for x in mem.aliases(e1.entity_id)) and not any("business" in x for x in mem.aliases(e2.entity_id))


def test_ng_a_named_group_keeps_its_name_as_a_scoped_alias(mem):
    a, b = mem.chat([(A, "My goldfish Bubbles swim in circles."), (A, "My goldfish Finn swim in circles.")])
    e = mem.entity(stored(mem.file(a, "my goldfish Bubbles", "circles")))
    assert e.canonical_name == "Asha's goldfish" and "bubbles" in mem.aliases(e.entity_id)
    held(mem, mem.file(b, "my goldfish Finn", "circles"), DIFFERENT_NAME)


# ------------------------------------------------------------------ HM, BS, OU, TH, PO: home, business, "our", "the", places
@pytest.mark.parametrize("sentence,subject,obj", [
    ("My home is near the park.", "my home", "the park"),
    ("My store sells tea.", "my store", "tea"),
], ids=["HM home", "BS store"])
def test_hm_bs_two_speakers_get_two_entities(mem, sentence, subject, obj):
    a, b = mem.chat([(A, sentence), (B, sentence)])
    ea, eb = mem.entity(stored(mem.file(a, subject, obj))), mem.entity(stored(mem.file(b, subject, obj)))
    assert ea.entity_id != eb.entity_id and ea.entity_type == eb.entity_type == "thing"


def test_ou_our_with_an_animal_word_is_held(mem):
    [s] = mem.chat([(A, "Our dog barks at night.")])
    before = mem.state()
    held(mem, mem.file(s, "our dog", "night"), OUR, before)


def test_th_the_with_an_animal_word_is_one_shared_entity(mem):
    a, b = mem.chat([(A, "The dog barks at night."), (B, "The dog sleeps all day.")])
    ea, eb = mem.entity(stored(mem.file(a, "The dog", "night"))), mem.entity(stored(mem.file(b, "The dog", "all day")))
    assert ea.entity_id == eb.entity_id and ea.entity_type == "animal" and "relation_of" not in (ea.metadata or {})


def test_po_my_school_is_a_shared_place(mem):
    a, b = mem.chat([(A, "My school is in Pune."), (B, "My school is in Goa.")])
    ea, eb = mem.entity(stored(mem.file(a, "my school", "Pune"))), mem.entity(stored(mem.file(b, "my school", "Goa")))
    assert ea.entity_id == eb.entity_id and ea.entity_type == "place"


# ------------------------------------------------------------------ VS, VB, VC, VE: versioning by speaker (section 6)
def test_vs_another_speakers_newer_fact_does_not_replace(mem):
    a, b = mem.chat([(A, "The cafe opens at nine."), (B, "The cafe opens at ten.")])
    one, two = stored(mem.file(a, "The cafe", "nine")), stored(mem.file(b, "The cafe", "ten"))
    assert (mem.status(one), mem.status(two)) == ("active", "active")


def test_vb_a_fact_backed_by_both_speakers_is_never_replaced(mem):
    a, b, c = mem.chat([(A, "The cafe opens at nine."), (B, "The cafe opens at nine."), (A, "The cafe opens at ten.")])
    one = stored(mem.file(a, "The cafe", "nine"))
    assert stored(mem.file(b, "The cafe", "nine")).fact_id == one.fact_id
    two = stored(mem.file(c, "The cafe", "ten"))
    assert (mem.status(one), mem.status(two)) == ("active", "active")


def test_vc_the_same_speakers_newer_fact_replaces(mem):
    a, b = mem.chat([(A, "The cafe opens at nine."), (A, "The cafe opens at ten.")])
    one, two = stored(mem.file(a, "The cafe", "nine")), stored(mem.file(b, "The cafe", "ten"))
    assert (mem.status(one), mem.status(two)) == ("superseded", "active")


VE_TODAY = ("active", "active")   # read from today's code (7f3b240) before the build


def test_control_ve_a_slotted_word_is_the_state_engines_as_today(mem):
    """D-11b: the state engine (4A15) is unchanged. The statuses below are today's, read from today's code."""
    a, b = mem.chat([(A, "The band is based in Pune."), (B, "The band is based in Goa.")])
    one, two = stored(mem.file(a, "The band", "Pune", "lives_in")), stored(mem.file(b, "The band", "Goa", "lives_in"))
    assert (mem.status(one), mem.status(two)) == VE_TODAY


# ------------------------------------------------------------------ BR, BC: borrowing (section 7)
DOG_MAX, PARK = "My dog Max barks at night.", "He loves the park."
REX, NAP = "Today Rex chased a ball.", "He sleeps all day."
KAYAK, PIER = "Last week Tobias bought a small blue kayak.", "He keeps it by the old pier."


def test_br_a_borrowed_name_of_an_animal_is_held(mem):
    a, b = mem.chat([(A, DOG_MAX), (A, PARK)])
    stored(mem.file(a, "my dog Max", "night"))
    held(mem, mem.file(b, "Max", "the park", subject_from=a, reading=A), BORROWED)


def test_br_a_borrowed_name_the_writer_calls_an_animal_is_held(mem):
    a, b = mem.chat([(A, REX), (A, NAP)])
    held(mem, mem.file(b, "Rex", "all day", subject_from=a, reading=A, subject_kind="animal"), BORROWED)


def test_br_a_borrowed_name_the_writer_calls_a_person_is_stored(mem):
    a, b = mem.chat([(A, REX), (A, NAP)])
    assert kind_name(mem, mem.file(b, "Rex", "all day", subject_from=a, reading=A, subject_kind="person")) == ("person", "Rex")


def test_br_a_borrowed_name_of_no_known_kind_passes_borrowing_then_k10_holds_it(mem):
    """P-1 (S): borrowed as today (E-1), then held at creation because no kind is decided."""
    a, b = mem.chat([(A, REX), (A, NAP)])
    before = mem.state()
    out = mem.file(b, "Rex", "all day", subject_from=a, reading=A)
    held(mem, out, NO_KIND("Rex"), before)
    assert BORROWED not in out.reasons


def test_bc_increment_4s_borrowing_of_a_person_is_unchanged_with_a_kind(mem):
    a, b = mem.chat([(A, KAYAK), (A, PIER)])
    e = mem.entity(stored(mem.file(b, "Tobias", "the old pier", subject_from=a, reading=A, subject_kind="person")))
    assert (e.canonical_name, e.entity_type) == ("Tobias", "person")


def test_control_bc_increment_4s_holds_keep_their_reasons_before_k10(mem):
    """P-1 (S): a hold of Increment 4's step 2b comes first; K-10 is never reached."""
    [b] = mem.chat([(A, "He told Tobias the shop opens at nine.")])
    out = mem.file(b, "Tobias", "the shop opens at nine", subject_from=b, reading=A)
    assert out.verdict == UNCERTAIN and out.reasons == (R2B,)


def test_control_a_refusal_stays_a_refusal(mem):
    """P-1 (S): a name not in its sentence is refused, never turned into a K-10 hold."""
    [s] = mem.chat([(A, "Someone plays chess.")])
    out = mem.layer.file(s, "Rob", "chess", "claim", word="other")
    assert out.verdict == REJECTED and not any("kind of" in r for r in out.reasons)


# ------------------------------------------------------------------ OLD: entities already in a store (K-6)
def test_old_an_old_shared_my_dog_is_left_and_a_new_one_made(mem):
    [s] = mem.chat([(A, "My dog barks at night.")])
    old = mem.kb.add_entity(Entity.create("my dog", "unknown"))
    e = mem.entity(stored(mem.file(s, "my dog", "night")))
    assert e.entity_id != old.entity_id and e.canonical_name == "Asha's dog"
    again = mem.kb.entity(old.entity_id)
    assert (again.canonical_name, again.entity_type) == ("my dog", "unknown")


# ------------------------------------------------------------------ CT: controls, Increment 2 and 4 cases (kind aside)
def test_control_ct_a_relation_is_stored_as_today(mem):
    [s] = mem.chat([(A, "My sister lives in Pune.")])
    assert mem.entity(stored(mem.file(s, "my sister", "Pune", "lives_in"))).canonical_name == "Asha's sister"


def test_ct_a_relation_is_a_person(mem):
    [s] = mem.chat([(A, "My sister lives in Pune.")])
    assert mem.entity(stored(mem.file(s, "my sister", "Pune", "lives_in"))).entity_type == "person"


def test_control_ct_he_is_held_as_today(mem):
    [s] = mem.chat([(A, "He lives in Pune.")])
    out = mem.file(s, "He", "Pune", "lives_in")
    assert out.verdict == UNCERTAIN and HE in out.reasons


# ------------------------------------------------------------------ CL: the classic path (P-3, P-4)
# On the classic path a fact about anyone but the speaker is held today with "reported by someone else, not the subject"
# (P2's attribution check; base 2 drops that reason, the classic path keeps it). Under P-1 (S) that hold comes first, so
# such a fact reaches K-10 only when a person approves it (P-5, P-6). These tests therefore file, then approve.
HEARSAY = "reported by someone else, not the subject"


def approve(mem, out, **kw):
    return KnowledgePipeline(mem.m.db).approve(out.review_id, **kw)


def test_cl_the_speaker_is_a_person_on_the_classic_path(mem):
    [s] = mem.chat([(A, "I love Pune.")])
    assert kind_name(mem, mem.classic(s, "I", "Pune"))[0] == "person"


def test_cl_a_listed_word_takes_its_kind_on_the_classic_path(mem):
    [s] = mem.chat([(A, "The pony loves apples.")])
    out = mem.classic(s, "The pony", "apples")
    held(mem, out, HEARSAY)
    assert mem.kb.entity(approve(mem, out).fact.subject_id).entity_type == "animal"


def test_cl_my_dog_is_the_speakers_own_on_the_classic_path(mem):
    [s] = mem.chat([(A, "My dog loves the park.")])
    out = mem.classic(s, "my dog", "the park")
    e = mem.kb.entity(approve(mem, out).fact.subject_id)
    assert (e.entity_type, e.canonical_name) == ("animal", "Asha's dog")


@pytest.mark.parametrize("given", KINDS)
def test_cl_the_writers_kind_on_the_classic_path(mem, given):
    [s] = mem.chat([(A, "Rob loves chess.")])
    out = mem.classic(s, "Rob", "chess", subject_kind=given)
    held(mem, out, HEARSAY)
    e = mem.kb.entity(approve(mem, out).fact.subject_id)
    assert (e.entity_type, e.canonical_name) == (given, "Rob")


@pytest.mark.parametrize("given", [_UNSET, "robot"], ids=["none", "invalid"])
def test_cl_no_kind_on_the_classic_path_is_refused_on_approval(mem, given):
    [s] = mem.chat([(A, "Rob loves chess.")])
    out = mem.classic(s, "Rob", "chess", subject_kind=given)
    before = mem.state()
    with pytest.raises(RecordError, match=NO_KIND("Rob")):
        approve(mem, out)
    assert mem.state() == before and mem.kb.review(out.review_id) is not None


def test_cl_the_writers_kind_wins_over_the_kind_given_on_approval_on_the_classic_path(mem):
    [s] = mem.chat([(A, "Rob loves chess.")])
    out = mem.classic(s, "Rob", "chess", subject_kind="person")
    assert mem.kb.entity(approve(mem, out, subject_kind="animal").fact.subject_id).entity_type == "person"


def test_control_cl_a_fact_about_another_is_held_on_the_classic_path_as_today(mem):
    [s] = mem.chat([(A, "Rob loves chess.")])
    out = mem.classic(s, "Rob", "chess")
    assert out.verdict == UNCERTAIN and out.reasons == (HEARSAY,)


def test_control_cl_candidate_without_a_kind_is_built_as_today():
    assert Candidate("I", "likes", "tea") == Candidate("I", "likes", "tea", (), "", "", "", "", "")


# ------------------------------------------------------------------ AP: approving a held fact (P-5, P-6)
def test_ap_approving_a_k10_hold_without_a_kind_is_refused_and_it_stays(mem):
    [s] = mem.chat([(A, "Rob plays chess.")])
    out = mem.file(s, "Rob", "chess")
    before = mem.state()
    with pytest.raises(RecordError, match=NO_KIND("Rob")):
        KnowledgePipeline(mem.m.db).approve(out.review_id)
    assert mem.kb.review(out.review_id) is not None and mem.state() == before


@pytest.mark.parametrize("given", ["robot", None])
def test_ap_an_invalid_kind_on_approval_counts_as_none(mem, given):
    [s] = mem.chat([(A, "Rob plays chess.")])
    out = mem.file(s, "Rob", "chess")
    with pytest.raises(RecordError, match=NO_KIND("Rob")):
        KnowledgePipeline(mem.m.db).approve(out.review_id, subject_kind=given)
    assert mem.kb.review(out.review_id) is not None


def test_ap_a_kind_given_on_approval_stores_it(mem):
    [s] = mem.chat([(A, "Rob plays chess.")])
    out = mem.file(s, "Rob", "chess")
    fact = KnowledgePipeline(mem.m.db).approve(out.review_id, subject_kind="person")
    e = mem.kb.entity(fact.fact.subject_id)
    assert (e.canonical_name, e.entity_type) == ("Rob", "person") and mem.kb.review(out.review_id) is None


def test_ap_naming_an_existing_entity_needs_no_kind(mem):
    a, b = mem.chat([(A, "I live in Pune."), (A, "Rob plays chess.")])
    stored(mem.file(a, "I", "Pune", "lives_in"))
    out = mem.file(b, "Rob", "chess")
    fact = KnowledgePipeline(mem.m.db).approve(out.review_id, entity_name=A)
    assert fact.fact.subject_id == mem.speaker_entity(A).entity_id


def test_ap_the_writers_kind_kept_with_the_fact_wins_on_approval(mem):
    """P-6 (b). Held first by Increment 4's step 2b, with the writer's kind kept in the held fact."""
    [b] = mem.chat([(A, "He told Tobias the shop opens at nine.")])
    out = mem.file(b, "Tobias", "the shop opens at nine", subject_from=b, reading=A, subject_kind="person")
    assert out.reasons == (R2B,)
    fact = KnowledgePipeline(mem.m.db).approve(out.review_id, subject_kind="animal")
    assert mem.kb.entity(fact.fact.subject_id).entity_type == "person"


def test_ap_any_other_base2_hold_is_not_approved_by_this_route(mem):
    """C-4 (his (b), 23 November 14:02): only a base 2 fact held under K-10 or at Increment 4's step 2b is approved through
    base 2's checks. A fact held for any other reason (here step 8a, "may be another dog") is left to the code that was there
    before the build; as at 7f3b240, that code cannot build a classic Candidate from a base 2 item and raises TypeError. Nothing
    is stored and the fact stays in the review list. This pins today's behaviour, not a chosen refusal (his word, 15:06)."""
    a, b = mem.chat([(A, "My dog barks at night."), (A, "My dog sleeps all day.")])
    stored(mem.file(a, "my dog", "night"))
    out = mem.file(b, "my dog", "all day")
    assert out.verdict == UNCERTAIN and out.reasons == (ANOTHER("dog"),)
    before = mem.state()
    with pytest.raises(TypeError):
        KnowledgePipeline(mem.m.db).approve(out.review_id, subject_kind="animal")
    assert mem.kb.review(out.review_id) is not None and mem.state() == before


# ------------------------------------------------------------------ the writer's reply and the runner (FP-4, P-7)
LINES = {"L1"}


def _reply(**row):
    return json.dumps({"facts": [dict(line="L1", subject="Rob", word="other", object="chess") | row]})


def test_fp4_a_given_subject_kind_is_kept_from_the_reply():
    [r] = S.parse_proposals(_reply(subject_kind="person"), LINES)
    assert r["subject_kind"] == "person"


def test_fp4_a_given_subject_kind_is_kept_in_a_block_reading():
    [r] = S.parse_proposals(_reply(subject_kind="animal"), LINES, block_lines=LINES)
    assert r["subject_kind"] == "animal"


def test_fp4_an_invalid_subject_kind_is_kept_as_given_and_counts_as_no_kind_when_filed():
    """Reading R-1 of the package (for his word): kept as given, as subject_from is (Increment 4, N8 (b)); file decides."""
    [r] = S.parse_proposals(_reply(subject_kind="robot"), LINES)
    assert r["subject_kind"] == "robot"


def test_fp4_a_spaced_subject_kind_is_kept_unchanged():
    """His R-1 ("exactly as received") and his word of 22:22: the space is kept (Increment 4 trims subject_from; this does not)."""
    [r] = S.parse_proposals(_reply(subject_kind=" person"), LINES)
    assert r["subject_kind"] == " person"


def test_control_fp4_a_reply_without_subject_kind_parses_exactly_as_today():
    assert S.parse_proposals(_reply(), LINES) == [dict(line="L1", subject="Rob", word="other", object="chess")]


def test_p7_the_runner_passes_the_parsed_subject_kind_to_file():
    """P-7 (a), one stated exception to section 8. A source check only: the runner's filing call passes subject_kind
    from the parsed proposal, and only when the reply gave one (his requirement 1: omitted stays omitted). Its behaviour
    with a model is not tested here."""
    import kit_tools.lme_gpt4o as R
    calls = [ln for ln in inspect.getsource(R).splitlines() if "layer.file(" in ln]
    assert calls and all('{"subject_kind": p["subject_kind"]} if "subject_kind" in p else {}' in ln for ln in calls)


# ------------------------------------------------------------------ the prompts (3.4, O-4): the approved texts
def test_prompt_the_writer_prompt_is_the_approved_version_b():
    assert hashlib.sha256(S.WRITER_PROMPT.encode()).hexdigest() == "0a7a0718248d69d2e17f728473d5e4effc5abaf669fd400b90c07424fb6fe878"


def test_prompt_the_block_prompt_is_the_approved_version_b():
    assert hashlib.sha256(S.BLOCK_PROMPT.encode()).hexdigest() == "34360fa97f5b092562cff458d1ec7f39204efe73e84cf0d255689785270c2fc7"


def test_control_the_store_schema_is_unchanged():
    from engram_knowledge.schema import SCHEMA_VERSION
    assert SCHEMA_VERSION == 4
