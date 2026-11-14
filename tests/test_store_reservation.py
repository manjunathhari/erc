"""Step 3, the store reservation (contract v1 sections 1.5, 1.6 and 6.1; Amendment 4, 4A2): one migration step, version 3 to 4,
adding two empty tables. Nothing writes to them. Rows are put in here by plain SQL only, to test what the tables themselves refuse."""
import hashlib
import json
import os
import re
import sqlite3

import pytest

import engram_chat as E
import engram_knowledge.schema as S
from conftest import ROOT, fill, load
from engram_knowledge.migrations import STEPS, migrate
from engram_knowledge.normalizer import PREDICATE_CUES, PREDICATE_TYPES
from engram_knowledge.transition import CLOSES, MULTI, OPENS, SINGLE
from engram_records import Entity, EntityAlias, FactEvidence, FactWithEvidence, KnowledgeBase, KnowledgeFact, RecordError

DATA = load("basic_conversation.json")
NEW = ("record_relations", "vocabulary")
STORE = ("knowledge_meta", "entities", "entity_aliases", "knowledge_records", "record_evidence", "review_queue", "review_sources", "state_reviews")
# The store's own tables and indexes exactly as version 3 defines them at 39e9308 (29 objects): SHA-256 of their sqlite_master rows.
V3_DEFINITIONS = "a4227e55adfb3b54361d2473ec8c70016a8b9ddc180f1a4765dd7f77d6b5b8cf"
STAMP = "2026-11-14T00:00:00+00:00"


# ---------- helpers ----------
def objects(db, tables=None):
    rows = db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
    return sorted((r for r in rows if tables is None or r[2] in tables), key=lambda r: (r[0], r[1]))


def rows_of(db, table):
    keys = [c[1] for c in sorted(db.execute(f"PRAGMA table_info({table})").fetchall(), key=lambda c: c[5]) if c[5]]
    return db.execute(f"SELECT * FROM {table} ORDER BY {', '.join(keys) if keys else 'rowid'}").fetchall()


def snapshot(db):
    """Every definition and every row of every table, the layer-1 tables included (R4)."""
    return dict(objects=objects(db), rows={r[1]: rows_of(db, r[1]) for r in objects(db) if r[0] == "table"})


def version_three(path, extra=()):
    """A database as 39e9308 leaves it: version 3, with sentences, entities, an alias, facts, evidence, a waiting review and a decision."""
    m = E.ChatMemory(path)
    ids = fill(m, DATA)
    kb = KnowledgeBase(m.db)
    asha = kb.add_entity(Entity.create("Asha", "person"))
    made = []
    for value, sids in (("beagle", [ids["B1:1"], ids["B3:1"]]), ("terrier", [ids["B2:1"]])):
        f = KnowledgeFact.create(subject_id=asha.entity_id, predicate="owns", object_type="text", fact_type="relationship", source_type="explicit", object_value=value)
        made.append(kb.add(FactWithEvidence(f, tuple(FactEvidence.create(f.fact_id, s) for s in sids))).fact.fact_id)
    kb.add_alias(EntityAlias.create(asha.entity_id, "Ash", "sentence", source_id=ids["B1:1"]))
    kb.add_review("{}", ["x"], [ids["B2:2"]])
    m.db.execute("INSERT INTO state_reviews VALUES('rev_1', 'req_1', 'retain', ?, ?, 'Manj', 'both hold', NULL, '{}', '{}', ?)", (made[0], made[1], STAMP))
    m.db.commit(); m.close()
    raw = sqlite3.connect(path)
    for t in NEW: raw.execute(f"DROP TABLE IF EXISTS {t}")
    raw.execute("UPDATE knowledge_meta SET value='3' WHERE key='schema_version'")
    for t in ("entities", "knowledge_records"): raw.execute(f"UPDATE {t} SET schema_version=3")
    for statement in extra: raw.execute(statement)
    raw.commit()
    before = snapshot(raw)
    raw.close()
    return ids, made, before


def fresh(path):
    m = E.ChatMemory(path)
    return m, KnowledgeBase(m.db)


