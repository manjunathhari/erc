"""B5, Amendment 2 (approved 12 Nov 2026; SHA-256 eeffe7ad745f1bbe5ba42a36f547897a63c59558f5560fe6e721935dba1783a2;
appended beneath the freeze record, claude/erc-b5-freeze-record.md). Criteria A27 and A28.

A27 (A2-1): a rule that declares nothing and a rule that declares never share a conclusion, whichever rule id sorts
first. The plain rule's 0.7.0 duplicate handling is kept for every proposition given to the run and for the conclusions
of other plain rules.

A28 (A2-2): the order of derivations is worked out only for a conclusion that has a choice. A number that is not finite
beneath such a conclusion is refused with one fixed message; anywhere else it changes nothing.

These tests are additions. The tests of the frozen specification and of Amendment 1 are in test_conclusion_time.py and
tests/test_erc_overlay_conclusion_time.py and are not edited; their helpers are borrowed from there.
"""
import itertools
import math

import pytest

from engram_erc import (
    ConclusionTemplate, Evidence, EvidenceLink, EvidenceRelation, Proposition, PropositionKind, PropositionPattern,
    ReasoningRequest, RuleDefinition, RuleSet, SourceKind, TemporalConstraint, TimeInterval as TI, Variable,
    evaluate_conclusions, execute_rules, orchestrate,
)
from engram_erc.tests import test_conclusion_time as b5t
from engram_erc.tests.test_conclusion_time import (
    JOB_19_21, NOT_ESTABLISHED, OK, SINCE_2010, Thought, X, C, Y, K, S, at, b5, job, on, overlaps, place, P,
)

NAN, INF = float("nan"), float("inf")
CITY_PREMISES = (PropositionPattern(X, "works_at", C, name="job"), PropositionPattern(C, "located_in", Y, name="place"))
CITY = ConclusionTemplate(X, "works_in_city", Y)
VISIT_PREMISES = (PropositionPattern(X, "visited", Y, name="visit"),)
WENT = ConclusionTemplate(X, "went_to", Y)
CITY_FACTS = (job(JOB_19_21), place())
VISIT_FACTS = (P("v", "asha", "visited", "delhi", on(2021, 6, 1)),)


def plain(rule_id, premises=CITY_PREMISES, conclusion=CITY):
    """A rule that declares nothing: neither temporal requirements nor a conclusion time."""
    b5()                                             # so that every test here fails by itself before B5 exists
    return RuleDefinition(rule_id, "1", premises, conclusion)


# The declaring rule of each kind, its facts, and what its conclusion must carry: its time, its recorded status, its decision.
DECLARING = {
    "a timeless rule": (
        lambda rid: RuleDefinition(rid, "1", CITY_PREMISES, CITY, conclusion_time=b5().Time("timeless")),
        CITY_PREMISES, CITY, CITY_FACTS, (None, None), "timeless", "accepted"),
    "a rule with requirements only": (
        lambda rid: RuleDefinition(rid, "1", CITY_PREMISES, CITY, temporal=(overlaps("job", "place"),)),
        CITY_PREMISES, CITY, CITY_FACTS, (None, None), "not_established", "provisional"),
    "a rule that takes an event's time": (
        lambda rid: RuleDefinition(rid, "1", VISIT_PREMISES, WENT, conclusion_time=b5().Time("as_premise", ("visit",))),
        VISIT_PREMISES, WENT, VISIT_FACTS, (None, on(2021, 6, 1)), "timed", "accepted"),
    "a rule that takes a state's time": (
        lambda rid: RuleDefinition(rid, "1", CITY_PREMISES, CITY, conclusion_time=b5().Time("as_premise", ("job",))),
        CITY_PREMISES, CITY, CITY_FACTS, (JOB_19_21, None), "timed", "accepted"),
}
ORDERS = {"the plain rule's id sorts first": ("aaa_plain", "zzz_declares"), "the declaring rule's id sorts first": ("zzz_plain", "aaa_declares")}


def statuses(execution):
    return [(entry.rule_id, entry.status) for entry in execution.trace]


