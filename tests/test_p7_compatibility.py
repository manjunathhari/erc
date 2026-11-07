import copy
import hashlib
import json
import unittest

from engram_p7 import (
    DestinationProfile, ModelCompatibilityValidator, CompatibilityValidationError
)


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def transfer_fixture():
    prior = {
        "context_key": "ctx-A", "source_policy_version": 3,
        "source_algorithm": "beta_shrinkage_v1", "prior_multiplier": 1.04,
        "prior_strength": 2.5, "confidence": .72,
        "log_multiplier_dispersion": .04, "source_policy_count": 4,
        "effective_policy_count": 3.2, "support_status": "supported",
        "semantics": "context_prior_for_destination_local_learning",
    }
    transfer = {
        "format": "engram-context-intelligence-transfer",
        "format_version": 1,
        "transfer_algorithm": "confidence_weighted_log_pool_v1",
        "source": {"p71_package_sha256": "a" * 64, "p6_3_version": 3,
                   "p6_3_algorithm": "beta_shrinkage_v1", "p6_6_bundle_version": 4},
        "context_priors": [prior],
        "model_configuration": {
            "p63": {"algorithm": "beta_shrinkage_v1",
                    "config": {"prior_alpha": 1, "prior_beta": 1, "min_evidence": 2,
                               "min_multiplier": .8, "max_multiplier": 1.2}},
            "p64": {"config": {"half_life_days": 90, "trend_window_days": 30},
                    "status": "configuration_transferred"},
            "retrieval": {"config": {"mode": "shadow"},
                          "status": "configuration_transferred_not_applied"},
        },
        "destination_contract": {
            "source_memory_ids_required": False,
            "source_conversations_required": False,
            "source_experience_events_required": False,
            "source_per_memory_policies_are_executable": False,
            "context_prior_is_initialization_not_destination_fact": True,
            "destination_feedback_must_update_local_policy": True,
            "destination_knowledge_is_not_modified": True,
        },
        "privacy": {
            "conversation_content_included": False,
            "p61_experience_events_included": False,
            "p1_p5_knowledge_included": False,
            "source_memory_identifiers_included": False,
            "source_per_memory_policy_rows_included": False,
        },
    }
    return {"transfer": transfer, "integrity": {
        "algorithm": "sha256", "transfer_sha256": hashlib.sha256(canon(transfer)).hexdigest()
    }}


def capable_profile(**kwargs):
    base = dict(
        installation_id="destination-test",
        p7_2_format_versions=(1,),
        transfer_algorithms=("confidence_weighted_log_pool_v1",),
        p63_algorithms=("beta_shrinkage_v1",),
        context_prior_api_version=1,
        context_key_scheme="sha256_context_key_v1",
        supports_local_policy_learning=True,
        supports_context_prior_consumption=True,
        max_prior_strength=4.0,
        min_multiplier=.8,
        max_multiplier=1.2,
    )
    base.update(kwargs)
    return DestinationProfile(**base)