def relation(db, name, from_kind, from_id, to_kind, to_id, basis=None, method="rule:test", rid=None):
    rid = rid or "rel_" + hashlib.sha256(repr((name, from_kind, from_id, to_kind, to_id, basis, method)).encode()).hexdigest()[:12]
    db.execute("INSERT INTO record_relations(relation_id, relation, from_kind, from_id, to_kind, to_id, basis_sentence, method, version, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (rid, name, from_kind, from_id, to_kind, to_id, basis, method, "1", STAMP))


def refused(db, action):
    with pytest.raises(sqlite3.IntegrityError): action()  # the refused statement alone is undone; rows put in before it stay


def valid(name, from_kind, to_kind):
    """A row for this combination that breaks no other rule: different ends, and a basis sentence where one is required."""
    a, b = ("7" if from_kind == "sentence" else from_kind + "_a"), ("8" if to_kind == "sentence" else to_kind + "_b")
    return (name, from_kind, a, to_kind, b, a if name == "mentions" or from_kind == "sentence" else "7")


EIGHT = ("supports", "updates", "extends", "contradicts", "derives", "qualifies", "mentions", "relates_to")
KINDS = ("sentence", "fact", "entity")
PERMITTED = {(r, "fact", "fact") for r in EIGHT if r != "mentions"} | {("mentions", "sentence", "entity"), ("relates_to", "entity", "entity")}
WORD = dict(domain="general", word="works_at", fact_type="relationship", time_kind="state", cardinality="single", opens="works_at", closes=None, cue_words='["work", "job"]',
            outside_system=None, outside_code=None, source="hand-written", source_version=None, vocabulary_version="1", status="active", owner="Engram track", state_engine_approved=0)


def word(db, **change):
    row = WORD | change
    db.execute(f"INSERT INTO vocabulary({', '.join(row)}) VALUES({', '.join('?' * len(row))})", list(row.values()))


# ---------- 6.1: the migration, version 3 to 4 (A10, R4) ----------
def test_the_version_is_four_and_the_only_new_step_is_three_to_four():
    assert S.SCHEMA_VERSION == 4 and sorted(STEPS) == [1, 2, 3]


def test_the_test_database_really_is_version_three(path):
    """Guards the tests below, and the rule that no existing definition is altered: the store's objects match 39e9308 exactly."""
    ids, made, before = version_three(path)
    store = [o for o in before["objects"] if o[2] in STORE]
    assert len(store) == 29 and hashlib.sha256(json.dumps(store, ensure_ascii=False).encode()).hexdigest() == V3_DEFINITIONS
    assert not [o for o in before["objects"] if o[2] in NEW]


def test_a_version_three_database_gains_the_two_empty_tables_and_nothing_else_changes(path):
    ids, made, before = version_three(path)
    m = E.ChatMemory(path)
    kb = KnowledgeBase(m.db)
    after = snapshot(m.db)
    new = [o for o in after["objects"] if o not in before["objects"]]
    assert {o[1] for o in new if o[0] == "table"} == set(NEW) and {o[2] for o in new} == set(NEW)  # only the two tables and their indexes
    assert [o for o in after["objects"] if o not in new] == before["objects"]  # every earlier definition, text compared exactly
    changed = {t for t in before["rows"] if after["rows"][t] != before["rows"][t]}
    assert changed == {"knowledge_meta"} and before["rows"]["knowledge_meta"] == [("schema_version", "3")] and after["rows"]["knowledge_meta"] == [("schema_version", "4")]
    assert after["rows"]["record_relations"] == [] and after["rows"]["vocabulary"] == []
    assert kb.integrity_check() == [] and [s.text for s in kb.trace(made[0])][0].startswith("I adopted a beagle")
    m.close()


def test_the_step_is_reported_once_and_a_second_opening_does_nothing(path):
    version_three(path)
    raw = sqlite3.connect(path)
    assert KnowledgeBase(raw).migrated == ["3 to 4"]
    first = snapshot(raw)
    raw.close()
    for _ in range(2):
        m = E.ChatMemory(path)
        assert KnowledgeBase(m.db).migrated == [] and snapshot(m.db) == first
        m.close()


def test_a_fresh_database_is_made_at_version_four_with_the_same_definitions_as_a_migrated_one(tmp_path):
    version_three(str(tmp_path / "old.db"))
    old, new = E.ChatMemory(str(tmp_path / "old.db")), E.ChatMemory(str(tmp_path / "new.db"))
    for db in (old.db, new.db): KnowledgeBase(db)
    assert new.db.execute("SELECT value FROM knowledge_meta").fetchall() == [("4",)]
    assert objects(new.db, STORE + NEW) == objects(old.db, STORE + NEW)
    assert rows_of(new.db, "record_relations") == [] and rows_of(new.db, "vocabulary") == []
    assert hashlib.sha256(json.dumps(objects(new.db, STORE), ensure_ascii=False).encode()).hexdigest() == V3_DEFINITIONS
    old.close(); new.close()


@pytest.mark.parametrize("extra,why", [
    ("CREATE TABLE record_relations(x TEXT)", "breaks a rule"),  # something else already holds the name: it is never taken over
    ("CREATE TABLE vocabulary(x TEXT)", "breaks a rule"),
    ("INSERT INTO record_evidence VALUES('ev_lost', 'fact_missing', 'sentence', '1', 'supports', NULL, NULL, 'x')", "links"),
])
def test_a_step_that_cannot_finish_changes_nothing_and_says_why(path, extra, why):
    ids, made, before = version_three(path, extra=("PRAGMA foreign_keys=OFF", extra))
    with pytest.raises(RecordError, match=why) as e: E.ChatMemory(path)
    assert "Nothing was changed" in str(e.value)
    raw = sqlite3.connect(path)
    assert snapshot(raw) == before and raw.execute("SELECT value FROM knowledge_meta").fetchall() == [("3",)]
    raw.close()


def test_a_database_newer_than_the_code_is_refused_unchanged(path):
    m, kb = fresh(path)
    m.db.execute("UPDATE knowledge_meta SET value='5'"); m.db.commit()
    before = snapshot(m.db)
    m.close()
    with pytest.raises(RecordError, match="newer than this code"): E.ChatMemory(path)
    raw = sqlite3.connect(path)
    assert snapshot(raw) == before
    with pytest.raises(RecordError, match="Nothing was changed"): migrate(raw, "5")
    assert migrate(raw, "4") == []  # forward only: there is no step back
    raw.close()


# ---------- nothing writes to either table ----------
def test_using_the_store_leaves_both_tables_empty(path):
    import engram_structure as B2
    m = E.ChatMemory(path)
    m.open_chat("3 March 2023")
    layer = B2.StructureLayer(m.db)
    for text, obj, w in (("I work at Manipal.", "Manipal", "works_at"), ("I have 3 bikes.", "3 bikes", "number"), ("I left Manipal in March 2024.", "Manipal", "left_job")):
        layer.file(m.add("User", text, date="3 March 2023"), "I", obj, word=w)
    first = m.db.execute("SELECT min(sid) FROM sentences").fetchone()[0]
    m.forget_sentence(first)
    assert m.db.execute("SELECT count(*) FROM knowledge_records").fetchone()[0] >= 2
    assert rows_of(m.db, "record_relations") == [] and rows_of(m.db, "vocabulary") == []
    assert len(PREDICATE_TYPES) == 31  # the words stay in code
    m.close()


def test_no_code_reads_or_writes_either_table():
    found = []
    for folder, _, names in os.walk(ROOT):
        if any(part in folder for part in (os.sep + "tests", os.sep + ".git", os.sep + "locomo", "__pycache__")): continue
        for name in names:
            if name.endswith(".py") and name != "check_base2_breakage.py":
                text = open(os.path.join(folder, name), encoding="utf-8", errors="replace").read()
                if re.search(r"\b(INTO|FROM|UPDATE|JOIN)\s+(record_relations|vocabulary)\b", text, re.I): found.append(name)
    assert found == []


def test_an_export_still_carries_the_four_tables_only(tmp_path):
    from engram_knowledge.serialization import export_knowledge
    m, kb = fresh(str(tmp_path / "m.db"))
    export_knowledge(kb, tmp_path / "k.json")
    payload = json.loads((tmp_path / "k.json").read_text())
    assert sorted(payload["data"]) == ["entities", "entity_aliases", "knowledge_records", "record_evidence", "sentences"] and payload["schema_version"] == 4
    m.close()


def test_p1_an_export_made_at_version_three_is_refused_and_nothing_is_imported(tmp_path):
    """S3-3: the exact version check stays. Recorded as outstanding portability issue P-1."""
    from engram_knowledge.serialization import export_knowledge, import_knowledge
    ids, made, before = version_three(str(tmp_path / "m.db"))
    m = E.ChatMemory(str(tmp_path / "m.db"))
    kb = KnowledgeBase(m.db)
    export_knowledge(kb, tmp_path / "k.json")
    payload = json.loads((tmp_path / "k.json").read_text())
    payload["schema_version"] = 3  # what version-3 code wrote; the data and its checksum are the same
    (tmp_path / "old.json").write_text(json.dumps(payload))
    rows = snapshot(m.db)
    with pytest.raises(RecordError, match="this code reads format 1, version 4"): import_knowledge(kb, tmp_path / "old.json")
    assert snapshot(m.db) == rows
    m.close()


# ---------- 1.5: the relationships table ----------
def test_the_relationships_table_has_the_contracts_columns(path):
    m, kb = fresh(path)
    assert [c[1] for c in m.db.execute("PRAGMA table_info(record_relations)")] == ["relation_id", "relation", "from_kind", "from_id", "to_kind", "to_id", "basis_sentence", "method", "version", "created_at"]
    m.close()


@pytest.mark.parametrize("name,from_kind,to_kind", [(r, f, t) for r in EIGHT for f in KINDS for t in KINDS])
def test_3r1_the_table_admits_exactly_the_nine_permitted_combinations(path, name, from_kind, to_kind):
    m, kb = fresh(path)
    put = lambda: relation(m.db, *valid(name, from_kind, to_kind))
    if (name, from_kind, to_kind) in PERMITTED:
        put()
        assert m.db.execute("SELECT count(*) FROM record_relations").fetchone()[0] == 1
    else:
        refused(m.db, put)
    m.close()


def test_3r1_there_are_nine_permitted_combinations_and_eight_names(path):
    m, kb = fresh(path)
    assert len(PERMITTED) == 9 and {p[0] for p in PERMITTED} == set(EIGHT)
    refused(m.db, lambda: relation(m.db, "causes", "fact", "fact_a", "fact", "fact_b"))  # a ninth name
    refused(m.db, lambda: relation(m.db, "SUPPORTS", "fact", "fact_a", "fact", "fact_b"))  # the names are stored one way only
    m.close()


@pytest.mark.parametrize("name", ["supports", "contradicts", "qualifies"])
def test_c12_a_sentence_to_fact_link_never_enters_the_new_table(path, name):
    m, kb = fresh(path)
    refused(m.db, lambda: relation(m.db, name, "sentence", "7", "fact", "fact_b", basis="7"))
    m.close()


@pytest.mark.parametrize("name,kind", [(r, "fact") for r in EIGHT if r != "mentions"] + [("relates_to", "entity")])
def test_3r1_a_link_from_a_thing_to_itself_is_refused(path, name, kind):
    m, kb = fresh(path)
    refused(m.db, lambda: relation(m.db, name, kind, "same", kind, "same", basis="7"))
    m.close()


def test_3r2_the_same_link_cannot_be_stored_twice_and_a_missing_basis_counts_as_a_value(path):
    m, kb = fresh(path)
    relation(m.db, "updates", "fact", "fact_a", "fact", "fact_b", basis="7", rid="rel_1")
    refused(m.db, lambda: relation(m.db, "updates", "fact", "fact_a", "fact", "fact_b", basis="7", rid="rel_2"))
    relation(m.db, "updates", "fact", "fact_c", "fact", "fact_d", rid="rel_3")  # made by a rule, no basis sentence
    refused(m.db, lambda: relation(m.db, "updates", "fact", "fact_c", "fact", "fact_d", rid="rel_4"))
    refused(m.db, lambda: relation(m.db, "extends", "fact", "fact_x", "fact", "fact_y", rid="rel_1"))  # one id, one row
    assert m.db.execute("SELECT count(*) FROM record_relations").fetchone()[0] == 2
    m.close()


def test_3r2_a_second_sentence_another_method_or_the_other_direction_is_another_row(path):
    m, kb = fresh(path)
    relation(m.db, "updates", "fact", "fact_a", "fact", "fact_b", basis="7")
    relation(m.db, "updates", "fact", "fact_a", "fact", "fact_b", basis="9")  # a second sentence states the same link
    relation(m.db, "updates", "fact", "fact_a", "fact", "fact_b", basis="7", method="review:manj")
    relation(m.db, "contradicts", "fact", "fact_b", "fact", "fact_a", basis="7")
    assert m.db.execute("SELECT count(*) FROM record_relations").fetchone()[0] == 4
    m.close()


@pytest.mark.parametrize("change", [dict(method=""), dict(method="  "), dict(method=None), dict(from_id=""), dict(to_id=""), dict(basis=""), dict(from_kind="chat"), dict(to_kind="chat")])
def test_a5_a_relationship_must_say_what_made_it_and_name_its_ends(path, change):
    m, kb = fresh(path)
    row = dict(name="updates", from_kind="fact", from_id="fact_a", to_kind="fact", to_id="fact_b", basis="7", method="rule:test") | change
    refused(m.db, lambda: relation(m.db, **row))
    m.close()


def test_a5_mentions_rests_on_its_own_sentence_and_relates_to_on_a_stated_sentence(path):
    """S3-4 (Amendment 5, 5A1): both rules are in the table's own definition."""
    m, kb = fresh(path)
    refused(m.db, lambda: relation(m.db, "mentions", "sentence", "7", "entity", "ent_a"))  # no basis
    refused(m.db, lambda: relation(m.db, "mentions", "sentence", "7", "entity", "ent_a", basis="9"))  # another sentence
    for kind in ("fact", "entity"):
        refused(m.db, lambda: relation(m.db, "relates_to", kind, "x_a", kind, "x_b", method="model:similarity"))  # R2: never without a stated sentence
    relation(m.db, "mentions", "sentence", "7", "entity", "ent_a", basis="7")
    relation(m.db, "relates_to", "entity", "ent_a", "entity", "ent_b", basis="7")
    m.close()


# ---------- 1.6: the vocabulary table ----------
def test_the_vocabulary_table_has_the_contracts_columns(path):
    m, kb = fresh(path)
    assert sorted(c[1] for c in m.db.execute("PRAGMA table_info(vocabulary)")) == sorted(WORD)
    m.close()


def test_a_word_is_accepted_and_starts_active_and_not_approved_for_the_state_engine(path):
    m, kb = fresh(path)
    m.db.execute("INSERT INTO vocabulary(domain, word, fact_type, time_kind, source, vocabulary_version, owner) VALUES('general', 'attended', 'event', 'event', 'hand-written', '1', 'Engram track')")
    assert m.db.execute("SELECT status, state_engine_approved, cue_words, cardinality, opens, closes, outside_system, outside_code FROM vocabulary").fetchall() == [("active", 0, "[]", None, None, None, None, None)]
    m.close()


@pytest.mark.parametrize("change", [
    dict(fact_type="measurement"), dict(fact_type=None), dict(time_kind="point"), dict(time_kind=None), dict(cardinality="one"), dict(status="retired"), dict(status=None),
    dict(state_engine_approved=2), dict(state_engine_approved="yes"), dict(state_engine_approved=None), dict(word=" "), dict(word=None), dict(domain=""), dict(domain=None),
    dict(source=" "), dict(source=None), dict(owner=""), dict(owner=None), dict(vocabulary_version=""), dict(vocabulary_version=None), dict(cue_words="work job"), dict(cue_words=None),
    dict(outside_system="wikidata"), dict(outside_code="P108")])
def test_3r3_the_table_refuses_a_bad_word_even_without_the_code(path, change):
    m, kb = fresh(path)
    refused(m.db, lambda: word(m.db, **change))
    m.close()


def test_a_word_is_stored_once_in_a_domain_and_may_appear_in_another(path):
    """S3-5: the key is domain and word together."""
    m, kb = fresh(path)
    word(m.db)
    refused(m.db, lambda: word(m.db, cue_words="[]"))
    word(m.db, domain="surgical", outside_system="snomed", outside_code="12345", status="deprecated", state_engine_approved=1)
    assert m.db.execute("SELECT count(*) FROM vocabulary").fetchone()[0] == 2
    m.close()


def test_a7_every_one_of_the_31_words_in_code_fits_the_table_as_it_stands(path):
    """The later load (A7) needs no second store change. S3-6 (5A2): 19 words are in neither the single nor the many list, so
    cardinality may be empty. The rows are written to a scratch database only and rolled back."""
    m, kb = fresh(path)
    for w, kind in PREDICATE_TYPES.items():
        word(m.db, word=w, fact_type=kind, time_kind="event" if kind == "event" else "state", cardinality="single" if w in SINGLE else "many" if w in MULTI else None,
             opens=OPENS.get(w), closes=CLOSES.get(w), cue_words=json.dumps(PREDICATE_CUES.get(w, "").split()))
    assert m.db.execute("SELECT count(*), count(cardinality), count(opens), count(closes) FROM vocabulary").fetchall() == [(31, 12, 19, 7)]
    m.db.rollback()
    assert rows_of(m.db, "vocabulary") == []
    m.close()