@pytest.mark.parametrize("order", sorted(ORDERS))
@pytest.mark.parametrize("kind", sorted(DECLARING))
def test_a27_a_plain_rule_and_a_declaring_rule_give_two_conclusions_each_by_its_own_rule_in_either_order(kind, order):
    make, premises, conclusion, facts, (period, event), status, decision = DECLARING[kind]
    plain_id, declaring_id = ORDERS[order]
    rules = [plain(plain_id, premises, conclusion), make(declaring_id)]
    for listed in (rules, rules[::-1]):                        # the order the rules are handed over in changes nothing
        execution = execute_rules(facts, RuleSet(tuple(listed)))
        derived = [p for p in execution.propositions if p.kind == PropositionKind.INFERENCE]
        # two conclusions, one claim, two ids
        assert len(derived) == 2 and len({p.id for p in derived}) == 2
        assert len({(p.subject, p.predicate, p.object_value, p.polarity) for p in derived}) == 1
        # each has exactly one producing step, and that step is its own rule's
        assert len(execution.inference_steps) == 2
        by_rule = {step.rule_id: step for step in execution.inference_steps}
        assert set(by_rule) == {f"{plain_id}@1", f"{declaring_id}@1"}
        own, other = by_rule[f"{plain_id}@1"], by_rule[f"{declaring_id}@1"]
        assert own.output_proposition_refs != other.output_proposition_refs
        assert {own.output_proposition_refs[0], other.output_proposition_refs[0]} == {p.id for p in derived}
        assert own.input_refs == other.input_refs == tuple(f.id for f in facts)
        # neither match is a no-op, and neither is recorded as an alternative derivation of the other
        assert sorted(statuses(execution)) == sorted([(f"{plain_id}@1", "derived"), (f"{declaring_id}@1", "derived")])
        assert [e.rule_id for e in execution.trace] == sorted(e.rule_id for e in execution.trace)      # rules run in id order
        assert not any(e.status in ("no_op_duplicate_conclusion", "derived_alternative") for e in execution.trace)
        assert {e.explanation_code for e in execution.trace} == {"RULE_PREMISES_MATCHED"}
        assert sorted(e.output_refs for e in execution.trace) == sorted([own.output_proposition_refs, other.output_proposition_refs])
        # the plain rule's conclusion is as in 0.7.0: no time, no status; the declaring rule's carries what it declares
        by_id = {p.id: p for p in derived}
        mine, theirs = by_id[own.output_proposition_refs[0]], by_id[other.output_proposition_refs[0]]
        assert (mine.valid_time, mine.occurred) == (None, None) and "conclusion_time" not in own.parameters
        assert (theirs.valid_time, theirs.occurred) == (period, event)
        assert other.parameters["conclusion_time"]["status"] == status
    # evaluated: each on its own, with one derivation each
    t = Thought(rules, facts)
    rows = {row.steps[0].rule_id: row for row in t.rows}
    assert set(rows) == {f"{plain_id}@1", f"{declaring_id}@1"} and all(len(row.steps) == 1 and row.each == [] for row in t.rows)
    assert (rows[f"{plain_id}@1"].decision, rows[f"{plain_id}@1"].reasons) == ("accepted", OK)
    assert NOT_ESTABLISHED not in rows[f"{plain_id}@1"].e.limitations
    assert rows[f"{declaring_id}@1"].decision == decision
    assert [u.affected_refs for u in t.time_uncertainty] == ([(rows[f"{declaring_id}@1"].p.id,)] if status == "not_established" else [])


@pytest.mark.parametrize("kind", sorted(DECLARING))
def test_a27_the_result_is_the_same_conclusions_whichever_rule_id_sorts_first(kind):
    make, premises, conclusion, facts, *_ = DECLARING[kind]
    seen = []
    for plain_id, declaring_id in ORDERS.values():
        execution = execute_rules(facts, RuleSet((plain(plain_id, premises, conclusion), make(declaring_id))))
        steps = {s.output_proposition_refs[0]: s for s in execution.inference_steps}
        seen.append(sorted(((p.subject, p.predicate, p.object_value, p.polarity, p.valid_time, p.occurred,
                             "plain" if "plain" in steps[p.id].rule_id else "declares",
                             (steps[p.id].parameters.get("conclusion_time") or {}).get("status"))
                            for p in execution.propositions if p.kind == PropositionKind.INFERENCE), key=repr))
    assert seen[0] == seen[1] and len(seen[0]) == 2


