import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engram_p7.benchmark import BenchmarkError, RetrievalBenchmark, make_dataset_row


class TestP77(unittest.TestCase):
    def setUp(self):
        self.benchmark = RetrievalBenchmark(
            k_values=(1, 2, 3), bootstrap_samples=200, permutation_samples=300, seed=19
        )

    def dataset(self):
        q1 = make_dataset_row(
            "q1", "ctx-a", "2026-10-01T10:00:00+00:00",
            ["m1", "m2"], ["m2"], ["m1"],
            ["m3", "m1", "m2"], ["m2", "m1", "m3"], ["m1", "m2", "m3"],
            "2026-09-30T10:00:00+00:00",
        )
        q2 = make_dataset_row(
            "q2", "ctx-b", "2026-10-02T10:00:00+00:00",
            ["m4"], ["m4"], [],
            ["m5", "m4", "m6"], ["m4", "m5", "m6"], ["m4", "m5", "m6"],
            "2026-10-01T10:00:00+00:00",
        )
        return {
            "format": "engram-p7.7-benchmark-dataset",
            "format_version": 1,
            "judgment_source": "human_adjudicated_holdout",
            "queries": [q1, q2],
        }

    def test_metrics_and_paired_comparison(self):
        report = self.benchmark.run(self.dataset())
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["query_count"], 2)
        self.assertIn("inherited_local_vs_baseline", report["paired_comparisons"])
        self.assertGreater(
            report["aggregate_metrics"]["inherited_local"]["recall@2"],
            report["aggregate_metrics"]["baseline"]["recall@2"],
        )

    def test_future_cutoff_rejected(self):
        data = self.dataset()
        data["queries"][0]["provenance"]["inherited_cutoff"] = "2026-10-02T10:00:00+00:00"
        with self.assertRaises(BenchmarkError):
            self.benchmark.run(data)

    def test_candidate_set_must_match(self):
        data = self.dataset()
        data["queries"][0]["rankings"]["inherited"] = ["m1", "m2"]
        with self.assertRaises(BenchmarkError):
            self.benchmark.run(data)

    def test_rare_and_correction_labels_must_be_relevant(self):
        data = self.dataset()
        data["queries"][0]["rare_important_refs"] = ["unknown"]
        with self.assertRaises(BenchmarkError):
            self.benchmark.run(data)

    def test_holdout_label_declaration_required(self):
        data = self.dataset()
        data["judgment_source"] = "model_generated"
        with self.assertRaises(BenchmarkError):
            self.benchmark.run(data)

    def test_report_integrity(self):
        import tempfile, os
        report = self.benchmark.run(self.dataset())
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            self.benchmark.write_report(report, path)
            altered = dict(report)
            altered["query_count"] = 999
            with self.assertRaises(BenchmarkError):
                self.benchmark.write_report(altered, path)
        finally:
            os.unlink(path)

    def test_deterministic_report_metrics(self):
        one = self.benchmark.run(self.dataset())
        two = self.benchmark.run(self.dataset())
        self.assertEqual(one["aggregate_metrics"], two["aggregate_metrics"])
        self.assertEqual(one["paired_comparisons"], two["paired_comparisons"])


if __name__ == "__main__":
    unittest.main()
