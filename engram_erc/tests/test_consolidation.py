import unittest
from datetime import datetime, timezone, timedelta

from engram_erc.feedback import FeedbackLedger, OutcomeEvent, OutcomeLabel
from engram_erc.consolidation import (
    ExperienceRecord, ConsolidationPolicy, ConsolidationStatus,
    ConsolidationDisposition, ConsolidationReview, ConsolidationReviewLedger,
    consolidate_experience, apply_consolidation_reviews,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)

def event(eid, outcome=OutcomeLabel.VERIFIED_SUPPORTED, result=None, conclusion="c1", at=NOW):
    return OutcomeEvent(eid, result or f"r-{eid}", conclusion, outcome, at,
        f"adjudicator:{eid}", "robotic_gi", context_tags=("colorectal",))

def record(eid, outcome_id=None, site="site-a", statement="Check perfusion before anastomosis",
           context="robotic_gi|colorectal", result=None, conclusion="c1", recorded=NOW,
           procedure="low_anterior_resection", kind="technical_observation"):
    return ExperienceRecord(eid, result or f"r-{outcome_id or eid}", conclusion,
        outcome_id or eid, context, "robotic_gi", site, procedure, kind,
        statement, (f"registry:{eid}",), recorded, ("anastomosis",))

def policy(**kw):
    base = dict(min_adjudicated_cases=2, min_distinct_sites=2, min_distinct_activities=1)
    base.update(kw)
    return ConsolidationPolicy(**base)

