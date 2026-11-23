"""Stage 2, Increment 2 (who a fact is about), with contract Amendment 8 (8A1, 8A2).

Frozen specification and test plan: claude/engram-stage2-inc2-spec-draft7.md, frozen 17 November 2026
(SHA-256 657351b2dfbf3c1d4a7faf4fa8e8a32e1fd7836043a5563abc5f956f6d3160b0). Section numbers below are that document's.
Cases and guarantees it takes "as Draft 2" are from claude/engram-stage2-inc2-spec-draft2.md, sections 8.3 to 8.5.

  Section 3    a relation of a speaker is an entity of its own, named "<speaker>'s <base word>[ <Name>]", held by the
               metadata keys relation_of (the speaker's entity_id) and relation (the base word with any change word)
  Section 3.1  a bare name is looked up first among the speaker's own relations, then among entities that are no one's
               relation; never through another speaker's relation; two matches are held
  Section 4    the rules, steps 0 to 11, and the relation-identity check across steps 7 and 8a to 8f
  Section 5    the word lists L1 to L6
  Section 8    the test plan: 8.2 and 8.3 (cases), 8.4 (guarantees G1 to G11)

Fixed, hand-written proposals only; no model is called. Every sentence is made up. None is LoCoMo text.

TESTS FIRST. This file is written before the build. Until Increment 2 is built, the tests whose names begin test_case,
test_held_, test_classic_, test_alias_is_, test_alias_learned_, test_alias_none_when_, test_approve_, test_relation_keys_,
test_relation_identified_ and test_walk_ are expected to FAIL, except where today's result is already the wanted one
(test_case for IN-6, CT-1 to CT-6, CT-10 and X-SOMEBODY; test_held_ for a hold that today's rules already make). Every test
whose name begins test_control_, test_pin_, test_g4_, test_g7_, test_preserved_, test_sentence_, test_alias_none_from_ or
test_relation_entities_ passes today and must pass after the build. The run is reported in
claude/engram-stage2-inc2-tests-first.md.
"""
import hashlib
import json

import pytest

import engram_chat as E
import engram_structure as S
from engram_knowledge.database import KnowledgeBase
from engram_knowledge.fact_validator import ACCEPTED, REJECTED, UNCERTAIN, Candidate, KnowledgePipeline
from engram_knowledge.models import Entity, EntityAlias
from engram_knowledge.schema import SCHEMA_VERSION

SAID = "2:15 pm on 12 June, 2025"
A, B, C = "Asha", "Ben", "Caroline"

# ------------------------------------------------------------------ the fixed reason texts (sections 3.1 and 4)
OUR = "'our' does not say whose"                                                    # step 1
INDEFINITE = "an indefinite person is not stored"                                   # step 2
DEMONSTRATIVE = "'these friends' and the like do not say who"                       # step 3
MIDDLE = "a friend, colleague or the like does not say which one"                   # step 5a
GROUP = "a group other than family is not stored"                                   # step 6
DIFFERENT_NAME = "a different name from the one stored for this relation"           # step 7
OTHER_SPEAKERS = "the name belongs to another speaker's relation"                   # section 3.1, step 4


def ANOTHER(relation):                                                              # step 8a
    return f"may be another {relation}: no name links it to the one already stored"


def ALREADY(relation):                                                              # steps 8c and 8f
    return f"may be the {relation} already stored: no name links them"


def NOT_A_SPEAKER(name):                                                            # step 9
    return f"'{name}' is not a speaker in this conversation"


# Sections 3.1 (steps 1', 2', 3) and 4 (D1-12.5) say "held as ambiguous" and "held" without a reason text. Those holds are
# tested as held, with no reason asserted (tests-first report, point TF-1).
AMBIGUOUS = None

# "someone" and "somebody" are on list L1 (step 2) but keep today's reason texts (his decision TF-2, 18 November 2026,
# option (a)): IN-6 stays a full control and G6 holds without exception.
SOMEONE = "'someone' does not say who"
SOMEBODY = "'somebody' does not say who"

# Today's reason texts that steps 11 and 0 keep (G6).
HE = "'he' does not say who"
WE = "'we' does not say who"

HELD, REFUSED = "held", "refused"


# ------------------------------------------------------------------ the chat
class Chat:
    """One store, one chat. Asha and Ben each say an opening line; then every step's sentence is said in turn (and any
    extra lines after them); then the steps are filed in order, each on base 2's path unless marked classic."""

    def __init__(self, tmp_path, steps, extra=(), prepare=None):
        self.m = E.ChatMemory(str(tmp_path / "m.db"), durable=False)
        self.kb = KnowledgeBase(self.m.db)
        self.layer = S.StructureLayer(self.m.db)
        self.m.open_chat(SAID)
        self.m.add(A, "Hi Ben, good to see you.", date=SAID)
        self.m.add(B, "Hi Asha, likewise.", date=SAID)
        self.sids = [self.m.add(st[0], st[1], date=SAID) for st in steps]
        self.extra = [self.m.add(sp, t, date=SAID) for sp, t in extra]
        self.m.close_chat(write_note=False)
        self.steps = steps
        if prepare: prepare(self)
        self.out, self.before, self.after = [], [], []

    def file_all(self, classic_last=False):
        for i, (st, sid) in enumerate(zip(self.steps, self.sids)):
            self.before.append(self.snapshot())
            if classic_last and i == len(self.steps) - 1:
                self.out.append(self.classic(sid, st))
            else:
                self.out.append(self.layer.file(sid, st[2], st[3], "claim", word=st[4], **_kind(st)))
            self.after.append(self.snapshot())
        return self

    def classic(self, sid, st):
        word = st[4] if st[4] != "other" else "likes"
        d, rid = KnowledgePipeline(self.m.db).process(Candidate(st[2], word, st[3], (sid,), "", "test", "1", **_kind(st)))
        return S.Outcome(d.verdict, d.reasons, rid if d.verdict == ACCEPTED else None, rid if d.verdict == UNCERTAIN else None)

    def snapshot(self):
        q = lambda sql: self.m.db.execute(sql).fetchall()
        return dict(entities=q("SELECT entity_id, canonical_name, metadata FROM entities ORDER BY entity_id"),
                    aliases=q("SELECT entity_id, normalized_alias, source_kind, source_id FROM entity_aliases ORDER BY alias_id"),
                    facts=q("SELECT fact_id, subject_id, status FROM knowledge_records ORDER BY fact_id"),
                    sentences=q("SELECT * FROM sentences ORDER BY sid"))

    # reading the store
    def subject(self, out):
        return self.kb.entity(self.kb.get(out.fact_id).fact.subject_id)

    def speaker_entity(self, label):
        """The speaker's stable identity (section 3): the one entity the label leads to that is no one's relation."""
        rows = [self.kb.entity(r[0]) for r in self.m.db.execute("SELECT entity_id FROM entities WHERE normalized_name=?", (label.casefold(),))]
        rows = [e for e in rows if "relation_of" not in (e.metadata or {})]
        return rows[0] if len(rows) == 1 else None

    def aliases_of(self, entity_id):
        return [a.normalized_alias for a in self.kb.aliases(entity_id)]

    def all_aliases(self):
        return [r[0] for r in self.m.db.execute("SELECT normalized_alias FROM entity_aliases")]

    def review_reasons(self, out):
        return self.kb.review(out.review_id)["reasons"] if out.review_id else None

    def close(self):
        self.m.close()


def run(tmp_path, steps, extra=(), prepare=None, classic_last=False):
    return Chat(tmp_path, steps, extra, prepare).file_all(classic_last)