@pytest.mark.parametrize("order", sorted(ORDERS))
def test_a27_a_plain_rule_is_still_a_no_op_against_a_stated_proposition_and_a_declaring_rule_still_is_not(order):
    """The 0.7.0 handling, kept: a proposition given to the run with the same claim and the same valid_time makes the
    plain rule's match a recorded no-op. Beside it, the declaring rule's conclusion is neither absorbed nor a duplicate."""
    plain_id, declaring_id = ORDERS[order]
    stated_claim = P("s", "asha", "works_in_city", "blr")
    make = DECLARING["a timeless rule"][0]
    execution = execute_rules(CITY_FACTS + (stated_claim,), RuleSet((plain(plain_id), make(declaring_id))))
    assert sorted(statuses(execution)) == sorted([(plain_id, "no_op_duplicate_conclusion"), (f"{declaring_id}@1", "derived")])
    (no_op,) = [e for e in execution.trace if e.status == "no_op_duplicate_conclusion"]
    assert (no_op.explanation_code, no_op.output_refs, no_op.input_refs) == ("CONCLUSION_ALREADY_PRESENT", ("s",), ("a", "b"))
    (step,) = execution.inference_steps
    assert step.rule_id == f"{declaring_id}@1" and step.output_proposition_refs != ("s",)
    assert [p.id for p in execution.propositions if p.kind == PropositionKind.INFERENCE] == list(step.output_proposition_refs)
    # alone, exactly as before B5
    alone = execute_rules(CITY_FACTS + (stated_claim,), RuleSet((plain(plain_id),)))
    assert statuses(alone) == [(plain_id, "no_op_duplicate_conclusion")] and alone.inference_steps == ()


def test_a27_a_plain_rule_is_still_a_no_op_against_an_inference_given_to_the_run_whatever_its_kind():
    given = Proposition("g", "asha", "works_in_city", "blr", kind=PropositionKind.INFERENCE)
    make = DECLARING["a timeless rule"][0]
    for plain_id, declaring_id in ORDERS.values():
        execution = execute_rules(CITY_FACTS + (given,), RuleSet((plain(plain_id), make(declaring_id))))
        assert sorted(statuses(execution)) == sorted([(plain_id, "no_op_duplicate_conclusion"), (f"{declaring_id}@1", "derived")])
        assert [e.output_refs for e in execution.trace if e.status.startswith("no_op")] == [("g",)]


@pytest.mark.parametrize("declaring_id", ["aaa_declares", "mmm_declares", "zzz_declares"])
def test_a27_two_plain_rules_still_share_one_conclusion_and_a_declaring_rule_beside_them_has_its_own(declaring_id):
    """The second plain rule's match is a no-op against the first plain rule's conclusion, as in 0.7.0, wherever the
    declaring rule's id falls among them; it is never a no-op against the declaring rule's conclusion."""
    make = DECLARING["a timeless rule"][0]
    execution = execute_rules(CITY_FACTS, RuleSet((plain("bbb_plain"), plain("yyy_plain"), make(declaring_id))))
    assert sorted(statuses(execution)) == sorted([("bbb_plain@1", "derived"), ("yyy_plain", "no_op_duplicate_conclusion"),
                                                  (f"{declaring_id}@1", "derived")])
    steps = {s.rule_id: s for s in execution.inference_steps}
    assert set(steps) == {"bbb_plain@1", f"{declaring_id}@1"}
    (no_op,) = [e for e in execution.trace if e.status == "no_op_duplicate_conclusion"]
    assert no_op.output_refs == steps["bbb_plain@1"].output_proposition_refs != steps[f"{declaring_id}@1"].output_proposition_refs
    assert sum(p.kind == PropositionKind.INFERENCE for p in execution.propositions) == 2
    # two plain rules alone: one conclusion, as before
    alone = execute_rules(CITY_FACTS, RuleSet((plain("bbb_plain"), plain("yyy_plain"))))
    assert statuses(alone) == [("bbb_plain@1", "derived"), ("yyy_plain", "no_op_duplicate_conclusion")]