class TestP73(unittest.TestCase):
    def setUp(self):
        self.validator = ModelCompatibilityValidator()
        self.transfer = transfer_fixture()

    def test_compatible_destination(self):
        report = self.validator.validate(self.transfer, capable_profile())
        self.assertEqual(report["report"]["status"], "compatible_with_warnings")
        self.assertFalse(report["report"]["activation_authorized"])
        self.assertIn("RETRIEVAL_CONFIG_NOT_APPLIED", [x["code"] for x in report["report"]["warnings"]])
        self.assertTrue(self.validator.verify_report(report))

    def test_default_unintegrated_destination_is_incompatible(self):
        profile = DestinationProfile(installation_id="baseline-engram")
        report = self.validator.validate(self.transfer, profile)["report"]
        self.assertEqual(report["status"], "incompatible")
        self.assertIn("NO_CONTEXT_PRIOR_CONSUMER", [x["code"] for x in report["blockers"]])

    def test_unsupported_p63_algorithm(self):
        report = self.validator.validate(
            self.transfer, capable_profile(p63_algorithms=("other_algo",))
        )["report"]
        self.assertIn("UNSUPPORTED_P63_ALGORITHM", [x["code"] for x in report["blockers"]])

    def test_unsupported_config_key_blocks(self):
        doc = copy.deepcopy(self.transfer)
        doc["transfer"]["model_configuration"]["p63"]["config"]["new_knob"] = 1
        doc["integrity"]["transfer_sha256"] = hashlib.sha256(canon(doc["transfer"])).hexdigest()
        report = self.validator.validate(self._resign(doc), capable_profile())["report"]
        self.assertIn("UNSUPPORTED_P63_CONFIG_KEYS", [x["code"] for x in report["blockers"]])

    def test_unknown_p64_key_warns_not_applies(self):
        doc = copy.deepcopy(self.transfer)
        doc["transfer"]["model_configuration"]["p64"]["config"]["new_knob"] = 1
        doc = self._resign(doc)
        report = self.validator.validate(doc, capable_profile())["report"]
        self.assertEqual(report["status"], "compatible_with_warnings")
        self.assertIn("UNRECOGNISED_P64_CONFIG_KEYS", [x["code"] for x in report["warnings"]])

    def test_context_key_scheme_missing_warns(self):
        report = self.validator.validate(
            self.transfer, capable_profile(context_key_scheme="unknown")
        )["report"]
        self.assertIn("CONTEXT_KEY_SCHEME_UNDECLARED", [x["code"] for x in report["warnings"]])

    def test_prior_out_of_bounds_blocks(self):
        doc = copy.deepcopy(self.transfer)
        doc["transfer"]["context_priors"][0]["prior_multiplier"] = 1.5
        doc = self._resign(doc)
        report = self.validator.validate(doc, capable_profile())["report"]
        self.assertIn("PRIOR_MULTIPLIER_OUT_OF_BOUNDS", [x["code"] for x in report["blockers"]])

    def test_tampered_transfer_rejected(self):
        doc = copy.deepcopy(self.transfer)
        doc["transfer"]["context_priors"][0]["prior_strength"] = 3.0
        with self.assertRaisesRegex(CompatibilityValidationError, "checksum"):
            self.validator.validate(doc, capable_profile())

    def test_unsafe_privacy_declaration_blocks(self):
        doc = copy.deepcopy(self.transfer)
        doc["transfer"]["privacy"]["conversation_content_included"] = True
        doc = self._resign(doc)
        report = self.validator.validate(doc, capable_profile())["report"]
        self.assertIn("PRIVACY_DECLARATION_FAILED", [x["code"] for x in report["blockers"]])

    def test_insufficient_support_must_be_neutral(self):
        doc = copy.deepcopy(self.transfer)
        prior = doc["transfer"]["context_priors"][0]
        prior["support_status"] = "insufficient_support"
        prior["prior_multiplier"] = 1.05
        doc = self._resign(doc)
        report = self.validator.validate(doc, capable_profile())["report"]
        self.assertIn("UNSAFE_INSUFFICIENT_PRIOR", [x["code"] for x in report["blockers"]])

    def test_report_checksum_tampering_rejected(self):
        report = self.validator.validate(self.transfer, capable_profile())
        report["report"]["status"] = "compatible"
        with self.assertRaisesRegex(CompatibilityValidationError, "checksum"):
            self.validator.verify_report(report)

    def test_validation_does_not_authorize_activation(self):
        report = self.validator.validate(self.transfer, capable_profile())["report"]
        self.assertFalse(report["activation_authorized"])
        self.assertFalse(report["summary"]["ready_for_activation"])

    @staticmethod
    def _resign(doc):
        doc["integrity"]["transfer_sha256"] = hashlib.sha256(canon(doc["transfer"])).hexdigest()
        return doc


if __name__ == "__main__":
    unittest.main()
