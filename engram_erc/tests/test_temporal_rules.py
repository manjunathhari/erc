"""B4 - Rule temporal requirements (ERC 0.7.0).

A rule may declare the temporal relationship it needs between named premises: `overlaps`, `before`, `during`. For each
match ERC answers established, disproved or indeterminate, and only an established match fires. A rule that declares
nothing behaves exactly as it did. B4 gives no conclusion a time (B5) and does not read `as_of` (B6).

Specification: claude/erc-b4-spec.md, frozen 11 Nov 2026, SHA-256 bea15c132a9f2eb02b665277f1cf087a549da375306f6028f7bd824d001b3f07.
Test names carry that document's acceptance criteria (A1 .. A21, section 8); scenario numbers are its section 6.
A7's recording of the existing suite and A16 (the unedited adapter tests, the recorded four) are checks run on the whole
suite and are reported with the build; the adapter half of A9 is in tests/test_erc_overlay_temporal_rules.py.

Everything B4 adds is reached through `b4()`, at call time, so that every test in this file fails by itself until B4 is
implemented. A test that says "this stays as it is" also builds something only B4 allows, for the same reason.
"""
import datetime as dt
import functools
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

import engram_erc
from engram_erc import (
    ConclusionTemplate, Evidence, EvidenceLink, EvidenceRelation, Occurrence, Proposition, PropositionKind,
    PropositionPattern, ReasoningRequest, ReasoningStatus, RuleDefinition, RuleSet, SourceKind, TimeInterval as TI,
    TraceEntry, UncertaintyKind, Variable, evaluate_conclusions, execute_rules, match_rule, orchestrate,
)
from engram_erc.inference import ExecutionLimits
from engram_erc.orchestration import OrchestrationLimits
from engram_erc.primitives.comparison import TemporalRelation, _temporal_relation
from engram_erc.tests import test_domain_profiles as pins

UTC = dt.timezone.utc
US = dt.timedelta(microseconds=1)
PKG = Path(engram_erc.__file__).parent
EST, DIS, IND = "established", "disproved", "indeterminate"
HINT = "Supply the missing or more precise times for the named premises."


def b4():
    """What B4 adds. Imported when called, never at module level."""
    from engram_erc import rules
    from engram_erc import temporal_requirements as tr
    return SimpleNamespace(check=tr.check_temporal_requirements, Outcome=tr.TemporalOutcome, Check=tr.TemporalCheck,
                           Constraint=rules.TemporalConstraint, Kind=rules.TemporalRequirementKind)


def at(year, month=1, day=1):
    return dt.datetime(year, month, day, tzinfo=UTC)


def last(year, month=None, day=None):
    """The last instant of a year, or of a day."""
    return (at(year + 1) if month is None else at(year, month, day) + dt.timedelta(days=1)) - US


def year(y):
    return Occurrence(at(y), last(y))


def on(*date):
    return Occurrence(at(*date), at(*date))


# --------------------------------------------------------------------------
# Rules and runs used throughout
# --------------------------------------------------------------------------

A, B, C3, X, C, Y = (Variable(n) for n in ("a", "b", "c3", "x", "c", "y"))


def pair_rule(*constraints, names=("left", "right"), rule_id="pair", **kw):
    """Two independent premises, `left_of` and `right_of`, named; the conclusion relates their subjects."""
    return RuleDefinition(rule_id, "1",
                          (PropositionPattern(A, "left_of", Variable("p"), name=names[0]),
                           PropositionPattern(B, "right_of", Variable("q"), name=names[1])),
                          ConclusionTemplate(A, "related_to", B),
                          temporal=tuple(b4().Constraint(*c) for c in constraints), **kw)


def triple_rule(*constraints):
    return RuleDefinition("triple", "1",
                          (PropositionPattern(A, "left_of", Variable("p"), name="one"),
                           PropositionPattern(B, "right_of", Variable("q"), name="two"),
                           PropositionPattern(C3, "third_of", Variable("r"), name="three")),
                          ConclusionTemplate(A, "related_to", B),
                          temporal=tuple(b4().Constraint(*c) for c in constraints))


def city(temporal="declared", version="1"):
    """works_at(X, C) and located_in(C, Y) give works_in_city(X, Y). `declared`: the two must hold at the same time."""
    if temporal == "declared":
        temporal = (b4().Constraint("overlaps", "job", "place"),)
    return RuleDefinition("works_in_city", version,
                          (PropositionPattern(X, "works_at", C, name="job"), PropositionPattern(C, "located_in", Y, name="place")),
                          ConclusionTemplate(X, "works_in_city", Y), temporal=temporal)


def prop(pid, predicate, time=None, *, subject=None, obj=None, kind=PropositionKind.ASSERTION, qualifiers=None):
    return Proposition(pid, subject or f"s:{pid}", predicate, obj or f"o:{pid}", kind=kind, qualifiers=qualifiers or {},
                       valid_time=time if isinstance(time, TI) else None, occurred=time if isinstance(time, Occurrence) else None)


def left(time, pid="l", **kw):
    return prop(pid, "left_of", time, **kw)


def right(time, pid="r", **kw):
    return prop(pid, "right_of", time, **kw)


def job(time, pid="a", **kw):
    return prop(pid, "works_at", time, subject="asha", obj="manipal", **kw)


def place(time, pid="b", **kw):
    return prop(pid, "located_in", time, subject="manipal", obj="blr", **kw)


def execute(rules, props, **kw):
    return execute_rules(props, RuleSet(tuple(rules)), **kw)


def think(rules, props, *, supported=None, as_of=at(2024, 6, 1), observed_at=None, limits=OrchestrationLimits()):
    """orchestrate + evaluate, every proposition (or `supported`) backed by one piece of evidence."""
    ids = [p.id for p in props] if supported is None else supported
    evidence = tuple(Evidence(f"e:{i}", f"e:{i}", SourceKind.OTHER, observed_at=observed_at) for i in ids)
    links = tuple(EvidenceLink(f"e:{i}", i, EvidenceRelation.SUPPORTS) for i in ids)
    request = ReasoningRequest("q", "state_question", tuple(props), evidence, links, as_of=as_of)
    run = orchestrate(request, ruleset=RuleSet(tuple(rules)), limits=limits)
    return run, evaluate_conclusions(run.result, evidence=evidence, evidence_links=links)


def temporal_entries(trace):
    return [e for e in trace if e.status.startswith("temporal_requirement_")]


def temporal_uncertainty(result):
    return [u for u in result.uncertainty if u.id.startswith("uncertainty_temporal_requirement_")]


def conclusions(run):
    return [(p.subject, p.predicate, p.object_value) for p in run.result.propositions if p.kind == PropositionKind.INFERENCE]


def answer(relation, a, b):
    """The outcome of one constraint over two premises, and its reason, through the check alone."""
    check = b4().check(pair_rule((relation, "left", "right")), [left(a), right(b)])
    (item,) = check.constraints
    assert check.outcome.value == item["outcome"]
    return item["outcome"], item.get("reason")


