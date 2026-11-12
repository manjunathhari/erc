"""B5 through the adapter (specification frozen 12 Nov 2026, Draft 1.4 revision 2, SHA-256
ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581; section B5-08 as extended by Amendment 1, criterion
A17): explain() prints one
`time:` line under each conclusion of a rule that declares, and the other derivations of a conclusion that has several.
Only erc_overlay/reasoner.py changes; erc_overlay/knowledge.py and tests/test_erc_overlay.py are not edited.

Every shape the adapter can actually send is tested through the adapter and Engram, with the normal fact lines. The
others hand explain() a Reasoning built from ERC propositions directly, so that every boundary wording the contract allows
can be reached; explain() reads nothing else. Made-up people only.
"""
import datetime as dt

import pytest

from engram_erc import (
    ConclusionTemplate, DecisionPolicy, Evidence, EvidenceLink, EvidenceRelation, Occurrence, Proposition,
    PropositionPattern, ReasoningRequest, RuleDefinition, RuleSet, SourceKind, TemporalConstraint, TimeInterval as TI,
    Variable, evaluate_conclusions, orchestrate,
)
from engram_erc.orchestration import OrchestrationLimits
from erc_overlay import Reasoner
from erc_overlay.knowledge import AdaptedRequest
from erc_overlay.reasoner import Reasoning

from test_erc_overlay import AS_OF, CITY, world  # noqa: F401  (world is a fixture)

UTC = dt.timezone.utc
US = dt.timedelta(microseconds=1)
X, C, Y, K = Variable("x"), Variable("c"), Variable("y"), Variable("k")
Q = {"status": "active", "validation_status": "accepted", "source_type": "explicit", "start_basis": "stated", "end_basis": "stated"}
WHY = {"no_conclusion_time_declared": "the rule declares temporal requirements but not the time of its conclusion",
       "premise_carries_no_time": "job carries no time", "premise_time_unknown": "the time of job is not known"}


def at(year, month=1, day=1):
    return dt.datetime(year, month, day, tzinfo=UTC)


def last(year, month, day):
    return at(year, month, day) + dt.timedelta(days=1) - US


SINCE_2010 = TI(at(2010), end_unbounded=True)
JOB_19_21 = TI(at(2019), at(2021))


def conclusion_time(kind, *names):
    from engram_erc import ConclusionTime
    return ConclusionTime(kind, names)


def city(temporal="declared", time="while_all"):
    if temporal == "declared":
        temporal = (TemporalConstraint("overlaps", "job", "place"),)
    if time == "while_all":
        time = conclusion_time("while_all", "job", "place")
    return RuleDefinition("works_in_city", "1",
                          (PropositionPattern(X, "works_at", C, name="job"), PropositionPattern(C, "located_in", Y, name="place")),
                          ConclusionTemplate(X, "works_in_city", Y), temporal=temporal, conclusion_time=time)


def visit_rule():
    return RuleDefinition("visit", "1", (PropositionPattern(X, "visited", Y, name="visit"), PropositionPattern(X, "works_at", C, name="job")),
                          ConclusionTemplate(X, "visited_as_employee_of", C), temporal=(TemporalConstraint("during", "visit", "job"),),
                          conclusion_time=conclusion_time("as_premise", "visit"))


def moved_rule():
    return RuleDefinition("moved", "1", (PropositionPattern(X, "left_job", Y, name="left"), PropositionPattern(X, "works_at", C, name="next")),
                          ConclusionTemplate(X, "moved_on_to", C), temporal=(TemporalConstraint("before", "left", "next"),),
                          conclusion_time=conclusion_time("as_premise", "next"))


FIRST_SAID = {**Q, "start_basis": "first_said"}


def P(pid, subject, predicate, obj, time=None, polarity=True, q=Q):
    return Proposition(pid, subject, predicate, obj, polarity=polarity, qualifiers=q,
                       valid_time=time if isinstance(time, TI) else None, occurred=time if isinstance(time, Occurrence) else None)


def job(time, pid="a", employer="manipal", q=Q):
    return P(pid, "asha", "works_at", employer, time, q=q)


