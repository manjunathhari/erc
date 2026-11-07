import unittest
from pathlib import Path

# The stage packages are joined in engram_p7, so they are imported from there instead of loaded by file path.
from engram_p7.context_transfer import ContextPolicyTransfer
from engram_p7.compatibility import ModelCompatibilityValidator
from engram_p7.restoration import IntelligenceRestorer
from engram_p7.portability import CrossInstallationHarness, build_summary


class TestCrossInstallation(unittest.TestCase):
    def setUp(self):
        self.harness = CrossInstallationHarness(
            ContextPolicyTransfer(),
            ModelCompatibilityValidator(),
            lambda db, installation_id: IntelligenceRestorer(db, installation_id),
        )

    def test_full_portability_suite(self):
        results = self.harness.run_suite()
        summary = build_summary(results)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["passed"], 7)
        self.assertEqual(summary["failed"], 0)

    def test_destination_memory_is_not_overwritten(self):
        result = self.harness.run_happy_path("source-unique", "destination-unique")
        db = result["destination_db"]
        row = db.execute(
            "SELECT content FROM local_knowledge WHERE record_id='destination-unique-fact-1'"
        ).fetchone()
        self.assertEqual(row[0], "Private knowledge belonging to destination-unique")

    def test_active_prior_is_available_without_source_memory_ids(self):
        result = self.harness.run_happy_path()
        prior = result["restorer"].get_active_prior("ctx-shared")
        self.assertIsNotNone(prior)
        self.assertNotIn("target_ref", dict(prior))
        self.assertNotIn("policy_id", dict(prior))

    def test_summary_integrity(self):
        results = self.harness.run_suite()
        summary = build_summary(results)
        from hashlib import sha256
        import json
        payload = {k: v for k, v in summary.items() if k != "integrity"}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        self.assertEqual(summary["integrity"]["report_sha256"], sha256(canonical).hexdigest())


if __name__ == "__main__":
    unittest.main()
