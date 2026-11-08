import unittest
from datetime import datetime, timezone, timedelta
from engram_erc.contracts import Proposition, Evidence, EvidenceLink, EvidenceKind, SourceKind, EvidenceRelation, TimeInterval
from engram_erc.failure_analysis import (
    AttributionStatus, FailureCategory, FailureCaseAnalysis, FailureSymptom,
    RootCauseAttribution,
)
from engram_erc.inference import ExecutionLimits
from engram_erc.rules import RuleSet, RuleDefinition, PropositionPattern, ConclusionTemplate
from engram_erc.recovery import (
    GuardKind, GuardStatus, RecoveryPolicy, RecoveryRequest, RecoveryStatus,
    run_guarded_recovery,
)

def history(category, status=AttributionStatus.CONFIRMED_BY_ADJUDICATOR):
    attr = RootCauseAttribution(category, status, 1, 1, 0, ("p0",),
        ("adjudication:1",) if status == AttributionStatus.CONFIRMED_BY_ADJUDICATOR else (),
        ("reviewed",), "test")
    return (FailureCaseAnalysis("old", "old-result", "p1", "outcome",
        FailureSymptom.INCORRECT_CONCLUSION, ("p0",), (attr,), False, (), "robotic_gi"),)

def base_request(**kw):
    p = Proposition("p0", "case", "finding", "present")
    rule = RuleDefinition("r1", "1", (PropositionPattern("case", "finding", "present"),),
        ConclusionTemplate("case", "assessment", "review"))
    values = dict(case_id="new-case", context_key="robotic_gi",
        propositions=(p,), ruleset=RuleSet((rule,)))
    values.update(kw)
    return RecoveryRequest(**values)

class RecoveryTests(unittest.TestCase):
    def test_no_history_executes_but_requires_review(self):
        r = run_guarded_recovery(base_request(), ())
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)
        self.assertIsNotNone(r.execution)
        self.assertTrue(any(g.status == GuardStatus.NOT_TRIGGERED for g in r.guards))

    def test_confirmed_premise_failure_blocks_without_ack(self):
        r = run_guarded_recovery(base_request(), history(FailureCategory.PREMISE_EXTRACTION_ERROR))
        self.assertEqual(r.status, RecoveryStatus.BLOCKED)
        self.assertIsNone(r.execution)

    def test_premise_ack_allows_execution(self):
        req = base_request(acknowledged_controls=(GuardKind.PREMISE_EXTRACTION_ACK,))
        r = run_guarded_recovery(req, history(FailureCategory.PREMISE_EXTRACTION_ERROR))
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)

    def test_missing_evidence_blocks(self):
        req = base_request(required_evidence_proposition_refs=("p0",))
        r = run_guarded_recovery(req, history(FailureCategory.MISSING_KNOWLEDGE_OR_EVIDENCE))
        self.assertEqual(r.status, RecoveryStatus.BLOCKED)
        self.assertIn("p0", r.guards[0].related_refs)

    def test_linked_evidence_passes_evidence_guard(self):
        ev = Evidence("e1", "registry:row:1", SourceKind.REGISTRY, EvidenceKind.STRUCTURED_RECORD)
        req = base_request(evidence=(ev,), evidence_links=(EvidenceLink("e1","p0",EvidenceRelation.SUPPORTS),),
            required_evidence_proposition_refs=("p0",))
        r = run_guarded_recovery(req, history(FailureCategory.MISSING_KNOWLEDGE_OR_EVIDENCE))
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)
        self.assertEqual(r.guards[0].status, GuardStatus.PASS)

    def test_missed_definite_contradiction_blocks(self):
        interval = TimeInterval(datetime(2026,1,1,tzinfo=timezone.utc),
                                datetime(2027,1,1,tzinfo=timezone.utc))
        p1 = Proposition("p1", "case", "finding", "present", True, valid_time=interval)
        p2 = Proposition("p2", "case", "finding", "present", False, valid_time=interval)
        req = base_request(propositions=(p1,p2))
        r = run_guarded_recovery(req, history(FailureCategory.MISSED_CONTRADICTION))
        self.assertEqual(r.status, RecoveryStatus.BLOCKED)

    def test_potential_contradiction_does_not_block_by_default(self):
        p1 = Proposition("p1", "case", "finding", "present", True)
        p2 = Proposition("p2", "case", "finding", "present", False)
        req = base_request(propositions=(p1,p2))
        r = run_guarded_recovery(req, history(FailureCategory.MISSED_CONTRADICTION))
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)

    def test_temporal_guard_requires_as_of(self):
        p = Proposition("p0", "case", "finding", "present",
            valid_time=TimeInterval())
        req = base_request(propositions=(p,))
        r = run_guarded_recovery(req, history(FailureCategory.TEMPORAL_REASONING_ERROR))
        self.assertEqual(r.status, RecoveryStatus.BLOCKED)

    def test_temporal_guard_with_as_of_still_requires_review(self):
        p = Proposition("p0", "case", "finding", "present", valid_time=TimeInterval())
        req = base_request(propositions=(p,), as_of=datetime(2026, 11, 7, tzinfo=timezone.utc))
        r = run_guarded_recovery(req, history(FailureCategory.TEMPORAL_REASONING_ERROR))
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)
        self.assertEqual(r.guards[0].status, GuardStatus.REVIEW_REQUIRED)

    def test_failure_history_from_other_context_does_not_trigger(self):
        other = (FailureCaseAnalysis("old", "old-result", "p1", "outcome",
            FailureSymptom.INCORRECT_CONCLUSION, ("p0",),
            history(FailureCategory.RULE_APPLICATION_ERROR)[0].attributions,
            False, (), "upper_gi"),)
        r = run_guarded_recovery(base_request(), other)
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)
        self.assertEqual(r.triggered_categories, ())

    def test_supported_hypothesis_ignored_by_default(self):
        r = run_guarded_recovery(base_request(),
            history(FailureCategory.RULE_APPLICATION_ERROR, AttributionStatus.SUPPORTED_HYPOTHESIS))
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)

    def test_supported_hypothesis_can_be_enabled(self):
        r = run_guarded_recovery(base_request(),
            history(FailureCategory.RULE_APPLICATION_ERROR, AttributionStatus.SUPPORTED_HYPOTHESIS),
            policy=RecoveryPolicy(use_supported_hypotheses=True))
        self.assertEqual(r.status, RecoveryStatus.BLOCKED)

    def test_rule_and_context_acknowledgements_are_independent(self):
        req = base_request(acknowledged_controls=(GuardKind.RULE_APPLICATION_ACK,))
        r = run_guarded_recovery(req, history(FailureCategory.RULE_APPLICATION_ERROR))
        self.assertEqual(r.status, RecoveryStatus.EXECUTED_REVIEW_REQUIRED)

    def test_recovery_never_claims_auto_acceptance(self):
        r = run_guarded_recovery(base_request(), ())
        self.assertTrue(any("requires external review" in item for item in r.limitations))

    def test_naive_as_of_datetime_rejected(self):
        p = Proposition("p0", "case", "finding", "present", valid_time=TimeInterval())
        with self.assertRaises(ValueError):
            base_request(propositions=(p,), as_of=datetime(2026, 11, 7))

    def test_duplicate_acknowledgements_rejected(self):
        with self.assertRaises(ValueError):
            base_request(acknowledged_controls=(GuardKind.RULE_APPLICATION_ACK,)*2)

    def test_duplicate_required_refs_rejected(self):
        with self.assertRaises(ValueError):
            base_request(required_evidence_proposition_refs=("p0","p0"))

if __name__ == "__main__":
    unittest.main()