# ------------------------------------------------------------------ prepared stores
def two_ashas(chat):
    """CT-10 and the like: the label "Asha" leads to two entities (names may repeat, SF-2)."""
    chat.kb.add_entity(Entity.create("Asha", "person"))
    chat.kb.add_entity(Entity.create("Asha", "person"))


def sv7_store(chat):
    """SV-7 (SF-11: sentences alone do not produce this): for Asha, "Asha's sister Sara" and an unnamed "Asha's sister",
    held as section 3 sets out. Asha's own entity is made first, as her own first fact would make it."""
    asha = chat.kb.add_entity(Entity.create("Asha", "unknown"))
    sara = chat.kb.add_entity(Entity.create("Asha's sister Sara", "unknown", metadata=dict(relation_of=asha.entity_id, relation="sister")))
    chat.kb.add_alias(EntityAlias.create(sara.entity_id, "Sara", "sentence", chat.extra[0]))
    chat.kb.add_entity(Entity.create("Asha's sister", "unknown", metadata=dict(relation_of=asha.entity_id, relation="sister")))


# ------------------------------------------------------------------ the cases (8.2, 8.3) and further cases
# A step: (speaker, sentence, subject, object, word). A wanted result per step:
#   ("e1", display name or None, owner or None, relation or None)  stored under the case's first, second ... entity;
#                                                                  a relation entity's owner and relation when given
#   (HELD, reason or None)                                         held for review; the reason when the text fixes one
#   (REFUSED,)                                                     not accepted, nothing stored
def st(speaker, sentence, subject, obj, word, subject_kind=None):
    """Increment 5 (P-2): a sixth element, the writer's subject_kind, only when the case gives one."""
    return (speaker, sentence, subject, obj, word) if subject_kind is None else (speaker, sentence, subject, obj, word, subject_kind)


def _kind(step):
    return {"subject_kind": step[5]} if len(step) > 5 else {}


def sis(sp, place="Pune"): return st(sp, f"My sister lives in {place}.", "my sister", place, "lives_in")