@pytest.mark.parametrize("order", sorted(ORDERS))
def test_a27_each_family_keeps_its_own_handling_of_a_second_match_side_by_side(order):
    """Two employers in one city. The plain rule's second match is a no-op against its own first conclusion (0.7.0). The
    declaring rule's second match is an alternative derivation of its own conclusion (B5-04). Neither crosses over."""
    plain_id, declaring_id = ORDERS[order]
    facts = (job(JOB_19_21, "a1"), place(pid="b1"), job(JOB_19_21, "a2", "apollo"), place(pid="b2", employer="apollo"))
    make = DECLARING["a timeless rule"][0]
    execution = execute_rules(facts, RuleSet((plain(plain_id), make(declaring_id))))
    assert sorted(statuses(execution)) == sorted([(f"{plain_id}@1", "derived"), (plain_id, "no_op_duplicate_conclusion"),
                                                  (f"{declaring_id}@1", "derived"), (f"{declaring_id}@1", "derived_alternative")])
    produced = {}
    for step in execution.inference_steps:
        produced.setdefault(step.output_proposition_refs[0], []).append(step.rule_id)
    assert sorted(produced.values()) == sorted([[f"{plain_id}@1"], [f"{declaring_id}@1"] * 2])
    (plain_conclusion,) = [ref for ref, rules in produced.items() if rules == [f"{plain_id}@1"]]
    (declared_conclusion,) = [ref for ref, rules in produced.items() if len(rules) == 2]
    by_status = {e.status: e for e in execution.trace if e.status in ("no_op_duplicate_conclusion", "derived_alternative")}
    assert by_status["no_op_duplicate_conclusion"].output_refs == (plain_conclusion,)
    assert by_status["derived_alternative"].output_refs == (declared_conclusion,)
    t = Thought([plain(plain_id), make(declaring_id)], facts)
    assert sorted(len(row.e.derivations) for row in t.rows) == [0, 2] and [row.decision for row in t.rows] == ["accepted"] * 2


# --------------------------------------------------------------------------
# A28: non-finite numbers and the order of derivations
# --------------------------------------------------------------------------

def message(conclusion_id, proposition_id):
    return (f"Alternative derivations of conclusion {conclusion_id} cannot be ordered: "
            f"proposition {proposition_id} holds a number that is not finite.")


def evaluate(rules, facts, supported=None):
    """orchestrate, then evaluate with every fact supported (or those named). Returns the run and the report."""
    facts = tuple(facts)
    evidence, links = b5t.backing([f.id for f in facts] if supported is None else supported)
    run = orchestrate(ReasoningRequest("q", "state_question", facts, evidence, links, as_of=at(2024, 6, 1)), ruleset=RuleSet(tuple(rules)))
    return run, lambda: evaluate_conclusions(run.result, evidence=evidence, evidence_links=links)


def timeless_city():
    return RuleDefinition("city", "1", CITY_PREMISES, CITY, conclusion_time=b5().Time("timeless"))


def fond():
    return plain("fond", (PropositionPattern(X, "likes", Y, name="likes"),), ConclusionTemplate(X, "is_fond_of", Y))


def fond_declared():
    return RuleDefinition("fond", "1", (PropositionPattern(X, "likes", Y, name="likes"),), ConclusionTemplate(X, "is_fond_of", Y),
                          conclusion_time=b5().Time("timeless"))


