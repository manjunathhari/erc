import copy
import hashlib
import json
import sqlite3
import unittest

from engram_p7 import IntelligenceRestorer, RestorationError


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fixtures(installation_id="node-A", warnings=None):
    transfer = {
        "format": "engram-context-intelligence-transfer",
        "format_version": 1,
        "transfer_algorithm": "confidence_weighted_log_pool_v1",
        "source": {"p71_package_sha256": "a"*64, "p6_3_version": 3,
                   "p6_3_algorithm": "beta_shrinkage_v1", "p6_6_bundle_version": 4},
        "context_priors": [{
            "context_key": "ctx-A", "source_policy_version": 3,
            "source_algorithm": "beta_shrinkage_v1", "prior_multiplier": 1.04,
            "prior_strength": 2.5, "confidence": .72,
            "log_multiplier_dispersion": .04, "source_policy_count": 4,
            "effective_policy_count": 3.2, "support_status": "supported",
            "semantics": "context_prior_for_destination_local_learning",
        }],
        "model_configuration": {
            "p63": {"algorithm": "beta_shrinkage_v1",
                    "config": {"prior_alpha": 1, "prior_beta": 1, "min_evidence": 2,
                               "min_multiplier": .8, "max_multiplier": 1.2}},
            "p64": {"config": {"half_life_days": 90}, "status": "configuration_transferred"},
            "retrieval": {"config": {"mode": "shadow"},
                          "status": "configuration_transferred_not_applied"},
        },
        "destination_contract": {
            "source_memory_ids_required": False, "source_conversations_required": False,
            "source_experience_events_required": False,
            "source_per_memory_policies_are_executable": False,
            "context_prior_is_initialization_not_destination_fact": True,
            "destination_feedback_must_update_local_policy": True,
            "destination_knowledge_is_not_modified": True,
        },
        "privacy": {
            "conversation_content_included": False, "p61_experience_events_included": False,
            "p1_p5_knowledge_included": False, "source_memory_identifiers_included": False,
            "source_per_memory_policy_rows_included": False,
        },
    }
    td = {"transfer": transfer, "integrity": {
        "algorithm": "sha256", "transfer_sha256": hashlib.sha256(canon(transfer)).hexdigest()
    }}
    report = {
        "format": "engram-p7.3-validation-report", "format_version": 1,
        "destination_installation_id": installation_id,
        "status": "compatible_with_warnings" if warnings else "compatible",
        "checks": {"package_integrity": "passed"},
        "blockers": [], "warnings": warnings or [],
        "activation_authorized": False, "validation_only": True,
        "transfer_sha256": td["integrity"]["transfer_sha256"],
        "destination_profile": {
            "installation_id": installation_id,
            "supports_context_prior_consumption": True,
            "context_prior_api_version": 1,
        },
        "summary": {
            "compatible_for_restoration": True, "ready_for_activation": False,
        },
    }
    rd = {"report": report, "integrity": {
        "algorithm": "sha256", "report_sha256": hashlib.sha256(canon(report)).hexdigest()
    }}
    return td, rd