CASES = {
    # --- 8.2: measured 15 November
    "ID-1": ([sis(A), sis(B, "Delhi")], [("e1", "Asha's sister", A, "sister"), ("e2", "Ben's sister", B, "sister")]),
    "ID-2": ([st(A, "My mom lives in Pune.", "my mom", "Pune", "lives_in"), st(B, "My mom lives in Delhi.", "my mom", "Delhi", "lives_in")],
             [("e1", "Asha's mother", A, "mother"), ("e2", "Ben's mother", B, "mother")]),
    "ID-3": ([st(A, "My family lives in Mysore.", "my family", "Mysore", "lives_in"), st(B, "My family lives in Delhi.", "my family", "Delhi", "lives_in")],
             [("e1", "Asha's family", A, "family"), ("e2", "Ben's family", B, "family")]),
    "SV-1": ([sis(A), st(A, "My sister works at Infosys.", "my sister", "Infosys", "works_at")],
             [("e1", "Asha's sister", A, "sister"), (HELD, ANOTHER("sister"))]),
    "SV-2": ([st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"), st(A, "My sister Sara works at Infosys.", "my sister Sara", "Infosys", "works_at")],
             [("e1", "Asha's sister Sara", A, "sister"), ("e1", None, None, None)]),
    "SV-3": ([st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"), st(A, "My sister Priya lives in Delhi.", "my sister Priya", "Delhi", "lives_in")],
             [("e1", "Asha's sister Sara", A, "sister"), ("e2", "Asha's sister Priya", A, "sister")]),
    "SV-4": ([st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"), st(A, "My sister works at Infosys.", "my sister", "Infosys", "works_at")],
             [("e1", "Asha's sister Sara", A, "sister"), (HELD, ANOTHER("sister"))]),
    "SV-5": ([st(A, "My son studies at Inventure Academy.", "my son", "Inventure Academy", "studies_at"), st(A, "My son plays the violin.", "my son", "the violin", "hobby")],
             [("e1", "Asha's son", A, "son"), (HELD, ANOTHER("son"))]),
    "SV-6": ([sis(A), st(A, "My sister Sara works at Infosys.", "my sister Sara", "Infosys", "works_at")],
             [("e1", "Asha's sister", A, "sister"), (HELD, ALREADY("sister"))]),
    "OP-1": ([st(A, "My mom lives in Pune.", "my mom", "Pune", "lives_in"), st(A, "My mom works at Infosys.", "my mom", "Infosys", "works_at")],
             [("e1", "Asha's mother", A, "mother"), ("e1", None, None, None)]),
    "OP-2": ([st(A, "My husband Raj works at Infosys.", "my husband Raj", "Infosys", "works_at"), st(A, "My husband Raj lives in Pune.", "my husband Raj", "Pune", "lives_in")],
             [("e1", "Asha's husband Raj", A, "husband"), ("e1", None, None, None)]),
    "OP-3": ([st(A, "My husband Raj works at Infosys.", "my husband Raj", "Infosys", "works_at"), st(A, "My husband Vikram lives in Pune.", "my husband Vikram", "Pune", "lives_in")],
             [("e1", "Asha's husband Raj", A, "husband"), (HELD, DIFFERENT_NAME)]),
    "OP-4": ([st(A, "My husband Raj works at Infosys.", "my husband Raj", "Infosys", "works_at"), st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in")],
             [("e1", "Asha's husband Raj", A, "husband"), ("e1", None, None, None)]),
    "OP-5": ([st(A, "My mom lives in Pune.", "my mom", "Pune", "lives_in"), st(A, "My mother works at Infosys.", "my mother", "Infosys", "works_at")],
             [("e1", "Asha's mother", A, "mother"), ("e1", None, None, None)]),
    "OP-6": ([st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in"), st(A, "My husband Raj works at Infosys.", "my husband Raj", "Infosys", "works_at")],
             [("e1", "Asha's husband", A, "husband"), ("e1", "Asha's husband", A, "husband")]),
    "CH-1": ([st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in"), st(A, "My ex-husband lives in Delhi.", "my ex-husband", "Delhi", "lives_in")],
             [("e1", "Asha's husband", A, "husband"), ("e2", "Asha's ex husband", A, "ex husband")]),
    "CH-2": ([st(A, "My father lives in Pune.", "my father", "Pune", "lives_in"), st(A, "My late father worked at BHEL.", "my late father", "BHEL", "works_at")],
             [("e1", "Asha's father", A, "father"), ("e2", "Asha's late father", A, None)]),
    "CH-3": ([st(A, "My mom lives in Pune.", "my mom", "Pune", "lives_in"), st(A, "My stepmom lives in Mysore.", "my stepmom", "Mysore", "lives_in")],
             [("e1", "Asha's mother", A, "mother"), ("e2", "Asha's stepmother", A, None)]),
    "CH-4": ([st(A, "My ex-husband lives in Delhi.", "my ex-husband", "Delhi", "lives_in"), st(A, "My ex-husband works at Wipro.", "my ex-husband", "Wipro", "works_at")],
             [("e1", "Asha's ex husband", A, "ex husband"), ("e1", None, None, None)]),
    "DS-1": ([st(A, "My older sister lives in Pune.", "my older sister", "Pune", "lives_in")], [("e1", "Asha's sister", A, "sister")]),
    "DS-2": ([st(A, "My older sister lives in Pune.", "my older sister", "Pune", "lives_in"), st(A, "My sister works at Infosys.", "my sister", "Infosys", "works_at")],
             [("e1", "Asha's sister", A, "sister"), (HELD, ANOTHER("sister"))]),
    "DS-3": ([st(A, "My little brother lives in Pune.", "my little brother", "Pune", "lives_in")], [("e1", "Asha's brother", A, "brother")]),
    "DS-4": ([st(A, "My best friend lives in Goa.", "my best friend", "Goa", "lives_in")], [(HELD, MIDDLE)]),
    "MD-1": ([st(A, "My friend lives in Goa.", "my friend", "Goa", "lives_in")], [(HELD, MIDDLE)]),
    "MD-2": ([st(A, "My colleague lives in Goa.", "my colleague", "Goa", "lives_in")], [(HELD, MIDDLE)]),
    "MD-3": ([st(A, "My buddy lives in Goa.", "my buddy", "Goa", "lives_in")], [(HELD, MIDDLE)]),
    "MD-4": ([st(A, "My boss lives in Goa.", "my boss", "Goa", "lives_in")], [(HELD, MIDDLE)]),
    "GR-1": ([st(A, "My family lives in Mysore.", "my family", "Mysore", "lives_in")], [("e1", "Asha's family", A, "family")]),
    "GR-2": ([st(A, "My kids study at Inventure Academy.", "my kids", "Inventure Academy", "studies_at")], [("e1", "Asha's kids", A, "kids")]),
    "GR-3": ([st(A, "My parents live in Mysore.", "my parents", "Mysore", "lives_in")], [("e1", "Asha's parents", A, "parents")]),
    "GR-4": ([st(A, "My friends live in Goa.", "my friends", "Goa", "lives_in")], [(HELD, GROUP)]),
    "GR-5": ([st(A, "My team plays at Kanteerava Stadium.", "my team", "Kanteerava Stadium", "other")], [(HELD, GROUP)]),
    "GR-6": ([st(A, "My teammates live in Pune.", "my teammates", "Pune", "lives_in")], [(HELD, GROUP)]),
    "OU-1": ([st(A, "Our kids study at Inventure Academy.", "our kids", "Inventure Academy", "studies_at")], [(HELD, OUR)]),
    "OU-2": ([st(A, "Our family lives in Mysore.", "our family", "Mysore", "lives_in")], [(HELD, OUR)]),
    "OU-3": ([st(A, "Our neighbours live in Goa.", "our neighbours", "Goa", "lives_in")], [(HELD, OUR)]),
    "IN-1": ([st(A, "A pal of mine adopted a beagle.", "a pal of mine", "a beagle", "adopted")], [(HELD, INDEFINITE)]),
    "IN-2": ([st(A, "A friend lives in Goa.", "a friend", "Goa", "lives_in")], [(HELD, INDEFINITE)]),
    "IN-3": ([st(A, "One of my friends lives in Goa.", "one of my friends", "Goa", "lives_in")], [(HELD, INDEFINITE)]),
    "IN-4": ([st(A, "Some of my colleagues live in Goa.", "some of my colleagues", "Goa", "lives_in")], [(HELD, INDEFINITE)]),
    "IN-5": ([st(A, "A colleague of mine works at Infosys.", "a colleague of mine", "Infosys", "works_at")], [(HELD, INDEFINITE)]),
    "IN-6": ([st(A, "Someone I know lives in Goa.", "someone", "Goa", "lives_in")], [(HELD, SOMEONE)]),
    "IN-7": ([st(A, "Some friends of mine live in Goa.", "some friends of mine", "Goa", "lives_in")], [(HELD, INDEFINITE)]),
    "NP-1": ([st(A, "Ben's sister lives in Delhi.", "Ben's sister", "Delhi", "lives_in")], [("e1", "Ben's sister", B, "sister")]),
    "NP-2": ([st(B, "My mom lives in Delhi.", "my mom", "Delhi", "lives_in"), st(A, "Ben's mom works at Wipro.", "Ben's mom", "Wipro", "works_at")],
             [("e1", "Ben's mother", B, "mother"), ("e1", None, None, None)]),
    "NP-3": ([st(A, "Caroline's sister lives in Goa.", "Caroline's sister", "Goa", "lives_in")], [(HELD, NOT_A_SPEAKER("Caroline"))]),
    "CT-1": ([st(A, "I live in Pune.", "I", "Pune", "lives_in")], [("e1", "Asha", None, None)]),
    "CT-2": ([st(A, "Max lives in Goa.", "Max", "Goa", "lives_in", "person")], [("e1", "Max", None, None)]),
    "CT-3": ([st(A, "He lives in Goa.", "he", "Goa", "lives_in")], [(HELD, HE)]),
    "CT-4": ([st(A, "We live in Goa.", "we", "Goa", "lives_in")], [(HELD, WE)]),
    "CT-5": ([st(A, "I love my job at Infosys.", "my job", "Infosys", "works_at")], [("e1", "Asha", None, None)]),
    "CT-6": ([st(A, "I live in Pune.", "I", "Pune", "lives_in"), st(B, "Asha works at Infosys.", "Asha", "Infosys", "works_at")],
             [("e1", "Asha", None, None), ("e1", None, None, None)]),
    "CT-7": ([st(A, "My sister lives in Paris.", "my sister", "Paris", "lives_in"), st(A, "My brother lives in Rome.", "my brother", "Rome", "lives_in")],
             [("e1", "Asha's sister", A, "sister"), ("e2", "Asha's brother", A, "brother")]),
    "CT-8": ([st(A, "My sister lives in Paris.", "my sister", "Paris", "lives_in"), st(A, "I work with Dave.", "my sister", "Dave", "other")],
             [("e1", "Asha's sister", A, "sister"), (REFUSED,)]),
    "CT-10": ([st(A, "I live in Pune.", "I", "Pune", "lives_in")], [(HELD, AMBIGUOUS)]),
    # --- 8.3: naming
    "NM-2": ([st(A, "My mum lives in Pune.", "my mum", "Pune", "lives_in")], [("e1", "Asha's mother", A, "mother")]),
    # --- 8.3: scoped aliases
    "AL-1": ([st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"), st(A, "Sara works at Infosys.", "Sara", "Infosys", "works_at")],
             [("e1", "Asha's sister Sara", A, "sister"), ("e1", None, None, None)]),
    "AL-2": ([st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"), st(B, "Sara works at Wipro.", "Sara", "Wipro", "works_at")],
             [("e1", "Asha's sister Sara", A, "sister"), (HELD, OTHER_SPEAKERS)]),
    "AL-3": ([st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"), st(B, "My cousin Sara lives in Delhi.", "my cousin Sara", "Delhi", "lives_in"),
              st(B, "Sara works at Wipro.", "Sara", "Wipro", "works_at")],
             [("e1", "Asha's sister Sara", A, "sister"), ("e2", "Ben's cousin Sara", B, "cousin"), ("e2", None, None, None)]),
    "AL-4": ([st(A, "Sara lives in Mumbai.", "Sara", "Mumbai", "lives_in", "person"), st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"),
              st(B, "Sara lives in Delhi.", "Sara", "Delhi", "lives_in")],
             [("e1", "Sara", None, None), ("e2", "Asha's sister Sara", A, "sister"), ("e1", None, None, None)]),
    "AL-5": ([st(A, "Sara lives in Mumbai.", "Sara", "Mumbai", "lives_in", "person"), st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"),
              st(A, "Sara called me.", "Sara", "called me", "other")],
             [("e1", "Sara", None, None), ("e2", "Asha's sister Sara", A, "sister"), (HELD, AMBIGUOUS)]),
    "AL-6": ([sis(A), st(B, "Asha's sister lives in Pune.", "Asha's sister", "Pune", "lives_in")],
             [("e1", "Asha's sister", A, "sister"), (HELD, ANOTHER("sister"))]),
    "AL-7": ([st(A, "My sister Sara lives in Pune.", "my sister Sara", "Pune", "lives_in"), st(A, "My cousin Sara lives in Delhi.", "my cousin Sara", "Delhi", "lives_in"),
              st(A, "Sara called me.", "Sara", "called me", "other")],
             [("e1", "Asha's sister Sara", A, "sister"), ("e2", "Asha's cousin Sara", A, "cousin"), (HELD, AMBIGUOUS)]),
    # --- 8.3: the named middle case
    "MN-1": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other")], [("e1", "Asha's colleague Rob", A, "colleague")]),
    "MN-2": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other"), st(A, "My colleague Rob works at Wipro.", "my colleague Rob", "Wipro", "works_at")],
             [("e1", "Asha's colleague Rob", A, "colleague"), ("e1", None, None, None)]),
    "MN-3": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other"), st(A, "Rob lives in Pune.", "Rob", "Pune", "lives_in")],
             [("e1", "Asha's colleague Rob", A, "colleague"), ("e1", None, None, None)]),
    "MN-4": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other"), st(B, "Rob lives in Delhi.", "Rob", "Delhi", "lives_in")],
             [("e1", "Asha's colleague Rob", A, "colleague"), (HELD, OTHER_SPEAKERS)]),
    "MN-5": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other"), st(A, "My colleague lives in Goa.", "my colleague", "Goa", "lives_in")],
             [("e1", "Asha's colleague Rob", A, "colleague"), (HELD, MIDDLE)]),
    "MN-6": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other"), st(A, "My colleague Priya lives in Goa.", "my colleague Priya", "Goa", "lives_in")],
             [("e1", "Asha's colleague Rob", A, "colleague"), ("e2", "Asha's colleague Priya", A, "colleague")]),
    "MN-7": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other"), st(A, "My colleague Priya lives in Goa.", "my colleague Priya", "Goa", "lives_in"),
              st(A, "My colleague lives in Goa.", "my colleague", "Goa", "lives_in")],
             [("e1", "Asha's colleague Rob", A, "colleague"), ("e2", "Asha's colleague Priya", A, "colleague"), (HELD, MIDDLE)]),
    # --- 8.3: partner and "old"
    "PT-1": ([st(A, "My partner lives in Pune.", "my partner", "Pune", "lives_in")], [("e1", "Asha's partner", A, "partner")]),
    "PT-2": ([st(A, "My partner lives in Pune.", "my partner", "Pune", "lives_in"), st(A, "My partner works at Infosys.", "my partner", "Infosys", "works_at")],
             [("e1", "Asha's partner", A, "partner"), ("e1", None, None, None)]),
    "OL-1": ([st(A, "My old boss lives in Goa.", "my old boss", "Goa", "lives_in")], [(HELD, MIDDLE)]),
    "OL-2": ([st(A, "My old sister lives in Pune.", "my old sister", "Pune", "lives_in")], [("e1", "Asha's sister", A, "sister")]),
    "CH-5": ([st(A, "My ex-husband Raj lives in Delhi.", "my ex-husband Raj", "Delhi", "lives_in"), st(A, "My ex-husband Vikram works at Wipro.", "my ex-husband Vikram", "Wipro", "works_at")],
             [("e1", "Asha's ex husband Raj", A, "ex husband"), (HELD, DIFFERENT_NAME)]),
    # --- 8.3: the interpretations
    "DM-1": ([st(A, "That guy fixed my car.", "that guy", "my car", "other")], [(HELD, DEMONSTRATIVE)]),
    "DM-2": ([st(A, "These friends helped me move.", "these friends", "move", "other")], [(HELD, DEMONSTRATIVE)]),
    "HN-1": ([sis(A), st(A, "My sister Mia moved to Delhi.", "my sister Mia", "Delhi", "moved_to"), st(A, "Mia called me.", "Mia", "called me", "other", "person")],
             [("e1", "Asha's sister", A, "sister"), (HELD, ALREADY("sister")), ("e2", "Mia", None, None)]),
    "NS-1": ([st(A, "Sara, my sister, called me.", "my sister", "called me", "other")], [("e1", "Asha's sister", A, "sister")]),
    "NS-2": ([st(A, "my sister sara lives in Pune.", "my sister sara", "Pune", "lives_in")], [("e1", "Asha's sister", A, "sister")]),
    "RQ-1": ([sis(A), st(A, "She just got promoted.", "my sister", "promoted", "other")], [("e1", "Asha's sister", A, "sister"), (REFUSED,)]),
    # --- 8.3: settled in Draft 5
    "CK-1": ([sis(A), st(A, "My stepsister lives in Delhi.", "my stepsister", "Delhi", "lives_in")],
             [("e1", "Asha's sister", A, "sister"), ("e2", "Asha's stepsister", A, None)]),
    # --- 8.3: animals
    "AN-3": ([st(A, "My little pals love lettuce.", "my little pals", "lettuce", "likes")], [(HELD, GROUP)]),

    # --- further cases, each from a settled rule (section 4 and the lists of section 5)
    "X-HUBBY": ([st(A, "My hubby works at Wipro.", "my hubby", "Wipro", "works_at")], [("e1", "Asha's husband", A, "husband")]),            # L2a forms
    "X-BABY-BROTHER": ([st(A, "My baby brother lives in Pune.", "my baby brother", "Pune", "lives_in")], [("e1", "Asha's brother", A, "brother")]),  # L2b, D1-6c
    "X-BABY": ([st(A, "My baby sleeps at night.", "my baby", "night", "other")], [("e1", "Asha's child", A, "child")]),                       # L2b, D1-6c
    "X-CHILDREN": ([st(A, "My children study at Inventure Academy.", "my children", "Inventure Academy", "studies_at")], [("e1", "Asha's kids", A, "kids")]),  # L3a
    "X-FOLKS": ([st(A, "My folks live in Mysore.", "my folks", "Mysore", "lives_in")], [("e1", "Asha's family", A, "family")]),             # L3a, D1-6d
    "X-SISTERS": ([st(A, "My sisters live in Pune.", "my sisters", "Pune", "lives_in"), st(A, "My sister Sara lives in Delhi.", "my sister Sara", "Delhi", "lives_in")],
                  [("e1", "Asha's sisters", A, "sisters"), ("e2", "Asha's sister Sara", A, "sister")]),                                       # L3a, D1-6d
    "X-FAMILY-TWICE": ([st(A, "My family lives in Mysore.", "my family", "Mysore", "lives_in"), st(A, "My family loves cricket.", "my family", "cricket", "likes")],
                       [("e1", "Asha's family", A, "family"), ("e1", None, None, None)]),                                                    # step 7
    "X-MIXED": ([st(A, "My friends, cousins and neighbours came to the wedding.", "my friends, cousins and neighbours", "the wedding", "other")], [(HELD, GROUP)]),  # D1-6e
    "X-COLLEAGUES": ([st(A, "My colleagues live in Goa.", "my colleagues", "Goa", "lives_in")], [(HELD, GROUP)]),                              # L3b
    "X-DOCTOR": ([st(A, "My doctor works at Manipal.", "my doctor", "Manipal", "works_at")], [(HELD, MIDDLE)]),                                # L4
    "X-DOCTOR-NAMED": ([st(A, "My doctor Mehta works at Manipal.", "my doctor Mehta", "Manipal", "works_at")], [("e1", "Asha's doctor Mehta", A, "doctor")]),  # D1-6f
    "X-TWO-WORD-NAME": ([st(A, "My colleague Rob Smith works at Wipro.", "my colleague Rob Smith", "Wipro", "works_at")],
                        [("e1", "Asha's colleague Rob Smith", A, "colleague")]),                                                              # D1-12.9
    "X-BEN-ROB": ([st(A, "My colleague Rob plays chess.", "my colleague Rob", "chess", "other"), st(B, "My colleague Rob lives in Delhi.", "my colleague Rob", "Delhi", "lives_in")],
                  [("e1", "Asha's colleague Rob", A, "colleague"), ("e2", "Ben's colleague Rob", B, "colleague")]),                           # D1-8, scope
    "X-SECOND-HUSBAND": ([st(A, "My second husband works at Wipro.", "my second husband", "Wipro", "works_at")], [("e1", "Asha's second husband", A, None)]),  # L5
    "X-NEW-HUSBAND": ([st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in"), st(A, "My new husband works at Wipro.", "my new husband", "Wipro", "works_at"),
                       st(A, "My husband plays the violin.", "my husband", "the violin", "hobby")],
                      [("e1", "Asha's husband", A, "husband"), ("e2", "Asha's new husband", A, None), ("e1", None, None, None)]),            # D1-6g
    "X-CURRENT-HUSBAND": ([st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in"), st(A, "My current husband works at Wipro.", "my current husband", "Wipro", "works_at")],
                          [("e1", "Asha's husband", A, "husband"), ("e1", None, None, None)]),                                               # D1-6h
    "X-EX-LATE": ([st(A, "My ex-husband lives in Delhi.", "my ex-husband", "Delhi", "lives_in"), st(A, "My late husband worked at BHEL.", "my late husband", "BHEL", "works_at")],
                  [("e1", "Asha's ex husband", A, "ex husband"), ("e2", "Asha's late husband", A, None)]),                                   # the relation-identity check
    "X-EX-PLAIN": ([st(A, "My ex-husband lives in Delhi.", "my ex-husband", "Delhi", "lives_in"), st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in")],
                   [("e1", "Asha's ex husband", A, "ex husband"), ("e2", "Asha's husband", A, "husband")]),                                  # the relation-identity check
    "X-ALIAS-LATER": ([st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in"), st(A, "My husband Raj works at Infosys.", "my husband Raj", "Infosys", "works_at"),
                       st(A, "Raj plays the violin.", "Raj", "the violin", "hobby")],
                      [("e1", "Asha's husband", A, "husband"), ("e1", None, None, None), ("e1", None, None, None)]),                         # D1-12.2, D1-10
    "X-ALIAS-LATER-CONFLICT": ([st(A, "My husband lives in Pune.", "my husband", "Pune", "lives_in"), st(A, "My husband Raj works at Infosys.", "my husband Raj", "Infosys", "works_at"),
                                st(A, "My husband Vikram plays the violin.", "my husband Vikram", "the violin", "hobby")],
                               [("e1", "Asha's husband", A, "husband"), ("e1", None, None, None), (HELD, DIFFERENT_NAME)]),                  # step 7
    "X-COUSIN-NAMED": ([st(A, "My cousin Sara lives in Delhi.", "my cousin Sara", "Delhi", "lives_in")], [("e1", "Asha's cousin Sara", A, "cousin")]),  # 8d
    "X-SCREENPLAY": ([st(A, "My sister read my first novel.", "my sister", "my first novel", "other")], [("e1", "Asha's sister", A, "sister")]),  # L5, IB2-24
    "X-BEN-EX-WIFE": ([st(A, "Ben's ex-wife lives in Goa.", "Ben's ex-wife", "Goa", "lives_in")], [("e1", "Ben's ex wife", B, "ex wife")]),   # step 9 with step 4
    "X-BEN-COLLEAGUE": ([st(A, "Ben's colleague lives in Goa.", "Ben's colleague", "Goa", "lives_in")], [(HELD, MIDDLE)]),                    # step 9 with step 5a
    "X-BEN-FRIENDS": ([st(A, "Ben's friends live in Goa.", "Ben's friends", "Goa", "lives_in")], [(HELD, GROUP)]),                            # step 9 with step 6
    "X-ANOTHER": ([st(A, "Another friend lives in Goa.", "another friend", "Goa", "lives_in")], [(HELD, INDEFINITE)]),                         # L1
    "X-BOTH-OF": ([st(A, "Both of my brothers live in Pune.", "both of my brothers", "Pune", "lives_in")], [(HELD, INDEFINITE)]),             # L1
    "X-SOMEBODY": ([st(A, "Somebody fixed my car.", "somebody", "my car", "other")], [(HELD, SOMEBODY)]),                                      # L1; today's reason (TF-2)
    "X-THOSE": ([st(A, "Those colleagues work at Wipro.", "those colleagues", "Wipro", "works_at")], [(HELD, DEMONSTRATIVE)]),                 # step 3
    "X-OUR-SISTER": ([st(A, "Our sister lives in Pune.", "our sister", "Pune", "lives_in")], [(HELD, OUR)]),                                   # step 1
}

# Cases on a prepared store (section 8.3, SV-7; CT-10 and D1-12.5)
PREPARED = {
    "SV-7": ([st(A, "My sister Mia moved to Delhi.", "my sister Mia", "Delhi", "moved_to")], [(HELD, ALREADY("sister"))], sv7_store,
             [(A, "My sister Sara is lovely.")]),
    "CT-10": ([st(A, "I live in Pune.", "I", "Pune", "lives_in")], [(HELD, AMBIGUOUS)], two_ashas, ()),
    "X-UNIDENTIFIED": ([sis(A)], [(HELD, AMBIGUOUS)], two_ashas, ()),                                                                      # D1-12.5
}
CASES.pop("CT-10")   # it lives in PREPARED

# The controls of Draft 2, section 8.3: today's result and the wanted result are the same apart from naming (G5).
# Increment 5 (his R-3, 22 November 22:12): CT-2 left this list; it now gives subject_kind, so it cannot pass before the build.
CONTROLS = ["SV-2", "OP-1", "OP-2", "CH-1", "CH-3", "CT-7", "MD-1", "IN-6", "CT-1", "CT-3", "CT-4", "CT-5", "CT-6", "CT-8", "CH-4"]


def ids_of(table): return list(table)


def check(chat, wanted):
    """Compares each step's outcome with its wanted result. Returns a list of differences, empty when all agree."""
    bad, labels = [], {}
    for i, (out, want) in enumerate(zip(chat.out, wanted), 1):
        if want[0] == HELD:
            if out.verdict != UNCERTAIN: bad.append(f"step {i}: wanted held, got {out.verdict} {out.reasons}"); continue
            if want[1] is not None and want[1] not in out.reasons: bad.append(f"step {i}: wanted reason {want[1]!r}, got {out.reasons}")
            continue
        if want[0] == REFUSED:
            if out.verdict == ACCEPTED or out.fact_id: bad.append(f"step {i}: wanted not accepted, got {out.verdict}")
            continue
        if out.verdict != ACCEPTED or not out.fact_id: bad.append(f"step {i}: wanted stored {want[0]}, got {out.verdict} {out.reasons}"); continue
        ent = chat.subject(out)
        label, name, owner, relation = want
        if label in labels and labels[label] != ent.entity_id: bad.append(f"step {i}: wanted the same entity as {label}, got another ({ent.canonical_name!r})")
        if label not in labels and ent.entity_id in labels.values(): bad.append(f"step {i}: wanted a new entity {label}, got an earlier one ({ent.canonical_name!r})")
        labels.setdefault(label, ent.entity_id)
        if name is not None and ent.canonical_name != name: bad.append(f"step {i}: wanted the name {name!r}, got {ent.canonical_name!r}")
        meta = ent.metadata or {}
        if owner is not None:
            who = chat.speaker_entity(owner)
            if who is None or meta.get("relation_of") != who.entity_id: bad.append(f"step {i}: wanted relation_of {owner}'s entity, got {meta.get('relation_of')!r}")
        elif name is not None and "relation_of" in meta: bad.append(f"step {i}: wanted no relation_of, got one")
        if relation is not None and meta.get("relation") != relation: bad.append(f"step {i}: wanted relation {relation!r}, got {meta.get('relation')!r}")
    return bad


# ------------------------------------------------------------------ the cases, in full: expected to fail until the build
@pytest.mark.parametrize("cid", ids_of(CASES))
def test_case(tmp_path, cid):
    steps, wanted = CASES[cid]
    chat = run(tmp_path, steps)
    try:
        assert check(chat, wanted) == []
    finally:
        chat.close()


@pytest.mark.parametrize("cid", ids_of(PREPARED))
def test_case_prepared(tmp_path, cid):
    steps, wanted, prepare, extra = PREPARED[cid]
    chat = run(tmp_path, steps, extra, prepare)
    try:
        assert check(chat, wanted) == []
    finally:
        chat.close()


# ------------------------------------------------------------------ G5: the controls keep their structure (pass before and after)
def structure(want):
    return want if want[0] in (HELD, REFUSED) else (want[0], None, None, None)


@pytest.mark.parametrize("cid", CONTROLS)
def test_control_keeps_its_result(tmp_path, cid):
    """Same verdicts, and the same entity or a different one at each step, as today. Naming is checked by test_case."""
    steps, wanted = CASES[cid]
    wanted = [structure(w) if w[0] != HELD else (HELD, None) for w in wanted]
    chat = run(tmp_path, steps)
    try:
        assert check(chat, wanted) == []
    finally:
        chat.close()


@pytest.mark.parametrize("cid,reason", [("CT-3", HE), ("CT-4", WE)])
def test_control_keeps_its_reason_text(tmp_path, cid, reason):
    """G6: step 11 leaves today's reasons as they are."""
    chat = run(tmp_path, CASES[cid][0])
    try:
        assert chat.out[0].reasons == (reason,)
    finally:
        chat.close()


# ------------------------------------------------------------------ G2 and G3: a held proposal
def held_steps():
    for cid, (steps, wanted) in CASES.items():
        for i, w in enumerate(wanted):
            if w[0] == HELD: yield pytest.param(cid, i, id=f"{cid}-step{i + 1}")


@pytest.mark.parametrize("cid,i", list(held_steps()))
def test_held_stores_nothing_and_keeps_its_sentence(tmp_path, cid, i):
    """G2, D1-12.3: no fact, no entity, no alias; the sentence unchanged (PR-1). G3: one item in the review queue."""
    steps, wanted = CASES[cid]
    chat = run(tmp_path, steps[:i + 1])
    try:
        out, before, after = chat.out[i], chat.before[i], chat.after[i]
        assert out.verdict == UNCERTAIN and out.fact_id is None
        assert after["facts"] == before["facts"] and after["entities"] == before["entities"] and after["aliases"] == before["aliases"]
        assert after["sentences"] == before["sentences"]
        assert chat.kb.review(out.review_id) is not None
    finally:
        chat.close()


def held_with_reason():
    for cid, (steps, wanted) in CASES.items():
        for i, w in enumerate(wanted):
            if w[0] == HELD and w[1] is not None and cid not in ("CT-3", "CT-4"): yield pytest.param(cid, i, w[1], id=f"{cid}-step{i + 1}")


@pytest.mark.parametrize("cid,i,reason", list(held_with_reason()))
def test_held_item_carries_exactly_its_reason(tmp_path, cid, i, reason):
    """G3: the review queue holds the proposal with exactly its rule's reason (section 4's text, word for word)."""
    chat = run(tmp_path, CASES[cid][0][:i + 1])
    try:
        out = chat.out[i]
        assert out.verdict == UNCERTAIN and out.reasons == (reason,)
        assert chat.review_reasons(out) == [reason]
    finally:
        chat.close()


@pytest.mark.parametrize("cid", ids_of(PREPARED))
def test_held_prepared_stores_nothing(tmp_path, cid):
    steps, wanted, prepare, extra = PREPARED[cid]
    chat = run(tmp_path, steps, extra, prepare)
    try:
        out, before, after = chat.out[0], chat.before[0], chat.after[0]
        assert out.verdict == UNCERTAIN and out.fact_id is None
        assert after["facts"] == before["facts"] and after["entities"] == before["entities"] and after["aliases"] == before["aliases"]
        assert after["sentences"] == before["sentences"]
    finally:
        chat.close()


# ------------------------------------------------------------------ G1: the same rules on the classic path
CLASSIC_WORDS = {"lives_in", "works_at", "moved_to", "adopted", "likes", "hobby"}


def classic_held():
    for cid, (steps, wanted) in CASES.items():
        w, last = wanted[-1], steps[-1]
        if w[0] == HELD and w[1] is not None and last[4] in CLASSIC_WORDS and cid not in ("CT-3", "CT-4"):
            yield pytest.param(cid, w[1], id=cid)


@pytest.mark.parametrize("cid,reason", list(classic_held()))
def test_classic_path_holds_with_the_same_reason(tmp_path, cid, reason):
    """G1: the case's last proposal, filed on the classic path (the earlier ones on base 2's path), is held with the
    rule's reason among its reasons, and stores nothing."""
    chat = run(tmp_path, CASES[cid][0], classic_last=True)
    try:
        out = chat.out[-1]
        assert out.verdict == UNCERTAIN and reason in out.reasons
        assert chat.after[-1]["facts"] == chat.before[-1]["facts"] and chat.after[-1]["entities"] == chat.before[-1]["entities"]
    finally:
        chat.close()


# ------------------------------------------------------------------ G8: approving a held item gives the same scoped entity
def test_approve_on_the_classic_path_gives_the_scoped_entity(tmp_path):
    """G8 and G1: the classic path holds "My mom lives in Pune." (it is reported about someone else); a person approves
    it; the fact goes to Asha's mother, scoped to Asha, and base 2's later "My mom works at Infosys." finds the same entity."""
    steps = [st(A, "My mom lives in Pune.", "my mom", "Pune", "lives_in"), st(A, "My mom works at Infosys.", "my mom", "Infosys", "works_at")]
    chat = Chat(tmp_path, steps)
    try:
        held = chat.classic(chat.sids[0], steps[0])
        assert held.verdict == UNCERTAIN
        stored = KnowledgePipeline(chat.m.db).approve(held.review_id)
        ent = chat.kb.entity(stored.fact.subject_id)
        assert ent.canonical_name == "Asha's mother"
        assert (ent.metadata or {}).get("relation_of") == chat.speaker_entity(A).entity_id
        later = chat.layer.file(chat.sids[1], "my mom", "Infosys", "claim", word="works_at")
        assert later.verdict == ACCEPTED and chat.subject(later).entity_id == ent.entity_id
    finally:
        chat.close()


# ------------------------------------------------------------------ scoped aliases (D1-10, D1-12.1, D1-12.2, D1-12.3, D1-12.9; PR-5)
@pytest.mark.parametrize("cid,step,alias", [
    ("SV-2", 0, "sara"), ("OP-2", 0, "raj"), ("MN-1", 0, "rob"), ("MN-6", 1, "priya"), ("SV-3", 1, "priya"),
    ("OP-6", 1, "raj"), ("AL-3", 1, "sara"), ("CH-5", 0, "raj"), ("X-DOCTOR-NAMED", 0, "mehta"),
])
def test_alias_is_recorded_on_the_relation_with_its_sentence(tmp_path, cid, step, alias):
    """A relation's name is an alias of the relation's own entity, its source the sentence it came from (PR-5)."""
    chat = run(tmp_path, CASES[cid][0][:step + 1])
    try:
        out = chat.out[step]
        assert out.verdict == ACCEPTED
        ent = chat.subject(out)
        rows = [a for a in chat.kb.aliases(ent.entity_id) if a.normalized_alias == alias]
        assert len(rows) == 1 and rows[0].source_kind == "sentence" and rows[0].source_id == str(chat.sids[step])
        assert chat.all_aliases().count(alias) == (2 if cid == "AL-3" else 1)   # AL-3: Asha's sister Sara and Ben's cousin Sara each hold "sara"
    finally:
        chat.close()


def test_alias_learned_later_does_not_rename(tmp_path):
    """D1-12.2 (OP-6): the display name stays as created; Raj is added as an alias; contract C9 is unchanged."""
    chat = run(tmp_path, CASES["OP-6"][0])
    try:
        assert chat.out[1].verdict == ACCEPTED
        ent = chat.subject(chat.out[1])
        assert ent.canonical_name == "Asha's husband" and chat.aliases_of(ent.entity_id) == ["raj"]
    finally:
        chat.close()


@pytest.mark.parametrize("cid", ["NS-1", "NS-2", "SV-1", "DS-1", "ID-1"])
def test_alias_none_when_no_name_is_given_in_the_subject(tmp_path, cid):
    """D1-12.9: a name placed elsewhere in the sentence, or in lower case, is not taken. An unnamed relation has no alias."""
    chat = run(tmp_path, CASES[cid][0])
    try:
        assert chat.out[0].verdict == ACCEPTED and chat.subject(chat.out[0]).canonical_name.startswith(("Asha's ", "Ben's "))
        assert chat.all_aliases() == []
    finally:
        chat.close()


@pytest.mark.parametrize("cid", ["HN-1", "SV-6", "OP-3", "CH-5", "AL-2", "MN-4"])
def test_alias_none_from_a_held_proposal(tmp_path, cid):
    """D1-12.3: a held proposal adds no alias. Only the stored relations' own names are recorded."""
    steps, wanted = CASES[cid]
    first_held = next(i for i, w in enumerate(wanted) if w[0] == HELD)
    chat = run(tmp_path, steps[:first_held + 1])
    try:
        assert chat.out[first_held].verdict == UNCERTAIN
        assert chat.after[first_held]["aliases"] == chat.before[first_held]["aliases"]
    finally:
        chat.close()


# ------------------------------------------------------------------ relation keys: G11 and the speaker's identity
def test_relation_keys_not_the_name_tell_ben_s_sister_apart(tmp_path):
    """NP-1, G11: today's stored name "Ben's sister" (the words as said) equals the wanted display name, so the keys
    are what show it is Ben's relation."""
    chat = run(tmp_path, CASES["NP-1"][0])
    try:
        assert chat.out[0].verdict == ACCEPTED
        ent = chat.subject(chat.out[0])
        ben = chat.speaker_entity(B)
        assert ben is not None and ent.metadata.get("relation_of") == ben.entity_id and ent.metadata.get("relation") == "sister"
    finally:
        chat.close()


def test_relation_identified_speaker_who_speaks_later(tmp_path):
    """SP-1 (D1-12.4): Caroline speaks later in the same chat. Ben's "Caroline's sister" creates Caroline's entity and
    stores the sister as her relation; Caroline's own later "I live in Goa." files to that same Caroline entity."""
    steps = [st(B, "Caroline's sister moved to Pune.", "Caroline's sister", "Pune", "moved_to"), st(C, "I live in Goa.", "I", "Goa", "lives_in")]
    chat = run(tmp_path, steps)
    try:
        sister = chat.subject(chat.out[0])
        assert chat.out[0].verdict == ACCEPTED and sister.canonical_name == "Caroline's sister"
        assert chat.out[1].verdict == ACCEPTED
        assert sister.metadata.get("relation_of") == chat.subject(chat.out[1]).entity_id
    finally:
        chat.close()


def test_relation_entities_are_no_bare_name_match(tmp_path):
    """Section 3.1, step 2: a relation entity never takes part in the unscoped lookup. Ben's bare "Sara" after only
    Asha's sister Sara is held (step 4), never filed under Asha's sister and never as a new person."""
    chat = run(tmp_path, CASES["AL-2"][0])
    try:
        assert chat.out[1].verdict == UNCERTAIN
        assert len(chat.after[1]["entities"]) == len(chat.before[1]["entities"])
    finally:
        chat.close()


# ------------------------------------------------------------------ naming (D1-1, NM-1, NM-3)
def test_walk_reaches_only_asha_s_sister(tmp_path):
    """NM-1: ID-1's two sentences; the base 2 walk asked "Where does Asha's sister live?" reaches Pune, not Delhi."""
    chat = run(tmp_path, CASES["ID-1"][0])
    try:
        g = chat.layer.graph()
        got = [g.facts[f]["object"] for f in S.walk(g, "Where does Asha's sister live?", hubs=[A, B])]
        assert got == ["pune"]
    finally:
        chat.close()


def test_sentence_reads_back_as_spoken(tmp_path):
    """NM-3 (safeguard 1 of D1-1): the sentence reads back exactly as said, whatever the relation is named."""
    chat = run(tmp_path, [st(A, "My mom lives in Pune.", "my mom", "Pune", "lives_in")])
    try:
        assert chat.out[0].verdict == ACCEPTED
        assert chat.m.text_of([chat.sids[0]]).endswith("Asha: My mom lives in Pune.")
    finally:
        chat.close()


@pytest.mark.parametrize("cid", ["ID-1", "OP-6", "SV-3", "MN-6", "NP-2", "GR-1"])
def test_sentence_store_never_holds_a_display_name(tmp_path, cid):
    """PR-6: the sentence store holds only what was said: no row is added (so no display name is written there), and every
    sentence still holds its words as spoken ("my sister")."""
    steps = CASES[cid][0]
    chat = run(tmp_path, steps)
    try:
        assert chat.m.db.execute("SELECT COUNT(*) FROM sentences").fetchone()[0] == 2 + len(steps)
        for sid, s in zip(chat.sids, steps):
            assert chat.m.db.execute("SELECT speaker, text, date FROM sentences WHERE sid=?", (sid,)).fetchone() == (s[0], s[1], SAID)
    finally:
        chat.close()


# ------------------------------------------------------------------ preservation (PR-2 to PR-4): pass before and after
@pytest.mark.parametrize("cid", ids_of(CASES))
def test_preserved_sentences_every_case(tmp_path, cid):
    """PR-4 and G2: the number of sentences, and every sentence's speaker, text and date, are the same before and after
    every proposal of every case."""
    chat = run(tmp_path, CASES[cid][0])
    try:
        for b, a in zip(chat.before, chat.after): assert a["sentences"] == b["sentences"]
    finally:
        chat.close()


@pytest.mark.parametrize("cid", ["CT-8", "RQ-1"])
def test_preserved_refused_stores_nothing(tmp_path, cid):
    """PR-2: a refused proposal stores nothing and queues nothing; its sentence is unchanged."""
    chat = run(tmp_path, CASES[cid][0])
    try:
        out, b, a = chat.out[-1], chat.before[-1], chat.after[-1]
        assert out.verdict == REJECTED and out.fact_id is None and out.review_id is None
        assert a == b
    finally:
        chat.close()


@pytest.mark.parametrize("cid", ["CT-1", "CT-2", "ID-1", "GR-1", "SV-2", "MN-1", "NP-1", "CH-1"])
def test_preserved_evidence_points_at_its_sentence(tmp_path, cid):
    """PR-3: a stored fact's evidence is its own sentence, unchanged."""
    chat = run(tmp_path, CASES[cid][0])
    try:
        for out, sid in zip(chat.out, chat.sids):
            if out.verdict == ACCEPTED:
                assert str(sid) in [e.source_id for e in chat.kb.get(out.fact_id).evidence]
    finally:
        chat.close()


# ------------------------------------------------------------------ G4: two speakers never share a relation entity
@pytest.mark.parametrize("cid", ids_of(CASES))
def test_g4_no_relation_entity_is_shared_between_speakers(tmp_path, cid):
    """Over every case's store: each relation entity's name starts with its owner's name, and every fact under it rests on
    a sentence said by its owner or naming its owner ("Ben's mom", said by Asha). Passes vacuously while no relation
    entity exists."""
    chat = run(tmp_path, CASES[cid][0])
    try:
        for eid, name, meta in chat.m.db.execute("SELECT entity_id, canonical_name, metadata FROM entities"):
            owner_id = json.loads(meta).get("relation_of")
            if not owner_id: continue
            owner = chat.kb.entity(owner_id)
            assert owner is not None and name.startswith(owner.canonical_name + "'s ")
            for f in chat.kb.about_entity(eid, statuses=("active", "superseded")):
                for ev in f.evidence:
                    sp, text = chat.m.db.execute("SELECT speaker, text FROM sentences WHERE sid=?", (int(ev.source_id),)).fetchone()
                    assert sp.casefold() == owner.canonical_name.casefold() or (owner.canonical_name + "'s").casefold() in text.casefold()
    finally:
        chat.close()


# ------------------------------------------------------------------ G7: no store change
SCHEMA_SHA256 = "3b4fd85430bcf8f8016324edfedd5d2e890906933a7b7d32d6f467c623b6a326"   # measured at 25b6ffb, 18 November 2026


def schema_text(db):
    return "\n".join(r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"))


def test_g7_store_schema_is_unchanged(tmp_path):
    """G7: the schema text of a fresh store, compared exactly (by its SHA-256 at 25b6ffb), and the version still 4."""
    chat = run(tmp_path, [sis(A)])
    try:
        assert SCHEMA_VERSION == 4
        assert chat.m.db.execute("SELECT value FROM knowledge_meta WHERE key='schema_version'").fetchone()[0] == "4"
        assert hashlib.sha256(schema_text(chat.m.db).encode()).hexdigest() == SCHEMA_SHA256
    finally:
        chat.close()


# ------------------------------------------------------------------ recorded risks and the deferred gap: today's result, pinned
PINS = {
    # AN-1, AN-2 and AN-4 moved to ANIMALS below (Increment 5, K-3 and D-2): "my" + an animal is now the speaker's own.
    # JS-1 to JS-3 [RISK] TF-3, D1-9: no wanted result; today's is recorded and fails only if it changes without his word.
    "JS-1": ([st(A, "My husband and I moved to Pune.", "my husband and I", "Pune", "moved_to", "person")], [("e1", "my husband and I")]),
    "JS-2": ([st(A, "My husband and I moved to Pune.", "my husband", "Pune", "moved_to")], [("e1", None)]),
    "JS-3": ([st(A, "My classmates and I won the cup.", "my classmates and I", "the cup", "other", "person")], [("e1", "my classmates and I")]),
}


@pytest.mark.parametrize("cid", ids_of(PINS))
def test_pin_recorded_risk_is_as_today(tmp_path, cid):
    """JS-2 passes before and after the build. JS-1 and JS-3 now give subject_kind="person" (Increment 5, his (c), 22 November
    18:15 and 18:17), so they fail on the code before the build and are expected to pass after it. JS-2's subject is a plain
    one-person relation ("my husband"), so its name follows D1-1 and is not pinned; only that it is stored (tests-first report,
    point TF-4)."""
    steps, wanted = PINS[cid]
    chat = run(tmp_path, steps)
    try:
        labels = {}
        for out, (label, name) in zip(chat.out, wanted):
            assert out.verdict == ACCEPTED
            ent = chat.subject(out)
            assert labels.setdefault(label, ent.entity_id) == ent.entity_id
            if name is not None: assert ent.canonical_name == name and "relation_of" not in (ent.metadata or {})
    finally:
        chat.close()


# ------------------------------------------------------------------ Increment 5: the joint subjects with no kind (JS-1, JS-3, his (c))
JOINT_NO_KIND = {
    "JS-1": st(A, "My husband and I moved to Pune.", "my husband and I", "Pune", "moved_to"),
    "JS-3": st(A, "My classmates and I won the cup.", "my classmates and I", "the cup", "other"),
}


@pytest.mark.parametrize("cid", list(JOINT_NO_KIND))
def test_pin_a_joint_subject_with_no_kind_is_held(tmp_path, cid):
    """Increment 5, K-10: the same line with no subject_kind is held, and nothing is stored."""
    step = JOINT_NO_KIND[cid]
    chat = run(tmp_path, [step])
    try:
        out = chat.out[0]
        assert out.verdict == UNCERTAIN and f"the kind of '{step[2]}' is not known" in out.reasons
        assert chat.after[0]["entities"] == chat.before[0]["entities"] and chat.after[0]["facts"] == chat.before[0]["facts"]
    finally:
        chat.close()


# ------------------------------------------------------------------ Increment 5: AN-1, AN-2, AN-4 (K-3, D-2; Draft 5, section 10)
ANIMALS = {
    "AN-1": ([st(A, "My dog lives with my parents in Mysore.", "my dog", "Mysore", "lives_in")], [("e1", "Asha's dog", A, "animal")]),
    "AN-2": ([st(A, "My turtles love the sun.", "my turtles", "the sun", "likes")], [("e1", "Asha's turtles", A, "animal")]),
    # AN-4, TF-11, resolved by Increment 5: each speaker's "my dog" is their own.
    "AN-4": ([st(A, "My dog is called Max.", "my dog", "Max", "name"), st(B, "My dog is called Max.", "my dog", "Max", "name")],
             [("e1", "Asha's dog", A, "animal"), ("e2", "Ben's dog", B, "animal")]),
}


@pytest.mark.parametrize("cid", list(ANIMALS))
def test_an_my_animal_is_the_speakers_own(tmp_path, cid):
    steps, wanted = ANIMALS[cid]
    chat = run(tmp_path, steps)
    try:
        labels = {}
        for out, (label, name, owner, kind) in zip(chat.out, wanted):
            assert out.verdict == ACCEPTED
            ent = chat.subject(out)
            assert labels.setdefault(label, ent.entity_id) == ent.entity_id
            assert ent.canonical_name == name and ent.entity_type == kind
            assert ent.metadata["relation_of"] == chat.speaker_entity(owner).entity_id
        assert len(set(labels.values())) == len(labels)
    finally:
        chat.close()
