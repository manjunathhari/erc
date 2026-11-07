import unittest
from datetime import datetime, timezone

from engram_erc import (
    Proposition, PropositionKind, Evidence, EvidenceKind, EvidenceLink,
    EvidenceRelation, SourceKind, ReasoningRequest, ReasoningStatus,
    Variable, PropositionPattern, ConclusionTemplate, RuleDefinition, RuleSet,
    StrategyDefinition, StrategyCatalog, StrategyOperation, TimeInterval, orchestrate,
    default_strategy_catalog,
)


class OrchestrationTests(unittest.TestCase):
    def request(self, *, task="review", propositions=(), evidence=(), links=()):
        return ReasoningRequest(
            id="req-1", task_type=task, propositions=tuple(propositions),
            evidence=tuple(evidence), evidence_links=tuple(links),
        )

    def test_default_selects_consistency_without_evidence_or_rules(self):
        req = self.request(propositions=[Proposition("p1", "x", "active", True)])
        out = orchestrate(req)
        self.assertEqual(out.selected_strategy.strategy_id, "consistency_review")
        self.assertEqual(out.result.status, ReasoningStatus.COMPLETE)

    def test_evidence_strategy_selected_when_evidence_available(self):
        p = Proposition("p1", "x", "active", True)
        e = Evidence("e1", "source-1", SourceKind.USER_PROVIDED, EvidenceKind.OBSERVATION)
        req = self.request(propositions=[p], evidence=[e],
                           links=[EvidenceLink("e1", "p1", EvidenceRelation.SUPPORTS)])
        out = orchestrate(req)
        self.assertEqual(out.selected_strategy.strategy_id, "evidence_review")
        self.assertEqual(len(out.evidence_assessments), 1)

    def test_no_evidence_is_uncertainty_not_falsehood(self):
        req = self.request(propositions=[Proposition("p1", "x", "active", True)],
                           evidence=[Evidence("e1", "s", SourceKind.USER_PROVIDED)])
        # The evidence exists but is not linked; it must not count as support.
        out = orchestrate(req)
        self.assertEqual(out.evidence_assessments[0].evidence_count, 0)
        self.assertTrue(any("does not establish falsehood" in u.description
                            for u in out.result.uncertainty))

    def test_definite_conflict_halts_rule_execution(self):
        interval = TimeInterval(
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2027, 1, 1, tzinfo=timezone.utc),
        )
        a = Proposition("p1", "patient", "has_condition", True, valid_time=interval)
        b = Proposition("p2", "patient", "has_condition", True, polarity=False, valid_time=interval)
        x = Variable("x")
        rule = RuleDefinition(
            "r1", "1", (PropositionPattern(x, "has_condition", True),),
            ConclusionTemplate(x, "review_needed", True), "test",
        )
        out = orchestrate(self.request(propositions=[a, b]),
                          ruleset=RuleSet((rule,), "1"))
        self.assertTrue(out.stopped_before_inference)
        self.assertIsNone(out.rule_execution)
        self.assertEqual(out.result.status, ReasoningStatus.CONFLICT)
        self.assertEqual(len(out.result.inference_steps), 0)

    def test_potential_temporal_conflict_does_not_halt(self):
        a = Proposition("p1", "patient", "has_condition", True)
        b = Proposition("p2", "patient", "has_condition", False)
        x = Variable("x")
        rule = RuleDefinition(
            "r1", "1", (PropositionPattern(x, "has_condition", True),),
            ConclusionTemplate(x, "review_needed", True), "test",
        )
        # Missing intervals make the contradiction potential, not definite.
        out = orchestrate(self.request(propositions=[a, b]),
                          ruleset=RuleSet((rule,), "1"))
        self.assertFalse(out.stopped_before_inference)
        self.assertIsNotNone(out.rule_execution)
        self.assertEqual(len(out.result.inference_steps), 1)

    def test_rule_strategy_preflights_evidence_and_conflicts(self):
        p = Proposition("p1", "x", "risk", True)
        e = Evidence("e1", "source", SourceKind.USER_PROVIDED)
        x = Variable("x")
        rule = RuleDefinition(
            "r1", "1", (PropositionPattern(x, "risk", True),),
            ConclusionTemplate(x, "action", "consider"), "test",
        )
        req = self.request(propositions=[p], evidence=[e],
                           links=[EvidenceLink("e1", "p1", EvidenceRelation.SUPPORTS)])
        out = orchestrate(req, ruleset=RuleSet((rule,), "1"))
        self.assertEqual(out.selected_strategy.strategy_id, "rule_reasoning")
        ops = [t.operation for t in out.result.trace]
        self.assertLess(ops.index("detect_contradictions"), ops.index("assess_evidence"))
        self.assertTrue(any(op.startswith("rule:") for op in ops))
        self.assertEqual(out.result.propositions[-1].kind, PropositionKind.INFERENCE)

    def test_catalog_priority_and_deterministic_tie_break(self):
        a = StrategyDefinition("z", "1", ("review",), (StrategyOperation.DETECT_CONTRADICTIONS,), 5)
        b = StrategyDefinition("a", "1", ("review",), (StrategyOperation.DETECT_CONTRADICTIONS,), 5)
        out = orchestrate(self.request(), catalog=StrategyCatalog((a, b)))
        self.assertEqual(out.selected_strategy.strategy_id, "a")

    def test_adaptive_override_selects_only_an_eligible_strategy(self):
        a = StrategyDefinition("a", "1", ("review",), (StrategyOperation.DETECT_CONTRADICTIONS,), 5)
        b = StrategyDefinition("b", "1", ("review",), (StrategyOperation.ASSESS_EVIDENCE,), 1)
        catalog = StrategyCatalog((a, b))
        out = orchestrate(self.request(), catalog=catalog, strategy_ref_override="b@1")
        self.assertEqual(out.selected_strategy.strategy_id, "b")

    def test_adaptive_override_cannot_bypass_eligibility(self):
        only = StrategyDefinition("needs_evidence", "1", ("review",),
            (StrategyOperation.ASSESS_EVIDENCE,), requires_evidence=True)
        with self.assertRaises(LookupError):
            orchestrate(self.request(), catalog=StrategyCatalog((only,)),
                        strategy_ref_override="needs_evidence@1")

    def test_no_eligible_strategy_is_explicit(self):
        only = StrategyDefinition(
            "evidence_only", "1", ("special",),
            (StrategyOperation.ASSESS_EVIDENCE,), requires_evidence=True,
        )
        with self.assertRaises(LookupError):
            orchestrate(self.request(task="other"), catalog=StrategyCatalog((only,)))

    def test_strategy_contract_rejects_rule_requirement_without_rule_operation(self):
        with self.assertRaises(ValueError):
            StrategyDefinition("bad", "1", ("*",),
                               (StrategyOperation.DETECT_CONTRADICTIONS,),
                               requires_rules=True)

    def test_potential_conflict_after_rule_derivation_is_reported(self):
        # Rule can derive a claim opposite to an existing one; final scan catches it.
        p1 = Proposition("p1", "x", "eligible", True)
        p2 = Proposition("p2", "x", "not_eligible", False, polarity=True)
        x = Variable("x")
        rule = RuleDefinition(
            "r1", "1", (PropositionPattern(x, "eligible", True),),
            ConclusionTemplate(x, "not_eligible", False, polarity=False), "derive opposite polarity",
        )
        out = orchestrate(self.request(propositions=[p1, p2]),
                          ruleset=RuleSet((rule,), "1"))
        self.assertTrue(out.contradictions)
        self.assertEqual(out.contradictions[0].certainty.value, "potential")
        self.assertEqual(out.result.status, ReasoningStatus.COMPLETE)


if __name__ == "__main__":
    unittest.main()