TWO_EMPLOYERS = (job(None, "a1"), place(None, "b1"), job(None, "a2", "apollo"), place(None, "b2", "apollo"))
NOT_FINITE = {   # where the number sits in a stated proposition
    "NaN, a qualifier": dict(qualifiers={"score": NAN}),
    "infinity, a qualifier": dict(qualifiers={"score": INF}),
    "minus infinity, a qualifier": dict(qualifiers={"score": -INF}),
    "NaN, nested in a mapping in the qualifiers": dict(qualifiers={"measure": {"unit": "kg", "value": NAN}}),
    "infinity, nested in a list in a mapping in the qualifiers": dict(qualifiers={"measure": {"values": [1, 2.5, {"deep": INF}]}}),
    "minus infinity, nested in a list in the qualifiers": dict(qualifiers={"values": [0, [1, [-INF]]]}),
    "NaN, the object itself": dict(obj=NAN),
    "infinity, nested in a mapping in the object": dict(obj={"amount": {"value": INF, "unit": "ml"}}),
    "minus infinity, nested in a list in the object": dict(obj=["a", [1, {"x": [-INF]}]]),
}
FINITE = {   # nothing here is a number that is not finite
    "ordinary numbers": dict(qualifiers={"score": 1.5, "count": 3, "flag": True, "nothing": None}),
    "the words NaN and Infinity as text": dict(qualifiers={"score": "NaN", "other": "Infinity"}, obj="inf"),
    "nested ordinary values": dict(obj={"amount": {"value": 2.0, "parts": [1, 2, {"x": 0.0}]}}),
    "a very large finite number": dict(qualifiers={"score": 1.7976931348623157e308}),
}


def liking(pid="u", subject="ravi", obj="tea", qualifiers=None):
    return Proposition(pid, subject, "likes", obj, qualifiers=qualifiers or {})


@pytest.mark.parametrize("where", sorted(NOT_FINITE))
@pytest.mark.parametrize("other_rule", ["a plain rule", "a declaring rule"])
def test_a28a_a_conclusion_with_one_derivation_is_evaluated_as_before_whatever_else_the_result_holds(where, other_rule):
    """One conclusion has two derivations. An unrelated conclusion has one, and rests on a fact holding a number that is
    not finite. Both evaluate; the unrelated one exactly as it does in a result that has no alternatives at all."""
    unrelated = liking(**NOT_FINITE[where])
    other = fond() if other_rule == "a plain rule" else fond_declared()
    run, report = evaluate([timeless_city(), other], TWO_EMPLOYERS + (unrelated,))
    assert len(run.result.inference_steps) == 3                              # two for the city, one for the unrelated conclusion
    evaluations = {e.conclusion_id: e for e in report().evaluations}
    by_predicate = {p.predicate: evaluations[p.id] for p in run.result.propositions if p.id in evaluations}
    assert by_predicate["works_in_city"].decision.value == "accepted" and len(by_predicate["works_in_city"].derivations) == 2
    assert by_predicate["is_fond_of"].decision.value == "accepted" and by_predicate["is_fond_of"].derivations == ()
    # the same conclusion, in a result with nothing else in it: the same evaluation, field for field
    alone_run, alone_report = evaluate([other], (unrelated,))
    (alone,) = alone_report().evaluations
    assert alone == by_predicate["is_fond_of"] and alone.conclusion_id == by_predicate["is_fond_of"].conclusion_id
    # a fact that holds such a number and lies beneath no conclusion at all changes nothing either
    stray = Proposition("stray", "ravi", "weighs", "unknown", qualifiers={"kg": NAN})
    run, report = evaluate([timeless_city()], TWO_EMPLOYERS + (stray,))
    assert [e.decision.value for e in report().evaluations] == ["accepted"]


def any_source():
    return RuleDefinition("any", "1", (PropositionPattern(S, "src", K, name="src"),), ConclusionTemplate("thing", "holds", "yes"),
                          conclusion_time=b5().Time("timeless"))


def source(pid, obj="a", qualifiers=None):
    return Proposition(pid, "s", "src", obj, qualifiers=qualifiers or {})


@pytest.mark.parametrize("where", sorted(NOT_FINITE))
def test_a28b_a_number_that_is_not_finite_beneath_a_conclusion_that_has_a_choice_is_refused_with_the_fixed_message(where):
    bad = source("bad", **NOT_FINITE[where])
    for facts in ((source("good", "g"), bad), (bad, source("good", "g"))):
        run, report = evaluate([any_source()], facts)
        (conclusion,) = run.result.conclusion_refs
        assert len(run.result.inference_steps) == 2                           # the run itself is not affected
        with pytest.raises(ValueError) as raised:
            report()
        assert str(raised.value) == message(conclusion, "bad")
    # the run and the engine alone raise nothing
    assert len(execute_rules(facts, RuleSet((any_source(),))).inference_steps) == 2


