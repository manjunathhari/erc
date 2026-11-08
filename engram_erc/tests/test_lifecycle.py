import unittest
from datetime import datetime, timezone

from engram_erc.feedback import FeedbackLedger, OutcomeEvent, OutcomeLabel
from engram_erc.consolidation import (
    ExperienceRecord, ConsolidationPolicy, ConsolidationDisposition,
    ConsolidationReview, ConsolidationReviewLedger, consolidate_experience,
    apply_consolidation_reviews,
)
from engram_erc.lifecycle import (
    KnowledgeStage, EvidenceRelation, EvidenceClass, LifecycleAction,
    EvidenceLinkRecord, ExternalValidationRecord, PromotionPolicy,
    assess_promotion, LifecycleEvent, KnowledgeLifecycleLedger,
    build_lifecycle_event,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)


def reviewed_candidate():
    events = tuple(OutcomeEvent(f"e{i}", f"r{i}", "c1", OutcomeLabel.VERIFIED_SUPPORTED,
        NOW, f"adj:{i}", "robotic_gi") for i in range(2))
    records = tuple(ExperienceRecord(f"x{i}", f"r{i}", "c1", f"e{i}", "ctx:colorectal",
        "robotic_gi", f"site-{i}", "low_anterior_resection", "technical_observation",
        "Check perfusion before anastomosis", (f"registry:{i}",), NOW) for i in range(2))
    report = consolidate_experience(records, FeedbackLedger(events),
        policy=ConsolidationPolicy(min_adjudicated_cases=2, min_distinct_sites=2))
    c = report.candidates[0]
    review = ConsolidationReview(c.candidate_id, ConsolidationDisposition.ACCEPT_FOR_KNOWLEDGE_REVIEW,
        "reviewer:senior", "adjudication:review-1", NOW, "Accepted for knowledge review")
    return apply_consolidation_reviews(report, ConsolidationReviewLedger((review,))).candidates[0]


def evidence(candidate, ref="paper:1", relation=EvidenceRelation.SUPPORTS, independent=True, ctx="ctx:colorectal"):
    return EvidenceLinkRecord(ref, relation, EvidenceClass.SYSTEMATIC_REVIEW, "source:"+ref,
        candidate.candidate_id, ctx, NOW, independent, ("population differs",))


def validation(candidate, ref, site, passed=True):
    return ExternalValidationRecord(ref, "cohort:"+ref, site, candidate.context_key,
        "result:"+ref, "adjudication:"+ref, NOW, passed)


