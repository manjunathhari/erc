from datetime import datetime, timedelta, timezone
import pytest
from engram_erc.prospective_learning import (
    ProspectiveCase, ProspectiveEvent, ProspectiveEventKind as K, ProspectiveLearningLedger,
)
from engram_erc.temporal_patterns import EpisodeOutcome
from engram_erc.longitudinal_learning import (
    LongitudinalObservation, LongitudinalPolicy, analyze_longitudinal_learning,
)
from engram_erc.lifecycle import EvidenceClass, EvidenceRelation
from engram_erc.knowledge_synthesis import (
    LocalSignal, PopulationApplicability, SynthesisStatus, PracticeDisposition,
    ReviewDecision, LocalPracticeClaim, ExternalEvidence, SynthesisPolicy,
    synthesize_practice_intelligence, PracticeReview, PracticeReviewLedger,
    build_practice_review,
)

T = datetime(2026, 1, 1, tzinfo=timezone.utc)

def case(ref, site, outcome=EpisodeOutcome.IMPROVED):
    c = ProspectiveCase(ref, f"result:{ref}", "procedure:colectomy", "context:postop:v1",
                        "postop_review", site, T, (f"registry:{ref}",))
    ledger = ProspectiveLearningLedger().open_case(c)
    def ev(suffix, kind, mins, **kw):
        return ProspectiveEvent(f"{ref}:{suffix}", ref, kind, T + timedelta(minutes=mins),
                                "actor:reviewer", (f"source:{ref}:{suffix}",), **kw)
    ledger = ledger.append(ev("d", K.DECISION_RECORDED, 1, related_refs=(f"decision:{ref}",)))
    ledger = ledger.append(ev("a", K.ACTION_RECORDED, 2, related_refs=(f"action:{ref}",)))
    ledger = ledger.append(ev("f", K.FOLLOW_UP_RECORDED, 60, related_refs=(f"followup:{ref}",)))
    ledger = ledger.append(ev("o", K.OUTCOME_ADJUDICATED, 1440, adjudication_ref=f"adj:{ref}", case_outcome=outcome))
    ledger = ledger.append(ev("close", K.CASE_CLOSED, 1500))
    row = LongitudinalObservation(ref, "procedure:colectomy", "context:postop:v1", site,
        ("signal", "review", "reassessment"), ("early_review", "repeat_assessment"),
        outcome, T + timedelta(minutes=1440), f"adj:{ref}", (f"source:{ref}:o",),
        practitioner_ref=f"surgeon:{site}")
    return ledger, row

def merge(*pairs):
    return ProspectiveLearningLedger(tuple(c for l, _ in pairs for c in l.cases),
        tuple(e for l, _ in pairs for e in l.events))

def setup(n=5):
    pairs = [case(f"case:{i}", f"site:{i%2+1}", EpisodeOutcome.IMPROVED if i < n-1 else EpisodeOutcome.ADVERSE_EVENT) for i in range(n)]
    registry = merge(*pairs)
    lr = analyze_longitudinal_learning([x[1] for x in pairs], registry,
        generated_at=T + timedelta(days=40),
        policy=LongitudinalPolicy(minimum_cases_for_pattern=3, minimum_sites_for_cross_site=2,
                                  minimum_cases_for_outcome_summary=3))
    p = lr.patterns[0]
    a = lr.action_outcome_summaries[0]
    claim = LocalPracticeClaim("claim:1", p.pattern_id, a.action_pattern,
        "Early review followed by repeat assessment was observed in this trajectory.",
        LocalSignal.SUPPORTS, p.adjudication_refs, p.source_refs, "reviewer:1", p.context_key, p.activity_ref)
    return lr, claim

def evidence(claim, relation=EvidenceRelation.SUPPORTS, population=PopulationApplicability.MATCH, ref="paper:1", **kw):
    return ExternalEvidence(ref, claim.claim_ref, relation, EvidenceClass.SYSTEMATIC_REVIEW,
        f"source:{ref}", f"appraisal:{ref}", claim.activity_ref, claim.context_key,
        claim.action_pattern, population, True, T - timedelta(days=100), "postoperative_outcome", (), **kw)

def run(lr, claim, evidences=(), policy=SynthesisPolicy()):
    return synthesize_practice_intelligence(lr, [claim], evidences,
        generated_at=T + timedelta(days=40), policy=policy).items[0]

def test_concordant_independent_matching_evidence_becomes_review_candidate():
    lr, claim = setup()
    item = run(lr, claim, [evidence(claim)])
    assert item.synthesis_status == SynthesisStatus.CONCORDANT
    assert item.disposition == PracticeDisposition.EXPERT_REVIEW_CANDIDATE

def test_conflicting_external_evidence_is_conflicted():
    lr, claim = setup()
    item = run(lr, claim, [evidence(claim), evidence(claim, EvidenceRelation.CONTRADICTS, ref="paper:2")])
    assert item.synthesis_status == SynthesisStatus.CONFLICTED
    assert item.disposition == PracticeDisposition.CONFLICT_REVIEW_REQUIRED

def test_discordant_local_and_external_signal_requires_conflict_review():
    lr, claim = setup()
    opposing = LocalPracticeClaim(claim.claim_ref, claim.pattern_id, claim.action_pattern,
        claim.learning_statement, LocalSignal.CONTRADICTS, claim.adjudication_refs,
        claim.source_refs, claim.reviewer_ref, claim.context_key, claim.activity_ref)
    item = run(lr, opposing, [evidence(opposing)])
    assert item.synthesis_status == SynthesisStatus.DISCORDANT
    assert item.disposition == PracticeDisposition.CONFLICT_REVIEW_REQUIRED

