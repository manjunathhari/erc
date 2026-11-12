"""B5 - Conclusion temporal propagation (ERC 0.8.0).

A rule may declare the time its conclusion takes: the period all named premises share (`while_all`), the time of one
premise (`as_premise`), or none (`timeless`). The conclusion's temporal status (timed, timeless, not established) is
derivation metadata on the inference step. Alternative derivations are kept and each is evaluated on its own. B5 reads
no `as_of` (B6).

Specification: frozen 12 Nov 2026, Draft 1.4 revision 2, SHA-256
ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581 (claude/erc-b5-spec.md and -part2.md; freeze record
claude/erc-b5-freeze-record.md), with Amendment 1 (the step record of an event, the names of the derivation record, and
the wording of explain()). Test names carry that document's acceptance criteria (A1 .. A26, section 8) and its
scenario numbers (S1 .. S26, section 7). A2's recording of the existing suite and A23 (the unedited adapter tests, the
recorded four) are checks run on the whole suite and reported with the build; A17 is in
tests/test_erc_overlay_conclusion_time.py.

Everything B5 adds is reached through `b5()`, at call time, so that every test in this file fails by itself until B5
is implemented. A test that says "this stays as it is" also builds something only B5 allows, for the same reason.
"""
import dataclasses
import datetime as dt
import functools
import gzip
import hashlib
import itertools
import json
import random
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

import engram_erc
from engram_erc import (
    ConclusionTemplate, DecisionPolicy, Evidence, EvidenceLink, EvidenceRelation, Occurrence, Proposition,
    PropositionKind, PropositionPattern, ReasoningRequest, ReasoningStatus, RuleDefinition, RuleSet, SourceKind,
    TemporalConstraint, TimeInterval as TI, UncertaintyKind, Variable, evaluate_conclusions, execute_rules, orchestrate,
    to_reasoning_result,
)
from engram_erc.orchestration import OrchestrationLimits
from engram_erc.tests import test_domain_profiles as pins
from engram_erc.tests import test_temporal_rules as b4t

UTC = dt.timezone.utc
US = dt.timedelta(microseconds=1)
PKG = Path(engram_erc.__file__).parent
FAULT = "Conclusion time for rule {}: the shared period of an established overlap is not certain."
HINT = "Declare how the conclusion's time follows from its premises, or supply the missing times."
OK = ["PREMISE_LINEAGE_COMPLETE_AND_SUPPORT_THRESHOLD_MET"]
UNSUPPORTED = ["ONE_OR_MORE_ROOT_PREMISES_LACK_REQUIRED_SUPPORT"]
NOT_ESTABLISHED = "CONCLUSION_TIME_NOT_ESTABLISHED"
TRUNCATED = "ALTERNATIVE_DERIVATIONS_TRUNCATED"
REASON_TEXT = {
    "no_conclusion_time_declared": "the rule declares temporal requirements but not the time of its conclusion",
    "premise_carries_no_time": "{} carries no time",
    "premise_time_unknown": "the time of {} is not known",
}


def b5():
    """What B5 adds: its four public names, taken from the package itself (Amendment 1: which module holds them is not
    part of the contract). Read when called, never at module level."""
    return SimpleNamespace(Time=engram_erc.ConclusionTime, Kind=engram_erc.ConclusionTimeKind, Status=engram_erc.ConclusionTimeStatus,
                           Derivation=engram_erc.DerivationEvaluation)


def at(year, month=1, day=1):
    return dt.datetime(year, month, day, tzinfo=UTC)


def last(year, month=None, day=None):
    """The last instant of a year, or of a day."""
    return (at(year + 1) if month is None else at(year, month, day) + dt.timedelta(days=1)) - US


def on(*date):
    return Occurrence(at(*date), last(*date) if len(date) == 3 else at(*date))


# --------------------------------------------------------------------------
# Rules, facts and runs used throughout
# --------------------------------------------------------------------------

X, C, Y, M, K, S = (Variable(n) for n in ("x", "c", "y", "m", "k", "s"))
SINCE_2010 = TI(at(2010), end_unbounded=True)
JOB_19_21 = TI(at(2019), at(2021))


def overlaps(a, b):
    return TemporalConstraint("overlaps", a, b)


def city(temporal="declared", time="while_all", rule_id="city"):
    """works_at(X, C) and located_in(C, Y) give works_in_city(X, Y). By default rule C of B5-02: the two must hold at
    the same time and the conclusion holds while both do. `city(None, None)` is rule A; `city(time=None)` rule B."""
    n = b5()
    if temporal == "declared":
        temporal = (overlaps("job", "place"),)
    if time == "while_all":
        time = n.Time("while_all", ("job", "place"))
    return RuleDefinition(rule_id, "1",
                          (PropositionPattern(X, "works_at", C, name="job"), PropositionPattern(C, "located_in", Y, name="place")),
                          ConclusionTemplate(X, "works_in_city", Y), temporal=temporal, conclusion_time=time)


def metro():
    return RuleDefinition("metro", "1",
                          (PropositionPattern(X, "works_in_city", Y, name="incity"), PropositionPattern(Y, "has_metro", M, name="metro")),
                          ConclusionTemplate(X, "can_commute_by", M), temporal=(overlaps("incity", "metro"),),
                          conclusion_time=b5().Time("while_all", ("incity", "metro")))


def season_pass():
    return RuleDefinition("pass", "1",
                          (PropositionPattern(X, "can_commute_by", M, name="commute"), PropositionPattern(M, "sells_pass", K, name="pass")),
                          ConclusionTemplate(X, "can_buy", K), temporal=(overlaps("commute", "pass"),),
                          conclusion_time=b5().Time("while_all", ("commute", "pass")))


def visit_rule():
    return RuleDefinition("visit", "1",
                          (PropositionPattern(X, "visited", Y, name="visit"), PropositionPattern(X, "works_at", C, name="job")),
                          ConclusionTemplate(X, "visited_as_employee_of", C), temporal=(TemporalConstraint("during", "visit", "job"),),
                          conclusion_time=b5().Time("as_premise", ("visit",)))


def moved_rule():
    return RuleDefinition("moved", "1",
                          (PropositionPattern(X, "left_job", Y, name="left"), PropositionPattern(X, "works_at", C, name="next")),
                          ConclusionTemplate(X, "moved_on_to", C), temporal=(TemporalConstraint("before", "left", "next"),),
                          conclusion_time=b5().Time("as_premise", ("next",)))


def P(pid, subject, predicate, obj, time=None, *, polarity=True, **kw):
    return Proposition(pid, subject, predicate, obj, polarity=polarity,
                       valid_time=time if isinstance(time, TI) else None, occurred=time if isinstance(time, Occurrence) else None, **kw)


def job(time, pid="a", employer="manipal", **kw):
    return P(pid, "asha", "works_at", employer, time, **kw)


def place(time=SINCE_2010, pid="b", employer="manipal", where="blr", **kw):
    return P(pid, employer, "located_in", where, time, **kw)


def backing(ids, observed_at=None):
    evidence = tuple(Evidence(f"e:{i}", f"src:{i}", SourceKind.USER_PROVIDED, observed_at=observed_at) for i in ids)
    return evidence, tuple(EvidenceLink(f"e:{i}", i, EvidenceRelation.SUPPORTS) for i in ids)


def when(p):
    return p.valid_time if p.valid_time is not None else p.occurred


def _sort_time(p):
    t = when(p)
    stamp = lambda m: "" if m is None else m.isoformat()
    if t is None:
        return ("",)
    return tuple(stamp(getattr(t, f, None)) for f in ("start", "start_latest", "end_earliest", "end", "earliest", "latest"))


class Thought:
    """orchestrate + evaluate. `rows`: one per conclusion (its proposition, evaluation, producing steps and the recorded
    conclusion time), ordered by what the conclusion says and never by an id."""

    def __init__(self, rules, props, *, supported=None, functional=frozenset(), as_of=at(2024, 6, 1), observed_at=None):
        props = tuple(props)
        self.evidence, self.links = backing([p.id for p in props] if supported is None else supported, observed_at)
        request = ReasoningRequest("q", "state_question", props, self.evidence, self.links, as_of=as_of)
        self.run = orchestrate(request, ruleset=RuleSet(tuple(rules)), limits=OrchestrationLimits(functional_predicates=functional))
        self.result = self.run.result
        self.report = evaluate_conclusions(self.result, evidence=self.evidence, evidence_links=self.links,
                                           policy=DecisionPolicy(functional_predicates=functional))
        self.props = {p.id: p for p in self.result.propositions}
        steps = {}
        for step in self.result.inference_steps:
            (out,) = step.output_proposition_refs
            steps.setdefault(out, []).append(step)
        self.rows = sorted((SimpleNamespace(p=self.props[e.conclusion_id], e=e, steps=steps[e.conclusion_id],
                                            record=steps[e.conclusion_id][0].parameters.get("conclusion_time"),
                                            decision=e.decision.value, reasons=list(e.reasons),
                                            each=[d.decision.value for d in e.derivations])
                            for e in self.report.evaluations),
                           key=lambda r: (r.p.predicate, json.dumps(r.p.object_value, sort_keys=True, default=str), _sort_time(r.p)))

    @property
    def only(self):
        (row,) = self.rows
        return row

    def row(self, predicate):
        (row,) = [r for r in self.rows if r.p.predicate == predicate]
        return row

    @property
    def overall(self):
        return self.report.overall_decision.value

    def entries(self, prefix):
        return [e for e in self.result.trace if e.status.startswith(prefix)]

    @property
    def time_uncertainty(self):
        return [u for u in self.result.uncertainty if u.id.startswith("uncertainty_conclusion_time_")]

    @property
    def requirement_uncertainty(self):
        return [u for u in self.result.uncertainty if u.id.startswith("uncertainty_temporal_requirement_")]


