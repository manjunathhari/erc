import unittest

from engram_erc import Proposition, PropositionKind, ReasoningStatus
from engram_erc.rules import (
    Variable, PropositionPattern, ConclusionTemplate, RuleDefinition, RuleSet,
)
from engram_erc.inference import (
    ExecutionLimits, execute_rules, match_rule, to_reasoning_result,
)


class RuleContractTests(unittest.TestCase):
    def test_rejects_unbound_conclusion_variable(self):
        with self.assertRaisesRegex(ValueError, "unbound variables"):
            RuleDefinition(
                "r1", "1",
                (PropositionPattern(Variable("x"), "is", True),),
                ConclusionTemplate(Variable("x"), "has", Variable("missing")),
            )

    def test_requires_premise(self):
        with self.assertRaisesRegex(ValueError, "at least one premise"):
            RuleDefinition("r1", "1", (), ConclusionTemplate("x", "p", True))


class RuleMatchingTests(unittest.TestCase):
    def setUp(self):
        self.x = Variable("x")
        self.rule = RuleDefinition(
            "person_is_patient", "1.0",
            (PropositionPattern(self.x, "is_patient", True),),
            ConclusionTemplate(self.x, "requires_review", True),
        )

    def test_matches_and_binds_variable(self):
        props = (
            Proposition("p1", "patient_1", "is_patient", True),
            Proposition("p2", "patient_2", "is_patient", False),
        )
        matches = match_rule(self.rule, props)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].bindings["x"], "patient_1")

    def test_shared_variables_must_unify(self):
        rule = RuleDefinition(
            "same_subject", "1",
            (
                PropositionPattern(self.x, "has_symptom", "fever"),
                PropositionPattern(self.x, "has_symptom", "pain"),
            ),
            ConclusionTemplate(self.x, "has_multiple_symptoms", True),
        )
        props = (
            Proposition("a", "patient_1", "has_symptom", "fever"),
            Proposition("b", "patient_1", "has_symptom", "pain"),
            Proposition("c", "patient_2", "has_symptom", "pain"),
        )
        matches = match_rule(rule, props)
        self.assertEqual(len(matches), 1)
        self.assertEqual(set(matches[0].premise_ids), {"a", "b"})

    def test_does_not_reuse_same_premise_by_default(self):
        rule = RuleDefinition(
            "two_facts", "1",
            (
                PropositionPattern(self.x, "fact", True),
                PropositionPattern(self.x, "fact", True),
            ),
            ConclusionTemplate(self.x, "two_facts", True),
        )
        props = (Proposition("a", "x", "fact", True),)
        self.assertEqual(match_rule(rule, props), ())


class ExecutionTests(unittest.TestCase):
    def test_derives_proposition_and_builds_trace(self):
        x = Variable("x")
        rule = RuleDefinition(
            "screening", "1.0",
            (PropositionPattern(x, "has_risk_factor", True),),
            ConclusionTemplate(x, "screening_indicated", True),
            description="A defined screening rule.",
        )
        source = Proposition("p1", "patient_1", "has_risk_factor", True)
        execution = execute_rules((source,), RuleSet((rule,), "2026.1"))
        derived = [p for p in execution.propositions if p.kind == PropositionKind.INFERENCE]
        self.assertEqual(len(derived), 1)
        self.assertEqual(derived[0].predicate, "screening_indicated")
        self.assertEqual(execution.firings_executed, 1)
        self.assertEqual(execution.trace[0].status, "derived")
        self.assertEqual(execution.inference_steps[0].input_refs, ("p1",))

    def test_forward_chaining_across_rounds(self):
        x = Variable("x")
        r1 = RuleDefinition(
            "r1", "1", (PropositionPattern(x, "a", True),),
            ConclusionTemplate(x, "b", True),
        )
        r2 = RuleDefinition(
            "r2", "1", (PropositionPattern(x, "b", True),),
            ConclusionTemplate(x, "c", True),
        )
        execution = execute_rules(
            (Proposition("p0", "s", "a", True),), RuleSet((r1, r2))
        )
        self.assertTrue(any(p.predicate == "c" for p in execution.propositions))
        self.assertGreaterEqual(execution.rounds_executed, 2)
        self.assertEqual(execution.firings_executed, 2)

    def test_execution_limit_returns_partial(self):
        x = Variable("x")
        rule = RuleDefinition(
            "derive", "1", (PropositionPattern(x, "a", True),),
            ConclusionTemplate(x, "b", True),
        )
        props = tuple(Proposition(f"p{i}", f"s{i}", "a", True) for i in range(3))
        execution = execute_rules(
            props, RuleSet((rule,)), limits=ExecutionLimits(max_rounds=3, max_total_firings=1)
        )
        self.assertEqual(execution.status, ReasoningStatus.PARTIAL)
        self.assertEqual(execution.firings_executed, 1)

    def test_per_rule_firing_limit_applies_across_rounds(self):
        x = Variable("x")
        r1 = RuleDefinition(
            "r1", "1", (PropositionPattern(x, "a", True),),
            ConclusionTemplate(x, "b", True), max_firings=1,
        )
        r2 = RuleDefinition(
            "r2", "1", (PropositionPattern(x, "b", True),),
            ConclusionTemplate(x, "c", True),
        )
        props = (
            Proposition("p1", "s1", "a", True),
            Proposition("p2", "s2", "a", True),
        )
        execution = execute_rules(props, RuleSet((r1, r2)))
        self.assertEqual(
            sum(step.rule_id.startswith("r1@") for step in execution.inference_steps),
            1,
        )
        self.assertEqual(execution.status, ReasoningStatus.PARTIAL)

    def test_no_duplicate_conclusion(self):
        x = Variable("x")
        rule = RuleDefinition(
            "derive", "1", (PropositionPattern(x, "a", True),),
            ConclusionTemplate(x, "b", True),
        )
        props = (
            Proposition("p1", "s", "a", True),
            Proposition("already", "s", "b", True),
        )
        execution = execute_rules(props, RuleSet((rule,)))
        self.assertEqual(len(execution.propositions), 2)
        self.assertEqual(execution.firings_executed, 0)
        self.assertEqual(execution.trace[0].status, "no_op_duplicate_conclusion")

    def test_result_contract_wraps_execution(self):
        x = Variable("x")
        rule = RuleDefinition(
            "derive", "1", (PropositionPattern(x, "a", True),),
            ConclusionTemplate(x, "b", True),
        )
        execution = execute_rules((Proposition("p1", "s", "a", True),), RuleSet((rule,)))
        result = to_reasoning_result(execution, request_id="req-1", result_id="res-1")
        self.assertEqual(result.request_id, "req-1")
        self.assertEqual(result.status, ReasoningStatus.COMPLETE)
        self.assertEqual(len(result.inference_steps), 1)
        self.assertTrue(result.conclusion_refs)


if __name__ == "__main__":
    unittest.main()