def place(time=SINCE_2010, pid="b", employer="manipal", q=Q):
    return P(pid, employer, "located_in", "blr", time, q=q)


def explained(world, rules, props, supported=None, list_facts=True):
    """explain() over a request made of the given propositions, as if the adapter had sent them. `list_facts=False`
    leaves the `fact:` lines out, for the few shapes the adapter never sends and the existing fact lines (not changed
    by B5) cannot print; the lines under the conclusion are explained from the result all the same."""
    props = tuple(props)
    ids = [p.id for p in props] if supported is None else supported
    evidence = tuple(Evidence(f"e:{i}", f"src:{i}", SourceKind.USER_PROVIDED) for i in ids)
    links = tuple(EvidenceLink(f"e:{i}", i, EvidenceRelation.SUPPORTS) for i in ids)
    request = ReasoningRequest("q", "state_question", props, evidence, links, as_of=AS_OF)
    run = orchestrate(request, ruleset=RuleSet(tuple(rules)), limits=OrchestrationLimits())
    report = evaluate_conclusions(run.result, evidence=evidence, evidence_links=links, policy=DecisionPolicy())
    shown = request if list_facts else ReasoningRequest("q", "state_question", (), as_of=AS_OF)
    return Reasoner(world.kb).explain(Reasoning(AdaptedRequest(shown, frozenset(), (), (), "UTC"), run, report))