# --------------------------------------------------------------------------
# A1, A2: declaring a requirement
# --------------------------------------------------------------------------

def test_a1_every_existing_way_of_building_a_rule_works_and_a_name_changes_no_match():
    plain = RuleDefinition("r", "1", (PropositionPattern(X, "works_at", C), PropositionPattern(C, "located_in", Y, True)),
                           ConclusionTemplate(X, "works_in_city", Y), "why", 7)
    assert (plain.description, plain.max_firings, plain.temporal) == ("why", 7, None)
    assert plain.premises[0].name is None and plain.premises[1].polarity is True
    assert plain == RuleDefinition("r", "1", plain.premises, plain.conclusion, description="why", max_firings=7, temporal=None)
    named = RuleDefinition("r", "1", (PropositionPattern(X, "works_at", C, name="job"),
                                      PropositionPattern(C, "located_in", Y, True, name="place")),
                           ConclusionTemplate(X, "works_in_city", Y), "why", 7)
    assert [p.name for p in named.premises] == ["job", "place"] and named.temporal is None
    props = [job(TI(at(2019), at(2021))), job(None, "a2"), place(None), place(TI(at(2010), end_unbounded=True), "b2"),
             prop("z", "works_at", None, subject="ravi", obj="apollo")]
    assert match_rule(plain, props) == match_rule(named, props) and len(match_rule(named, props)) == 4
    assert RuleSet((named,)).rules == (named,)


def test_a1_the_relation_is_an_enum_and_its_text_values_are_accepted():
    n = b4()
    assert [k.value for k in n.Kind] == ["overlaps", "before", "during"]
    assert n.Constraint("overlaps", "job", "place") == n.Constraint(n.Kind.OVERLAPS, "job", "place")
    assert n.Constraint("during", "e", "s").relation is n.Kind.DURING
    assert [o.value for o in n.Outcome] == [EST, DIS, IND]
    rule = city()
    assert rule.temporal == (n.Constraint(n.Kind.OVERLAPS, "job", "place"),)
    assert city(()).temporal == () and city(None).temporal is None and city(()) != city(None)


def test_a1_the_name_and_the_declaration_are_keyword_only():
    # B4-01: both are keyword-only, so no positional call that worked before can come to mean something else
    with pytest.raises(TypeError):
        PropositionPattern(X, "works_at", C, True, "job")
    with pytest.raises(TypeError):
        RuleDefinition("r", "1", (PropositionPattern(X, "works_at", C),), ConclusionTemplate(X, "employed", True), "why", 7, ())
    assert PropositionPattern(X, "works_at", C, True, name="job").name == "job"
    assert RuleDefinition("r", "1", (PropositionPattern(X, "works_at", C),), ConclusionTemplate(X, "employed", True), "why", 7,
                          temporal=()).temporal == ()