class LifecycleTests(unittest.TestCase):
    def test_candidate_must_be_reviewed_before_assessment_eligible(self):
        c = reviewed_candidate()
        e = evidence(c)
        report = assess_promotion(c, evidence=(e,))
        self.assertTrue(report.eligible)
        self.assertEqual(report.proposed_stage, KnowledgeStage.EVIDENCE_CORROBORATED)

    def test_unreviewed_candidate_blocked(self):
        c = reviewed_candidate()
        from dataclasses import replace
        c = replace(c, status=__import__('engram_erc.consolidation', fromlist=['ConsolidationStatus']).ConsolidationStatus.CANDIDATE)
        report = assess_promotion(c, evidence=(evidence(c),))
        self.assertIn("CANDIDATE_NOT_ACCEPTED_FOR_KNOWLEDGE_REVIEW", report.blockers)

    def test_contradictory_evidence_blocks_promotion(self):
        c = reviewed_candidate()
        report = assess_promotion(c, evidence=(evidence(c), evidence(c,"paper:2",EvidenceRelation.CONTRADICTS)))
        self.assertFalse(report.eligible)
        self.assertIn("CONTRADICTORY_EVIDENCE_REQUIRES_EXPERT_RESOLUTION", report.blockers)

    def test_context_mismatch_does_not_corroborate(self):
        c = reviewed_candidate()
        report = assess_promotion(c, evidence=(evidence(c,ctx="ctx:upper_gi"),))
        self.assertIn("NO_LINKED_SUPPORTING_EVIDENCE", report.blockers)

    def test_surgical_experience_not_independent_evidence(self):
        c = reviewed_candidate()
        e = EvidenceLinkRecord("experience:1", EvidenceRelation.SUPPORTS,
            EvidenceClass.PRACTITIONER_EXPERIENCE, "registry:1", c.candidate_id,
            c.context_key, NOW, False)
        report = assess_promotion(c, evidence=(e,))
        self.assertIn("NO_INDEPENDENT_EVIDENCE_CORROBORATION", report.blockers)

    def test_external_validation_requires_distinct_sites(self):
        c = reviewed_candidate()
        report = assess_promotion(c, evidence=(evidence(c),),
            external_validations=(validation(c,"v1","site-x"),))
        self.assertEqual(report.proposed_stage, KnowledgeStage.EVIDENCE_CORROBORATED)
        report2 = assess_promotion(c, evidence=(evidence(c),),
            external_validations=(validation(c,"v1","site-x"),validation(c,"v2","site-y")))
        self.assertEqual(report2.proposed_stage, KnowledgeStage.EXTERNALLY_VALIDATED)

    def test_failed_external_validation_is_visible_and_blocks(self):
        c = reviewed_candidate()
        report = assess_promotion(c, evidence=(evidence(c),),
            external_validations=(validation(c,"v1","site-x",False),))
        self.assertIn("FAILED_EXTERNAL_VALIDATION_PRESENT", report.blockers)

    def test_full_human_governed_lifecycle(self):
        c = reviewed_candidate()
        ev = (evidence(c),)
        vals = (validation(c,"v1","site-x"), validation(c,"v2","site-y"))
        assessment = assess_promotion(c, evidence=ev, external_validations=vals)
        ledger = KnowledgeLifecycleLedger()
        e1 = build_lifecycle_event(event_id="l1",candidate_id=c.candidate_id,
            action=LifecycleAction.ADVANCE,current_stage=KnowledgeStage.EXPERIENCE_CANDIDATE,
            reviewer_ref="reviewer:1",adjudication_ref="adj:1",rationale="Expert review complete",occurred_at=NOW)
        ledger = ledger.append(e1)
        for idx, stage in enumerate((KnowledgeStage.EXPERT_REVIEWED,
            KnowledgeStage.EVIDENCE_CORROBORATED, KnowledgeStage.EXTERNALLY_VALIDATED), start=2):
            event = build_lifecycle_event(event_id=f"l{idx}",candidate_id=c.candidate_id,
                action=LifecycleAction.ADVANCE,current_stage=stage,reviewer_ref="reviewer:1",
                adjudication_ref=f"adj:{idx}",rationale="Gate reviewed",occurred_at=NOW,
                assessment=assessment)
            ledger = ledger.append(event)
        self.assertEqual(ledger.current_stage(c.candidate_id), KnowledgeStage.PRACTICE_ELIGIBLE)
        self.assertEqual(len(ledger.events), 4)

    def test_advance_requires_assessment_after_expert_review(self):
        c = reviewed_candidate()
        with self.assertRaises(ValueError):
            build_lifecycle_event(event_id="l",candidate_id=c.candidate_id,
                action=LifecycleAction.ADVANCE,current_stage=KnowledgeStage.EXPERT_REVIEWED,
                reviewer_ref="r",adjudication_ref="a",rationale="advance",occurred_at=NOW)

    def test_lifecycle_append_idempotent_and_collision_rejected(self):
        c = reviewed_candidate()
        e = build_lifecycle_event(event_id="l1",candidate_id=c.candidate_id,
            action=LifecycleAction.ADVANCE,current_stage=KnowledgeStage.EXPERIENCE_CANDIDATE,
            reviewer_ref="r",adjudication_ref="a",rationale="review",occurred_at=NOW)
        ledger = KnowledgeLifecycleLedger().append(e)
        self.assertIs(ledger.append(e), ledger)
        changed = LifecycleEvent("l1",c.candidate_id,LifecycleAction.REJECT,
            KnowledgeStage.EXPERIENCE_CANDIDATE,KnowledgeStage.REJECTED,"r","a","reject",NOW)
        with self.assertRaises(ValueError): ledger.append(changed)

    def test_invalid_transition_rejected(self):
        c = reviewed_candidate()
        with self.assertRaises(ValueError):
            event = LifecycleEvent("l",c.candidate_id,LifecycleAction.ADVANCE,
                KnowledgeStage.EXPERIENCE_CANDIDATE,KnowledgeStage.PRACTICE_ELIGIBLE,
                "r","a","skip gates",NOW)
            KnowledgeLifecycleLedger((event,))

    def test_terminal_state_cannot_be_reopened(self):
        c = reviewed_candidate()
        reject = LifecycleEvent("l1",c.candidate_id,LifecycleAction.REJECT,
            KnowledgeStage.EXPERIENCE_CANDIDATE,KnowledgeStage.REJECTED,"r","a","reject",NOW)
        reopen = LifecycleEvent("l2",c.candidate_id,LifecycleAction.ADVANCE,
            KnowledgeStage.REJECTED,KnowledgeStage.EXPERT_REVIEWED,"r","a2","reopen",NOW)
        with self.assertRaises(ValueError): KnowledgeLifecycleLedger((reject,reopen))

    def test_supersede_requires_replacement_reference(self):
        with self.assertRaises(ValueError):
            LifecycleEvent("l","c",LifecycleAction.SUPERSEDE,KnowledgeStage.EXPERIENCE_CANDIDATE,
                KnowledgeStage.SUPERSEDED,"r","a","supersede",NOW)

    def test_cannot_bypass_evidence_refs_with_direct_event(self):
        with self.assertRaises(ValueError):
            LifecycleEvent("l","c",LifecycleAction.ADVANCE,KnowledgeStage.EXPERT_REVIEWED,
                KnowledgeStage.EVIDENCE_CORROBORATED,"r","a","skip evidence",NOW)

    def test_cannot_bypass_external_validation_refs_with_direct_event(self):
        with self.assertRaises(ValueError):
            LifecycleEvent("l","c",LifecycleAction.ADVANCE,KnowledgeStage.EVIDENCE_CORROBORATED,
                KnowledgeStage.EXTERNALLY_VALIDATED,"r","a","skip validation",NOW,
                evidence_refs=("paper:1",))

if __name__ == "__main__": unittest.main()
