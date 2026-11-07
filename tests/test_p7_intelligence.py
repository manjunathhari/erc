import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from engram_p7 import IntelligenceExporter, IntelligenceExportError


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE p6_policy_versions(
      version INTEGER PRIMARY KEY, context_key TEXT, created_at TEXT,
      algorithm TEXT, config_json TEXT, source_max_event_id TEXT,
      policy_count INTEGER, note TEXT);
    CREATE TABLE p6_scoring_policies(
      policy_id TEXT PRIMARY KEY, version INTEGER, context_key TEXT, target_ref TEXT,
      positive_count INTEGER, negative_count INTEGER, posterior_mean REAL,
      confidence REAL, adjustment REAL, multiplier REAL, evidence_count INTEGER,
      source_event_count INTEGER, assessment TEXT, created_at TEXT,
      algorithm TEXT, config_json TEXT);
    CREATE TABLE p6_model_bundles(
      bundle_id TEXT PRIMARY KEY, bundle_version INTEGER UNIQUE, created_at TEXT,
      p63_policy_version INTEGER, p63_context_key TEXT, p63_algorithm TEXT,
      p63_config_json TEXT, p64_config_json TEXT, retrieval_config_json TEXT,
      bundle_sha256 TEXT, note TEXT);
    CREATE TABLE p6_model_bundle_active(
      singleton INTEGER PRIMARY KEY, bundle_id TEXT, activated_at TEXT,
      activated_by TEXT, reason TEXT);
    CREATE TABLE p6_experience_events(event_id TEXT, original_text TEXT);
    CREATE TABLE knowledge_records(id TEXT, original_text TEXT);
    """)
    return db


def seed(db):
    cfg = {"prior_alpha": 1.0, "prior_beta": 1.0, "min_evidence": 2}
    cfgj = json.dumps(cfg, sort_keys=True)
    for version, values in [
        (1, [("id-A", .9, "positive_adaptation"), ("id-B", 1.1, "positive_adaptation")]),
        (2, [("id-C", 1.05, "positive_adaptation"), ("id-D", .95, "neutral")]),
    ]:
        db.execute("INSERT INTO p6_policy_versions VALUES(?,?,?,?,?,?,?,?)",
                   (version, "ctx-hash", f"2026-01-0{version}T00:00:00Z",
                    "beta_shrinkage_v1", cfgj, f"event-{version}", len(values), "fixture"))
        for i, (ref, mult, assessment) in enumerate(values):
            db.execute("""INSERT INTO p6_scoring_policies VALUES(
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f"policy-{version}-{i}", version, "ctx-hash", ref, 3, 1, .7,
                 .5, mult-1, mult, 4, 4, assessment,
                 f"2026-01-0{version}T00:00:00Z", "beta_shrinkage_v1", cfgj))
    bundle = {
        "format_version": 1, "bundle_id": "bundle-2", "bundle_version": 1,
        "created_at": "2026-01-02T00:00:00Z", "p63_policy_version": 2,
        "p63_context_key": "ctx-hash", "p63_algorithm": "beta_shrinkage_v1",
        "p63_config": cfg, "p64_config": {"half_life_days": 90, "trend_window_days": 30},
        "retrieval_config": {"mode": "shadow"}, "note": "fixture",
    }
    from engram_p7.intelligence import IntelligenceExporter
    digest = IntelligenceExporter._sha256(bundle)
    db.execute("""INSERT INTO p6_model_bundles VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        ("bundle-2", 1, bundle["created_at"], 2, "ctx-hash", "beta_shrinkage_v1",
         json.dumps(cfg, sort_keys=True), json.dumps(bundle["p64_config"], sort_keys=True),
         json.dumps(bundle["retrieval_config"], sort_keys=True), digest, "fixture"))
    db.execute("INSERT INTO p6_model_bundle_active VALUES(1,'bundle-2','2026-01-02T01:00:00Z','tester','approved')")
    db.execute("INSERT INTO p6_experience_events VALUES('e1','PRIVATE CONVERSATION MUST NOT EXPORT')")
    db.execute("INSERT INTO knowledge_records VALUES('k1','PRIVATE FACT MUST NOT EXPORT')")
    db.commit()


class TestP71(unittest.TestCase):
    def setUp(self):
        self.db = make_db()
        seed(self.db)
        self.exporter = IntelligenceExporter(self.db)

    def test_extract_active_bundle(self):
        doc = self.exporter.extract()
        self.assertTrue(self.exporter.verify_package(doc))
        self.assertEqual(doc["package"]["intelligence"]["p63"]["selected_version"], 2)

    def test_policy_history_and_context_profile(self):
        p63 = self.exporter.extract()["package"]["intelligence"]["p63"]
        self.assertEqual([v["version"] for v in p63["version_history"]], [1, 2])
        self.assertEqual(p63["portable_context_profile"]["source_policy_count"], 2)
        self.assertEqual(p63["portable_context_profile"]["interpretation"],
                         "portable_context_seed_not_executable_policy")

    def test_no_target_refs_or_conversation_content(self):
        raw = json.dumps(self.exporter.extract())
        self.assertNotIn("id-A", raw)
        self.assertNotIn("PRIVATE CONVERSATION", raw)
        self.assertNotIn("PRIVATE FACT", raw)
        self.assertNotIn('"target_ref":', raw)
        self.assertNotIn('"policy_id":', raw)
        self.assertNotIn('"source_max_event_id":', raw)

    def test_policy_rows_are_explicitly_source_scoped(self):
        records = self.exporter.extract()["package"]["intelligence"]["p63"]["source_scoped_policy_archive"]
        self.assertTrue(all(r["scope"] == "source_installation_only" for r in records))
        self.assertTrue(all("target_ref" not in r for r in records))
        self.assertTrue(all("policy_id" not in r for r in records))

    def test_checksum_tampering_rejected(self):
        doc = self.exporter.extract()
        doc["package"]["intelligence"]["p64"]["config"]["half_life_days"] = 7
        with self.assertRaisesRegex(IntelligenceExportError, "checksum"):
            self.exporter.verify_package(doc)

    def test_p66_checksum_checked(self):
        self.db.execute("UPDATE p6_model_bundles SET note='tampered'")
        self.db.commit()
        with self.assertRaisesRegex(IntelligenceExportError, "P6.6 bundle checksum"):
            self.exporter.extract()

    def test_policy_manifest_count_checked(self):
        self.db.execute("DELETE FROM p6_scoring_policies WHERE version=2")
        self.db.commit()
        with self.assertRaisesRegex(IntelligenceExportError, "count"):
            self.exporter.extract()

    def test_missing_active_bundle_is_explicit(self):
        self.db.execute("DELETE FROM p6_model_bundle_active")
        self.db.commit()
        with self.assertRaisesRegex(IntelligenceExportError, "no active"):
            self.exporter.extract()

    def test_source_database_not_mutated(self):
        before = self.db.total_changes
        self.exporter.extract()
        self.assertEqual(self.db.total_changes, before)

    def test_write_json(self):
        doc = self.exporter.extract()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "intelligence.json"
            self.exporter.write_json(doc, str(path))
            self.assertTrue(self.exporter.verify_package(json.loads(path.read_text())))


if __name__ == "__main__":
    unittest.main()
