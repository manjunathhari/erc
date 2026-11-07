import sqlite3
import unittest

# P6 comes from this repository's engram_p6, not from copies of the separate P6.1 and P6.3 packages.
from engram_p6 import AdaptiveScorer, ExperienceRecorder
from engram_p7.adaptation import DestinationIntelligenceAdapter, RetrievalIntegrationError


class FakeActivePrior:
    def __init__(self, prior=None):
        self.prior = prior

    def get_active_prior(self, context_key):
        if self.prior and self.prior["context_key"] == context_key:
            return dict(self.prior)
        return None


class Memory:
    def __init__(self, ref):
        self.id = ref


class StubRetriever:
    def __init__(self, indices):
        self.indices = indices
        self.called = None

    def retrieve(self, query, **kwargs):
        self.called = (query, kwargs)
        return list(self.indices)


class TestP76(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.recorder = ExperienceRecorder(self.db)
        self.scorer = AdaptiveScorer(self.db)
        self.prior = FakeActivePrior({
            "context_key": "ctx-source",
            "prior_multiplier": 0.90,
            "prior_strength": 4.0,
            "support_status": "supported",
        })

    def add_feedback(self, ref, signal, n, context="ctx-destination"):
        for i in range(n):
            self.recorder.record(
                "feedback", idempotency_key=f"{ref}-{signal}-{i}",
                context_key=context, target_ref=ref, signal=signal,
            )

    def adapter(self, mode="shadow", context_map=None):
        return DestinationIntelligenceAdapter(
            self.prior, self.scorer, mode=mode, context_map=context_map
        )

    def test_inherited_prior_is_used_for_destination_context(self):
        adapter = self.adapter(context_map={"ctx-destination": "ctx-source"})
        result = adapter.effective_multiplier("memory-a", "ctx-destination")
        self.assertEqual(result.source, "inherited_context_prior")
        self.assertEqual(result.multiplier, 0.9)
        self.assertEqual(result.source_context_key, "ctx-source")

    def test_exact_context_key_is_default_and_mismatch_is_neutral(self):
        adapter = self.adapter()
        result = adapter.effective_multiplier("memory-a", "ctx-destination")
        self.assertEqual(result.source, "neutral")
        self.assertEqual(result.multiplier, 1.0)

    def test_local_feedback_is_blended_and_can_dominate_prior(self):
        self.add_feedback("memory-a", "helpful", 100)
        snapshot = self.scorer.build_policy("ctx-destination")
        adapter = self.adapter(context_map={"ctx-destination": "ctx-source"})
        result = adapter.effective_multiplier("memory-a", "ctx-destination")
        self.assertEqual(result.source, "prior_plus_local")
        self.assertGreater(result.local_weight, 4.0)
        self.assertGreater(result.multiplier, 0.9)
        self.assertEqual(result.local_policy_version, snapshot.version)

    def test_shadow_mode_does_not_change_returned_order(self):
        self.add_feedback("memory-a", "helpful", 2000)
        self.add_feedback("memory-b", "irrelevant", 2000)
        self.scorer.build_policy("ctx-destination")
        memories = [Memory("memory-a"), Memory("memory-b"), Memory("memory-c"), Memory("memory-d")]
        result = self.adapter(context_map={"ctx-destination": "ctx-source"}).rank(
            [3, 2, 1, 0], memories, "ctx-destination"
        )
        self.assertEqual(result.indices, (3, 2, 1, 0))
        self.assertLess(result.proposed_indices.index(0), result.proposed_indices.index(1))
        self.assertFalse(result.applied)

    def test_apply_mode_reorders_only_existing_candidates(self):
        self.add_feedback("memory-a", "helpful", 2000)
        self.add_feedback("memory-b", "irrelevant", 2000)
        self.scorer.build_policy("ctx-destination")
        memories = [Memory("memory-a"), Memory("memory-b"), Memory("memory-c"), Memory("memory-d")]
        result = self.adapter(
            mode="apply", context_map={"ctx-destination": "ctx-source"}
        ).rank([3, 2, 1, 0], memories, "ctx-destination")
        self.assertEqual(set(result.indices), {0, 1, 2, 3})
        self.assertLess(result.indices.index(0), result.indices.index(1))
        self.assertTrue(result.applied)

    def test_retrieve_wrapper_preserves_retrieve_contract(self):
        memories = [Memory("a"), Memory("b"), Memory("c")]
        retriever = StubRetriever([2, 0])
        result = self.adapter().retrieve(
            retriever, memories, "test query", "ctx-destination", trace=True
        )
        self.assertEqual(result, [2, 0])
        self.assertEqual(retriever.called, ("test query", {"trace": True}))

    def test_no_stable_memory_id_fails_closed_to_neutral(self):
        memories = [object()]
        result = self.adapter().rank([0], memories, "ctx-destination")
        self.assertEqual(result.trace[0]["source"], "neutral_missing_reference")
        self.assertEqual(result.indices, (0,))

    def test_bad_prior_bounds_rejected(self):
        bad = FakeActivePrior({
            "context_key": "ctx-destination",
            "prior_multiplier": 1.5,
            "prior_strength": 2,
        })
        adapter = DestinationIntelligenceAdapter(bad, self.scorer)
        with self.assertRaises(RetrievalIntegrationError):
            adapter.effective_multiplier("memory-a", "ctx-destination")

    def test_duplicate_candidate_indices_rejected(self):
        with self.assertRaises(RetrievalIntegrationError):
            self.adapter().rank([0, 0], [Memory("a")], "ctx-destination")

    def test_no_fact_or_experience_mutation_during_ranking(self):
        self.add_feedback("memory-a", "helpful", 3)
        self.scorer.build_policy("ctx-destination")
        before = self.db.execute("SELECT COUNT(*) FROM p6_experience_events").fetchone()[0]
        policies_before = self.db.execute("SELECT COUNT(*) FROM p6_scoring_policies").fetchone()[0]
        self.adapter().rank([0], [Memory("memory-a")], "ctx-destination")
        after = self.db.execute("SELECT COUNT(*) FROM p6_experience_events").fetchone()[0]
        policies_after = self.db.execute("SELECT COUNT(*) FROM p6_scoring_policies").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(policies_before, policies_after)


if __name__ == "__main__":
    unittest.main()
