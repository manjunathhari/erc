"""The knowledge tables. Version 2 adds checks inside the database itself, so bad values are refused even by code that skips the checks in models.py,
and lets two entities share a name or an alias."""
SCHEMA_VERSION = 4
TABLES = ("entities", "entity_aliases", "knowledge_records", "record_evidence")

V1_SCHEMA = """
    CREATE TABLE IF NOT EXISTS knowledge_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS entities(entity_id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE, entity_type TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', schema_version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS entity_aliases(alias_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL, alias TEXT NOT NULL, normalized_alias TEXT NOT NULL UNIQUE, source_kind TEXT NOT NULL, source_id TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS knowledge_records(fact_id TEXT PRIMARY KEY, subject_id TEXT, predicate TEXT, object_type TEXT, object_value TEXT, object_entity_id TEXT, fact_type TEXT NOT NULL, status TEXT NOT NULL, validation_status TEXT NOT NULL, source_type TEXT NOT NULL, valid_from TEXT, valid_to TEXT, recorded_at TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', note TEXT NOT NULL DEFAULT '', schema_version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS record_evidence(evidence_id TEXT PRIMARY KEY, fact_id TEXT NOT NULL, source_kind TEXT NOT NULL, source_id TEXT NOT NULL, evidence_role TEXT NOT NULL, extraction_method TEXT, extraction_version TEXT, created_at TEXT NOT NULL, UNIQUE(fact_id, source_kind, source_id));
    CREATE TABLE IF NOT EXISTS review_queue(review_id TEXT PRIMARY KEY, candidate TEXT NOT NULL, reasons TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_sources(review_id TEXT NOT NULL, sid INTEGER NOT NULL, PRIMARY KEY(review_id, sid));
    CREATE INDEX IF NOT EXISTS review_sources_sid ON review_sources(sid);
    CREATE INDEX IF NOT EXISTS record_evidence_source ON record_evidence(source_kind, source_id);
    CREATE INDEX IF NOT EXISTS record_evidence_fact ON record_evidence(fact_id);
    CREATE INDEX IF NOT EXISTS knowledge_records_subject ON knowledge_records(subject_id);
    CREATE INDEX IF NOT EXISTS entity_aliases_source ON entity_aliases(source_kind, source_id);
"""