def record_of(record):
    """A recorded `conclusion_time` with its ISO texts read back as instants, so that the test fixes the content and
    not one spelling of an instant. Only stated fields are recorded (Amendment 1): a period's unstated field and an
    event's unstated side are left out, never written as null or false."""
    out = dict(record)
    for key in ("valid_time", "occurred"):
        if key in out:
            assert all(v is True or isinstance(v, str) for v in out[key].values()), out[key]
            out[key] = {k: (v if v is True else dt.datetime.fromisoformat(v)) for k, v in out[key].items()}
    return out


def timed(mode, names, **time):
    return {"status": "timed", "mode": mode, "premises": list(names), **time}


def unsettled(reason, mode=None, names=()):
    return {"status": "not_established", "mode": mode, "premises": list(names), "reason": reason}


# --------------------------------------------------------------------------
# A1: declaring the conclusion's time
# --------------------------------------------------------------------------

def test_a1_every_existing_way_of_building_a_rule_works_and_the_declaration_is_keyword_only():
    n = b5()
    plain = RuleDefinition("r", "1", (PropositionPattern(X, "works_at", C), PropositionPattern(C, "located_in", Y, True)),
                           ConclusionTemplate(X, "works_in_city", Y), "why", 7)
    assert (plain.description, plain.max_firings, plain.temporal, plain.conclusion_time) == ("why", 7, None, None)
    assert plain == RuleDefinition("r", "1", plain.premises, plain.conclusion, description="why", max_firings=7, temporal=None,
                                   conclusion_time=None)
    b4_rule = RuleDefinition("city", "1", city().premises, city().conclusion, temporal=(overlaps("job", "place"),))
    assert b4_rule.conclusion_time is None and b4_rule != city() and b4_rule == city(time=None)
    field = {f.name: f for f in dataclasses.fields(RuleDefinition)}["conclusion_time"]
    assert field.kw_only and field.default is None
    with pytest.raises(TypeError):
        RuleDefinition("r", "1", plain.premises, plain.conclusion, "why", 7, n.Time("timeless"))
    assert RuleSet((city(),)).rules == (city(),)


def test_a1_the_kind_is_an_enum_its_text_values_are_accepted_and_there_are_three_statuses():
    n = b5()
    assert [k.value for k in n.Kind] == ["while_all", "as_premise", "timeless"]
    assert (n.Kind.WHILE_ALL, n.Kind.AS_PREMISE, n.Kind.TIMELESS) == tuple(n.Kind)
    assert n.Time("while_all", ("job", "place")) == n.Time(n.Kind.WHILE_ALL, ("job", "place"))
    assert n.Time("as_premise", ("job",)).kind is n.Kind.AS_PREMISE and n.Time("timeless").premises == ()
    assert city().conclusion_time == n.Time(n.Kind.WHILE_ALL, ("job", "place"))
    assert [s.value for s in n.Status] == ["timed", "timeless", "not_established"]
    assert (n.Status.TIMED, n.Status.TIMELESS, n.Status.NOT_ESTABLISHED) == tuple(n.Status)


def three(time, *pairs):
    return RuleDefinition("three", "1", (PropositionPattern(X, "p1", Y, name="one"), PropositionPattern(X, "p2", Y, name="two"),
                                         PropositionPattern(X, "p3", Y, name="three")),
                          ConclusionTemplate(X, "all", Y), temporal=tuple(overlaps(*p) for p in pairs), conclusion_time=time)


