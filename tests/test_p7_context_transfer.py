import copy
import hashlib
import json
import unittest

from engram_p7 import ContextPolicyTransfer, ContextTransferError


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def p71_fixture():
    cfg = {
        "prior_alpha": 1.0, "prior_beta": 1.0, "min_evidence": 2,
        "min_multiplier": 0.8, "max_multiplier": 1.2,
    }
    policies = [
        {"version": 3, "context_key": "ctx-A", "positive_count": 5,
         "negative_count": 1, "posterior_mean": .75, "confidence": .8,
         "adjustment": .08, "multiplier": 1.08, "evidence_count": 9,
         "assessment": "positive_adaptation", "algorithm": "beta_shrinkage_v1",
         "config": cfg, "scope": "source_installation_only"},
        {"version": 3, "context_key": "ctx-A", "positive_count": 3,
         "negative_count": 2, "posterior_mean": .6, "confidence": .6,
         "adjustment": -.04, "multiplier": .96, "evidence_count": 4,
         "assessment": "neutral", "algorithm": "beta_shrinkage_v1",
         "config": cfg, "scope": "source_installation_only"},
        # Older version must not be double-counted in the selected prior.
        {"version": 2, "context_key": "ctx-A", "positive_count": 8,
         "negative_count": 0, "posterior_mean": .9, "confidence": .9,
         "adjustment": .15, "multiplier": 1.15, "evidence_count": 16,
         "assessment": "positive_adaptation", "algorithm": "beta_shrinkage_v1",
         "config": cfg, "scope": "source_installation_only"},
    ]
    package = {
        "format": "engram-intelligence-package", "format_version": 1,
        "exporter_version": "p7.1.0",
        "intelligence": {
            "selected_bundle": {"bundle_version": 4},
            "p63": {"selected_version": 3, "context_key": "ctx-A",
                    "algorithm": "beta_shrinkage_v1", "config": cfg,
                    "source_scoped_policy_archive": policies},
            "p64": {"config": {"half_life_days": 90}},
            "retrieval": {"config": {"mode": "shadow"}},
        },
        "privacy": {
            "conversation_content_included": False,
            "p61_experience_events_included": False,
            "p1_p5_knowledge_included": False,
        },
    }
    return {"package": package, "integrity": {
        "algorithm": "sha256", "package_sha256": hashlib.sha256(canonical(package)).hexdigest()
    }}


class TestP72(unittest.TestCase):
    def setUp(self):
        self.builder = ContextPolicyTransfer()
        self.source = p71_fixture()

    def test_build_portable_context_prior(self):
        result = self.builder.build(self.source)
        self.assertTrue(self.builder.verify_transfer(result))
        prior = result["transfer"]["context_priors"][0]
        self.assertEqual(prior["context_key"], "ctx-A")
        self.assertEqual(prior["source_policy_count"], 2)
        self.assertEqual(prior["support_status"], "supported")
        self.assertGreater(prior["prior_strength"], 0)

    def test_older_versions_not_double_counted(self):
        prior = self.builder.build(self.source)["transfer"]["context_priors"][0]
        self.assertEqual(prior["source_policy_count"], 2)
        self.assertEqual(prior["source_policy_version"], 3)

    def test_neutral_when_support_is_insufficient(self):
        doc = copy.deepcopy(self.source)
        archive = doc["package"]["intelligence"]["p63"]["source_scoped_policy_archive"]
        archive[:] = [p for p in archive if p["version"] == 3][:1]
        doc["integrity"]["package_sha256"] = hashlib.sha256(canonical(doc["package"])).hexdigest()
        result = self.builder.build(doc)
        prior = result["transfer"]["context_priors"][0]
        self.assertEqual(prior["prior_multiplier"], 1.0)
        self.assertEqual(prior["prior_strength"], 0.0)
        self.assertEqual(prior["support_status"], "insufficient_support")

    def test_source_ids_and_rows_not_transferred(self):
        result = self.builder.build(self.source)
        raw = json.dumps(result)
        self.assertNotIn("target_ref", raw)
        self.assertNotIn("policy_id", raw)
        self.assertNotIn("source_scoped_policy_archive", raw)
        self.assertNotIn("source_max_event_id", raw)

    def test_no_conversation_or_experience_data(self):
        privacy = self.builder.build(self.source)["transfer"]["privacy"]
        self.assertFalse(privacy["conversation_content_included"])
        self.assertFalse(privacy["p61_experience_events_included"])
        self.assertFalse(privacy["p1_p5_knowledge_included"])

    def test_p71_checksum_tampering_rejected(self):
        doc = copy.deepcopy(self.source)
        doc["package"]["intelligence"]["p63"]["config"]["min_evidence"] = 99
        with self.assertRaisesRegex(ContextTransferError, "P7.1 checksum"):
            self.builder.build(doc)

    def test_mismatched_context_rejected(self):
        doc = copy.deepcopy(self.source)
        doc["package"]["intelligence"]["p63"]["source_scoped_policy_archive"][0]["context_key"] = "other"
        doc["integrity"]["package_sha256"] = hashlib.sha256(canonical(doc["package"])).hexdigest()
        with self.assertRaisesRegex(ContextTransferError, "context"):
            self.builder.build(doc)

    def test_invalid_multiplier_rejected(self):
        doc = copy.deepcopy(self.source)
        doc["package"]["intelligence"]["p63"]["source_scoped_policy_archive"][0]["multiplier"] = 9
        doc["integrity"]["package_sha256"] = hashlib.sha256(canonical(doc["package"])).hexdigest()
        with self.assertRaisesRegex(ContextTransferError, "outside"):
            self.builder.build(doc)

    def test_transfer_checksum_tampering_rejected(self):
        result = self.builder.build(self.source)
        result["transfer"]["context_priors"][0]["prior_multiplier"] = 1.19
        with self.assertRaisesRegex(ContextTransferError, "checksum"):
            self.builder.verify_transfer(result)

    def test_destination_contract_is_non_mutating(self):
        contract = self.builder.build(self.source)["transfer"]["destination_contract"]
        self.assertTrue(contract["destination_knowledge_is_not_modified"])
        self.assertTrue(contract["destination_feedback_must_update_local_policy"])
        self.assertFalse(contract["source_per_memory_policies_are_executable"])


if __name__ == "__main__":
    unittest.main()