def test_partial_population_evidence_cannot_establish_concordance_by_default():
    lr, claim = setup()
    item = run(lr, claim, [evidence(claim, population=PopulationApplicability.PARTIAL)])
    assert item.synthesis_status == SynthesisStatus.INCOMPARABLE
    assert item.disposition == PracticeDisposition.INSUFFICIENT_BASIS

def test_mismatched_context_evidence_excluded():
    lr, claim = setup()
    bad = ExternalEvidence("paper:x", claim.claim_ref, EvidenceRelation.SUPPORTS,
        EvidenceClass.PUBLISHED_STUDY, "src:x", "app:x", claim.activity_ref,
        "different-context", claim.action_pattern, PopulationApplicability.MATCH, True)
    report = synthesize_practice_intelligence(lr, [claim], [bad], generated_at=T + timedelta(days=40))
    assert report.excluded_evidence_refs == ("paper:x",)
    assert report.items[0].synthesis_status == SynthesisStatus.LOCAL_SIGNAL_ONLY

def test_local_experience_only_is_not_promoted():
    lr, claim = setup()
    item = run(lr, claim)
    assert item.synthesis_status == SynthesisStatus.LOCAL_SIGNAL_ONLY
    assert item.disposition == PracticeDisposition.NO_CHANGE

def test_insufficient_local_action_sample_withholds_synthesis():
    lr, claim = setup()
    item = run(lr, claim, [evidence(claim)], SynthesisPolicy(minimum_local_cases=99))
    assert item.synthesis_status == SynthesisStatus.INSUFFICIENT_LOCAL_EXPERIENCE
    assert item.disposition == PracticeDisposition.INSUFFICIENT_BASIS

def test_non_independent_or_experience_evidence_excluded():
    lr, claim = setup()
    bad = ExternalEvidence("experience:1", claim.claim_ref, EvidenceRelation.SUPPORTS,
        EvidenceClass.PRACTITIONER_EXPERIENCE, "src:1", "app:1", claim.activity_ref,
        claim.context_key, claim.action_pattern, PopulationApplicability.MATCH, False)
    report = synthesize_practice_intelligence(lr, [claim], [bad], generated_at=T + timedelta(days=40))
    assert report.excluded_evidence_refs == ("experience:1",)

def test_future_publication_date_excluded():
    lr, claim = setup()
    future = evidence(claim, ref="paper:future")
    future = ExternalEvidence(future.evidence_ref, future.claim_ref, future.relation, future.evidence_class,
        future.source_ref, future.appraisal_ref, future.activity_ref, future.context_key,
        future.action_pattern, future.population_applicability, future.independent_of_local_records,
        T + timedelta(days=100))
    report = synthesize_practice_intelligence(lr, [claim], [future], generated_at=T + timedelta(days=40))
    assert report.excluded_evidence_refs == ("paper:future",)

def test_claim_must_reference_pattern_adjudication_and_source():
    lr, claim = setup()
    bad = LocalPracticeClaim(claim.claim_ref, claim.pattern_id, claim.action_pattern,
        claim.learning_statement, claim.local_signal, ("unknown:adj",), claim.source_refs,
        claim.reviewer_ref, claim.context_key, claim.activity_ref)
    with pytest.raises(ValueError, match="adjudication references"):
        run(lr, bad, [evidence(bad)])

def test_review_ledger_is_append_only_idempotent_and_collision_safe():
    lr, claim = setup()
    report = synthesize_practice_intelligence(lr, [claim], [evidence(claim)], generated_at=T + timedelta(days=40))
    review = build_practice_review(report, review_id="review:1", claim_ref=claim.claim_ref,
        decision=ReviewDecision.ACCEPT_FOR_PRACTICE_REVIEW, reviewer_ref="expert:1",
        adjudication_ref="review-adj:1", rationale="Proceed to multidisciplinary practice review.",
        reviewed_at=T + timedelta(days=41))
    ledger = PracticeReviewLedger().append(review)
    assert ledger.append(review) == ledger
    altered = PracticeReview("review:1", claim.claim_ref, ReviewDecision.DEFER, "expert:1",
        "review-adj:1", "changed", T + timedelta(days=41))
    with pytest.raises(ValueError, match="collision"):
        ledger.append(altered)

def test_review_requires_known_claim_and_explicit_rationale():
    lr, claim = setup()
    report = synthesize_practice_intelligence(lr, [claim], [], generated_at=T + timedelta(days=40))
    with pytest.raises(ValueError, match="unknown claim"):
        build_practice_review(report, review_id="r", claim_ref="missing", decision=ReviewDecision.DEFER,
            reviewer_ref="expert", adjudication_ref="adj", rationale="defer", reviewed_at=T)
    with pytest.raises(ValueError):
        PracticeReview("r", claim.claim_ref, ReviewDecision.DEFER, "expert", "adj", " ", T)

def test_duplicate_claims_and_evidence_refs_rejected():
    lr, claim = setup()
    with pytest.raises(ValueError, match="claim_ref"):
        synthesize_practice_intelligence(lr, [claim, claim], [], generated_at=T + timedelta(days=40))
    ev = evidence(claim)
    with pytest.raises(ValueError, match="evidence_ref"):
        synthesize_practice_intelligence(lr, [claim], [ev, ev], generated_at=T + timedelta(days=40))