REFUSALS = {
    "an empty name": lambda n: PropositionPattern(X, "p", Y, name=" "),
    "a name that is not text": lambda n: PropositionPattern(X, "p", Y, name=3),
    "two premises with one name": lambda n: RuleDefinition("r", "1", (PropositionPattern(X, "p", Y, name="same"), PropositionPattern(Y, "q", C, name="same")), ConclusionTemplate(X, "c", C)),
    "a constraint naming no such premise": lambda n: pair_rule(("overlaps", "left", "middle")),
    "a constraint naming an unnamed premise": lambda n: RuleDefinition("r", "1", (PropositionPattern(X, "p", Y, name="left"), PropositionPattern(Y, "q", C)), ConclusionTemplate(X, "c", C), temporal=(n.Constraint("before", "left", "right"),)),
    "a premise related to itself": lambda n: n.Constraint("before", "left", "left"),
    "an unknown relation": lambda n: n.Constraint("after", "left", "right"),
    "an empty premise name in a constraint": lambda n: n.Constraint("before", "", "right"),
    "the same constraint twice": lambda n: pair_rule(("before", "left", "right"), ("before", "left", "right")),
    "overlaps twice with the names exchanged": lambda n: pair_rule(("overlaps", "left", "right"), ("overlaps", "right", "left")),
    "temporal given as a list": lambda n: RuleDefinition("r", "1", pair_rule().premises, pair_rule().conclusion, temporal=[n.Constraint("before", "left", "right")]),
    "temporal holding something that is no constraint": lambda n: RuleDefinition("r", "1", pair_rule().premises, pair_rule().conclusion, temporal=(("before", "left", "right"),)),
    "temporal given as one constraint, not a tuple": lambda n: RuleDefinition("r", "1", pair_rule().premises, pair_rule().conclusion, temporal=n.Constraint("before", "left", "right")),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_a2_a_malformed_declaration_is_refused_when_the_rule_is_built(case):
    n = b4()
    with pytest.raises(ValueError):
        REFUSALS[case](n)


def test_a2_what_is_not_refused():
    assert pair_rule(("before", "left", "right"), ("before", "right", "left")).temporal[1].left == "right"  # not the same constraint
    assert len(pair_rule(("overlaps", "left", "right"), ("before", "left", "right")).temporal) == 2        # A20: accepted
    assert pair_rule().temporal == ()


# --------------------------------------------------------------------------
# A3, A4, A5: the fixed answer table
# --------------------------------------------------------------------------

TABLE = Path(__file__).parent / "data" / "b4_expected_table.tsv.gz"
TABLE_SHA256 = "95d1df79b1f9903fa0d9bff4b0d5e68ca3d6e6374fccc384adb72a4297955840"  # the frozen table, before compression
# relation, left kind, right kind: (pairs, established, disproved, indeterminate, cautious) - section 6.2 of the specification
TABLE_COUNTS = {
    ("overlaps", "state", "state"): (24025, 695, 4658, 18672, 2664),
    ("before", "state", "state"): (24025, 2329, 6640, 15056, 4560),
    ("before", "event", "event"): (169, 16, 41, 112, 0),
    ("before", "event", "state"): (2015, 104, 671, 1240, 112),
    ("before", "state", "event"): (2015, 321, 382, 1312, 184),
    ("during", "event", "state"): (2015, 94, 425, 1496, 16),
}


@functools.lru_cache(maxsize=None)
def _shape(kind, fields):
    """Grid instant n is n days after 2020-01-01T00:00Z."""
    f = json.loads(fields)
    day = lambda n: None if n is None else at(2020) + dt.timedelta(days=n)
    if kind == "event":
        return Occurrence(day(f["earliest"]), day(f["latest"]))
    flags = {k: v for k, v in f.items() if isinstance(v, bool)}
    return TI(day(f.get("start")), day(f.get("end")), start_latest=day(f.get("start_latest")), end_earliest=day(f.get("end_earliest")), **flags)


@functools.lru_cache(maxsize=None)
def table_rows():
    raw = gzip.decompress(TABLE.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == TABLE_SHA256
    header, *lines = raw.decode().splitlines()
    assert header.split("\t") == ["relation", "left_kind", "right_kind", "left", "right", "left_fields", "right_fields",
                                  "expected", "oracle", "cautious"]
    return [line.split("\t") for line in lines]


@functools.lru_cache(maxsize=None)
def table_answers():
    """(relation, left kind, right kind, answer given, expected, oracle, left shape, right shape) for every row."""
    check = b4().check
    rules = {r: pair_rule((r, "left", "right")) for r in ("overlaps", "before", "during")}
    lefts, rights, out = {}, {}, []
    for relation, lk, rk, _, _, lf, rf, expected, oracle, _ in table_rows():
        a = lefts.setdefault((lk, lf), left(_shape(lk, lf)))
        b = rights.setdefault((rk, rf), right(_shape(rk, rf)))
        out.append((relation, lk, rk, check(rules[relation], [a, b]).outcome.value, expected, oracle, _shape(lk, lf), _shape(rk, rf)))
    return out


def test_a3_the_three_relations_reproduce_the_frozen_table_row_for_row():
    answers = table_answers()
    assert len(answers) == 54264
    wrong = [(r, lk, rk, a, b, got, want) for r, lk, rk, got, want, _, a, b in answers if got != want]
    assert not wrong, f"{len(wrong)} rows differ, first: {wrong[0]}"
    counts = {key: tuple(Counter((r, lk, rk) + (got,) for r, lk, rk, got, *_ in answers)[key + (o,)] for o in (EST, DIS, IND))
              for key in TABLE_COUNTS}
    totals = Counter((r, lk, rk) for r, lk, rk, *_ in answers)
    assert {key: (totals[key],) + counts[key] for key in TABLE_COUNTS} == {key: v[:4] for key, v in TABLE_COUNTS.items()}
    assert set(totals) == set(TABLE_COUNTS)


def test_a4_no_definite_answer_disagrees_with_the_oracle_and_caution_is_what_was_recorded():
    answers = table_answers()
    bold = [(r, a, b, got, oracle) for r, _, _, got, _, oracle, a, b in answers if got != IND and got != oracle]
    assert not bold, f"{len(bold)} wrong definite answers, first: {bold[0]}"
    cautious = Counter((r, lk, rk) for r, lk, rk, got, _, oracle, _, _ in answers if got == IND and oracle != IND)
    assert {key: cautious[key] for key in TABLE_COUNTS} == {key: v[4] for key, v in TABLE_COUNTS.items()}
    assert [row[9] for row in table_rows()].count("yes") == sum(cautious.values()) == 7536


def test_a5_overlaps_is_b3s_comparison_itself():
    b3 = {TemporalRelation.OVERLAP: EST, TemporalRelation.DISJOINT: DIS, TemporalRelation.UNKNOWN: IND}
    rows = [(a, b, got) for r, _, _, got, _, _, a, b in table_answers() if r == "overlaps"]
    assert len(rows) == 24025
    assert all(got == b3[_temporal_relation(a, b)] for a, b, got in rows)
    # and it is called, not copied: the comparison module keeps its 0.6.0 bytes
    assert hashlib.sha256((PKG / "primitives/comparison.py").read_bytes()).hexdigest() == pins.ERC_1X_RELEASE_PINS["primitives/comparison.py"][0]


# --------------------------------------------------------------------------
# A6: the named scenarios (section 6.1), through the check, execute_rules and orchestrate
# --------------------------------------------------------------------------

FIRST_SAID = TI(start_latest=last(2024, 3, 5), end_unbounded=True)   # a state first said on 5 Mar 2024, start not stated
ONLY_SAID = Occurrence(None, last(2024, 3, 5))                       # an event only said on 5 Mar 2024
JOB_19_22 = TI(at(2019), at(2022))
SCENARIOS = {
    "E1": ("before", on(2021, 3, 10), on(2022, 2, 1), EST, None),
    "E2": ("before", year(2021), year(2021), IND, "bounds_do_not_settle"),
    "E3": ("before", on(2021, 3, 10), on(2021, 3, 10), DIS, None),
    "E4": ("before", ONLY_SAID, on(2025), EST, None),
    "E5": ("before", ONLY_SAID, on(2023), IND, "bounds_do_not_settle"),
    "E6": ("before", JOB_19_22, TI(at(2022), end_unbounded=True), EST, None),
    "E7": ("before", TI(at(2019), end_unbounded=True), on(2025), DIS, None),
    "E8": ("before", TI(at(2015), at(2017)), FIRST_SAID, IND, "bounds_do_not_settle"),
    "E9": ("before", TI(at(2019), at(2024, 3, 6), end_is_upper_bound=True), on(2025), EST, None),
    "E10": ("before", Occurrence(), on(2025), IND, "bounds_do_not_settle"),
    "D1": ("during", on(2021, 6, 1), JOB_19_22, EST, None),
    "D2": ("during", year(2021), TI(at(2019), at(2022), end_earliest=at(2021, 1, 2)), IND, "bounds_do_not_settle"),
    "D3": ("during", on(2023, 6, 1), JOB_19_22, DIS, None),
    "D4": ("during", on(2025), FIRST_SAID, EST, None),
    "D5": ("during", on(2023, 6, 1), FIRST_SAID, IND, "bounds_do_not_settle"),
    "D6": ("during", ONLY_SAID, TI(at(2019), end_unbounded=True), IND, "bounds_do_not_settle"),
    "D7": ("during", on(2022), JOB_19_22, DIS, None),
    "D8": ("during", on(2019), JOB_19_22, EST, None),
    "D9": ("during", TI(at(2020), at(2021)), JOB_19_22, IND, "wrong_kind"),
    "O1": ("overlaps", TI(at(2021), start_latest=last(2021), end_unbounded=True), TI(at(2022), end_unbounded=True), EST, None),
    "O2": ("overlaps", JOB_19_22, TI(at(2022), end_unbounded=True), DIS, None),
    "O3": ("overlaps", TI(at(2019)), TI(at(2020), end_unbounded=True), IND, "bounds_do_not_settle"),
    "O4": ("overlaps", on(2021, 6, 1), JOB_19_22, IND, "wrong_kind"),
}


@pytest.mark.parametrize("sid", sorted(SCENARIOS, key=lambda s: (s[0], int(s[1:]))))
def test_a6_named_scenario(sid):
    relation, a, b, outcome, reason = SCENARIOS[sid]
    assert answer(relation, a, b) == (outcome, reason)
    rule, props = pair_rule((relation, "left", "right")), [left(a), right(b)]
    execution = execute([rule], props)
    assert len(execution.inference_steps) == (outcome == EST)
    assert [e.status for e in temporal_entries(execution.trace)] == ([] if outcome == EST else [f"temporal_requirement_{outcome}"])
    run, report = think([rule], props)
    assert conclusions(run) == ([("s:l", "related_to", "s:r")] if outcome == EST else [])
    assert len(temporal_uncertainty(run.result)) == (outcome == IND)
    assert report.overall_decision.value == ("accepted" if outcome == EST else "withheld")
    assert run.result.status == (ReasoningStatus.INDETERMINATE if outcome == IND else ReasoningStatus.COMPLETE)


def test_a6_there_are_twenty_three_named_scenarios():
    assert b4().check is engram_erc.check_temporal_requirements
    assert len(SCENARIOS) == 23 and Counter(s[0] for s in SCENARIOS.values()) == {"before": 10, "during": 9, "overlaps": 4}


# P1 .. P6 of section 6: (job, place, outcome with the rule declared, reason)
SINCE_2010 = TI(at(2010), end_unbounded=True)
P = {
    "P1": (TI(at(2019), at(2021)), SINCE_2010, EST, None),
    "P2": (TI(at(2015), at(2017)), TI(at(2020), end_unbounded=True), DIS, None),
    "P3": (TI(at(2021), start_latest=last(2021), end_unbounded=True), TI(at(2010), at(2022), end_earliest=at(2021, 1, 2)), IND, "bounds_do_not_settle"),
    "P4": (TI(), SINCE_2010, IND, "bounds_do_not_settle"),
    "P5": (None, SINCE_2010, IND, "no_temporal_statement"),
    "P6": (on(2021), SINCE_2010, IND, "wrong_kind"),
}


@pytest.mark.parametrize("pid", sorted(P))
def test_a6_the_city_rule_with_its_requirement_declared(pid):
    j, p, outcome, reason = P[pid]
    props = [job(j), place(p)]
    run, report = think([city()], props)
    assert conclusions(run) == ([("asha", "works_in_city", "blr")] if outcome == EST else [])
    (entry,) = temporal_entries(run.result.trace) or [None]
    if outcome == EST:
        assert entry is None and report.overall_decision.value == "accepted"   # F40: P1 is corrected only by B5 and B6
        (step,) = run.result.inference_steps
        assert step.parameters["temporal"] == [{"relation": "overlaps", "left": "job", "right": "place", "outcome": EST}]
    else:
        assert entry.status == f"temporal_requirement_{outcome}" and entry.details["temporal"][0].get("reason") == reason
        assert run.result.inference_steps == () and report.overall_decision.value == "withheld"
        assert len(temporal_uncertainty(run.result)) == (outcome == IND)


@pytest.mark.parametrize("pid", sorted(P))
def test_a7_a_rule_that_declares_nothing_or_declares_that_it_needs_nothing_runs_as_it_always_did(pid):
    j, p, _, _ = P[pid]
    props = [job(j), place(p)]
    plain = RuleDefinition("works_in_city", "1", (PropositionPattern(X, "works_at", C), PropositionPattern(C, "located_in", Y)),
                           ConclusionTemplate(X, "works_in_city", Y))
    old = execute([plain], props)
    for variant in (city(None), city(())):
        new = execute([variant], props)
        assert (new.propositions, new.inference_steps, new.trace, new.status) == (old.propositions, old.inference_steps, old.trace, old.status)
    (step,), (entry,) = old.inference_steps, old.trace
    assert set(step.parameters) == {"ruleset_version", "bindings", "description"}
    assert (entry.operation, entry.status, entry.explanation_code) == ("rule_execution", "derived", "RULE_PREMISES_MATCHED")
    assert set(entry.details) == {"rule_version", "ruleset_version", "inference_id", "bindings"}
    run, report = think([city(())], props)
    assert conclusions(run) == [("asha", "works_in_city", "blr")] and report.overall_decision.value == "accepted"
    assert temporal_entries(run.result.trace) == [] and temporal_uncertainty(run.result) == []


# --------------------------------------------------------------------------
# A8, A9: what is recorded, and on which path
# --------------------------------------------------------------------------

def test_a8_a_disproved_match_leaves_a_trace_entry_and_nothing_else():
    props = [job(P["P2"][0]), place(P["P2"][1])]
    execution = execute([city()], props)
    assert execution.propositions == tuple(props) and execution.inference_steps == ()
    assert execution.status == ReasoningStatus.COMPLETE and execution.firings_executed == 0
    assert execution.trace == (TraceEntry(
        sequence=0, operation="rule_evaluation", input_refs=("a", "b"), output_refs=(), status="temporal_requirement_disproved",
        rule_id="works_in_city", explanation_code="TEMPORAL_REQUIREMENT_DISPROVED",
        details={"rule_version": "1", "temporal": [{"relation": "overlaps", "left": "job", "right": "place", "outcome": DIS}]}),)
    run, report = think([city()], props)
    (entry,) = temporal_entries(run.result.trace)
    assert (entry.operation, entry.status, entry.input_refs, entry.details) == (
        "rule:rule_evaluation", "temporal_requirement_disproved", ("a", "b"), execution.trace[0].details)
    assert run.result.uncertainty == () and run.result.conclusion_refs == () and run.result.status == ReasoningStatus.COMPLETE
    assert report.evaluations == () and report.overall_decision.value == "withheld"


def test_a9_an_indeterminate_match_leaves_a_trace_entry_and_through_orchestrate_one_uncertainty_item():
    props = [job(P["P3"][0]), place(P["P3"][1])]
    execution = execute([city()], props)
    assert execution.propositions == tuple(props) and execution.inference_steps == () and execution.firings_executed == 0
    assert execution.trace == (TraceEntry(
        sequence=0, operation="rule_evaluation", input_refs=("a", "b"), output_refs=(), status="temporal_requirement_indeterminate",
        rule_id="works_in_city", explanation_code="TEMPORAL_REQUIREMENT_NOT_ESTABLISHED",
        details={"rule_version": "1", "temporal": [{"relation": "overlaps", "left": "job", "right": "place", "outcome": IND,
                                                    "reason": "bounds_do_not_settle"}]}),)
    assert not hasattr(execution, "uncertainty")   # a rule execution has no uncertainty list: recovery and counterfactual get the trace only
    run, report = think([city()], props)
    (entry,) = temporal_entries(run.result.trace)
    assert (entry.operation, entry.details) == ("rule:rule_evaluation", execution.trace[0].details)
    (item,) = run.result.uncertainty
    assert (item.id, item.kind, item.affected_refs, item.resolution_hint) == (
        "uncertainty_temporal_requirement_1", UncertaintyKind.TEMPORAL_AMBIGUITY, ("a", "b"), HINT)
    assert item.description == ("Rule works_in_city@1 not applied: whether job and place hold at the same time cannot be established "
                                "(the known dates do not settle it).")
    assert run.result.conclusion_refs == () and run.result.status == ReasoningStatus.INDETERMINATE
    assert report.overall_decision.value == "withheld"


def test_a9_the_direct_callers_of_the_engine_get_the_trace_entry_and_no_uncertainty():
    from engram_erc.counterfactual import RegressionCase, run_counterfactual_suite
    props = (job(P["P3"][0]), place(P["P3"][1]))
    plain, declared = RuleSet((city(None),), version="old"), RuleSet((city(),), version="new")
    report = run_counterfactual_suite((RegressionCase("case", props, expected_conclusions=()),), plain, declared)
    (replay,) = report.case_replays
    assert len(replay.baseline_conclusions) == 1 and replay.candidate_conclusions == ()   # the declared rule derives nothing
    assert replay.baseline_status == replay.candidate_status == ReasoningStatus.COMPLETE  # and the replay has no uncertainty to report


@pytest.mark.parametrize("pid", sorted(P))
def test_a9_recovery_respects_a_rules_temporal_requirements(pid):
    # recovery.py calls the engine itself: a match that does not establish the rule's requirement derives nothing there
    # either, and leaves the same trace entry, with its reason, as a direct call of the engine. No uncertainty item.
    from engram_erc.recovery import RecoveryRequest, RecoveryStatus, run_guarded_recovery
    job_time, place_time, outcome, reason = P[pid]
    props = (job(job_time), place(place_time))
    report = run_guarded_recovery(RecoveryRequest("case", "context", props, RuleSet((city(),))), ())
    direct = execute([city()], props)
    assert report.execution.trace == direct.trace and report.execution.inference_steps == direct.inference_steps
    assert len(report.derived_proposition_refs) == (1 if outcome == EST else 0)
    entries = temporal_entries(report.execution.trace)
    if outcome == EST:
        assert entries == [] and report.execution.inference_steps[0].parameters["temporal"][0]["outcome"] == EST
    else:
        (entry,) = entries
        assert entry.status == f"temporal_requirement_{outcome}" and entry.input_refs == ("a", "b")
        assert entry.details["temporal"] == [{"relation": "overlaps", "left": "job", "right": "place", "outcome": outcome,
                                              **({"reason": reason} if reason else {})}]
    assert report.status == RecoveryStatus.EXECUTED_REVIEW_REQUIRED and not hasattr(report.execution, "uncertainty")
    # the same request with the rule declaring nothing derives the conclusion, as recovery always did
    plain = run_guarded_recovery(RecoveryRequest("case", "context", props, RuleSet((city(None),))), ())
    assert len(plain.derived_proposition_refs) == 1 and temporal_entries(plain.execution.trace) == []


def test_a9_the_result_wrapper_of_a_direct_engine_run_carries_the_trace_entry_and_no_uncertainty():
    # A limitation carried forward, held here so that it cannot change unnoticed: `to_reasoning_result` wraps a direct
    # engine run as a ReasoningResult. Only `orchestrate` builds uncertainty items (B4-04), so for an indeterminate match
    # the wrapped result reports COMPLETE with no uncertainty item; the trace entry is the only record. Nothing in ERC or
    # in the adapter uses the wrapper.
    from engram_erc import to_reasoning_result
    props = (job(P["P3"][0]), place(P["P3"][1]))
    wrapped = to_reasoning_result(execute([city()], props), request_id="q")
    (entry,) = temporal_entries(wrapped.trace)
    assert entry.status == "temporal_requirement_indeterminate" and entry.details["temporal"][0]["reason"] == "bounds_do_not_settle"
    assert wrapped.conclusion_refs == () and wrapped.inference_steps == ()
    assert wrapped.uncertainty == () and wrapped.status == ReasoningStatus.COMPLETE
    run, _ = think([city()], list(props))                   # the same facts through orchestrate are reported as uncertain
    assert len(temporal_uncertainty(run.result)) == 1 and run.result.status == ReasoningStatus.INDETERMINATE


DERIVED = dict(kind=PropositionKind.INFERENCE)
OPEN = TI(at(2019), end_unbounded=True)
WORDING = {  # (relation, reason): (left premise, right premise, text inside the brackets)
    ("overlaps", "derived_premise"): (left(None, **DERIVED), right(OPEN), "left is a derived conclusion and carries no time yet"),
    ("overlaps", "no_temporal_statement"): (left(OPEN), right(None), "right carries no time"),
    ("overlaps", "wrong_kind"): (left(on(2021)), right(OPEN), "left is an event where a state is needed"),
    ("overlaps", "bounds_do_not_settle"): (left(TI(at(2019))), right(TI(at(2020), end_unbounded=True)), "the known dates do not settle it"),
    ("before", "derived_premise"): (left(on(2021)), right(None, **DERIVED), "right is a derived conclusion and carries no time yet"),
    ("before", "no_temporal_statement"): (left(None), right(on(2021)), "left carries no time"),
    ("before", "bounds_do_not_settle"): (left(year(2021)), right(year(2021)), "the known dates do not settle it"),
    ("during", "derived_premise"): (left(None, **DERIVED), right(OPEN), "left is a derived conclusion and carries no time yet"),
    ("during", "no_temporal_statement"): (left(on(2021)), right(None), "right carries no time"),
    ("during", "wrong_kind"): (left(TI(at(2020), at(2021))), right(OPEN), "left is a state where an event is needed"),
    ("during", "bounds_do_not_settle"): (left(year(2021)), right(TI(at(2019), at(2022), end_earliest=at(2021, 1, 2))), "the known dates do not settle it"),
}
CLAUSE = {"overlaps": "whether left and right hold at the same time cannot be established",
          "before": "whether left is over before right begins cannot be established",
          "during": "whether left happens while right holds cannot be established"}


@pytest.mark.parametrize("relation,reason", sorted(WORDING))
def test_a9_the_uncertainty_is_worded_for_the_relation_and_the_reason(relation, reason):
    a, b, text = WORDING[(relation, reason)]
    run, _ = think([pair_rule((relation, "left", "right"))], [a, b])
    (entry,) = temporal_entries(run.result.trace)
    assert entry.details["temporal"] == [{"relation": relation, "left": "left", "right": "right", "outcome": IND, "reason": reason}]
    (item,) = temporal_uncertainty(run.result)
    assert item.description == f"Rule pair@1 not applied: {CLAUSE[relation]} ({text})."
    assert item.resolution_hint == HINT and item.affected_refs == ("l", "r")


def test_a9_every_relation_and_every_reason_that_can_arise_is_worded():
    assert set(WORDING) == {(r, c) for r in ("overlaps", "before", "during")
                            for c in ("derived_premise", "no_temporal_statement", "wrong_kind", "bounds_do_not_settle")} - {("before", "wrong_kind")}
    assert answer("before", TI(at(2019), at(2020)), on(2021)) == (EST, None)   # `before` takes any two: no wrong kind


# --------------------------------------------------------------------------
# A10, A17, A20: several requirements in one rule
# --------------------------------------------------------------------------

ONE, TWO = TI(at(2019), at(2022)), TI(at(2020), at(2023))
SPAN = Occurrence(at(2022), at(2024))   # an event some time from 2022 to 2024: whether TWO was over before it cannot be told


def three(third, one=ONE):
    return [left(one, "p1"), right(TWO, "p2"), prop("p3", "third_of", third)]


def test_a10_all_requirements_must_be_established():
    check = b4().check
    rule = triple_rule(("overlaps", "one", "two"), ("before", "two", "three"))
    outcomes = lambda props: (check(rule, props).outcome.value, [c["outcome"] for c in check(rule, props).constraints])
    assert outcomes(three(on(2025))) == (EST, [EST, EST])
    assert outcomes(three(on(2021))) == (DIS, [EST, DIS])                              # one disproved
    assert outcomes(three(SPAN)) == (IND, [EST, IND])                                  # one indeterminate
    assert outcomes(three(on(2025), one=TI(at(2019)))) == (IND, [IND, EST])
    assert outcomes(three(on(2021), one=TI(at(2019)))) == (DIS, [IND, DIS])            # disproved whatever the others are
    assert isinstance(check(rule, three(on(2025))), b4().Check)
    run, _ = think([rule], three(on(2025)))
    assert conclusions(run) == [("s:p1", "related_to", "s:p2")]
    assert run.result.inference_steps[0].parameters["temporal"] == [
        {"relation": "overlaps", "left": "one", "right": "two", "outcome": EST},
        {"relation": "before", "left": "two", "right": "three", "outcome": EST}]


def test_a17_disproved_with_indeterminate_is_disproved_one_entry_and_no_uncertainty():
    rule = triple_rule(("overlaps", "one", "two"), ("before", "two", "three"))
    run, _ = think([rule], three(on(2021), one=TI(at(2019))))
    (entry,) = temporal_entries(run.result.trace)
    assert entry.status == "temporal_requirement_disproved" and entry.details["temporal"] == [
        {"relation": "overlaps", "left": "one", "right": "two", "outcome": IND, "reason": "bounds_do_not_settle"},
        {"relation": "before", "left": "two", "right": "three", "outcome": DIS}]
    assert run.result.uncertainty == () and conclusions(run) == [] and run.result.status == ReasoningStatus.COMPLETE
    # two indeterminate constraints: one item, a clause for each, in the order declared
    run, _ = think([triple_rule(("before", "two", "three"), ("overlaps", "one", "two"))], three(SPAN, one=TI(at(2019))))
    (item,) = temporal_uncertainty(run.result)
    assert item.description == ("Rule triple@1 not applied: whether two is over before three begins cannot be established "
                                "(the known dates do not settle it); whether one and two hold at the same time cannot be established "
                                "(the known dates do not settle it).")


def test_a20_a_rule_whose_requirements_cannot_all_hold_is_accepted_and_never_fires():
    rule = pair_rule(("overlaps", "left", "right"), ("before", "left", "right"))
    shapes = [ONE, TWO, TI(at(2015), at(2017)), TI(at(2023), end_unbounded=True), TI(at(2019)), TI()]
    for a in shapes:
        for b in shapes:
            execution = execute([rule], [left(a), right(b)])
            assert execution.inference_steps == () and len(temporal_entries(execution.trace)) == 1
            assert b4().check(rule, [left(a), right(b)]).outcome.value in (DIS, IND)


# A22 (Amendment 2): the wording comes from a second run of the check, and that run is guarded
GUARD = "Temporal recheck for rule triple@1 disagrees with the recorded trace entry; no uncertainty item was produced."
DISAGREEMENTS = {   # what the second run of the check reports for the same match; the overall outcome stays indeterminate
    "another reason": lambda items: [{**items[0], "reason": "no_temporal_statement"}, items[1]],
    "another order": lambda items: [items[1], items[0]],
    "another outcome for one constraint": lambda items: [items[0], {k: v for k, v in {**items[1], "outcome": EST}.items() if k != "reason"}],
    "another relation": lambda items: [{**items[0], "relation": "during"}, items[1]],
    "another left premise": lambda items: [{**items[0], "left": "one"}, items[1]],
    "another right premise": lambda items: [{**items[0], "right": "one"}, items[1]],
}


def _stand_in(patch, check, built):
    """Puts `check` wherever a module holds check_temporal_requirements, and records every uncertainty item orchestrate builds."""
    import engram_erc.inference, engram_erc.orchestration
    from engram_erc import temporal_requirements as tr
    for module in (tr, engram_erc.inference, engram_erc.orchestration, engram_erc):
        if hasattr(module, "check_temporal_requirements"):
            patch.setattr(module, "check_temporal_requirements", check)
    make = engram_erc.orchestration.UncertaintyItem

    def recording(*args, **kw):
        item = make(*args, **kw)
        built.append(item.id)
        return item
    patch.setattr(engram_erc.orchestration, "UncertaintyItem", recording)


def _reporting(alter, calls, from_call):
    """A check that reports the real result, altered from its `from_call`-th run on one match onward."""
    from engram_erc import temporal_requirements as tr
    real = tr.check_temporal_requirements

    def check(rule, premises):
        key = (rule.rule_id, tuple(p.id for p in premises))
        calls[key] += 1
        result = real(rule, premises)
        if calls[key] < from_call:
            return result
        return SimpleNamespace(outcome=result.outcome, constraints=tuple(alter([dict(c) for c in result.constraints])))
    return check


def test_a22_a_recheck_that_disagrees_with_the_trace_raises_and_builds_no_uncertainty_item(monkeypatch):
    rule = triple_rule(("before", "two", "three"), ("overlaps", "one", "two"))
    props, match = three(SPAN, one=TI(at(2019))), ("triple", ("p1", "p2", "p3"))
    calls, built = Counter(), []
    with monkeypatch.context() as patch:                   # undisturbed: the recheck agrees, one item, nothing raised
        _stand_in(patch, _reporting(lambda items: items, calls, 1), built)
        run, _ = think([rule], props)
    (entry,), (item,) = temporal_entries(run.result.trace), temporal_uncertainty(run.result)
    assert [c["outcome"] for c in entry.details["temporal"]] == [IND, IND] and item.description.startswith("Rule triple@1 not applied: ")
    assert calls[match] == 2                               # checked once by the engine, once again for the wording
    assert [i for i in built if "temporal_requirement" in i] == ["uncertainty_temporal_requirement_1"]   # the builder is the one watched below
    for name, alter in DISAGREEMENTS.items():
        calls, built = Counter(), []
        with monkeypatch.context() as patch:               # the engine's own check is real; the second run differs
            _stand_in(patch, _reporting(alter, calls, 2), built)
            with pytest.raises(RuntimeError) as raised:
                think([rule], props)
        assert str(raised.value) == GUARD, name
        assert calls[match] == 2, name
        assert [i for i in built if "temporal_requirement" in i] == [], name   # nothing was built from the second run


VERIFIED = [   # (rule, premises, what the check reports on BOTH runs, the wording that must follow from that report)
    (lambda: triple_rule(("before", "two", "three"), ("overlaps", "one", "two")), lambda: three(SPAN, one=TI(at(2019))),
     lambda items: [items[0], {k: v for k, v in {**items[1], "outcome": EST}.items() if k != "reason"}],
     "Rule triple@1 not applied: whether two is over before three begins cannot be established (the known dates do not settle it)."),
    (lambda: pair_rule(("overlaps", "left", "right")), lambda: [left(OPEN), right(None)],
     lambda items: [{**items[0], "reason": "bounds_do_not_settle"}],
     "Rule pair@1 not applied: whether left and right hold at the same time cannot be established (the known dates do not settle it)."),
]


def test_a22_the_wording_is_built_from_the_verified_second_result_and_not_from_a_third_evaluation(monkeypatch):
    for make_rule, make_props, alter, wording in VERIFIED:
        rule, props = make_rule(), make_props()
        calls, built = Counter(), []
        with monkeypatch.context() as patch:               # the check answers the same on both runs, and not as the dates would
            _stand_in(patch, _reporting(alter, calls, 1), built)
            run, _ = think([rule], props)
        (entry,), (item,) = temporal_entries(run.result.trace), temporal_uncertainty(run.result)
        real = b4().check(rule, props)
        assert entry.details["temporal"] == alter([dict(c) for c in real.constraints]) != [dict(c) for c in real.constraints]
        assert item.description == wording                 # a clause for what the verified result leaves open, with its reason
        assert list(calls.values()) == [2]

# --------------------------------------------------------------------------
# A11, A18: several matches of one rule
# --------------------------------------------------------------------------

OLD_STINT, CURRENT_STINT, FROM_2020 = TI(at(2015), at(2017)), TI(at(2022), at(2025)), TI(at(2020), end_unbounded=True)


@pytest.mark.parametrize("old_id,current_id", [("a1", "a2"), ("a2", "a1")])
def test_a11_a_failed_match_never_suppresses_another_whichever_sorts_first(old_id, current_id):
    props = [job(OLD_STINT, old_id), job(CURRENT_STINT, current_id), place(FROM_2020)]
    run, report = think([city()], props, supported=[current_id, "b"])
    (step,) = run.result.inference_steps
    assert step.input_refs == (current_id, "b") and conclusions(run) == [("asha", "works_in_city", "blr")]
    (ev,) = report.evaluations
    assert ev.decision.value == "accepted" and ev.premise_coverage.leaf_premise_ids == tuple(sorted((current_id, "b")))
    (entry,) = temporal_entries(run.result.trace)
    assert entry.status == "temporal_requirement_disproved" and entry.input_refs == (old_id, "b")
    run, report = think([city()], props, supported=[old_id, "b"])            # only the stint that does not count is supported
    assert report.evaluations[0].decision.value == "withheld"


def test_a18_each_match_is_judged_and_recorded_on_its_own():
    run, _ = think([city()], [job(CURRENT_STINT, "a1"), job(TI(at(2018)), "a2"), place(FROM_2020)])
    assert conclusions(run) == [("asha", "works_in_city", "blr")] and len(run.result.inference_steps) == 1
    (item,) = temporal_uncertainty(run.result)
    assert item.id == "uncertainty_temporal_requirement_1" and item.affected_refs == ("a2", "b")
    assert run.result.status == ReasoningStatus.COMPLETE          # something fired; the uncertainty is still listed
    run, _ = think([city()], [job(TI(at(2018)), "a1"), job(None, "a2"), place(FROM_2020)])
    items = temporal_uncertainty(run.result)
    assert [(i.id, i.affected_refs) for i in items] == [("uncertainty_temporal_requirement_1", ("a1", "b")),
                                                       ("uncertainty_temporal_requirement_2", ("a2", "b"))]
    assert [e.input_refs for e in temporal_entries(run.result.trace)] == [("a1", "b"), ("a2", "b")]
    assert items[1].description.endswith("(job carries no time).") and items[0].description.endswith("(the known dates do not settle it).")
    assert conclusions(run) == [] and run.result.status == ReasoningStatus.INDETERMINATE


# --------------------------------------------------------------------------
# A12, A19: a premise that is itself a conclusion
# --------------------------------------------------------------------------

EMPLOYED = RuleDefinition("a_employed", "1", (PropositionPattern(X, "works_at", C),), ConclusionTemplate(X, "employed_by", C))


def chained():
    return RuleDefinition("b_city", "1", (PropositionPattern(X, "employed_by", C, name="job"), PropositionPattern(C, "located_in", Y, name="place")),
                          ConclusionTemplate(X, "works_in_city", Y), temporal=(b4().Constraint("overlaps", "job", "place"),))


def test_a12_a19_a_requirement_over_a_derived_conclusion_is_indeterminate_and_leaves_the_first_conclusion_alone():
    props = [job(TI(at(2019), at(2021))), place(SINCE_2010)]
    alone, alone_report = think([EMPLOYED], props)
    run, report = think([EMPLOYED, chained()], props)
    assert conclusions(run) == conclusions(alone) == [("asha", "employed_by", "manipal")]
    assert run.result.conclusion_refs == alone.result.conclusion_refs and run.result.inference_steps == alone.result.inference_steps
    assert report.evaluations == alone_report.evaluations and report.overall_decision.value == "accepted"
    (entry,) = temporal_entries(run.result.trace)
    assert entry.input_refs == (run.result.conclusion_refs[0], "b")
    assert entry.details["temporal"] == [{"relation": "overlaps", "left": "job", "right": "place", "outcome": IND, "reason": "derived_premise"}]
    (item,) = temporal_uncertainty(run.result)
    assert item.description == ("Rule b_city@1 not applied: whether job and place hold at the same time cannot be established "
                                "(job is a derived conclusion and carries no time yet).")
    assert run.result.status == ReasoningStatus.COMPLETE and alone.result.uncertainty == ()
    # a proposition of kind inference that a caller supplies with a time is read like any other
    assert b4().check(city(), [job(TI(at(2019), at(2021)), **DERIVED), place(SINCE_2010)]).outcome.value == EST


def test_a19_a_conclusion_identical_to_an_untimed_stated_proposition_is_not_derived_again():
    stated = prop("stated", "employed_by", None, subject="asha", obj="manipal")
    run, _ = think([EMPLOYED, chained()], [job(TI(at(2019), at(2021))), place(SINCE_2010), stated])
    assert conclusions(run) == []
    (entry,) = temporal_entries(run.result.trace)
    assert entry.input_refs == ("stated", "b") and entry.details["temporal"][0]["reason"] == "no_temporal_statement"


# --------------------------------------------------------------------------
# A13: a match that does not fire is recorded once and uses no firing
# --------------------------------------------------------------------------

def test_a13_a_match_that_does_not_fire_is_recorded_once_and_counts_toward_no_limit():
    declared = RuleDefinition("a_city", "1", city().premises, city().conclusion, max_firings=1, temporal=city().temporal)
    props = [job(OLD_STINT, "a1"), job(TI(at(2018)), "a2"), job(CURRENT_STINT, "a3"), place(FROM_2020)]
    execution = execute([declared, EMPLOYED], props, limits=ExecutionLimits(max_rounds=5, max_total_firings=4))
    # a1 is disproved and a2 indeterminate before a3 is reached: neither uses the rule's single firing
    assert execution.status == ReasoningStatus.COMPLETE and execution.rounds_executed >= 2
    assert [s.input_refs for s in execution.inference_steps if s.rule_id == "a_city@1"] == [("a3", "b")]
    assert execution.firings_executed == 2       # a_city once; employed_by once (its three matches give one conclusion)
    assert [(e.input_refs, e.status) for e in temporal_entries(execution.trace)] == [
        (("a1", "b"), "temporal_requirement_disproved"), (("a2", "b"), "temporal_requirement_indeterminate")]
    run, _ = think([declared, EMPLOYED], props, limits=OrchestrationLimits(execution=ExecutionLimits(max_rounds=5, max_total_firings=4)))
    assert len(temporal_uncertainty(run.result)) == 1 and run.result.status == ReasoningStatus.COMPLETE


# --------------------------------------------------------------------------
# A14: nothing but the temporal contract is read
# --------------------------------------------------------------------------

def test_a14_no_qualifier_no_evidence_date_and_no_as_of_changes_an_outcome():
    plain = {pid: [job(j), place(p)] for pid, (j, p, _, _) in P.items()}
    loud = {pid: [job(j, qualifiers={"valid_time": "unknown", "time_kind": "event", "start_basis": "first_said", "end_basis": "closed"}),
                  place(p, qualifiers={"valid_time": "known", "end_basis": "open"})] for pid, (j, p, _, _) in P.items()}
    for pid, (_, _, outcome, reason) in P.items():
        baseline, _ = think([city()], plain[pid])
        summary = lambda run: ([e.details for e in temporal_entries(run.result.trace)], conclusions(run),
                               [u.description for u in temporal_uncertainty(run.result)], run.result.status)
        for props, as_of, observed in ((loud[pid], at(2024, 6, 1), None), (plain[pid], at(1800), None), (plain[pid], at(2100), at(2100)),
                                       (plain[pid], None, at(1990))):
            run, _ = think([city()], props, as_of=as_of, observed_at=observed)
            assert summary(run) == summary(baseline), (pid, as_of)
        assert b4().check(city(), loud[pid]).outcome.value == outcome


# --------------------------------------------------------------------------
# A15: version, pins, public names
# --------------------------------------------------------------------------

PUBLIC_NAMES_AT_B4 = (305, "0ebca2a8058e41153a798aae237f2747beee407956086dc1ae63ceeaa4dff59f")   # the 300 of 0.6.0 and the five below
NEW_PUBLIC_NAMES = ["TemporalCheck", "TemporalConstraint", "TemporalOutcome", "TemporalRequirementKind", "check_temporal_requirements"]


def test_a15_version_and_release_pins():
    assert engram_erc.__version__ == (PKG / "VERSION").read_text().strip() == "0.7.0"
    assert pins.ERC_1X_FILES_CHANGED_SINCE_0_4_0 == {"contracts.py", "primitives/comparison.py", "rules.py", "inference.py", "orchestration.py"}
    for rel in ("rules.py", "inference.py", "orchestration.py"):
        digest, release, reason = pins.ERC_1X_RELEASE_PINS[rel]
        assert release == "0.7.0" and "B4" in reason
        assert digest == hashlib.sha256((PKG / rel).read_bytes()).hexdigest() != pins.ERC_1X_SHA256_AT_0_4_0[rel]
    # earlier pins are untouched, and the comparison is still its 0.6.0 bytes
    assert pins.ERC_1X_RELEASE_PINS["contracts.py"][1] == "0.5.0"
    assert pins.ERC_1X_RELEASE_PINS["primitives/comparison.py"][:2] == ("ead6a041f46db99faac626d43493350bcaaae3329316251322484a1411f20d8f", "0.6.0")
    canonical = "\n".join(f"{rel} {digest}" for rel, digest in sorted(pins.ERC_1X_SHA256_AT_0_4_0.items()))
    assert hashlib.sha256(canonical.encode()).hexdigest() == pins.ERC_1X_HISTORICAL_TABLE_SHA256 == "1d72e781ec1dcd5fcbbf20ad1580cd28d6321047cf1498d33049fe1763e53dda"


def test_a15_exactly_five_names_become_public():
    names = sorted(engram_erc.__all__)
    assert (len(names), hashlib.sha256(json.dumps(names).encode()).hexdigest()) == PUBLIC_NAMES_AT_B4
    assert [n for n in NEW_PUBLIC_NAMES if n in names] == NEW_PUBLIC_NAMES
    n = b4()
    assert (engram_erc.TemporalConstraint, engram_erc.TemporalRequirementKind, engram_erc.TemporalOutcome, engram_erc.TemporalCheck,
            engram_erc.check_temporal_requirements) == (n.Constraint, n.Kind, n.Outcome, n.Check, n.check)
    assert [r.value for r in engram_erc.TemporalRelation] == ["overlap", "disjoint", "unknown"]   # the comparison's own relation keeps its meaning


def test_a15_the_engine_reports_the_package_version():
    run, _ = think([city()], [job(P["P1"][0]), place(P["P1"][1])])
    assert run.result.engine_version == engram_erc.__version__ == "0.7.0"


# --------------------------------------------------------------------------
# A21: which premises a reason names
# --------------------------------------------------------------------------

STATE, EVENT = TI(at(2019), at(2022)), on(2021)
NAMED = {  # visit, job, reason, text - the five rows of B4-04, for `during`
    "both of the wrong kind": (STATE, EVENT, "wrong_kind", "visit is a state where an event is needed and job is an event where a state is needed"),
    "only the right one of the wrong kind": (EVENT, EVENT, "wrong_kind", "job is an event where a state is needed"),
    "neither carries a time": (None, None, "no_temporal_statement", "visit carries no time and job carries no time"),
    "left derived, right untimed": ("derived", None, "derived_premise", "visit is a derived conclusion and carries no time yet"),
    "left untimed, right of the wrong kind": (None, EVENT, "no_temporal_statement", "visit carries no time"),
}


def named_run(relation, visit, job_time):
    a = left(None, **DERIVED) if visit == "derived" else left(visit)
    return think([pair_rule((relation, "visit", "job"), names=("visit", "job"))], [a, right(job_time)])[0]


@pytest.mark.parametrize("case", sorted(NAMED))
def test_a21_the_reason_names_every_premise_it_applies_to_left_then_right(case):
    visit, job_time, reason, text = NAMED[case]
    run = named_run("during", visit, job_time)
    assert temporal_entries(run.result.trace)[0].details["temporal"] == [
        {"relation": "during", "left": "visit", "right": "job", "outcome": IND, "reason": reason}]
    (item,) = temporal_uncertainty(run.result)
    assert item.description == f"Rule pair@1 not applied: whether visit happens while job holds cannot be established ({text})."


def test_a21_overlaps_with_two_events_names_both():
    run = named_run("overlaps", EVENT, EVENT)
    assert temporal_entries(run.result.trace)[0].details["temporal"][0]["reason"] == "wrong_kind"
    (item,) = temporal_uncertainty(run.result)
    assert item.description == ("Rule pair@1 not applied: whether visit and job hold at the same time cannot be established "
                                "(visit is an event where a state is needed and job is an event where a state is needed).")
    run = named_run("overlaps", "derived", None)   # left derived, right untimed: only the derived one is named
    assert temporal_uncertainty(run.result)[0].description.endswith("(visit is a derived conclusion and carries no time yet).")
    both_derived = think([pair_rule(("before", "visit", "job"), names=("visit", "job"))], [left(None, **DERIVED), right(None, **DERIVED)])[0]
    assert temporal_uncertainty(both_derived.result)[0].description == (
        "Rule pair@1 not applied: whether visit is over before job begins cannot be established "
        "(visit is a derived conclusion and carries no time yet and job is a derived conclusion and carries no time yet).")
