"""Stage 2, K-6: entities already in a store. Control tests (PT-1, groups OK-1 to OK-4).
Specification: K-6 Specification Draft 9 (engram-stage2-k6-spec-draft9.md, SHA-256
52307e7f4f0aaeeeb244f836b66bb32ffd2b555e32af58f7e6db53bde95c8192), not frozen; decisions record r8.
K-6 as decided (KO-4 K-a, KO-5 S-a, KO-7 (a), KO-9 (a)) changes no code and no store. These tests pin today's behaviour
for an entity created before Increment 5, prepared here as an entity whose type is "unknown" (an "old" entity; how one is
recognised in a real store is open, KO-2). Every test is a control: it passes on today's code and must keep passing.
Fixed, hand-written proposals only; no model is called. Every sentence is made up and is copied from a test file already
in the repository (tests/test_stage2_inc5_kinds.py, tests/test_stage2_inc2_who.py); none is LoCoMo text.
"""
import pytest
import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, UNCERTAIN
from engram_knowledge.models import Entity

SAID = "2:15 pm on 12 June, 2025"
A, B = "Asha", "Ben"
OLD = "unknown"                                                         # base 2's type before Increment 5 (F5-2)
OUR = "'our' does not say whose"                                        # step 1'
BORROWED = "a borrowed name must be a person's"                         # section 7, Increment 5
def SIMILAR(name):                                                      # Increment 2, section 3.1, step 5 (_similar)
    return f"'{name}' may be someone already known"
def NO_KIND(subject):                                                   # Increment 5, 3.5, K-10
    return f"the kind of '{subject}' is not known"
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
        extra = {} if subject_kind is _UNSET else dict(subject_kind=subject_kind)
        return self.layer.file(sid, subject, obj, "claim", word=word, **block, **extra)

    def old(self, name, **metadata):
        """An entity as base 2 wrote it before Increment 5: type "unknown", no other change."""
        return self.kb.add_entity(Entity.create(name, OLD, metadata=metadata or None))

    def subject(self, out):
        return self.kb.entity(self.kb.get(out.fact_id).fact.subject_id)

    def state(self):
        return tuple(self.m.db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("entities", "entity_aliases", "knowledge_records"))


@pytest.fixture
def mem(tmp_path):
    m = Mem(tmp_path)
    yield m
    m.m.close()


def stored(out):
    assert out.verdict == ACCEPTED and out.fact_id, (out.verdict, out.reasons)
    return out


def held(mem, out, reason, before):
    """Held for review with the reason, and nothing stored: no entity, no alias, no fact."""
    assert out.verdict == UNCERTAIN and reason in out.reasons, (out.verdict, out.reasons)
    assert mem.state() == before


def unchanged(mem, old):
    again = mem.kb.entity(old.entity_id)
    assert (again.canonical_name, again.entity_type, dict(again.metadata or {})) == (old.canonical_name, OLD, dict(old.metadata or {}))


# ------------------------------------------------------------------ OK-1: an old entity found needs no kind (O2, O3, O6)
@pytest.mark.parametrize("old_name,sentence,subject,obj", [
    ("The dog", "The dog barks at night.", "The dog", "night"),        # O2: "the" + an animal word, step 11, shared
    ("Rob", "Rob plays chess.", "Rob", "chess"),                        # O3: a bare name, step 10 (also in Increment 5's test_kn_an_existing_unknown_entity_needs_no_kind)
    ("my school", "My school is in Pune.", "my school", "Pune"),        # O6: "my" + a place word, step 11, shared
], ids=["O2-the-dog", "O3-bare-name", "O6-my-school"])
def test_control_ok1_an_old_entity_found_takes_the_fact_and_stays_unknown(mem, old_name, sentence, subject, obj):
    [s] = mem.chat([(A, sentence)])
    old = mem.old(old_name)
    assert mem.subject(stored(mem.file(s, subject, obj))).entity_id == old.entity_id
    unchanged(mem, old)


# ------------------------------------------------------------------ OK-1: old speaker and old relation (O5)
def test_control_ok1_an_old_speaker_takes_the_fact_and_stays_unknown(mem):
    [s] = mem.chat([(A, "I live in Pune.")])
    asha = mem.old(A)
    assert mem.subject(stored(mem.file(s, "I", "Pune", "lives_in"))).entity_id == asha.entity_id
    unchanged(mem, asha)


def test_control_ok1_an_old_one_relation_takes_the_fact_and_stays_unknown(mem):
    """O5. "mother" is a one-per-speaker relation (Increment 2, step 7), so a later "my mom" finds the stored one."""
    [s] = mem.chat([(A, "My mom lives in Pune.")])
    asha = mem.old(A)
    mother = mem.old("Asha's mother", relation_of=asha.entity_id, relation="mother")
    assert mem.subject(stored(mem.file(s, "my mom", "Pune", "lives_in"))).entity_id == mother.entity_id
    unchanged(mem, mother)
    unchanged(mem, asha)


# ------------------------------------------------------------------ OK-2: an old "our dog" (O9)
def test_control_ok2_our_dog_is_held_before_any_lookup_and_the_old_one_is_left(mem):
    [s] = mem.chat([(A, "Our dog barks at night.")])
    old = mem.old("our dog")
    before = mem.state()
    held(mem, mem.file(s, "our dog", "night"), OUR, before)
    unchanged(mem, old)


# ------------------------------------------------------------------ OK-3: an old phrase-named entity (O8)
@pytest.mark.parametrize("given", [_UNSET, "animal"], ids=["no-kind", "writer-says-animal"])
def test_control_ok3_a_bare_name_inside_an_old_phrase_is_held_as_maybe_known(mem, given):
    """O8, as traced at 8669168: "Max" shares a word with the old "my dog Max", so Increment 2's similar-name check holds it
    before any kind is looked at; with or without the writer's kind (finding F-1; Draft 9, sections 4 and 4.1)."""
    [s] = mem.chat([(A, "Max sleeps all day.")])
    old = mem.old("my dog Max")
    before = mem.state()
    out = mem.file(s, "Max", "all day", subject_kind=given)
    held(mem, out, SIMILAR("Max"), before)
    assert NO_KIND("Max") not in out.reasons
    unchanged(mem, old)


# ------------------------------------------------------------------ OK-4: an old name borrowed (O4)
def test_control_ok4_an_old_unknown_name_is_borrowed_as_today(mem):
    """O4, KO-7 (a): an old entity of no known kind is not held as "a borrowed name must be a person's", even if in fact a pet."""
    a, b = mem.chat([(A, "Today Rex chased a ball."), (A, "He sleeps all day.")])
    old = mem.old("Rex")
    out = stored(mem.file(b, "Rex", "all day", subject_from=a, reading=A))
    assert BORROWED not in out.reasons and mem.subject(out).entity_id == old.entity_id
    unchanged(mem, old)