REFUSALS = {
    "an unknown kind": lambda n: n.Time("sometimes"),
    "premises given as a list": lambda n: n.Time("while_all", ["job", "place"]),
    "premises given as one name, not a tuple": lambda n: n.Time("as_premise", "job"),
    "an empty premise name": lambda n: n.Time("as_premise", ("",)),
    "a blank premise name": lambda n: n.Time("as_premise", (" ",)),
    "a premise name that is not text": lambda n: n.Time("as_premise", (3,)),
    "a name used twice": lambda n: n.Time("while_all", ("job", "job")),
    "while_all over one premise": lambda n: n.Time("while_all", ("job",)),
    "while_all over none": lambda n: n.Time("while_all"),
    "as_premise over two": lambda n: n.Time("as_premise", ("job", "place")),
    "as_premise over none": lambda n: n.Time("as_premise"),
    "timeless naming a premise": lambda n: n.Time("timeless", ("job",)),
    "a name no premise carries": lambda n: city(temporal=None, time=n.Time("as_premise", ("nobody",))),
    "while_all naming a premise the rule lacks": lambda n: city(time=n.Time("while_all", ("job", "nobody"))),
    "conclusion_time given as text": lambda n: city(temporal=None, time="timeless"),
    "conclusion_time given as a tuple": lambda n: city(time=("while_all", ("job", "place"))),
    "while_all with no requirements declared": lambda n: city(temporal=None),
    "while_all with requirements declared empty": lambda n: city(temporal=()),
    "while_all with only a before requirement": lambda n: city(temporal=(TemporalConstraint("before", "job", "place"),)),
    "while_all over three with one pair not required to overlap": lambda n: three(n.Time("while_all", ("one", "two", "three")), ("one", "two"), ("two", "three")),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_a1_a_malformed_declaration_is_refused_when_the_rule_is_built(case):
    n = b5()
    with pytest.raises(ValueError):
        REFUSALS[case](n)


def test_a1_what_is_not_refused():
    n = b5()
    assert city(temporal=None, time=n.Time("as_premise", ("place",))).temporal is None      # rule D
    assert city(temporal=None, time=n.Time("timeless")).conclusion_time.kind is n.Kind.TIMELESS
    assert city(time=n.Time("timeless")).temporal == (overlaps("job", "place"),)
    assert city(temporal=(overlaps("place", "job"),)).conclusion_time.premises == ("job", "place")   # overlaps has no direction
    assert city(time=n.Time("while_all", ("place", "job"))).conclusion_time.premises == ("place", "job")
    whole = three(n.Time("while_all", ("one", "two", "three")), ("one", "two"), ("three", "two"), ("one", "three"))
    assert len(whole.temporal) == 3
    assert three(n.Time("while_all", ("one", "three")), ("one", "three")).conclusion_time.premises == ("one", "three")   # never "all premises"


# --------------------------------------------------------------------------
# A3, A4: the fixed answer table for the shared period
# --------------------------------------------------------------------------

TABLE = Path(__file__).parent / "data" / "b5_expected_table.tsv.gz"
TABLE_SHA256 = "5cb865c2247eaae83dfe296bdd4d42ae693c40cfe6fb7e9603056ef36876f40e"   # the frozen table, before compression
TABLE_ROWS = {2: 695, 3: 1748, 4: 6384, 5: 17502}
GRID_LOW, GRID_HIGH = 0, 8             # an unknown bound ranges over 0 .. 8 in the oracle (section 6.2, grid 1)
INTERVAL_FIELDS = ("start", "start_latest", "end_earliest", "end", "start_unbounded", "end_unbounded",
                   "start_is_lower_bound", "end_is_upper_bound")


def day(n):
    """Grid instant n is n days after 2020-01-01T00:00Z."""
    return None if n is None else at(2020) + dt.timedelta(days=n)


@functools.lru_cache(maxsize=None)
def interval(fields):
    f = json.loads(fields)
    return TI(day(f.get("start")), day(f.get("end")), start_latest=day(f.get("start_latest")), end_earliest=day(f.get("end_earliest")),
              **{k: v for k, v in f.items() if v is True})


def stated(time):
    """The stated fields of an interval, grid instants as numbers: the table's own spelling."""
    out = {}
    for name in INTERVAL_FIELDS:
        value = getattr(time, name)
        if value is True:
            out[name] = True
        elif value:
            out[name] = (value - at(2020)).days
            assert day(out[name]) == value
    return out


@functools.lru_cache(maxsize=None)
def table_rule(n):
    names = [f"n{i}" for i in range(n)]
    return RuleSet((RuleDefinition(f"all{n}", "1", tuple(PropositionPattern(X, f"p{i}", Y, name=names[i]) for i in range(n)),
                                   ConclusionTemplate(X, "all", Y), temporal=tuple(overlaps(a, b) for a, b in itertools.combinations(names, 2)),
                                   conclusion_time=b5().Time("while_all", tuple(names))),))


@functools.lru_cache(maxsize=None)
def table_answers():
    """(number of premises, the conclusion's time through the engine, expected fields, the oracle's four ranges)."""
    raw = gzip.decompress(TABLE.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == TABLE_SHA256
    header, *lines = raw.decode().splitlines()
    assert header.split("\t") == ["premises", "premise_fields", "expected", "oracle_start_min", "oracle_start_max",
                                  "oracle_end_min", "oracle_end_max"]
    out = []
    for line in lines:
        n, premises, expected, *oracle = line.split("\t")
        props = tuple(Proposition(f"p{i}", "s", f"p{i}", "o", valid_time=interval(f)) for i, f in enumerate(premises.split(" | ")))
        assert len(props) == int(n)
        execution = execute_rules(props, table_rule(int(n)))
        (step,) = execution.inference_steps
        (conclusion,) = [p for p in execution.propositions if p.id == step.output_proposition_refs[0]]
        assert step.parameters["conclusion_time"]["status"] == "timed" and conclusion.occurred is None
        out.append((int(n), conclusion.valid_time, json.loads(expected), tuple(oracle)))
    return out


def test_a3_while_all_reproduces_the_frozen_table_row_for_row_through_the_engine():
    answers = table_answers()
    assert len(answers) == 26329 and Counter(n for n, *_ in answers) == TABLE_ROWS
    wrong = [(n, stated(got), want) for n, got, want, _ in answers if stated(got) != want]
    assert not wrong, f"{len(wrong)} rows differ, first: {wrong[0]}"
    assert not any(got.start_is_lower_bound or got.end_is_upper_bound for _, got, _, _ in answers)


def test_a4_no_row_is_bolder_or_looser_than_the_oracle():
    """The range of starts and of ends the conclusion states, against the range over every concrete history."""
    def stated_ranges(t):
        f = stated(t)
        start = ("always", "always") if t.start_unbounded else (f.get("start", GRID_LOW), f.get("start_latest", f.get("start")))
        end = ("never", "never") if t.end_unbounded else (f.get("end_earliest", f.get("end")), f.get("end", GRID_HIGH))
        return tuple(str(v) for v in start + end)
    differ = [(n, stated(got), stated_ranges(got), oracle) for n, got, _, oracle in table_answers() if stated_ranges(got) != oracle]
    assert not differ, f"{len(differ)} rows are bolder or looser than the oracle, first: {differ[0]}"


# --------------------------------------------------------------------------
# A5: as_premise copies the named premise's time
# --------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def shapes():
    """B4's frozen grid: every interval shape and every occurrence shape (155 and 13)."""
    states, events = {}, {}
    for _, lk, rk, _, _, lf, rf, *_ in b4t.table_rows():
        for kind, fields in ((lk, lf), (rk, rf)):
            (states if kind == "state" else events).setdefault(fields, b4t._shape(kind, fields))
    return tuple(states.values()), tuple(events.values())


def test_a5_as_premise_gives_the_named_premises_time_field_for_field_for_every_shape():
    n = b5()
    states, events = shapes()
    assert (len(states), len(events)) == (155, 13)
    rule = RuleSet((city(temporal=None, time=n.Time("as_premise", ("job",))),))
    seen = Counter()
    for shape in states + events:
        execution = execute_rules((job(shape), place()), rule)
        (step,) = execution.inference_steps
        (conclusion,) = [p for p in execution.propositions if p.kind == PropositionKind.INFERENCE]
        record = step.parameters["conclusion_time"]
        if shape in (TI(), Occurrence()):
            assert record == unsettled("premise_time_unknown", "as_premise", ["job"])
            assert conclusion.valid_time is None and conclusion.occurred is None
        else:
            assert record["status"] == "timed" and "reason" not in record
            assert (conclusion.valid_time, conclusion.occurred) == ((shape, None) if isinstance(shape, TI) else (None, shape))
            if isinstance(shape, TI):
                assert all(getattr(conclusion.valid_time, f) == getattr(shape, f) for f in INTERVAL_FIELDS)
        seen[record["status"]] += 1
    assert seen == {"timed": 166, "not_established": 2}


# --------------------------------------------------------------------------
# A6, A7: named scenarios and the exact records
# --------------------------------------------------------------------------

WHILE_ALL = {   # job, place, the conclusion's period
    "S1": (JOB_19_21, SINCE_2010, TI(at(2019), at(2021))),
    "S2": (TI(at(2021), start_latest=last(2021), end_unbounded=True), TI(at(2022), end_unbounded=True), TI(at(2022), end_unbounded=True)),
    "S3": (TI(at(2021), at(2024), start_latest=last(2021, 3, 31), end_earliest=at(2023, 1, 2)), TI(at(2021, 2, 1), end_unbounded=True),
           TI(at(2021, 2, 1), at(2024), start_latest=last(2021, 3, 31), end_earliest=at(2023, 1, 2))),
    "S4": (TI(start_latest=last(2024, 3, 5), end_unbounded=True), SINCE_2010, TI(at(2010), start_latest=last(2024, 3, 5), end_unbounded=True)),
}


@pytest.mark.parametrize("sid", sorted(WHILE_ALL))
def test_a6_a7_while_all_gives_the_shared_period_and_records_it(sid):
    job_time, place_time, period = WHILE_ALL[sid]
    t = Thought([city()], [job(job_time), place(place_time)])
    row = t.only
    assert (row.p.subject, row.p.predicate, row.p.object_value, row.p.polarity) == ("asha", "works_in_city", "blr", True)
    assert row.p.valid_time == period and row.p.occurred is None and row.p.kind == PropositionKind.INFERENCE
    assert all(getattr(row.p.valid_time, f) == getattr(period, f) for f in INTERVAL_FIELDS)
    assert (row.decision, row.reasons, row.each, t.overall) == ("accepted", OK, [], "accepted")
    assert t.result.status == ReasoningStatus.COMPLETE and t.time_uncertainty == []
    (step,) = row.steps
    want = timed("while_all", ["job", "place"], valid_time={f: getattr(period, f) for f in INTERVAL_FIELDS if getattr(period, f)})
    assert record_of(step.parameters["conclusion_time"]) == want
    assert step.parameters["temporal"] == [{"relation": "overlaps", "left": "job", "right": "place", "outcome": "established"}]
    (entry,) = t.entries("derived")
    assert (entry.status, entry.explanation_code, entry.rule_id) == ("derived", "RULE_PREMISES_MATCHED", "city@1")
    assert entry.details["conclusion_time"] == step.parameters["conclusion_time"] and entry.output_refs == (row.p.id,)
    # the engine alone gives the same proposition and the same step
    direct = execute_rules((job(job_time), place(place_time)), RuleSet((city(),)))
    assert direct.inference_steps == t.result.inference_steps and row.p in direct.propositions
    (entry,) = direct.trace
    assert (entry.operation, entry.status, entry.details["conclusion_time"]) == ("rule_execution", "derived", step.parameters["conclusion_time"])


def test_a6_s4b_an_end_that_was_only_said_still_establishes_no_overlap_and_gives_no_conclusion():
    t = Thought([city()], [job(TI(at(2019), at(2024, 3, 6), end_is_upper_bound=True)), place()])
    assert t.rows == [] and t.result.inference_steps == () and t.overall == "withheld"
    (entry,) = t.entries("temporal_requirement_")
    assert entry.status == "temporal_requirement_indeterminate" and entry.details["temporal"][0]["reason"] == "bounds_do_not_settle"
    assert len(t.requirement_uncertainty) == 1 and t.time_uncertainty == []


OLD_STINT, CURRENT_STINT = TI(at(2015), at(2017)), TI(at(2022), at(2025))
STINTS = {"S5a": (None, "accepted", "accepted", "accepted"), "S5b": ("old", "accepted", "withheld", "withheld"),
          "S5c": ("current", "withheld", "accepted", "withheld")}


@pytest.mark.parametrize("sid", sorted(STINTS))
@pytest.mark.parametrize("old_id,current_id", [("a1", "a2"), ("a2", "a1")])
def test_a6_a8_a10_two_periods_of_one_claim_are_two_conclusions_whichever_id_sorts_first(sid, old_id, current_id):
    which, old_decision, current_decision, overall = STINTS[sid]
    props = [job(OLD_STINT, old_id), job(CURRENT_STINT, current_id), place()]
    supported = None if which is None else [old_id if which == "old" else current_id, "b"]
    t = Thought([city()], props, supported=supported)
    old, current = t.rows
    assert (old.p.valid_time, current.p.valid_time) == (OLD_STINT, CURRENT_STINT) and old.p.id != current.p.id
    assert [(r.p.subject, r.p.predicate, r.p.object_value) for r in t.rows] == [("asha", "works_in_city", "blr")] * 2
    assert (old.decision, current.decision, t.overall) == (old_decision, current_decision, overall)   # F76: overall is still by the 0.7.0 rule
    assert [len(r.steps) for r in t.rows] == [1, 1] and old.each == current.each == []
    assert old.steps[0].input_refs == (old_id, "b") and current.steps[0].input_refs == (current_id, "b")
    assert t.entries("derived_alternative") == [] and t.entries("no_op") == []


def test_a8_periods_that_touch_at_one_instant_are_never_merged():
    t = Thought([city()], [job(TI(at(2015), at(2017)), "a1"), job(TI(at(2017), at(2019)), "a2"), place()])
    first, second = t.rows
    assert (first.p.valid_time, second.p.valid_time) == (TI(at(2015), at(2017)), TI(at(2017), at(2019)))
    assert first.decision == second.decision == "accepted" and len(t.result.inference_steps) == 2


TWO_EMPLOYERS = {"S6a": (None, "accepted", ["accepted", "accepted"]), "S6b": (("manipal", "manipal"), "accepted", ["accepted", "withheld"]),
                 "S6c": (("apollo", "apollo"), "accepted", ["accepted", "withheld"]), "S6d": (("manipal", "apollo"), "withheld", ["withheld", "withheld"])}


@pytest.mark.parametrize("sid", sorted(TWO_EMPLOYERS))
@pytest.mark.parametrize("manipal_id,apollo_id", [("a1", "a2"), ("a2", "a1")])
def test_a6_a9_a10_a11_a12_one_conclusion_with_two_derivations_each_decided_on_its_own_leaves(sid, manipal_id, apollo_id):
    which, decision, each = TWO_EMPLOYERS[sid]
    ids = {"manipal": (manipal_id, "b1"), "apollo": (apollo_id, "b2")}
    props = [job(JOB_19_21, manipal_id), place(pid="b1"), job(JOB_19_21, apollo_id, "apollo"), place(pid="b2", employer="apollo")]
    supported = None if which is None else [ids[which[0]][0], ids[which[1]][1]]
    t = Thought([city()], props, supported=supported)
    row = t.only
    assert row.p.valid_time == JOB_19_21 and (row.decision, row.each, t.overall) == (decision, each, decision)
    assert row.reasons == (OK if decision == "accepted" else UNSUPPORTED)
    # two steps, one per derivation, each with its own premises, both deriving the one conclusion, with one status
    assert sorted(s.input_refs for s in row.steps) == sorted(ids.values()) and len({s.id for s in row.steps}) == 2
    assert all(s.output_proposition_refs == (row.p.id,) for s in row.steps)
    assert row.steps[0].parameters["conclusion_time"] == row.steps[1].parameters["conclusion_time"]
    first, alternative = t.entries("derived")
    assert first.operation == alternative.operation and first.operation.endswith("rule_execution")
    assert (first.status, first.explanation_code) == ("derived", "RULE_PREMISES_MATCHED")
    assert (alternative.status, alternative.explanation_code) == ("derived_alternative", "ALTERNATIVE_DERIVATION_RECORDED")
    assert alternative.output_refs == first.output_refs == (row.p.id,) and alternative.rule_id == first.rule_id == "city@1"
    assert alternative.details["conclusion_time"] == first.details["conclusion_time"] == row.steps[0].parameters["conclusion_time"]
    assert alternative.details["inference_id"] != first.details["inference_id"]
    assert {alternative.details["inference_id"], first.details["inference_id"]} == {s.id for s in row.steps}
    # A12: every derivation listed, best first; among equals by content (apollo before manipal), never by id
    n = b5()
    assert len(row.e.derivations) == 2 and all(isinstance(d, n.Derivation) for d in row.e.derivations)
    assert [f.name for f in dataclasses.fields(n.Derivation)] == ["step_ids", "decision", "leaf_premise_ids", "reasons"]
    by_leaves = {tuple(sorted(v)): k for k, v in ids.items()}
    listed = [by_leaves[tuple(sorted(d.leaf_premise_ids))] for d in row.e.derivations]
    best = {"S6a": "apollo", "S6b": "manipal", "S6c": "apollo", "S6d": "apollo"}[sid]
    assert listed == [best, "manipal" if best == "apollo" else "apollo"]
    for d in row.e.derivations:
        (step_id,) = d.step_ids
        assert tuple(sorted(next(s for s in row.steps if s.id == step_id).input_refs)) == tuple(sorted(d.leaf_premise_ids))
        assert list(d.reasons) == (OK if d.decision.value == "accepted" else UNSUPPORTED)
    # the conclusion's own figures are its best derivation's: support is never pooled across derivations (S6d)
    assert row.e.premise_coverage.leaf_premise_ids == tuple(sorted(row.e.derivations[0].leaf_premise_ids))
    assert row.e.premise_coverage.complete and len(row.e.evidence_assessments) == 2


def test_a9_the_graph_shows_each_step_deriving_the_one_conclusion():
    from engram_erc import ReasoningGraphBuilder, ReasoningGraphView
    t = Thought([city()], [job(JOB_19_21, "a1"), place(pid="b1"), job(JOB_19_21, "a2", "apollo"), place(pid="b2", employer="apollo")])
    row = t.only
    builder = ReasoningGraphBuilder()
    for proposition in t.result.propositions:
        builder.add_proposition(proposition)
    for step in t.result.inference_steps:
        builder.add_inference(step)
        builder.connect_inference(step.id, premise_proposition_ids=step.input_refs, output_proposition_ids=step.output_proposition_refs)
    view = ReasoningGraphView(builder.build(), t.result.propositions, (), t.result.inference_steps)
    assert [view.conclusions_from(s.id) for s in row.steps] == [(row.p,), (row.p,)]
    assert sorted(tuple(sorted(p.id for p in view.premises_for(s.id))) for s in row.steps) == [("a1", "b1"), ("a2", "b2")]


def test_a11_a_contradiction_on_the_conclusion_applies_to_every_derivation():
    props = [job(JOB_19_21, "a1"), place(pid="b1"), job(JOB_19_21, "a2", "apollo"), place(pid="b2", employer="apollo"),
             P("n", "asha", "works_in_city", "blr", TI(at(2020), end_unbounded=True), polarity=False)]
    t = Thought([city()], props)
    row = t.only
    assert (row.decision, row.each, t.overall) == ("conflicted", ["conflicted", "conflicted"], "conflicted")
    assert t.result.status == ReasoningStatus.CONFLICT


def test_a12_a_single_derivation_lists_none_and_is_evaluated_exactly_as_a_rule_that_declares_nothing():
    facts = [job(JOB_19_21), place()]
    declared, plain = Thought([city()], facts), Thought([city(None, None)], facts)
    assert declared.only.e.derivations == () and plain.only.e.derivations == ()
    assert declared.only.p.id == plain.only.p.id and declared.only.e == plain.only.e      # every field, the new one included
    assert dataclasses.replace(declared.report, evaluations=()) == dataclasses.replace(plain.report, evaluations=())
    assert [f.name for f in dataclasses.fields(type(plain.only.e))][-1] == "derivations"


def test_a6_a15_s7_a_rule_with_requirements_reads_a_timed_conclusion_with_b4s_formulas():
    metro_from = lambda y: P("m", "blr", "has_metro", "namma", TI(at(y), end_unbounded=True))
    t = Thought([city(), metro()], [job(JOB_19_21), place(), metro_from(2023)])                     # S7a
    assert t.only.p.predicate == "works_in_city" and t.only.decision == "accepted"
    (entry,) = t.entries("temporal_requirement_")
    assert entry.status == "temporal_requirement_disproved" and entry.input_refs == (t.only.p.id, "m")   # 0.7.0: indeterminate, derived_premise
    assert entry.details["temporal"] == [{"relation": "overlaps", "left": "incity", "right": "metro", "outcome": "disproved"}]
    assert t.requirement_uncertainty == []
    t = Thought([city(), metro()], [job(JOB_19_21), place(), metro_from(2020)])                     # S7b
    commute, incity = t.row("can_commute_by"), t.row("works_in_city")
    assert commute.p.valid_time == TI(at(2020), at(2021)) and incity.p.valid_time == JOB_19_21
    assert commute.decision == incity.decision == t.overall == "accepted" and t.entries("temporal_requirement_") == []
    assert commute.steps[0].input_refs == (incity.p.id, "m")
    assert commute.e.premise_coverage.leaf_premise_ids == ("a", "b", "m")


def test_a6_a15_a26_s8_three_levels_agree_with_the_second_conclusion_fed_in_as_a_stated_fact():
    k = P("k", "namma", "sells_pass", "monthly", TI(at(2020, 7, 1), at(2022)))
    m = P("m", "blr", "has_metro", "namma", TI(at(2020), end_unbounded=True))
    whole = Thought([city(), metro(), season_pass()], [job(JOB_19_21), place(), m, k])
    assert [(r.p.predicate, r.p.valid_time, r.decision) for r in whole.rows] == [
        ("can_buy", TI(at(2020, 7, 1), at(2021)), "accepted"), ("can_commute_by", TI(at(2020), at(2021)), "accepted"),
        ("works_in_city", JOB_19_21, "accepted")]
    second = whole.row("can_commute_by").p
    fed = Thought([season_pass()], [P("fed", second.subject, second.predicate, second.object_value, second.valid_time), k])
    assert fed.only.p.valid_time == whole.row("can_buy").p.valid_time and fed.only.decision == "accepted"
    assert fed.only.steps[0].parameters["conclusion_time"] == whole.row("can_buy").steps[0].parameters["conclusion_time"]


def uncertainty_for(conclusion_id, rule, reason, name=None, number=1):
    return (f"uncertainty_conclusion_time_{number}", UncertaintyKind.TEMPORAL_AMBIGUITY, (conclusion_id,),
            f"Conclusion of rule {rule}: the time for which it holds is not established ({REASON_TEXT[reason].format(name)}).", HINT)


def as_tuple(item):
    return (item.id, item.kind, item.affected_refs, item.description, item.resolution_hint)


NOT_TIMED = {   # the rule, the job's time, the record
    "S9": (lambda n: city(time=None), JOB_19_21, "no_conclusion_time_declared", None, ()),
    "S12": (lambda n: city(temporal=None, time=n.Time("as_premise", ("job",))), None, "premise_carries_no_time", "as_premise", ("job",)),
    "S12b": (lambda n: city(temporal=None, time=n.Time("as_premise", ("job",))), TI(), "premise_time_unknown", "as_premise", ("job",)),
}


@pytest.mark.parametrize("sid", sorted(NOT_TIMED))
def test_a6_a7_a13_a14_a_time_that_is_not_established_is_recorded_caps_the_decision_and_is_reported_once(sid):
    rule, job_time, reason, mode, names = NOT_TIMED[sid]
    rule = rule(b5())
    t = Thought([rule], [job(job_time), place()])
    row = t.only
    assert row.p.valid_time is None and row.p.occurred is None and row.p.qualifiers == {} and row.p.source_refs == ()
    assert row.steps[0].parameters["conclusion_time"] == unsettled(reason, mode, names)
    assert t.entries("derived")[0].details["conclusion_time"] == unsettled(reason, mode, names)
    assert (row.decision, row.reasons, t.overall) == ("provisional", [NOT_ESTABLISHED], "provisional")
    assert row.e.escalation.value == "review" and NOT_ESTABLISHED in row.e.limitations
    assert [as_tuple(u) for u in t.time_uncertainty] == [uncertainty_for(row.p.id, "city@1", reason, "job")]
    assert t.result.status == ReasoningStatus.COMPLETE                      # a rule fired: complete, with the uncertainty listed
    # unsupported, the decision is withheld as it would be anyway; the limitation is listed in any case
    bare = Thought([rule], [job(job_time), place()], supported=[])
    assert (bare.only.decision, bare.only.reasons) == ("withheld", UNSUPPORTED) and NOT_ESTABLISHED in bare.only.e.limitations
    # the direct callers of the engine record it on the step and build no uncertainty item
    direct = execute_rules((job(job_time), place()), RuleSet((rule,)))
    assert direct.inference_steps == t.result.inference_steps and not hasattr(direct, "uncertainty")
    assert to_reasoning_result(direct, request_id="q").uncertainty == ()


def test_a6_s10_s11_as_premise_takes_an_event_or_a_state_unchanged():
    t = Thought([visit_rule()], [P("v", "asha", "visited", "delhi", on(2021, 6, 1)), job(TI(at(2019), at(2022)), "j")])   # S10
    row = t.only
    assert row.p.occurred == on(2021, 6, 1) and row.p.valid_time is None and row.decision == "accepted"
    assert record_of(row.steps[0].parameters["conclusion_time"]) == timed(
        "as_premise", ["visit"], occurred={"earliest": at(2021, 6, 1), "latest": last(2021, 6, 1)})
    window = Occurrence(at(2021, 3, 1), last(2021, 9, 30))                                                             # S10b
    t = Thought([visit_rule()], [P("v", "asha", "visited", "delhi", window), job(TI(at(2019), at(2022)), "j")])
    assert t.only.p.occurred == window and t.only.decision == "accepted"
    still = TI(at(2022, 2, 1), end_unbounded=True)                                                                     # S11
    t = Thought([moved_rule()], [P("l", "asha", "left_job", "apollo", on(2021, 3, 10)), job(still, "n")])
    row = t.only
    assert row.p.valid_time == still and row.p.occurred is None and row.decision == "accepted"
    assert record_of(row.steps[0].parameters["conclusion_time"]) == timed(
        "as_premise", ["next"], valid_time={"start": at(2022, 2, 1), "end_unbounded": True})
    by = Occurrence(None, last(2024, 3, 5))                                           # an event known only as "by" a day
    t = Thought([city(temporal=None, time=b5().Time("as_premise", ("job",)))], [job(by), place()])
    assert t.only.p.occurred == by
    assert record_of(t.only.steps[0].parameters["conclusion_time"]) == timed("as_premise", ["job"], occurred={"latest": last(2024, 3, 5)})
    assert set(t.only.steps[0].parameters["conclusion_time"]["occurred"]) == {"latest"}          # the unstated side is omitted
    since = Occurrence(at(2021, 6, 1), None)                                           # and one known only as "no earlier than"
    t = Thought([city(temporal=None, time=b5().Time("as_premise", ("job",)))], [job(since), place()])
    assert t.only.p.occurred == since
    assert record_of(t.only.steps[0].parameters["conclusion_time"]) == timed("as_premise", ["job"], occurred={"earliest": at(2021, 6, 1)})
    assert set(t.only.steps[0].parameters["conclusion_time"]["occurred"]) == {"earliest"}


def test_a6_a7_a13_s13_timeless_is_declared_accepted_and_never_read_as_a_time():
    n = b5()
    timeless = city(temporal=None, time=n.Time("timeless"))
    t = Thought([timeless], [job(JOB_19_21), place()])                                                  # S13a
    row = t.only
    assert row.p.valid_time is None and row.p.occurred is None
    assert row.steps[0].parameters["conclusion_time"] == {"status": "timeless", "mode": "timeless", "premises": []}
    assert "temporal" not in row.steps[0].parameters
    assert (row.decision, row.reasons, t.time_uncertainty) == ("accepted", OK, []) and NOT_ESTABLISHED not in row.e.limitations
    m = P("m", "blr", "has_metro", "namma", TI(at(2020), end_unbounded=True))
    t = Thought([timeless, metro()], [job(JOB_19_21), place(), m])                                      # S13b
    assert t.only.p.predicate == "works_in_city" and t.only.decision == "accepted"
    (entry,) = t.entries("temporal_requirement_")
    assert entry.details["temporal"][0]["reason"] == "derived_premise" and len(t.requirement_uncertainty) == 1
    # A26: the same conclusion handed back in as a stated fact is a stated fact with no temporal statement
    fed = Thought([metro()], [P("fed", "asha", "works_in_city", "blr"), m])
    (entry,) = fed.entries("temporal_requirement_")
    assert entry.details["temporal"][0]["reason"] == "no_temporal_statement" and fed.rows == []


def test_a13_a_time_not_established_anywhere_in_a_derivation_caps_what_rests_on_it():
    n = b5()
    onward = RuleDefinition("onward", "1", (PropositionPattern(X, "works_in_city", Y, name="incity"),),
                            ConclusionTemplate(X, "is_based_in", Y), conclusion_time=n.Time("timeless"))
    t = Thought([city(time=None), onward], [job(JOB_19_21), place()])
    based, incity = t.row("is_based_in"), t.row("works_in_city")
    assert based.steps[0].parameters["conclusion_time"]["status"] == "timeless"
    assert (based.decision, based.reasons, based.e.escalation.value) == ("provisional", [NOT_ESTABLISHED], "review")
    assert NOT_ESTABLISHED in based.e.limitations and incity.decision == "provisional"
    assert [u.affected_refs for u in t.time_uncertainty] == [(incity.p.id,)]          # one item, for the conclusion that lacks the time
    # the same chain over a timed conclusion is accepted: a timed or timeless status never caps
    t = Thought([city(), onward], [job(JOB_19_21), place()])
    assert t.row("is_based_in").decision == "accepted" and NOT_ESTABLISHED not in t.row("is_based_in").e.limitations


def test_a14_one_item_per_conclusion_in_step_order_after_b4s_items():
    props = [job(JOB_19_21, "a1"), place(pid="b1"), job(JOB_19_21, "a2", "apollo"), place(pid="b2", employer="apollo"),      # two derivations of one
             job(JOB_19_21, "a3", "fortis"), place(pid="b3", employer="fortis", where="pune"),                              # a second conclusion
             job(JOB_19_21, "a4", "aiims"), place(None, "b4", "aiims", "delhi")]                                            # B4: indeterminate
    t = Thought([city(time=None)], props)
    assert len(t.result.inference_steps) == 3 and len(t.rows) == 2
    first_steps = list(dict.fromkeys(s.output_proposition_refs[0] for s in t.result.inference_steps))
    assert [as_tuple(u) for u in t.time_uncertainty] == [
        uncertainty_for(ref, "city@1", "no_conclusion_time_declared", number=i + 1) for i, ref in enumerate(first_steps)]
    ids = [u.id for u in t.result.uncertainty if u.id.startswith(("uncertainty_temporal_requirement_", "uncertainty_conclusion_time_"))]
    assert ids == ["uncertainty_temporal_requirement_1", "uncertainty_conclusion_time_1", "uncertainty_conclusion_time_2"]
    # A24: every step producing one conclusion carries the same status
    for row in t.rows:
        assert len({json.dumps(s.parameters["conclusion_time"], sort_keys=True) for s in row.steps}) == 1


FUNCTIONAL = frozenset({"works_in_city"})
CONTRADICTION = "CONTRADICTORY_CLAIM_OR_MIXED_EVIDENCE_REQUIRES_ADJUDICATION"
POTENTIAL = "POTENTIAL_CONTRADICTION_REQUIRES_SCOPE_REVIEW"
TWO_CITIES = {   # the second job's time: contradictions, each decision, status
    "S14a": (TI(at(2022), end_unbounded=True), [], "accepted", OK, ReasoningStatus.COMPLETE),
    "S14b": (TI(at(2016), end_unbounded=True), ["definite"], "conflicted", [CONTRADICTION], ReasoningStatus.CONFLICT),
    "S14c": (TI(start_latest=last(2024, 3, 5), end_unbounded=True), ["potential"], "provisional", [POTENTIAL], ReasoningStatus.COMPLETE),
}


@pytest.mark.parametrize("sid", sorted(TWO_CITIES))
def test_a16_s14_two_values_of_a_one_valued_predicate_are_compared_by_their_periods(sid):
    second, contradictions, decision, reasons, status = TWO_CITIES[sid]
    props = [job(TI(at(2015), at(2017)), "a1", "apollo"), place(pid="b1", employer="apollo", where="chennai"), job(second, "a2"), place(pid="b2")]
    t = Thought([city()], props, functional=FUNCTIONAL)
    assert [c.certainty.value for c in t.run.contradictions] == contradictions
    assert [(r.p.object_value, r.decision, r.reasons) for r in t.rows] == [("blr", decision, reasons), ("chennai", decision, reasons)]
    assert t.result.status == status and t.overall == decision
    # 0.7.0, and a rule that declares nothing today: the conclusions carry no time, so the contradiction is potential
    plain = Thought([city(None, None)], props, functional=FUNCTIONAL)
    assert [c.certainty.value for c in plain.run.contradictions] == ["potential"] and plain.overall == "provisional"


@pytest.mark.parametrize("sid,since,contradictions,decision", [("S15a", 2023, [], "accepted"), ("S15b", 2020, ["definite"], "conflicted")])
def test_a16_s15_a_stated_denial_is_compared_with_the_conclusions_period(sid, since, contradictions, decision):
    denial = P("n", "asha", "works_in_city", "blr", TI(at(since), end_unbounded=True), polarity=False)
    t = Thought([city()], [job(JOB_19_21), place(), denial])
    assert [c.certainty.value for c in t.run.contradictions] == contradictions
    assert (t.only.decision, t.overall) == (decision, decision) and t.only.p.valid_time == JOB_19_21
    plain = Thought([city(None, None)], [job(JOB_19_21), place(), denial])
    assert [c.certainty.value for c in plain.run.contradictions] == ["potential"] and plain.overall == "provisional"


def test_a6_s16_a_stated_proposition_never_absorbs_a_derivation_of_a_rule_that_declares():
    n = b5()
    stated_untimed, stated_timed = P("s", "asha", "works_in_city", "blr"), P("s", "asha", "works_in_city", "blr", JOB_19_21)
    for stated_claim in (stated_untimed, stated_timed):                                             # S16a, S16b
        t = Thought([city()], [job(JOB_19_21), place(), stated_claim])
        row = t.only
        assert row.p.valid_time == JOB_19_21 and row.p.id != "s" and t.props["s"] == stated_claim and row.decision == "accepted"
        assert t.entries("no_op") == [] and len(t.result.inference_steps) == 1
    for rule in (city(time=None), city(temporal=None, time=n.Time("timeless"))):                    # rules B and D, both without a time
        t = Thought([rule], [job(JOB_19_21), place(), stated_untimed])
        assert t.only.p.id != "s" and t.only.p.valid_time is None and t.entries("no_op") == []
    t = Thought([city(None, None)], [job(JOB_19_21), place(), stated_untimed])                      # S16c: rule A, as 0.7.0
    assert t.rows == [] and t.result.inference_steps == () and t.overall == "withheld"
    (entry,) = t.entries("no_op")
    assert (entry.status, entry.explanation_code, entry.output_refs) == ("no_op_duplicate_conclusion", "CONCLUSION_ALREADY_PRESENT", ("s",))


def test_a6_a7_s17_a_rule_that_declares_nothing_gives_no_time_no_status_and_never_merges_with_one_that_declares():
    n = b5()
    t = Thought([city(None, None)], [job(JOB_19_21), place()])
    row = t.only
    assert row.p.valid_time is None and row.p.occurred is None and row.record is None
    assert set(row.steps[0].parameters) == {"ruleset_version", "bindings", "description"}
    assert "conclusion_time" not in t.entries("derived")[0].details and (row.decision, t.time_uncertainty) == ("accepted", [])
    assert Thought([city((), None)], [job(JOB_19_21), place()]).only.record is None
    # the same claim from a rule A and from a timeless rule D: two conclusions, in either order of the rules
    declared = city(temporal=None, time=n.Time("timeless"), rule_id="city_timeless")
    for rules in ([city(None, None), declared], [declared, city(None, None)]):
        t = Thought(rules, [job(JOB_19_21), place()])
        assert sorted((r.record or {}).get("status", "none") for r in t.rows) == ["none", "timeless"]
        assert len(t.result.inference_steps) == 2 and t.entries("derived_alternative") == []


def test_a24_conclusions_of_one_claim_with_the_same_time_fields_and_different_statuses_are_never_merged():
    """B5-04: only a conclusion with the same claim, time AND status is the same conclusion. A time that is not established
    and a declared timelessness both leave the time fields empty, and must stay two conclusions with two decisions."""
    n = b5()
    unsettled_rule, timeless_rule = city(time=None), city(temporal=None, time=n.Time("timeless"), rule_id="city_timeless")
    for rules in ([unsettled_rule, timeless_rule], [timeless_rule, unsettled_rule]):
        t = Thought(rules, [job(JOB_19_21), place()])
        assert len(t.rows) == 2 and len({r.p.id for r in t.rows}) == 2 and t.entries("derived_alternative") == []
        by_status = {r.record["status"]: r for r in t.rows}
        assert set(by_status) == {"not_established", "timeless"}
        assert all(r.p.valid_time is None and r.p.occurred is None and len(r.steps) == 1 for r in t.rows)
        assert (by_status["not_established"].decision, by_status["timeless"].decision) == ("provisional", "accepted")
        assert [u.affected_refs for u in t.time_uncertainty] == [(by_status["not_established"].p.id,)]


def test_a25_s20_an_event_under_while_all_is_refused_by_b4_and_the_calculation_is_never_reached():
    t = Thought([city()], [job(on(2021, 6, 1)), place()])
    assert t.rows == [] and t.result.inference_steps == () and t.overall == "withheld"
    (entry,) = t.entries("temporal_requirement_")
    assert entry.status == "temporal_requirement_indeterminate" and entry.details["temporal"][0]["reason"] == "wrong_kind"
    (item,) = t.requirement_uncertainty
    assert item.description == ("Rule city@1 not applied: whether job and place hold at the same time cannot be established "
                                "(job is an event where a state is needed).")
    assert t.time_uncertainty == [] and t.result.status == ReasoningStatus.INDETERMINATE


# --------------------------------------------------------------------------
# A18, A19: the paths agree; nothing else is read
# --------------------------------------------------------------------------

def derived(propositions):
    return sorted(((p.subject, p.predicate, p.object_value, p.polarity, p.valid_time, p.occurred) for p in propositions
                   if p.kind == PropositionKind.INFERENCE), key=repr)


def test_a18_s18_the_engine_orchestrate_recovery_and_counterfactual_give_the_same_conclusions_and_times():
    from engram_erc.counterfactual import RegressionCase, run_counterfactual_suite
    from engram_erc.recovery import RecoveryRequest, run_guarded_recovery
    rules = RuleSet((city(),))
    props = (job(OLD_STINT, "a1"), job(CURRENT_STINT, "a2"), place())
    direct = execute_rules(props, rules)
    run = orchestrate(ReasoningRequest("q", "state_question", props), ruleset=rules)
    recovery = run_guarded_recovery(RecoveryRequest("case", "context", props, rules), ())
    assert [p[4] for p in derived(direct.propositions)] == [OLD_STINT, CURRENT_STINT]
    assert derived(direct.propositions) == derived(run.result.propositions) == derived(recovery.execution.propositions)
    assert direct.inference_steps == run.result.inference_steps == recovery.execution.inference_steps
    assert direct.trace == recovery.execution.trace and not hasattr(recovery.execution, "uncertainty")
    # OP-8, F75: the counterfactual comparison is by claim alone, so two periods of one claim count once there
    (replay,) = run_counterfactual_suite((RegressionCase("case", props, expected_conclusions=()),), rules, rules).case_replays
    assert len(replay.candidate_conclusions) == 1 and replay.candidate_status == ReasoningStatus.COMPLETE


def test_a19_s19_no_qualifier_no_evidence_date_and_no_as_of_changes_a_proposition_a_step_or_a_decision():
    n = b5()
    rules = [city(), visit_rule(), city(temporal=None, time=n.Time("as_premise", ("place",)), rule_id="where")]
    facts = lambda **kw: [job(JOB_19_21, **kw), place(**kw), P("v", "asha", "visited", "delhi", on(2020, 6, 1), **kw)]
    base = Thought(rules, facts())
    assert [r.decision for r in base.rows] == ["accepted"] * 3 and len(base.rows) == 3
    for other in (Thought(rules, facts(), as_of=at(2020)), Thought(rules, facts(), as_of=at(2030)),
                  Thought(rules, facts(), observed_at=at(2000)), Thought(rules, facts(), observed_at=at(2040))):
        assert other.result.propositions == base.result.propositions and other.result.inference_steps == base.result.inference_steps
        assert [(r.decision, r.reasons) for r in other.rows] == [(r.decision, r.reasons) for r in base.rows]
    marked = Thought(rules, facts(qualifiers={"valid_time": "unknown", "end_basis": "closed", "start_basis": "first_said"}))
    assert derived(marked.result.propositions) == derived(base.result.propositions)
    assert marked.result.inference_steps == base.result.inference_steps
    assert [(r.decision, r.reasons) for r in marked.rows] == [(r.decision, r.reasons) for r in base.rows]


# --------------------------------------------------------------------------
# A20: the internal fault
# --------------------------------------------------------------------------

IMPOSSIBLE = {   # premises B4 would never establish as overlapping, reported established by a stand-in for B4's check
    "S22 an event under while_all": (on(2021, 6, 1), SINCE_2010),
    "a premise with no time": (None, SINCE_2010),
    "a premise whose time is unknown": (TI(), SINCE_2010),
    "states that are certainly disjoint": (TI(at(2015), at(2017)), TI(at(2020), end_unbounded=True)),
    "states whose overlap is not certain": (TI(at(2019)), TI(at(2020), end_unbounded=True)),
    "an end that is only an upper bound": (TI(at(2019), at(2024, 3, 6), end_is_upper_bound=True), SINCE_2010),
}


@pytest.mark.parametrize("case", sorted(IMPOSSIBLE))
def test_a20_a_shared_period_that_is_not_certain_after_an_established_match_is_an_internal_fault(case, monkeypatch):
    import sys
    from engram_erc import temporal_requirements
    job_time, place_time = IMPOSSIBLE[case]
    props = (job(job_time), place(place_time))
    rules = RuleSet((city(),))
    assert execute_rules(props, rules).inference_steps == ()            # B4 itself never lets these through
    real = temporal_requirements.check_temporal_requirements

    def established(rule, premises):
        check = real(rule, premises)
        Outcome = type(check.outcome)
        return SimpleNamespace(outcome=Outcome("established"),
                               constraints=tuple({**{k: v for k, v in c.items() if k != "reason"}, "outcome": "established"} for c in check.constraints))

    # B4's check is replaced wherever the package holds it, under whatever name, so that the test assumes nothing about
    # how the engine reaches it
    held = [(module, name) for key, module in list(sys.modules.items()) if key == "engram_erc" or key.startswith("engram_erc.")
            for name, value in list(vars(module).items()) if value is real]
    assert held
    for module, name in held:
        monkeypatch.setattr(module, name, established)
    with pytest.raises(RuntimeError) as raised:
        execute_rules(props, rules)
    assert str(raised.value) == FAULT.format("city@1")
    with pytest.raises(RuntimeError) as raised:
        orchestrate(ReasoningRequest("q", "state_question", props), ruleset=rules)       # no result, so no conclusion is built
    assert str(raised.value) == FAULT.format("city@1")
    # the stand-in changes nothing where the overlap is real: while_all gives a time, never "not established"
    good = execute_rules((job(JOB_19_21), place()), rules)
    assert good.inference_steps[0].parameters["conclusion_time"]["status"] == "timed"


# --------------------------------------------------------------------------
# A21: the limit of 64 derivations
# --------------------------------------------------------------------------

def nested_rules():
    n = b5()
    one = lambda source, out: RuleDefinition(f"r_{out}", "1", (PropositionPattern(X, source, K, name="src"),),
                                             ConclusionTemplate(X, out, "yes"), conclusion_time=n.Time("as_premise", ("src",)))
    join = RuleDefinition("r_join", "1", (PropositionPattern(X, "d1", "yes", name="one"), PropositionPattern(X, "d2", "yes", name="two")),
                          ConclusionTemplate(X, "final", "yes"), temporal=(overlaps("one", "two"),),
                          conclusion_time=n.Time("while_all", ("one", "two")))
    return [one("src1", "d1"), one("src2", "d2"), join]


def nested_facts(n):
    return [P(f"s1_{i}", "x", "src1", f"k{i}", JOB_19_21) for i in range(n)] + [P(f"s2_{i}", "x", "src2", f"k{i}", JOB_19_21) for i in range(n)]


def test_a21d_s21_each_row_of_the_truncation_table():
    rules, facts = nested_rules(), nested_facts(9)
    nothing = Thought(rules, facts, supported=[])                                                    # S21a
    final = nothing.row("final")
    assert len(final.steps) == 1 and [len(nothing.row(p).steps) for p in ("d1", "d2")] == [9, 9]
    assert len(final.e.derivations) == 64 and set(final.each) == {"withheld"}
    assert (final.decision, final.reasons, final.e.escalation.value) == ("provisional", [TRUNCATED], "review")
    assert TRUNCATED in final.e.limitations and nothing.overall == "provisional"
    assert all(len(d.step_ids) == 3 and len(d.leaf_premise_ids) == 2 for d in final.e.derivations)
    assert len({d.step_ids for d in final.e.derivations}) == 64
    assert TRUNCATED not in nothing.row("d1").e.limitations and nothing.row("d1").decision == "withheld"   # nine, all examined
    examined = {tuple(sorted(d.leaf_premise_ids)) for d in final.e.derivations}
    pairs = [(f"s1_{i}", f"s2_{j}") for i in range(9) for j in range(9)]
    inside, outside = [p for p in pairs if p in examined], [p for p in pairs if p not in examined]
    assert (len(inside), len(outside)) == (64, 17)
    one = Thought(rules, facts, supported=inside[0]).row("final")                                    # S21b
    assert (one.decision, one.reasons) == ("accepted", OK) and TRUNCATED in one.e.limitations
    assert one.each == ["accepted"] + ["withheld"] * 63
    beyond = Thought(rules, facts, supported=outside[0]).row("final")                                # S21c
    assert (beyond.decision, beyond.reasons) == ("provisional", [TRUNCATED]) and set(beyond.each) == {"withheld"}
    # a provisional best derivation keeps its own reasons: a potential contradiction beside the one supported derivation
    unsure = P("n", "x", "final", "yes", TI(start_latest=last(2024, 3, 5), end_unbounded=True), polarity=False)
    doubted = Thought(rules, facts + [unsure], supported=list(inside[0]) + ["n"])
    final = doubted.row("final")
    assert [c.certainty.value for c in doubted.run.contradictions] == ["potential"]
    assert (final.decision, final.reasons) == ("provisional", [POTENTIAL]) and TRUNCATED in final.e.limitations
    assert final.each == ["provisional"] + ["withheld"] * 63 and list(final.e.derivations[0].reasons) == [POTENTIAL]
    exact = Thought(nested_rules(), nested_facts(8), supported=[])                                   # S21d
    final = exact.row("final")
    assert len(final.e.derivations) == 64 and (final.decision, final.reasons) == ("withheld", UNSUPPORTED)
    assert TRUNCATED not in final.e.limitations and exact.overall == "withheld"


def test_a21e_a_definite_contradiction_on_the_conclusion_stands_although_derivations_were_left_out():
    denial = P("n", "x", "final", "yes", TI(at(2020), end_unbounded=True), polarity=False)
    t = Thought(nested_rules(), nested_facts(9) + [denial], supported=["s1_0", "s2_0"])
    final = t.row("final")
    assert [c.certainty.value for c in t.run.contradictions] == ["definite"]
    assert final.decision == "conflicted" and TRUNCATED in final.e.limitations and set(final.each) == {"conflicted"}


def plain(value):
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def canonical(p):
    """The key of a stated proposition as B5-05 words it, written here independently of the implementation."""
    instant = lambda m: None if m is None else m.astimezone(UTC).isoformat(timespec="microseconds")
    t, o = p.valid_time, p.occurred
    return json.dumps({
        "subject": p.subject, "predicate": p.predicate, "object": plain(p.object_value), "polarity": p.polarity, "kind": p.kind.value,
        "valid_time": None if t is None else {**{f: instant(getattr(t, f)) for f in INTERVAL_FIELDS[:4]}, **{f: getattr(t, f) for f in INTERVAL_FIELDS[4:]}},
        "occurred": None if o is None else {"earliest": instant(o.earliest), "latest": instant(o.latest)},
        "qualifiers": plain(p.qualifiers)}, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def any_source():
    """One premise, any subject and object, a fixed timeless conclusion: every matching fact is one more derivation."""
    return RuleDefinition("any", "1", (PropositionPattern(S, "src", K, name="src"),), ConclusionTemplate("thing", "holds", "yes"),
                          conclusion_time=b5().Time("timeless"))


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ORDERED = [   # facts that differ in one listed member each; the order of derivations is the order of their canonical text
    dict(obj="Z"), dict(obj="a"), dict(obj="é"), dict(obj=10), dict(obj=2), dict(obj="a", subject="t"),
    dict(obj="a", time=JOB_19_21), dict(obj="a", time=TI(at(2019), at(2021), start_latest=last(2019))),
    dict(obj="a", time=TI(at(2019), end_unbounded=True)), dict(obj="a", time=on(2021, 6, 1)), dict(obj="a", time=Occurrence(None, at(2021))),
    dict(obj="a", qualifiers={"status": "active"}), dict(obj="a", qualifiers={"status": "active", "n": {"b": 1, "a": 2}}),
]


def fact(pid, obj="a", subject="s", time=None, **kw):
    return P(pid, subject, "src", obj, time, **kw)


@pytest.mark.parametrize("seed", range(4))
def test_a21a_derivations_are_evaluated_in_ascending_order_of_the_content_key_and_no_id_enters_it(seed):
    ids = [f"p{i:02d}" for i in range(len(ORDERED))]
    random.Random(seed).shuffle(ids)
    facts = [fact(pid, source_refs=(f"sentence:{pid}",), **spec) for pid, spec in zip(ids, ORDERED)]
    t = Thought([any_source()], facts, supported=[])
    row = t.only
    assert len(row.steps) == len(ORDERED) and set(row.each) == {"withheld"} and len(row.e.derivations) == len(ORDERED)
    by_id = {f.id: f for f in facts}
    listed = [canonical(by_id[d.leaf_premise_ids[0]]) for d in row.e.derivations]
    assert listed == sorted(canonical(f) for f in facts) and len(set(listed)) == len(ORDERED)
    assert listed.index(canonical(fact("x", obj="é"))) < listed.index(canonical(fact("x", obj="a")))   # non-ASCII is escaped
    assert listed.index(canonical(fact("x", obj=10))) < listed.index(canonical(fact("x", obj=2)))           # text order, part by part


SAME_KEY = {   # two facts whose keys must be equal: the limit, falling between them, leaves both out
    "ids alone differ": (dict(), dict()),
    "source references differ": (dict(source_refs=("sentence:1",)), dict(source_refs=("sentence:2", "sentence:3"))),
    "one instant given in two zones": (dict(time=TI(at(2019), at(2021))),
                                       dict(time=TI(at(2019).astimezone(IST), at(2021).astimezone(IST)))),
    "qualifiers filled in another order": (dict(qualifiers={"a": 1, "b": 2}), dict(qualifiers={"b": 2, "a": 1})),
    "nested qualifiers filled in another order": (dict(qualifiers={"q": {"x": 1, "y": {"m": 1, "n": 2}}}),
                                                  dict(qualifiers={"q": {"y": {"n": 2, "m": 1}, "x": 1}})),
}
OTHER_KEY = {   # two facts that differ in one listed member: two keys, so the limit may fall between them
    "the object differs": (dict(obj="m"), dict(obj="m2")),
    "the subject differs": (dict(), dict(subject="t")),
    "the kind differs": (dict(), dict(kind=PropositionKind.HYPOTHESIS)),
    "the period differs": (dict(time=TI(at(2019), at(2021))), dict(time=TI(at(2019), at(2022)))),
    "a flag of the period differs": (dict(time=TI(at(2019), at(2021))), dict(time=TI(at(2019), at(2021), end_is_upper_bound=True))),
    "the event window differs": (dict(time=on(2021, 6, 1)), dict(time=on(2021, 6, 2))),
    "a qualifier differs": (dict(qualifiers={"a": 1}), dict(qualifiers={"a": 2})),
    "a nested qualifier differs": (dict(qualifiers={"q": {"x": 1}}), dict(qualifiers={"q": {"x": 2}})),
    "a list in a qualifier is in another order": (dict(qualifiers={"q": [1, 2]}), dict(qualifiers={"q": [2, 1]})),
}


@pytest.mark.parametrize("case", sorted(SAME_KEY) + sorted(OTHER_KEY))
@pytest.mark.parametrize("first_id,second_id", [("m1", "m2"), ("m2", "m1")])
def test_a21c_a21g_the_limit_never_divides_two_derivations_equal_in_content_and_divides_any_others(case, first_id, second_id):
    same = case in SAME_KEY
    a, b = (SAME_KEY if same else OTHER_KEY)[case]
    pair = [fact(first_id, **{"obj": "m", **a}), fact(second_id, **{"obj": "m", **b})]
    assert (canonical(pair[0]) == canonical(pair[1])) == same
    facts = [fact(f"f{i:02d}", obj=f"a{i:02d}") for i in range(63)] + pair + [fact("z", obj="z")]     # 66 derivations of one conclusion
    assert sum(canonical(f) < min(map(canonical, pair)) for f in facts) == 63
    t = Thought([any_source()], facts, supported=[])
    row = t.only
    assert len(row.steps) == 66 and TRUNCATED in row.e.limitations and (row.decision, row.reasons) == ("provisional", [TRUNCATED])
    examined = {d.leaf_premise_ids[0] for d in row.e.derivations}
    assert {f"f{i:02d}" for i in range(63)} <= examined and "z" not in examined or not same
    if same:
        assert len(row.e.derivations) == 63 and not {first_id, second_id} & examined      # the pair is left out whole
    else:
        assert len(row.e.derivations) == 64 and len({first_id, second_id, "z"} & examined) == 1
        (taken,) = {first_id, second_id, "z"} & examined
        candidates = {first_id: pair[0], second_id: pair[1], "z": facts[-1]}
        assert canonical(candidates[taken]) == min(canonical(f) for f in candidates.values())   # the one whose key comes first


SEEDS = range(12)


def shuffled_world(contents, seed):
    """`contents`: (predicate, object, copy number) per fact. The same facts under another assignment of ids; like the
    Engram adapter, each proposition names the generated id of the sentence it came from."""
    ids = [f"p{m:03d}" for m in range(len(contents))]
    random.Random(seed).shuffle(ids)
    props = tuple(Proposition(i, "x", c[0], c[1], valid_time=JOB_19_21, source_refs=(f"sentence:{i}",)) for i, c in zip(ids, contents))
    return props, dict(zip(ids, contents))


@functools.lru_cache(maxsize=None)
def _world_run(contents, seed):
    props, content = shuffled_world(contents, seed)
    run = orchestrate(ReasoningRequest("q", "state_question", props), ruleset=RuleSet(tuple(nested_rules())))
    final = next(p.id for p in run.result.propositions if p.predicate == "final")
    return run.result, content, final


def decide(contents, seed, supported):
    """The final conclusion's decision, the derivations examined (by content), and whether any were left out."""
    result, content, final = _world_run(contents, seed)
    back = {c: i for i, c in content.items()}
    evidence, links = backing([back[c] for c in supported])
    report = evaluate_conclusions(result, evidence=evidence, evidence_links=links)
    e = next(e for e in report.evaluations if e.conclusion_id == final)
    examined = frozenset(frozenset(content[leaf] for leaf in d.leaf_premise_ids) for d in e.derivations)
    return e.decision.value, examined, len(e.derivations), TRUNCATED in e.limitations


def nested_contents(n, duplicate=False):
    first = [("src1", f"k{i}", 0) for i in range(n)]
    second = [("src2", "k0", 0), ("src2", "k0", 1)] + [("src2", f"k{j}", 0) for j in range(1, n - 1)] if duplicate \
        else [("src2", f"k{j}", 0) for j in range(n)]
    return tuple(first + second), [(a, b) for a in first for b in second]


ID_INDEPENDENT = {   # facts per side, one fact present twice, derivations, examined, truncated
    "S23": (9, False, 81, 64, True),
    "S24": (9, True, 81, 63, True),
    "S25": (8, False, 64, 64, False),
}


@pytest.mark.parametrize("sid", sorted(ID_INDEPENDENT))
def test_a10_a21b_a21c_a21e_the_derivations_examined_and_every_decision_are_the_same_under_twelve_id_assignments(sid):
    n, duplicate, total, examined_count, truncated = ID_INDEPENDENT[sid]
    contents, pairs = nested_contents(n, duplicate)
    assert len(pairs) == total
    nothing = {seed: decide(contents, seed, ()) for seed in SEEDS}
    assert {v[1] for v in nothing.values()} == {nothing[0][1]}                       # the same derivations, by content, every time
    assert {(v[0], v[2], v[3]) for v in nothing.values()} == {("provisional" if truncated else "withheld", examined_count, truncated)}
    examined = nothing[0][1]
    outcomes = Counter()
    for pair in pairs:
        decisions = {decide(contents, seed, pair)[0] for seed in SEEDS}
        assert len(decisions) == 1, f"the decision for {pair} changes with the ids: {decisions}"
        (decision,) = decisions
        # one fully supported derivation is enough when it is among those examined; beyond them nothing definite is said
        assert decision == ("accepted" if frozenset(pair) in examined else "provisional")
        outcomes[decision] += 1
    assert outcomes == Counter({"accepted": examined_count, **({"provisional": total - examined_count} if truncated else {})})


def test_a21f_s26_more_than_64_derivations_identical_in_content_the_documented_exception():
    """F85, accepted as a bounded limitation at the freeze: the first tie group alone has 65 members, so its first 64 by
    step id are examined. Which they are may change with the ids; the outcome is accepted or provisional only."""
    contents = tuple([("src1", "k0", n) for n in range(65)] + [("src2", "k0", 0)])
    seen = Counter()
    for seed in SEEDS:
        decision, examined, count, truncated = decide(contents, seed, ())
        assert (decision, count, truncated) == ("provisional", 64, True)
        for copy in contents[:65]:
            decision, examined, count, truncated = decide(contents, seed, (copy, contents[65]))
            assert (count, truncated) == (64, True) and decision in ("accepted", "provisional")
            assert (decision == "accepted") == (frozenset((copy, contents[65])) in examined)
            seen[decision] += 1
    assert seen == {"accepted": 64 * len(SEEDS), "provisional": len(SEEDS)}


# --------------------------------------------------------------------------
# A22, A24: version, pins, names; the Proposition contract
# --------------------------------------------------------------------------

PUBLIC_NAMES_AT_B5 = (309, "66d154490ab78ed4793db270dead6840ebca0e414cb22137114a4ac8d0f5a2a3")   # the 305 of 0.7.0 and the four below
NEW_PUBLIC_NAMES = ["ConclusionTime", "ConclusionTimeKind", "ConclusionTimeStatus", "DerivationEvaluation"]
UNCHANGED_AT_B5 = {"temporal_requirements.py": "e33ae6a7228050027ed95ede70f523e15065def31feab25fe2449e236097b080",
                   "primitives/comparison.py": "ead6a041f46db99faac626d43493350bcaaae3329316251322484a1411f20d8f",
                   "contracts.py": "64ebe6722c734ad87f6163007b7c403b057765ba0fe1c3a6b7042a058e9fe8cd"}


def test_a22_version_and_release_pins():
    assert engram_erc.__version__ == (PKG / "VERSION").read_text().strip() == "0.8.0"
    assert pins.ERC_1X_FILES_CHANGED_SINCE_0_4_0 == {"contracts.py", "primitives/comparison.py", "rules.py", "inference.py",
                                                    "orchestration.py", "evaluation.py"}
    for rel in ("rules.py", "inference.py", "orchestration.py", "evaluation.py"):
        digest, release, reason = pins.ERC_1X_RELEASE_PINS[rel]
        assert release == "0.8.0" and "B5" in reason
        assert digest == hashlib.sha256((PKG / rel).read_bytes()).hexdigest() != pins.ERC_1X_SHA256_AT_0_4_0[rel]
    assert pins.ERC_1X_RELEASE_PINS["contracts.py"][1] == "0.5.0" and pins.ERC_1X_RELEASE_PINS["primitives/comparison.py"][1] == "0.6.0"
    for rel, digest in UNCHANGED_AT_B5.items():
        assert hashlib.sha256((PKG / rel).read_bytes()).hexdigest() == digest
    canonical_table = "\n".join(f"{rel} {digest}" for rel, digest in sorted(pins.ERC_1X_SHA256_AT_0_4_0.items()))
    assert hashlib.sha256(canonical_table.encode()).hexdigest() == pins.ERC_1X_HISTORICAL_TABLE_SHA256 == "1d72e781ec1dcd5fcbbf20ad1580cd28d6321047cf1498d33049fe1763e53dda"


def test_a22_exactly_four_names_become_public_and_the_calculation_is_not_one_of_them():
    names = sorted(engram_erc.__all__)
    assert (len(names), hashlib.sha256(json.dumps(names).encode()).hexdigest()) == PUBLIC_NAMES_AT_B5
    assert [name for name in NEW_PUBLIC_NAMES if name in names] == NEW_PUBLIC_NAMES
    n = b5()
    assert (engram_erc.ConclusionTime, engram_erc.ConclusionTimeKind, engram_erc.ConclusionTimeStatus, engram_erc.DerivationEvaluation) == (
        n.Time, n.Kind, n.Status, n.Derivation)
    # how a time is worked out is not public: the 305 names of 0.7.0 and these four, and nothing else (Amendment 1: where
    # the four are defined inside the package is not part of the contract)
    assert all(isinstance(getattr(engram_erc, name), type) for name in NEW_PUBLIC_NAMES)


def test_a22_the_engine_reports_the_package_version():
    assert Thought([city()], [job(JOB_19_21), place()]).result.engine_version == engram_erc.__version__ == "0.8.0"


def test_a24_the_status_is_on_the_steps_and_the_proposition_contract_is_unchanged():
    assert b5().Status.TIMED.value == "timed"
    assert [f.name for f in dataclasses.fields(Proposition)] == ["id", "subject", "predicate", "object_value", "polarity", "kind",
                                                                "source_refs", "valid_time", "qualifiers", "occurred"]
    assert hashlib.sha256((PKG / "contracts.py").read_bytes()).hexdigest() == pins.ERC_1X_RELEASE_PINS["contracts.py"][0]
    n = b5()
    statuses = {}
    for rule in (city(), city(time=None), city(temporal=None, time=n.Time("timeless")), city(None, None)):
        t = Thought([rule], [job(JOB_19_21), place()])
        p = t.only.p
        statuses[(t.only.record or {}).get("status")] = (p.valid_time, p.occurred, dict(p.qualifiers), p.source_refs, p.kind)
    untimed = (None, None, {}, (), PropositionKind.INFERENCE)
    assert statuses == {"timed": (JOB_19_21,) + untimed[1:], "not_established": untimed, "timeless": untimed, None: untimed}