def conclusion_blocks(lines):
    """For each `conclusion:` line, the lines that follow it up to the next line that is not indented."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("conclusion:"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("  "):
                j += 1
            out.append(lines[i + 1:j])
            i = j
        else:
            i += 1
    return out


WORDING = {   # the rule, the facts, the one line added under the conclusion
    "exact start, exact end": (
        city, [job(JOB_19_21), place()],
        "  time: holds from 2019-01-01 to 2021-01-01 (end exclusive); while job and place all hold, rule works_in_city@1"),
    "start within, end within": (
        city, [job(TI(at(2021), at(2024), start_latest=last(2021, 3, 31), end_earliest=at(2023, 1, 2))), place(TI(at(2021, 2, 1), end_unbounded=True))],
        "  time: holds from between 2021-02-01 and 2021-03-31 to between 2023-01-02 and 2024-01-01 (end exclusive); "
        "while job and place all hold, rule works_in_city@1"),
    "start no later than, still going": (
        city, [job(TI(start_latest=last(2024, 3, 5), end_unbounded=True), q=FIRST_SAID), place(TI(start_latest=last(2020, 1, 1), end_unbounded=True), q=FIRST_SAID)],
        "  time: holds from no later than 2024-03-05 still going; while job and place all hold, rule works_in_city@1"),
    "no stated beginning, exact end": (
        city, [job(TI(start_unbounded=True, end=at(2021))), place(TI(start_unbounded=True, end_unbounded=True))],
        "  time: holds with no stated beginning to 2021-01-01 (end exclusive); while job and place all hold, rule works_in_city@1"),
    "exact start, end no earlier than (facts not listed)": (
        city, [job(TI(at(2019), end_earliest=at(2021))), place()],
        "  time: holds from 2019-01-01 to no earlier than 2021-01-01 (end exclusive); while job and place all hold, rule works_in_city@1"),
    "exact start, still going": (
        city, [job(TI(at(2021), start_latest=last(2021, 12, 31), end_unbounded=True)), place(TI(at(2022), end_unbounded=True))],
        "  time: holds from 2022-01-01 still going; while job and place all hold, rule works_in_city@1"),
    "start no earlier than, end no later than": (
        lambda: city(None, conclusion_time("as_premise", "job")),
        [job(TI(at(2019), at(2024, 3, 6), start_is_lower_bound=True, end_is_upper_bound=True), q={**Q, "end_basis": "closed"}), place()],
        "  time: holds from no earlier than 2019-01-01 to no later than 2024-03-06 (end exclusive); the time of job, rule works_in_city@1"),
    "start not known, exact end": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(TI(None, at(2021))), place()],
        "  time: holds start not known to 2021-01-01 (end exclusive); the time of job, rule works_in_city@1"),
    "start not known, still going": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(TI(end_unbounded=True)), place()],
        "  time: holds start not known still going; the time of job, rule works_in_city@1"),
    "no stated beginning, still going": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(TI(start_unbounded=True, end_unbounded=True)), place()],
        "  time: holds with no stated beginning still going; the time of job, rule works_in_city@1"),
    "exact start, end not known (facts not listed)": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(TI(at(2019))), place()],
        "  time: holds from 2019-01-01 end not known; the time of job, rule works_in_city@1"),
    "no stated beginning, end not known (facts not listed)": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(TI(start_unbounded=True)), place()],
        "  time: holds with no stated beginning end not known; the time of job, rule works_in_city@1"),
    "the time of a state": (
        moved_rule, [P("l", "asha", "left_job", "apollo", Occurrence(at(2021, 3, 10), last(2021, 3, 10))), job(TI(at(2022, 2, 1), end_unbounded=True), "n")],
        "  time: holds from 2022-02-01 still going; the time of next, rule moved@1"),
    "an event on a day": (
        visit_rule, [P("v", "asha", "visited", "delhi", Occurrence(at(2021, 6, 1), last(2021, 6, 1))), job(TI(at(2019), at(2022)), "j")],
        "  time: event on 2021-06-01; the time of visit, rule visit@1"),
    "an event between two days": (
        visit_rule, [P("v", "asha", "visited", "delhi", Occurrence(at(2021, 3, 1), last(2021, 9, 30))), job(TI(at(2019), at(2022)), "j")],
        "  time: event between 2021-03-01 and 2021-09-30; the time of visit, rule visit@1"),
    "an event by a day": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(Occurrence(None, last(2024, 3, 5)), q=FIRST_SAID), place()],
        "  time: event by 2024-03-05; the time of job, rule works_in_city@1"),
    "an event no earlier than a day (facts not listed)": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(Occurrence(at(2021, 6, 1), None)), place()],
        "  time: event no earlier than 2021-06-01; the time of job, rule works_in_city@1"),
    "timeless": (
        lambda: city(None, conclusion_time("timeless")), [job(JOB_19_21), place()],
        "  time: timeless (declared by rule works_in_city@1)"),
    "not established, no declaration": (
        lambda: city(time=None), [job(JOB_19_21), place()], f"  time: not established ({WHY['no_conclusion_time_declared']})"),
    "not established, the premise carries no time": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(None), place()], f"  time: not established ({WHY['premise_carries_no_time']})"),
    "not established, the premise's time is unknown (facts not listed)": (
        lambda: city(None, conclusion_time("as_premise", "job")), [job(TI()), place()], f"  time: not established ({WHY['premise_time_unknown']})"),
}


@pytest.mark.parametrize("case", sorted(WORDING))
def test_b5_a17_explain_prints_exactly_the_specified_time_line_under_the_conclusion(world, case):
    rule, facts, line = WORDING[case]
    lines = explained(world, [rule()], facts, list_facts="facts not listed" not in case)
    (block,) = conclusion_blocks(lines)
    assert block[0] == line and block[1].startswith("  because:")
    assert [l for l in block if l.startswith("  time:")] == [line]              # one line, and only under the conclusion
    assert sum(l.startswith("  time: timeless") for l in lines) == (case == "timeless")
    assert not any(l.startswith("  also derived") or l.startswith("  further derivations") for l in lines)
    # every other line is what the same facts give under a rule that declares nothing, where that rule fires alike
    if case in ("exact start, exact end", "timeless"):
        plain = explained(world, [RuleDefinition("works_in_city", "1", city().premises, city().conclusion)], facts)
        assert conclusion_blocks(plain)[0][0].startswith("  because:")           # no line is added for a rule that declares nothing
        assert [l for l in lines if l != line] == plain


def test_b5_a17_a_boundary_that_is_not_known_is_never_printed_as_one_that_is_unbounded(world):
    """Amendment 1. A side of which nothing is stated and a side that is explicitly without a boundary are different facts
    and get different words, on both sides, whatever the other side is."""
    rule = lambda: city(None, conclusion_time("as_premise", "job"))
    def line(time):
        (block,) = conclusion_blocks(explained(world, [rule()], [job(time), place()], list_facts=False))
        return block[0]
    unknown_start, unbounded_start = line(TI(None, at(2021))), line(TI(start_unbounded=True, end=at(2021)))
    assert "start not known" in unknown_start and "no stated beginning" not in unknown_start
    assert "with no stated beginning" in unbounded_start and "not known" not in unbounded_start
    unknown_end, unbounded_end = line(TI(at(2019))), line(TI(at(2019), end_unbounded=True))
    assert unknown_end.startswith("  time: holds from 2019-01-01 end not known;") and "still going" not in unknown_end
    assert unbounded_end.startswith("  time: holds from 2019-01-01 still going;") and "not known" not in unbounded_end
    assert "(end exclusive)" not in unknown_end and "(end exclusive)" not in unbounded_end      # no end day is printed in either
    both = line(TI(start_unbounded=True, end_unbounded=True))
    assert both == "  time: holds with no stated beginning still going; the time of job, rule works_in_city@1"


def test_b5_a17_three_named_premises_are_joined_with_and(world):
    rule = RuleDefinition("all_three", "1", (PropositionPattern(X, "p1", Y, name="one"), PropositionPattern(X, "p2", Y, name="two"),
                                             PropositionPattern(X, "p3", Y, name="three")), ConclusionTemplate(X, "all", Y),
                          temporal=tuple(TemporalConstraint("overlaps", a, b) for a, b in (("one", "two"), ("one", "three"), ("two", "three"))),
                          conclusion_time=conclusion_time("while_all", "one", "two", "three"))
    facts = [P("p1", "s", "p1", "o", TI(at(2018), at(2022))), P("p2", "s", "p2", "o", JOB_19_21), P("p3", "s", "p3", "o", SINCE_2010)]
    (block,) = conclusion_blocks(explained(world, [rule], facts))
    assert block[0] == "  time: holds from 2019-01-01 to 2021-01-01 (end exclusive); while one and two and three all hold, rule all_three@1"


@pytest.mark.parametrize("supported,decision,other", [(None, "accepted", "accepted"), (["a1", "b1"], "accepted", "withheld"),
                                                      (["a1", "b2"], "withheld", "withheld")])
def test_b5_a17_the_other_derivations_of_a_conclusion_are_listed_after_the_chosen_ones_facts(world, supported, decision, other):
    facts = [job(JOB_19_21, "a1"), place(pid="b1"), job(JOB_19_21, "a2", "apollo"), place(pid="b2", employer="apollo")]
    lines = explained(world, [city()], facts, supported)
    (block,) = conclusion_blocks(lines)
    conclusion = next(l for l in lines if l.startswith("conclusion:"))
    assert conclusion.startswith(f"conclusion: asha works_in_city blr -> {decision} (")
    assert block[0] == "  time: holds from 2019-01-01 to 2021-01-01 (end exclusive); while job and place all hold, rule works_in_city@1"
    because = [l for l in block if l.startswith("  because:")]
    (also,) = [l for l in block if l.startswith("  also derived")]
    assert block[-1] == also and len(because) == 2                               # after the `because:` lines of the chosen derivation
    head, claims = also.split(" from: ")
    assert head == f"  also derived by rule works_in_city@1 ({other})"
    chosen = {l[len("  because: "):] for l in because}
    listed = set(claims.split("; "))
    both = {"asha works_at manipal", "manipal located_in blr"}, {"asha works_at apollo", "apollo located_in blr"}
    assert {frozenset(chosen), frozenset(listed)} == {frozenset(both[0]), frozenset(both[1])}
    assert "works_in_city" not in claims                                         # the conclusion's claim is not repeated
    if supported == ["a1", "b1"]:
        assert chosen == both[0]                                                 # the supported derivation is the one chosen


def test_b5_a17_derivations_left_out_by_the_limit_are_said_to_be_left_out(world):
    one = lambda source, out: RuleDefinition(f"r_{out}", "1", (PropositionPattern(X, source, K, name="src"),),
                                             ConclusionTemplate(X, out, "yes"), conclusion_time=conclusion_time("as_premise", "src"))
    join = RuleDefinition("r_join", "1", (PropositionPattern(X, "d1", "yes", name="one"), PropositionPattern(X, "d2", "yes", name="two")),
                          ConclusionTemplate(X, "final", "yes"), temporal=(TemporalConstraint("overlaps", "one", "two"),),
                          conclusion_time=conclusion_time("while_all", "one", "two"))
    facts = [P(f"s{side}_{i}", "x", f"src{side}", f"k{i}", JOB_19_21) for side in (1, 2) for i in range(9)]
    lines = explained(world, [one("src1", "d1"), one("src2", "d2"), join], facts, supported=[])
    blocks = dict(zip([l.split(" -> ")[0] for l in lines if l.startswith("conclusion:")], conclusion_blocks(lines)))
    final = blocks["conclusion: x final yes"]
    assert final[-1] == "  further derivations were not examined (limit 64)"
    also = [l for l in final if l.startswith("  also derived")]
    assert len(also) == 63 and set(l.split(" from: ")[0] for l in also) == {"  also derived by rule r_join@1 (withheld)"}
    assert all(len(l.split(" from: ")[1].split("; ")) == 2 for l in also)
    nine = blocks["conclusion: x d1 yes"]                                         # nine derivations, all examined
    assert len([l for l in nine if l.startswith("  also derived by rule r_d1@1 (withheld) from: x src1 k")]) == 8
    assert not any(l.startswith("  further derivations") for l in nine)


def declared(time):
    return RuleSet((city(time=time),))


def test_b5_a17_through_engram_a_timed_conclusion_prints_its_period(world):
    """Asha's job is stated from the year 2021, Manipal's place from 2010: the adapter sends the year as a window, and the
    conclusion holds from somewhere in that window, still going."""
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb)
    run = r.reason("Asha", ruleset=declared(conclusion_time("while_all", "job", "place")), as_of=AS_OF)
    assert run.evaluation.overall_decision.value == "accepted"
    lines = r.explain(run)
    (block,) = conclusion_blocks(lines)
    assert block[0] == ("  time: holds from between 2021-01-01 and 2021-12-31 still going; "
                        "while job and place all hold, rule works_in_city@1")
    plain = r.explain(r.reason("Asha", ruleset=CITY, as_of=AS_OF))
    assert [l for l in lines if l != block[0]] == plain and not any(l.startswith("  time: holds") for l in plain)


def test_b5_a17_through_engram_a_time_that_is_not_established_is_printed_as_such_and_reported(world):
    world.who("Manipal")
    world.obs("Asha", "works_at", "Manipal", valid_from="2021")
    world.obs("Manipal", "located_in", "Bengaluru", valid_from="2010")
    r = Reasoner(world.kb)
    run = r.reason("Asha", ruleset=declared(None), as_of=AS_OF)
    assert run.evaluation.overall_decision.value == "provisional"
    lines = r.explain(run)
    (block,) = conclusion_blocks(lines)
    assert block[0] == f"  time: not established ({WHY['no_conclusion_time_declared']})"
    assert next(l for l in lines if l.startswith("conclusion:")).endswith("-> provisional (CONCLUSION_TIME_NOT_ESTABLISHED)")
    assert lines.count("uncertain: Conclusion of rule works_in_city@1: the time for which it holds is not established "
                       f"({WHY['no_conclusion_time_declared']}).") == 1
    assert not any("timeless" in l for l in lines)


def one_fact(predicate, conclusion, name):
    """The conclusion takes the time of the one fact it rests on: whatever shape the adapter sent, explain() must word it."""
    return RuleSet((RuleDefinition("copied", "1", (PropositionPattern(X, predicate, C, name=name),), ConclusionTemplate(X, conclusion, C),
                                   conclusion_time=conclusion_time("as_premise", name)),))


def _closing_date_only_said(w):
    w.obs("Asha", "works_at", "Apollo", valid_from="2019")
    w.obs("Asha", "left_job", "Apollo")                              # said on 5 March 2024, no stated date


def _unreadable(w, text):
    w.m.open_chat("1:00 pm on 5 March, 2024"); sid = w.m.add("Asha", text, date="sometime"); w.m.close_chat(write_note=False)
    return sid


THROUGH_ENGRAM = {   # what Engram holds, the fact's predicate, the asked-at day, the line under the conclusion
    "a start stated to the year, still going": (
        lambda w: w.obs("Asha", "works_at", "Apollo", valid_from="2021"), "works_at", AS_OF,
        "  time: holds from between 2021-01-01 and 2021-12-31 still going; the time of job, rule copied@1"),
    "a start stated to the day, an end stated to the day": (
        lambda w: w.obs("Asha", "works_at", "Apollo", valid_from="2019-05-01", valid_to="2021-03-15"), "works_at", at(2020),
        "  time: holds from 2019-05-01 to 2021-03-16 (end exclusive); the time of job, rule copied@1"),
    "an end stated to the month": (
        lambda w: w.obs("Asha", "works_at", "Apollo", valid_from="2019", valid_to="2021-03"), "works_at", at(2020),
        "  time: holds from between 2019-01-01 and 2019-12-31 to between 2021-03-02 and 2021-04-01 (end exclusive); the time of job, rule copied@1"),
    "a start that was only first said": (
        lambda w: w.obs("Asha", "works_at", "Apollo"), "works_at", AS_OF,
        "  time: holds from no later than 2024-03-05 still going; the time of job, rule copied@1"),
    "a closing date that was only said": (
        _closing_date_only_said, "works_at", at(2023),
        "  time: holds from between 2019-01-01 and 2019-12-31 to no later than 2024-03-06 (end exclusive); the time of job, rule copied@1"),
    "an end with no start": (
        lambda w: w.obs("Asha", "works_at", "Apollo", valid_to="2021", sid=_unreadable(w, "Asha works_at Apollo.")), "works_at", at(2020),
        "  time: holds start not known to between 2021-01-02 and 2022-01-01 (end exclusive); the time of job, rule copied@1"),
    "an event stated to the day": (
        lambda w: w.obs("Asha", "started_job", "Apollo", valid_from="2021-06-01"), "started_job", AS_OF,
        "  time: event on 2021-06-01; the time of job, rule copied@1"),
    "an event stated to the year": (
        lambda w: w.obs("Asha", "started_job", "Apollo", valid_from="2021"), "started_job", AS_OF,
        "  time: event between 2021-01-01 and 2021-12-31; the time of job, rule copied@1"),
    "an event that was only said": (
        lambda w: w.obs("Asha", "started_job", "Apollo"), "started_job", AS_OF,
        "  time: event by 2024-03-05; the time of job, rule copied@1"),
}


@pytest.mark.parametrize("case", sorted(THROUGH_ENGRAM))
def test_b5_a17_through_engram_every_shape_the_adapter_sends_is_worded_with_the_fact_lines_beside_it(world, case):
    build, predicate, as_of, line = THROUGH_ENGRAM[case]
    build(world)
    r = Reasoner(world.kb)
    run = r.reason("Asha", ruleset=one_fact(predicate, "employment", "job"), as_of=as_of)
    (conclusion,) = [p for p in run.result.propositions if p.predicate == "employment"]
    (fact,) = [p for p in run.adapted.request.propositions if p.predicate == predicate]
    assert (conclusion.valid_time, conclusion.occurred) == (fact.valid_time, fact.occurred)     # copied, field for field
    lines = r.explain(run)
    (block,) = conclusion_blocks(lines)
    assert block[0] == line and block[1].startswith("  because:")
    # the normal fact lines are all there: the fact is listed with its own state and time lines
    assert sum(l.startswith(f"fact: Asha {predicate} Apollo; state:") for l in lines) == 1
    assert sum(l.startswith("  time: ") for l in lines) == 1 + len(run.adapted.request.propositions)
