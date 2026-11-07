from datetime import datetime, timezone, timedelta
import unittest

from engram_erc.contracts import (
    Proposition, PropositionKind, InferenceStep, ReasoningGraph,
    ReasoningResult, ReasoningStatus,
)
from engram_erc.feedback import FeedbackLedger, OutcomeEvent, OutcomeLabel
from engram_erc.trace_learning import TraceLearningPolicy, learn_reasoning_traces
from engram_erc.improvement import (
    ImprovementPolicy, ProposalKind, ProposalReview, ProposalReviewLedger,
    ReviewDisposition, generate_improvement_proposals,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def make_result():
    props = (
        Proposition("p0", "patient", "finding", "A"),
        Proposition("p1", "patient", "risk", "high", kind=PropositionKind.INFERENCE),
        Proposition("p2", "patient", "plan", "review", kind=PropositionKind.INFERENCE),
    )
    steps = (
        InferenceStep("s1", "rule_application", ("p0",), ("p1",), "RISK_RULE"),
        InferenceStep("s2", "rule_application", ("p1",), ("p2",), "PLAN_RULE"),
    )
    return ReasoningResult("res1", "req1", ReasoningStatus.COMPLETE, ("p2",), props, steps, ReasoningGraph())


def make_ledger(n=6, contradicted=2):
    events = []
    for i in range(n):
        outcome = OutcomeLabel.CONTRADICTED if i < contradicted else OutcomeLabel.VERIFIED_SUPPORTED
        events.append(OutcomeEvent(
            f"ev{i}", "res1", "p2", outcome, NOW - timedelta(days=i),
            f"adjudicator:{i}", "surgical_assessment", ("robotic",),
            rule_refs=("RISK_RULE", "PLAN_RULE"), notes_ref=f"note:{i}" if i < contradicted else None,
        ))
    return FeedbackLedger(tuple(events))


class ImprovementTests(unittest.TestCase):
    def setUp(self):
        self.ledger = make_ledger()
        self.trace = learn_reasoning_traces(
            self.ledger, (make_result(),),
            policy=TraceLearningPolicy(min_adjudicated_events=5), generated_at=NOW,
        )

    def test_generates_path_step_and_premise_review_proposals(self):
        report = generate_improvement_proposals(self.trace, self.ledger)
        kinds = {p.kind for p in report.proposals}
        self.assertEqual(kinds, {
            ProposalKind.REVIEW_REASONING_PATH,
            ProposalKind.REVIEW_RULE_APPLICATION,
            ProposalKind.REVIEW_PREMISE_REQUIREMENTS,
        })
        self.assertEqual(len(report.proposals), 4)

    def test_proposals_carry_adjudication_provenance(self):
        report = generate_improvement_proposals(self.trace, self.ledger)
        for proposal in report.proposals:
            self.assertEqual(len(proposal.adjudication_source_refs), 2)
            self.assertEqual(len(proposal.notes_refs), 2)
            self.assertEqual(proposal.contradicted_count, 2)

    def test_no_proposals_without_contradicted_outcomes(self):
        ledger = make_ledger(6, 0)
        trace = learn_reasoning_traces(ledger, (make_result(),), generated_at=NOW)
        report = generate_improvement_proposals(trace, ledger)
        self.assertEqual(report.proposals, ())

    def test_minimum_threshold_is_enforced(self):
        ledger = make_ledger(4, 2)
        trace = learn_reasoning_traces(ledger, (make_result(),),
            policy=TraceLearningPolicy(min_adjudicated_events=5), generated_at=NOW)
        report = generate_improvement_proposals(trace, ledger)
        self.assertEqual(report.proposals, ())
        self.assertGreater(report.skipped_below_threshold, 0)

    def test_inconclusive_outcomes_do_not_inflate_adjudicated_count(self):
        events = list(make_ledger(5, 2).events)
        events[-1] = OutcomeEvent("ev4", "res1", "p2", OutcomeLabel.INCONCLUSIVE,
            NOW - timedelta(days=4), "adjudicator:4", "surgical_assessment", ("robotic",))
        ledger = FeedbackLedger(tuple(events))
        trace = learn_reasoning_traces(ledger, (make_result(),),
            policy=TraceLearningPolicy(min_adjudicated_events=5), generated_at=NOW)
        self.assertEqual(generate_improvement_proposals(trace, ledger).proposals, ())

    def test_review_acceptance_is_record_only(self):
        proposal = generate_improvement_proposals(self.trace, self.ledger).proposals[0]
        review = ProposalReview(proposal.proposal_id,
            ReviewDisposition.ACCEPT_FOR_MANUAL_CHANGE, "reviewer:1",
            NOW.isoformat(), "Validate the proposed change in a separate test suite.")
        ledger = ProposalReviewLedger().append(review)
        self.assertEqual(ledger.reviews, (review,))
        self.assertEqual(ProposalReviewLedger().reviews, ())

    def test_review_ledger_is_immutable_and_idempotent(self):
        review = ProposalReview("p", ReviewDisposition.DEFER, "reviewer:1", NOW.isoformat(), "Need more data")
        ledger = ProposalReviewLedger().append(review)
        self.assertIs(ledger.append(review), ledger)
        self.assertEqual(len(ledger.reviews), 1)

    def test_proposal_ids_are_deterministic(self):
        a = generate_improvement_proposals(self.trace, self.ledger)
        b = generate_improvement_proposals(self.trace, self.ledger)
        self.assertEqual([p.proposal_id for p in a.proposals], [p.proposal_id for p in b.proposals])

    def test_review_requires_rationale(self):
        with self.assertRaises(ValueError):
            ProposalReview("p", ReviewDisposition.REJECT, "reviewer:1", NOW.isoformat(), " ")


if __name__ == "__main__":
    unittest.main()