SCHEMA = """
    CREATE TABLE IF NOT EXISTS knowledge_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS entities(
        entity_id TEXT PRIMARY KEY,
        canonical_name TEXT NOT NULL CHECK(length(trim(canonical_name)) > 0),
        normalized_name TEXT NOT NULL CHECK(length(normalized_name) > 0),
        entity_type TEXT NOT NULL CHECK(length(trim(entity_type)) > 0),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata)),
        schema_version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS entity_aliases(
        alias_id TEXT PRIMARY KEY,
        entity_id TEXT NOT NULL REFERENCES entities(entity_id),
        alias TEXT NOT NULL CHECK(length(trim(alias)) > 0),
        normalized_alias TEXT NOT NULL CHECK(length(normalized_alias) > 0),
        source_kind TEXT NOT NULL CHECK(source_kind IN ('sentence', 'manual')),
        source_id TEXT,
        created_at TEXT NOT NULL,
        CHECK((source_kind = 'sentence' AND source_id IS NOT NULL) OR (source_kind = 'manual' AND source_id IS NULL)),
        UNIQUE(entity_id, normalized_alias));
    CREATE TABLE IF NOT EXISTS knowledge_records(
        fact_id TEXT PRIMARY KEY,
        subject_id TEXT REFERENCES entities(entity_id),
        predicate TEXT, object_type TEXT, object_value TEXT,
        object_entity_id TEXT REFERENCES entities(entity_id),
        fact_type TEXT NOT NULL CHECK(fact_type IN ('attribute', 'relationship', 'event', 'preference', 'plan', 'observation')),
        status TEXT NOT NULL CHECK(status IN ('active', 'superseded', 'disputed', 'retracted', 'needs_review', 'invalidated')),
        validation_status TEXT NOT NULL CHECK(validation_status IN ('pending', 'accepted', 'rejected')),
        source_type TEXT NOT NULL CHECK(source_type IN ('explicit', 'inferred')),
        valid_from TEXT, valid_to TEXT,
        recorded_at TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata)),
        note TEXT NOT NULL DEFAULT '',
        schema_version INTEGER NOT NULL,
        CHECK(status = 'invalidated' OR COALESCE((
            subject_id IS NOT NULL AND length(trim(predicate)) > 0
            AND object_type IN ('text', 'number', 'date', 'boolean', 'json', 'entity')
            AND ((object_type = 'entity' AND object_entity_id IS NOT NULL AND object_value IS NULL)
                 OR (object_type <> 'entity' AND object_entity_id IS NULL AND length(trim(object_value)) > 0))
            AND (object_type <> 'boolean' OR object_value IN ('true', 'false'))
            AND (object_type <> 'json' OR json_valid(object_value))), 0)),  -- COALESCE: in SQL an unknown (NULL) would otherwise pass a check
        CHECK(status <> 'invalidated' OR (subject_id IS NULL AND predicate IS NULL AND object_value IS NULL AND object_entity_id IS NULL)),
        CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from));
    CREATE TABLE IF NOT EXISTS record_evidence(
        evidence_id TEXT PRIMARY KEY,
        fact_id TEXT NOT NULL REFERENCES knowledge_records(fact_id),
        source_kind TEXT NOT NULL CHECK(source_kind = 'sentence'),
        source_id TEXT NOT NULL CHECK(length(source_id) > 0),
        evidence_role TEXT NOT NULL CHECK(evidence_role IN ('supports', 'contradicts', 'qualifies')),
        extraction_method TEXT, extraction_version TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(fact_id, source_kind, source_id));
    CREATE TABLE IF NOT EXISTS review_queue(review_id TEXT PRIMARY KEY, candidate TEXT NOT NULL, reasons TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_sources(review_id TEXT NOT NULL, sid INTEGER NOT NULL, PRIMARY KEY(review_id, sid));
    CREATE INDEX IF NOT EXISTS review_sources_sid ON review_sources(sid);
    CREATE TABLE IF NOT EXISTS state_reviews(
        review_id TEXT PRIMARY KEY,
        request_id TEXT NOT NULL UNIQUE,
        action TEXT NOT NULL CHECK(action IN ('approve_supersession', 'mark_disputed', 'reject', 'retain')),
        keep_fact_id TEXT NOT NULL REFERENCES knowledge_records(fact_id),
        other_fact_id TEXT NOT NULL REFERENCES knowledge_records(fact_id),
        reviewer TEXT NOT NULL CHECK(length(trim(reviewer)) > 0),
        reason TEXT NOT NULL CHECK(length(trim(reason)) > 0),
        valid_to TEXT,
        before_state TEXT NOT NULL CHECK(json_valid(before_state)),
        after_state TEXT NOT NULL CHECK(json_valid(after_state)),
        created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS state_reviews_keep ON state_reviews(keep_fact_id);
    CREATE INDEX IF NOT EXISTS state_reviews_other ON state_reviews(other_fact_id);
    CREATE TABLE IF NOT EXISTS record_relations(
        relation_id TEXT PRIMARY KEY,
        relation TEXT NOT NULL CHECK(relation IN ('supports', 'updates', 'extends', 'contradicts', 'derives', 'qualifies', 'mentions', 'relates_to')),
        from_kind TEXT NOT NULL CHECK(from_kind IN ('sentence', 'fact', 'entity')),
        from_id TEXT NOT NULL CHECK(length(from_id) > 0),
        to_kind TEXT NOT NULL CHECK(to_kind IN ('sentence', 'fact', 'entity')),
        to_id TEXT NOT NULL CHECK(length(to_id) > 0),
        basis_sentence TEXT CHECK(basis_sentence IS NULL OR length(basis_sentence) > 0),
        method TEXT NOT NULL CHECK(length(trim(method)) > 0),
        version TEXT,
        created_at TEXT NOT NULL,
        CHECK((from_kind = 'fact' AND to_kind = 'fact' AND relation <> 'mentions')
              OR (relation = 'mentions' AND from_kind = 'sentence' AND to_kind = 'entity')
              OR (relation = 'relates_to' AND from_kind = 'entity' AND to_kind = 'entity')),
        CHECK(NOT (from_kind = to_kind AND from_id = to_id)),
        CHECK(relation <> 'mentions' OR COALESCE(basis_sentence = from_id, 0)),  -- COALESCE: a missing basis must not pass as unknown
        CHECK(relation <> 'relates_to' OR basis_sentence IS NOT NULL));
    CREATE UNIQUE INDEX IF NOT EXISTS record_relations_same ON record_relations(relation, from_kind, from_id, to_kind, to_id, COALESCE(basis_sentence, ''), method);
    CREATE INDEX IF NOT EXISTS record_relations_from ON record_relations(from_kind, from_id);
    CREATE INDEX IF NOT EXISTS record_relations_to ON record_relations(to_kind, to_id);
    CREATE INDEX IF NOT EXISTS record_relations_basis ON record_relations(basis_sentence);
    CREATE TABLE IF NOT EXISTS vocabulary(
        domain TEXT NOT NULL CHECK(length(trim(domain)) > 0),
        word TEXT NOT NULL CHECK(length(trim(word)) > 0),
        fact_type TEXT NOT NULL CHECK(fact_type IN ('attribute', 'relationship', 'event', 'preference', 'plan', 'observation')),
        time_kind TEXT NOT NULL CHECK(time_kind IN ('state', 'event')),
        cardinality TEXT CHECK(cardinality IN ('single', 'many')),
        opens TEXT, closes TEXT,
        cue_words TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(cue_words)),
        outside_system TEXT, outside_code TEXT,
        source TEXT NOT NULL CHECK(length(trim(source)) > 0),
        source_version TEXT,
        vocabulary_version TEXT NOT NULL CHECK(length(trim(vocabulary_version)) > 0),
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'deprecated')),
        owner TEXT NOT NULL CHECK(length(trim(owner)) > 0),
        state_engine_approved INTEGER NOT NULL DEFAULT 0 CHECK(state_engine_approved IN (0, 1)),
        CHECK((outside_system IS NULL) = (outside_code IS NULL)),
        PRIMARY KEY(domain, word));
    CREATE INDEX IF NOT EXISTS vocabulary_word ON vocabulary(word);
    CREATE INDEX IF NOT EXISTS record_evidence_source ON record_evidence(source_kind, source_id);
    CREATE INDEX IF NOT EXISTS record_evidence_fact ON record_evidence(fact_id);
    CREATE INDEX IF NOT EXISTS knowledge_records_subject ON knowledge_records(subject_id);
    CREATE INDEX IF NOT EXISTS knowledge_records_object ON knowledge_records(object_entity_id);
    CREATE INDEX IF NOT EXISTS entity_aliases_source ON entity_aliases(source_kind, source_id);
    CREATE INDEX IF NOT EXISTS entity_aliases_name ON entity_aliases(normalized_alias);
    CREATE INDEX IF NOT EXISTS entities_name ON entities(normalized_name);
"""