def test_a28b_of_several_offending_propositions_the_one_whose_id_sorts_first_is_named():
    ids = ["p9", "p10", "p2", "q1", "P5"]                                  # as text: "P5" < "p10" < "p2" < "p9" < "q1"
    assert sorted(ids)[0] == "P5" and sorted(ids[:4])[0] == "p10"
    for chosen in (ids, ids[:4], ["p9", "q1"], ["q1"]):
        for arrangement in itertools.islice(itertools.permutations(chosen), 6):
            facts = [source("ok1", "fine"), source("ok2", "also fine")]
            facts += [source(pid, f"value {pid}", qualifiers={"n": [1, {"x": NAN if n % 2 else INF}]}) for n, pid in enumerate(arrangement)]
            run, report = evaluate([any_source()], facts)
            (conclusion,) = run.result.conclusion_refs
            with pytest.raises(ValueError) as raised:
                report()
            assert str(raised.value) == message(conclusion, sorted(chosen)[0])


def test_a28b_the_number_is_found_beneath_a_derived_proposition_too_and_the_conclusion_named_is_the_one_being_evaluated():
    """Three levels: two ways to each of d1 and d2, joined into final. The offending fact lies beneath d1 and beneath
    final, which both have a choice, and not beneath d2, which evaluates."""
    rules = b5t.nested_rules()
    facts = [Proposition(f"s{side}_{i}", "x", f"src{side}", f"k{i}", valid_time=JOB_19_21) for side in (1, 2) for i in range(2)]
    facts[1] = Proposition("s1_1", "x", "src1", "k1", valid_time=JOB_19_21, qualifiers={"reading": {"values": [1.0, INF]}})
    run, report = evaluate(rules, facts)
    by_predicate = {p.predicate: p.id for p in run.result.propositions if p.kind == PropositionKind.INFERENCE}
    with pytest.raises(ValueError) as raised:
        report()
    affected = [ref for ref in run.result.conclusion_refs if ref in (by_predicate["d1"], by_predicate["final"])]
    assert str(raised.value) == message(affected[0], "s1_1")
    # d2 alone, from the same facts: it has a choice of two, nothing offending beneath it, and it evaluates
    d2_rule = rules[1]
    run, report = evaluate([d2_rule], facts)
    (evaluation,) = report().evaluations
    assert evaluation.decision.value == "accepted" and len(evaluation.derivations) == 2


@pytest.mark.parametrize("where", sorted(NOT_FINITE))
def test_a28c_with_no_alternatives_such_a_number_raises_nothing_for_a_plain_rule_or_a_declaring_rule(where):
    fact = liking(**NOT_FINITE[where])
    decisions = []
    for rule in (fond(), fond_declared()):
        run, report = evaluate([rule], (fact,))
        (evaluation,) = report().evaluations
        assert evaluation.decision.value == "accepted" and evaluation.derivations == ()
        decisions.append((evaluation.decision, evaluation.reasons, evaluation.premise_coverage.leaf_premise_ids))
    assert decisions[0] == decisions[1]
    # and unsupported: withheld, as any unsupported conclusion is
    run, report = evaluate([fond()], (fact,), supported=[])
    assert [e.decision.value for e in report().evaluations] == ["withheld"]


@pytest.mark.parametrize("what", sorted(FINITE))
def test_a28_values_that_are_finite_or_are_not_numbers_are_ordered_as_any_other(what):
    spec = FINITE[what]
    facts = (source("one", "first"), source("two", spec.get("obj", "second"), spec.get("qualifiers")))
    run, report = evaluate([any_source()], facts)
    (evaluation,) = report().evaluations
    assert evaluation.decision.value == "accepted" and len(evaluation.derivations) == 2
    listed = [b5t.canonical({f.id: f for f in facts}[d.leaf_premise_ids[0]]) for d in evaluation.derivations]
    assert listed == sorted(listed)
    assert not any(isinstance(v, float) and not math.isfinite(v) for v in (spec.get("qualifiers") or {}).values())