class ConsolidationTests(unittest.TestCase):
    def test_two_sites_two_supported_cases_create_candidate(self):
        events = (event("e1"), event("e2"))
        records = (record("x1","e1","site-a"), record("x2","e2","site-b"))
        report = consolidate_experience(records, FeedbackLedger(events), policy=policy())
        c = report.candidates[0]
        self.assertEqual(c.status, ConsolidationStatus.CANDIDATE)
        self.assertEqual(c.counts.supported, 2)
        self.assertEqual(len(c.distinct_sites), 2)

    def test_insufficient_case_count_not_candidate(self):
        report = consolidate_experience((record("x1","e1"),),
            FeedbackLedger((event("e1"),)), policy=policy())
        self.assertEqual(report.candidates[0].status, ConsolidationStatus.INSUFFICIENT_EXPERIENCE)

    def test_single_site_not_candidate_by_default(self):
        events=(event("e1"), event("e2", at=NOW-timedelta(days=1)))
        records=(record("x1","e1","site-a"), record("x2","e2","site-a"))
        report=consolidate_experience(records, FeedbackLedger(events), policy=policy())
        self.assertEqual(report.candidates[0].status, ConsolidationStatus.INSUFFICIENT_EXPERIENCE)

    def test_single_site_allowed_only_by_policy(self):
        events=(event("e1"), event("e2", at=NOW-timedelta(days=1)))
        records=(record("x1","e1","site-a"), record("x2","e2","site-a"))
        report=consolidate_experience(records, FeedbackLedger(events),
            policy=policy(allow_single_site_candidate=True))
        self.assertEqual(report.candidates[0].status, ConsolidationStatus.CANDIDATE)

    def test_mixed_adjudications_remain_conflicted(self):
        events=(event("e1"), event("e2", OutcomeLabel.CONTRADICTED))
        records=(record("x1","e1","site-a"), record("x2","e2","site-b"))
        report=consolidate_experience(records, FeedbackLedger(events), policy=policy())
        self.assertEqual(report.candidates[0].status, ConsolidationStatus.CONFLICTED)
        self.assertEqual(report.candidates[0].counts.contradicted, 1)

    def test_inconclusive_and_superseded_remain_visible_not_support(self):
        events=(event("e1"), event("e2", OutcomeLabel.INCONCLUSIVE),
                event("e3", OutcomeLabel.SUPERSEDED))
        records=tuple(record(f"x{i}",f"e{i}",f"site-{i}") for i in range(1,4))
        report=consolidate_experience(records, FeedbackLedger(events), policy=policy())
        c=report.candidates[0]
        self.assertEqual(c.counts.supported, 1)
        self.assertEqual(c.counts.inconclusive, 1)
        self.assertEqual(c.counts.superseded, 1)
        self.assertEqual(c.status, ConsolidationStatus.INSUFFICIENT_EXPERIENCE)

    def test_contexts_are_not_blended(self):
        events=(event("e1"), event("e2"))
        records=(record("x1","e1","site-a",context="robotic_gi|colorectal"),
                 record("x2","e2","site-b",context="robotic_gi|upper_gi"))
        report=consolidate_experience(records, FeedbackLedger(events), policy=policy())
        self.assertEqual(len(report.candidates), 2)

    def test_different_statements_are_not_semantically_merged(self):
        events=(event("e1"), event("e2"))
        records=(record("x1","e1","site-a",statement="Check perfusion"),
                 record("x2","e2","site-b",statement="Assess blood supply"))
        report=consolidate_experience(records, FeedbackLedger(events), policy=policy())
        self.assertEqual(len(report.candidates), 2)

    def test_missing_outcome_event_excluded(self):
        report=consolidate_experience((record("x1","missing"),), FeedbackLedger())
        self.assertEqual(report.excluded_experiences[0][1], "OUTCOME_EVENT_NOT_FOUND")

    def test_mismatched_outcome_link_excluded(self):
        ev=event("e1", result="r-different")
        rec=record("x1","e1",result="r-expected")
        report=consolidate_experience((rec,), FeedbackLedger((ev,)))
        self.assertEqual(report.excluded_experiences[0][1], "OUTCOME_LINK_MISMATCH")

    def test_optional_result_validation_checks_conclusion(self):
        from engram_erc.contracts import Proposition, ReasoningResult, ReasoningGraph, ReasoningStatus
        result=ReasoningResult("r-e1","req",ReasoningStatus.COMPLETE,("other",),
            (Proposition("other","s","p","v"),),(),ReasoningGraph())
        rec=record("x1","e1",result="r-e1",conclusion="c1")
        ev=event("e1",result="r-e1",conclusion="c1")
        report=consolidate_experience((rec,), FeedbackLedger((ev,)), results=(result,))
        self.assertEqual(report.excluded_experiences[0][1], "CONCLUSION_NOT_IN_RESULT")

    def test_future_experience_excluded(self):
        future=NOW+timedelta(days=1)
        ev=event("e1",at=future)
        rec=record("x1","e1",recorded=future)
        report=consolidate_experience((rec,), FeedbackLedger((ev,)), generated_at=NOW)
        self.assertEqual(report.excluded_experiences[0][1], "FUTURE_DATED")

    def test_duplicate_experience_ids_rejected(self):
        rec=record("x1","e1")
        with self.assertRaises(ValueError):
            consolidate_experience((rec,rec), FeedbackLedger((event("e1"),)))

    def test_review_accepts_for_review_not_authoritative_promotion(self):
        events=(event("e1"), event("e2"))
        records=(record("x1","e1","site-a"), record("x2","e2","site-b"))
        report=consolidate_experience(records, FeedbackLedger(events), policy=policy())
        c=report.candidates[0]
        review=ConsolidationReview(c.candidate_id,
            ConsolidationDisposition.ACCEPT_FOR_KNOWLEDGE_REVIEW,
            "reviewer:1","adjudication:review:1",NOW,"Reviewed for knowledge-base assessment.")
        reviewed=apply_consolidation_reviews(report,ConsolidationReviewLedger((review,)))
        self.assertEqual(reviewed.candidates[0].status, ConsolidationStatus.REVIEWED)
        self.assertIn("does not promote", reviewed.candidates[0].limitations[-1])

    def test_reject_review(self):
        report=consolidate_experience((record("x1","e1"),), FeedbackLedger((event("e1"),)))
        c=report.candidates[0]
        review=ConsolidationReview(c.candidate_id,ConsolidationDisposition.REJECT,
            "reviewer:1","adjudication:2",NOW,"Not sufficiently generalisable.")
        reviewed=apply_consolidation_reviews(report,ConsolidationReviewLedger((review,)))
        self.assertEqual(reviewed.candidates[0].status,ConsolidationStatus.REJECTED)

    def test_unknown_review_candidate_rejected(self):
        report=consolidate_experience((), FeedbackLedger())
        review=ConsolidationReview("unknown",ConsolidationDisposition.REJECT,
            "reviewer:1","adjudication:3",NOW,"Reject.")
        with self.assertRaises(ValueError):
            apply_consolidation_reviews(report,ConsolidationReviewLedger((review,)))

    def test_review_ledger_idempotency_and_collision(self):
        review=ConsolidationReview("c1",ConsolidationDisposition.DEFER,
            "reviewer:1","adjudication:4",NOW,"Wait.")
        ledger=ConsolidationReviewLedger().append(review)
        self.assertIs(ledger.append(review),ledger)
        changed=ConsolidationReview("c1",ConsolidationDisposition.REJECT,
            "reviewer:1","adjudication:4",NOW,"Changed.")
        with self.assertRaises(ValueError):
            ledger.append(changed)

    def test_source_references_are_mandatory(self):
        with self.assertRaises(ValueError):
            ExperienceRecord("x","r","c","e","ctx","task","site","procedure",
                "kind","statement",(),NOW)

    def test_candidate_has_no_probability_claim(self):
        events=(event("e1"), event("e2"))
        records=(record("x1","e1","site-a"), record("x2","e2","site-b"))
        c=consolidate_experience(records, FeedbackLedger(events), policy=policy()).candidates[0]
        self.assertIn("NOT_A_PROBABILITY",c.confidence_label)

if __name__ == "__main__":
    unittest.main()
