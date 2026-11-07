import unittest

from engram_erc import (
    Proposition, PropositionKind, Evidence, EvidenceKind, EvidenceLink,
    EvidenceRelation, SourceKind, ReasoningGraphBuilder, ReasoningResult,
    ReasoningStatus, InferenceStep, DecisionPolicy, ConclusionDecision,
    EscalationLevel, evaluate_conclusions,
)


def make_result(propositions, conclusions, steps=()):
    builder = ReasoningGraphBuilder()
    for p in propositions:
        builder.add_proposition(p)
    graph = builder.build()
    return ReasoningResult(
        id="result-1", request_id="request-1",
        status=ReasoningStatus.COMPLETE,
        conclusion_refs=tuple(conclusions),
        propositions=tuple(propositions),
        inference_steps=tuple(steps), graph=graph,
    )


class ConclusionEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.root = Proposition("p-root", "case-1", "has_risk", True)
        self.derived = Proposition(
            "p-derived", "case-1", "review_required", True,
            kind=PropositionKind.INFERENCE,
        )
        self.step = InferenceStep(
            "inf-1", "forward_rule", ("p-root",), ("p-derived",), "rule-1"
        )
        self.evidence = Evidence(
            "e-support", "source-1", SourceKind.EXTERNAL_DATABASE,
            EvidenceKind.STUDY_RESULT,
        )
        self.support_link = EvidenceLink(
            "e-support", "p-root", EvidenceRelation.SUPPORTS
        )

    def test_supported_complete_lineage_is_accepted(self):
        result = make_result([self.root, self.derived], ["p-derived"], [self.step])
        report = evaluate_conclusions(
            result, evidence=(self.evidence,), evidence_links=(self.support_link,)
        )
        item = report.evaluations[0]
        self.assertEqual(item.decision, ConclusionDecision.ACCEPTED)
        self.assertEqual(item.premise_coverage.leaf_premise_ids, ("p-root",))
        self.assertEqual(report.overall_decision, ConclusionDecision.ACCEPTED)

    def test_missing_root_evidence_withholds_not_rejects(self):
        result = make_result([self.root, self.derived], ["p-derived"], [self.step])
        report = evaluate_conclusions(result)
        self.assertEqual(report.evaluations[0].decision, ConclusionDecision.WITHHELD)
        self.assertEqual(report.evaluations[0].escalation, EscalationLevel.SOURCE_RETRIEVAL)
        self.assertEqual(report.rejected_refs, ())

    def test_contradicting_evidence_causes_conflicted_decision(self):
        result = make_result([self.root, self.derived], ["p-derived"], [self.step])
        contrary = Evidence(
            "e-contra", "source-2", SourceKind.EXTERNAL_DATABASE,
            EvidenceKind.STUDY_RESULT,
        )
        links = (
            self.support_link,
            EvidenceLink("e-contra", "p-root", EvidenceRelation.CONTRADICTS),
        )
        report = evaluate_conclusions(
            result, evidence=(self.evidence, contrary), evidence_links=links
        )
        self.assertEqual(report.overall_decision, ConclusionDecision.CONFLICTED)
        self.assertEqual(report.evaluations[0].escalation, EscalationLevel.EXPERT_ADJUDICATION)

    def test_complete_contrary_evidence_rejects_conclusion(self):
        result = make_result([self.root, self.derived], ["p-derived"], [self.step])
        contrary = Evidence(
            "e-contra", "source-2", SourceKind.EXTERNAL_DATABASE,
            EvidenceKind.STUDY_RESULT,
        )
        report = evaluate_conclusions(
            result, evidence=(contrary,),
            evidence_links=(EvidenceLink(
                "e-contra", "p-root", EvidenceRelation.CONTRADICTS
            ),),
        )
        self.assertEqual(report.evaluations[0].decision, ConclusionDecision.REJECTED)
        self.assertEqual(report.overall_decision, ConclusionDecision.REJECTED)
        self.assertEqual(report.rejected_refs, ("p-derived",))

    def test_policy_can_allow_contrary_evidence_only_as_provisional(self):
        result = make_result([self.root, self.derived], ["p-derived"], [self.step])
        contrary = Evidence("e-contra", "source-2", SourceKind.EXTERNAL_DATABASE)
        report = evaluate_conclusions(
            result, evidence=(self.evidence, contrary),
            evidence_links=(
                self.support_link,
                EvidenceLink("e-contra", "p-root", EvidenceRelation.CONTRADICTS),
            ),
            policy=DecisionPolicy(require_no_contradicting_evidence=False),
        )
        self.assertEqual(report.evaluations[0].decision, ConclusionDecision.PROVISIONAL)

    def test_qualifying_evidence_prevents_unqualified_acceptance(self):
        result = make_result([self.root, self.derived], ["p-derived"], [self.step])
        qualifying = Evidence("e-qual", "source-q", SourceKind.EXTERNAL_DATABASE)
        report = evaluate_conclusions(
            result, evidence=(self.evidence, qualifying),
            evidence_links=(
                self.support_link,
                EvidenceLink("e-qual", "p-root", EvidenceRelation.QUALIFIES),
            ),
        )
        self.assertEqual(report.evaluations[0].decision, ConclusionDecision.PROVISIONAL)

    def test_missing_inference_producer_is_not_assumed_to_be_a_root_fact(self):
        result = make_result([self.derived], ["p-derived"], ())
        report = evaluate_conclusions(result)
        self.assertFalse(report.evaluations[0].premise_coverage.complete)
        self.assertEqual(report.evaluations[0].decision, ConclusionDecision.WITHHELD)

    def test_no_conclusions_is_withheld_for_review(self):
        result = make_result([self.root], [])
        report = evaluate_conclusions(result)
        self.assertEqual(report.overall_decision, ConclusionDecision.WITHHELD)
        self.assertEqual(report.escalation, EscalationLevel.REVIEW)

    def test_zero_threshold_can_be_used_explicitly(self):
        result = make_result([self.root, self.derived], ["p-derived"], [self.step])
        report = evaluate_conclusions(
            result, policy=DecisionPolicy(
                min_supporting_sources_per_leaf=0,
                require_support_for_every_leaf=True,
            )
        )
        self.assertEqual(report.evaluations[0].decision, ConclusionDecision.ACCEPTED)

    def test_distinct_leaf_premises_all_need_coverage(self):
        second = Proposition("p-second", "case-1", "has_other_risk", True)
        derived2 = Proposition(
            "p-derived2", "case-1", "review_required", True,
            kind=PropositionKind.INFERENCE,
        )
        step = InferenceStep(
            "inf-2", "combined_rule", ("p-root", "p-second"),
            ("p-derived2",), "rule-2"
        )
        result = make_result(
            [self.root, second, derived2], ["p-derived2"], [step]
        )
        report = evaluate_conclusions(
            result, evidence=(self.evidence,), evidence_links=(self.support_link,)
        )
        self.assertEqual(report.evaluations[0].premise_coverage.uncovered_leaf_ids, ("p-second",))
        self.assertEqual(report.evaluations[0].decision, ConclusionDecision.WITHHELD)


if __name__ == "__main__":
    unittest.main()
