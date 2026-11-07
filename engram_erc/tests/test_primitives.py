import unittest
from datetime import datetime, timezone

from engram_erc import (
    Evidence, EvidenceKind, EvidenceLink, EvidenceRelation, Proposition,
    ReasoningGraphBuilder, ReasoningGraphView, SourceKind, TimeInterval,
    ComparisonKind, TemporalRelation, ContradictionCertainty,
    EvidenceAssessmentStatus, compare_propositions, find_contradictions,
    assess_evidence,
)


def dt(day):
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def prop(pid, *, subject="patient_1", predicate="has_fever", obj=True,
         polarity=True, start=1, end=10):
    interval = None if start is None and end is None else TimeInterval(
        dt(start) if start is not None else None,
        dt(end) if end is not None else None,
    )
    return Proposition(pid, subject, predicate, obj, polarity=polarity,
                       valid_time=interval)


def ev(eid, reliability=None):
    return Evidence(
        eid, f"source:{eid}", SourceKind.REGISTRY, EvidenceKind.OBSERVATION,
        reliability_score=reliability,
        reliability_method="adjudicated rubric v1" if reliability is not None else None,
    )


def make_view(propositions, evidence_links, evidence_items):
    b = ReasoningGraphBuilder()
    for p in propositions:
        b.add_proposition(p)
    for e in evidence_items:
        b.add_evidence(e)
    for link in evidence_links:
        b.link_evidence(link)
    return ReasoningGraphView(b.build(), b.propositions, b.evidence, b.inference_steps)


class ComparisonTests(unittest.TestCase):
    def test_same_claim(self):
        a, b = prop("a"), prop("b")
        result = compare_propositions(a, b)
        self.assertEqual(result.kind, ComparisonKind.SAME_CLAIM)
        self.assertEqual(result.temporal_relation, TemporalRelation.OVERLAP)

    def test_different_subject_not_compared_as_contradiction(self):
        a, b = prop("a"), prop("b", subject="patient_2", polarity=False)
        self.assertEqual(compare_propositions(a, b).kind, ComparisonKind.DIFFERENT_SUBJECT)
        self.assertEqual(find_contradictions([a, b]), ())

    def test_temporal_disjointness(self):
        a = prop("a", start=1, end=5)
        b = prop("b", polarity=False, start=5, end=10)
        self.assertEqual(compare_propositions(a, b).temporal_relation, TemporalRelation.DISJOINT)
        self.assertEqual(find_contradictions([a, b]), ())

    def test_unknown_temporal_scope_is_not_assumed_to_overlap(self):
        a = prop("a", start=None, end=None)
        b = prop("b", polarity=False, start=1, end=10)
        result = compare_propositions(a, b)
        self.assertEqual(result.temporal_relation, TemporalRelation.UNKNOWN)
        contradictions = find_contradictions([a, b])
        self.assertEqual(contradictions[0].certainty, ContradictionCertainty.POTENTIAL)


class ContradictionTests(unittest.TestCase):
    def test_opposite_polarity_overlapping_period_is_definite(self):
        found = find_contradictions([prop("a"), prop("b", polarity=False)])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].certainty, ContradictionCertainty.DEFINITE)

    def test_different_values_need_declared_functional_predicate(self):
        a = prop("a", predicate="blood_group", obj="A")
        b = prop("b", predicate="blood_group", obj="B")
        self.assertEqual(find_contradictions([a, b]), ())
        found = find_contradictions([a, b], functional_predicates=frozenset({"blood_group"}))
        self.assertEqual(found[0].reason_code, "MUTUALLY_EXCLUSIVE_FUNCTIONAL_VALUES")

    def test_different_values_of_nonfunctional_predicate_are_not_contradiction(self):
        a = prop("a", predicate="symptom", obj="fever")
        b = prop("b", predicate="symptom", obj="pain")
        self.assertEqual(find_contradictions([a, b]), ())


class EvidenceAssessmentTests(unittest.TestCase):
    def test_supporting_evidence(self):
        p = prop("p")
        view = make_view(
            [p], [EvidenceLink("e1", "p", EvidenceRelation.SUPPORTS)], [ev("e1", 0.8)]
        )
        result = assess_evidence(view, "p")
        self.assertEqual(result.status, EvidenceAssessmentStatus.SUPPORTED)
        self.assertEqual(result.reliability_scores_present, 1)

    def test_conflict_is_preserved_not_resolved(self):
        p = prop("p")
        links = [
            EvidenceLink("e1", "p", EvidenceRelation.SUPPORTS),
            EvidenceLink("e2", "p", EvidenceRelation.CONTRADICTS),
        ]
        view = make_view([p], links, [ev("e1"), ev("e2")])
        result = assess_evidence(view, "p")
        self.assertEqual(result.status, EvidenceAssessmentStatus.CONFLICT)
        self.assertIn("CONFLICT_RETAINED_NO_AUTOMATIC_ADJUDICATION", result.limitations)

    def test_no_evidence_does_not_mean_false(self):
        view = make_view([prop("p")], [], [])
        result = assess_evidence(view, "p")
        self.assertEqual(result.status, EvidenceAssessmentStatus.NO_LINKED_EVIDENCE)
        self.assertIn("NO_LINKED_EVIDENCE_DOES_NOT_ESTABLISH_FALSEHOOD", result.limitations)

    def test_qualifying_only_is_not_support(self):
        p = prop("p")
        view = make_view(
            [p], [EvidenceLink("e1", "p", EvidenceRelation.QUALIFIES)], [ev("e1")]
        )
        self.assertEqual(assess_evidence(view, "p").status, EvidenceAssessmentStatus.QUALIFIED)


if __name__ == "__main__":
    unittest.main()