class TestP74(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.restorer = IntelligenceRestorer(self.db, "node-A")
        self.t1, self.r1 = fixtures()
        self.t2, self.r2 = fixtures()
        # Make second transfer distinct without changing semantics.
        self.t2["transfer"]["source"]["p71_package_sha256"] = "b"*64
        self.t2["integrity"]["transfer_sha256"] = hashlib.sha256(canon(self.t2["transfer"])).hexdigest()
        self.r2["report"]["transfer_sha256"] = self.t2["integrity"]["transfer_sha256"]
        self.r2["integrity"]["report_sha256"] = hashlib.sha256(canon(self.r2["report"])).hexdigest()

    def test_restore_stages_without_activation(self):
        result = self.restorer.restore(self.t1, self.r1, imported_by="test")
        self.assertEqual(result["status"], "staged")
        self.assertIsNone(self.restorer.active_model())

    def test_restore_idempotent(self):
        a = self.restorer.restore(self.t1, self.r1, imported_by="test")
        b = self.restorer.restore(self.t1, self.r1, imported_by="test")
        self.assertFalse(a["idempotent"])
        self.assertTrue(b["idempotent"])

    def test_warning_requires_acknowledgement(self):
        warning = {"code": "CONTEXT_KEY_SCHEME_UNVERIFIED", "message": "review"}
        t, r = fixtures(warnings=[warning])
        with self.assertRaisesRegex(RestorationError, "acknowledgement"):
            self.restorer.restore(t, r, imported_by="test")
        self.restorer.restore(t, r, imported_by="test", acknowledge_warnings=True)

    def test_warning_acknowledgement_required_again_at_activation(self):
        warning = {"code": "CONTEXT_KEY_SCHEME_UNVERIFIED", "message": "review"}
        t, r = fixtures(warnings=[warning])
        self.restorer.restore(t, r, imported_by="test", acknowledge_warnings=True)
        self.db.execute(
            "UPDATE p7_restored_models SET warnings_acknowledged=0 WHERE transfer_sha256=?",
            (t["integrity"]["transfer_sha256"],),
        )
        with self.assertRaisesRegex(RestorationError, "not acknowledged"):
            self.restorer.activate(
                t["integrity"]["transfer_sha256"], activated_by="admin",
                reason="activation after review", validation_report=r
            )

    def test_wrong_destination_rejected(self):
        t, r = fixtures(installation_id="node-B")
        with self.assertRaisesRegex(RestorationError, "different destination"):
            self.restorer.restore(t, r, imported_by="test")

    def test_report_must_match_exact_transfer(self):
        t, r = fixtures()
        t2, _ = fixtures()
        t2["transfer"]["source"]["p71_package_sha256"] = "c"*64
        t2["integrity"]["transfer_sha256"] = hashlib.sha256(canon(t2["transfer"])).hexdigest()
        with self.assertRaisesRegex(RestorationError, "exact P7.2"):
            self.restorer.restore(t2, r, imported_by="test")

    def test_tampered_validation_report_rejected(self):
        r = copy.deepcopy(self.r1)
        r["report"]["destination_installation_id"] = "tampered-node"
        with self.assertRaisesRegex(RestorationError, "checksum"):
            self.restorer.restore(self.t1, r, imported_by="test")

    def test_incompatible_report_rejected(self):
        r = copy.deepcopy(self.r1)
        r["report"]["status"] = "incompatible"
        r["report"]["blockers"] = [{"code": "x"}]
        r["integrity"]["report_sha256"] = hashlib.sha256(canon(r["report"])).hexdigest()
        with self.assertRaisesRegex(RestorationError, "incompatible"):
            self.restorer.restore(self.t1, r, imported_by="test")

    def test_activate_and_read_prior(self):
        self.restorer.restore(self.t1, self.r1, imported_by="test")
        result = self.restorer.activate(
            self.t1["integrity"]["transfer_sha256"],
            activated_by="admin", reason="validated model activation",
            validation_report=self.r1,
        )
        self.assertEqual(result["status"], "active")
        self.assertAlmostEqual(self.restorer.get_active_prior("ctx-A")["prior_multiplier"], 1.04)

    def test_activate_requires_restore(self):
        with self.assertRaisesRegex(RestorationError, "not been restored"):
            self.restorer.activate(
                self.t1["integrity"]["transfer_sha256"],
                activated_by="admin", reason="activate",
                validation_report=self.r1,
            )

    def test_second_activation_can_rollback(self):
        self.restorer.restore(self.t1, self.r1, imported_by="test")
        self.restorer.activate(self.t1["integrity"]["transfer_sha256"],
                               activated_by="admin", reason="first validated activation",
                               validation_report=self.r1)
        self.restorer.restore(self.t2, self.r2, imported_by="test")
        self.restorer.activate(self.t2["integrity"]["transfer_sha256"],
                               activated_by="admin", reason="second validated activation",
                               validation_report=self.r2)
        rolled = self.restorer.rollback(actor="admin", reason="new model failed smoke test")
        self.assertEqual(rolled["active_transfer_sha256"], self.t1["integrity"]["transfer_sha256"])

    def test_deactivate_keeps_archive(self):
        self.restorer.restore(self.t1, self.r1, imported_by="test")
        self.restorer.activate(self.t1["integrity"]["transfer_sha256"],
                               activated_by="admin", reason="validated activation",
                               validation_report=self.r1)
        result = self.restorer.deactivate(actor="admin", reason="maintenance")
        self.assertEqual(result["status"], "inactive")
        self.assertIsNone(self.restorer.active_model())
        count = self.db.execute("SELECT COUNT(*) FROM p7_restored_models").fetchone()[0]
        self.assertEqual(count, 1)

    def test_source_p1_p6_tables_are_not_created_or_mutated(self):
        self.restorer.restore(self.t1, self.r1, imported_by="test")
        names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("knowledge_records", names)
        self.assertNotIn("p6_scoring_policies", names)

    def test_staged_checksum_tampering_blocks_activation(self):
        self.restorer.restore(self.t1, self.r1, imported_by="test")
        digest = self.t1["integrity"]["transfer_sha256"]
        self.db.execute("UPDATE p7_restored_models SET transfer_json='{}' WHERE transfer_sha256=?", (digest,))
        with self.assertRaisesRegex(RestorationError, "integrity"):
            self.restorer.activate(digest, activated_by="admin", reason="activation attempt",
                                  validation_report=self.r1)

    def test_transaction_rolls_back_partial_restore(self):
        self.db.execute("""CREATE TRIGGER fail_prior_insert BEFORE INSERT ON p7_restored_context_priors
                           BEGIN SELECT RAISE(ABORT, 'fixture failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.restorer.restore(self.t1, self.r1, imported_by="test")
        count = self.db.execute("SELECT COUNT(*) FROM p7_restored_models").fetchone()[0]
        self.assertEqual(count, 0)

    def test_validation_report_not_activation_authority(self):
        self.restorer.restore(self.t1, self.r1, imported_by="test")
        # Activation requires a separate explicit call and actor/reason.
        self.assertIsNone(self.restorer.active_model())


if __name__ == "__main__":
    unittest.main()
