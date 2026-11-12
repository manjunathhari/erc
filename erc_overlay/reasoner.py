"""reason() and explain(): ERC over the knowledge layers. Nothing is stored, so deleting a sentence needs no step here: the next
reason() simply no longer sees it. The engine and the layers are only read."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from engram_erc import DecisionPolicy, EvaluationReport, evaluate_conclusions, orchestrate
from engram_erc.conclusion_time import reason_text
from engram_erc.orchestration import OrchestrationLimits, OrchestrationResult

from .knowledge import NOT_IN_ZONE, AdaptedRequest, KnowledgeAdapter


@dataclass(frozen=True)
class Reasoning:
    adapted: AdaptedRequest
    orchestration: OrchestrationResult
    evaluation: EvaluationReport

    @property
    def result(self):
        return self.orchestration.result


class Reasoner:
    def __init__(self, kb, *, catalog=None, day_zone=None):
        self.kb = kb
        self.adapter = KnowledgeAdapter(kb, day_zone=day_zone)
        self.catalog = catalog

    def reason(self, entity: str, *, task_type: str = "state_question", ruleset=None, as_of: dt.datetime | None = None,
               hops: int = 1) -> Reasoning:
        adapted = self.adapter.request_for(entity, task_type=task_type, as_of=as_of, ruleset=ruleset, hops=hops)
        limits = OrchestrationLimits(functional_predicates=adapted.functional_predicates)
        run = orchestrate(adapted.request, ruleset=ruleset, catalog=self.catalog, limits=limits)
        report = evaluate_conclusions(run.result, evidence=adapted.request.evidence, evidence_links=adapted.request.evidence_links,
                                      policy=DecisionPolicy(functional_predicates=adapted.functional_predicates))
        return Reasoning(adapted, run, report)

    # ---------- explain ----------
    def _name(self, value):
        if isinstance(value, str):
            e = self.kb.entity(value)
            if e: return e.canonical_name
        return str(value)

    def _claim(self, p) -> str:
        return f"{self._name(p.subject)} {'' if p.polarity else 'not '}{p.predicate} {self._name(p.object_value)}"

    def _sentences(self, prop_id: str) -> list[str]:
        if not prop_id.startswith("fact:"): return []
        return [f'sentence {s.sid} ({s.speaker}, {s.date}): "{s.text}"' for s in self.kb.trace(prop_id[5:])]

    @staticmethod
    def _day(moment) -> str:
        return moment.date().isoformat()

    def _state_line(self, p, request) -> str:
        """A fact's Engram state, how it was sent, and the time it holds for: so a confirmed fact reads differently from an unchecked
        one. No end is shown that Engram does not hold: a state still going says so. A start that was only first said is "from no
        later than" that day, never "from" it; an end whose date was only said is "at the latest"."""
        q, day = p.qualifiers, self._day
        record = next((e for e in request.evidence if e.id == f"state:{p.id[5:]}"), None)
        sent = f"sent as {p.kind.value}" + (f" with a qualifying state record ({', '.join(record.metadata['qualified_for'])})" if record else "")
        t, o = p.valid_time, p.occurred
        if o is not None:
            if o.earliest is None: when = f"event by {day(o.latest)}"
            elif o.earliest.date() == o.latest.date(): when = f"event on {day(o.earliest)}"
            else: when = f"event between {day(o.earliest)} and {day(o.latest)}"
        elif t is None: when = "valid time unknown"
        else:
            if t.start: when = f"valid {day(t.start)}"
            elif t.start_latest: when = f"valid from no later than {day(t.start_latest)}"
            else: when = "valid ?"
            if t.end_unbounded: when += ", still going"
            else: when += f" to {day(t.end) if t.end else '?'}" + (" at the latest" if t.end_is_upper_bound else "")
        return f"state: status {q['status']}, validation {q['validation_status']}, source {q['source_type']}; {sent}; {when}"

    def _time_line(self, p, request, zone: str) -> str:
        """What is known about a fact's time and where it came from: a stated boundary, with its range when it was stated only to a
        year or month; a start that was never stated, only first said; how Engram ended the period, and whether that date was
        stated or only said; an event's window. A date that was only said is never shown as stated. An end is shown, as on the
        state line, as the first day the state no longer holds."""
        q, t, o, day = p.qualifiers, p.valid_time, p.occurred, self._day
        if o is not None:
            if q["start_basis"] != "stated": return f"time: event not stated (first said {day(o.latest)})"
            if o.earliest.date() == o.latest.date(): return f"time: event stated {day(o.earliest)}"
            return f"time: event stated, between {day(o.earliest)} and {day(o.latest)}"
        if t is None:
            record = next((e for e in request.evidence if e.id == f"state:{p.id[5:]}"), None)
            return f"time: not known ({NOT_IN_ZONE} {zone})" if record and NOT_IN_ZONE in record.metadata["qualified_for"] else "time: not known"
        if t.start is None and t.start_latest is None: start = "start not known"  # a known end with no start: nothing was stated and nothing first said
        elif q["start_basis"] == "first_said": start = f"start not stated (first said {day(t.start_latest)})"
        elif t.start_latest: start = f"start stated, between {day(t.start)} and {day(t.start_latest)}"
        else: start = f"start stated {day(t.start)}"
        if t.end_unbounded: end = "end open"
        elif t.end_earliest: end = f"end {q['end_basis']}, between {day(t.end_earliest)} and {day(t.end)}"
        elif t.end_is_upper_bound: end = f"end {q['end_basis']}, no later than {day(t.end)}"
        else: end = f"end {q['end_basis']} {day(t.end)}"
        return f"time: {start}; {end}"

    def _conclusion_time_line(self, p, record, rule) -> str:
        """The line under a conclusion of a rule that declares (ERC 0.8.0): its period or event window and what it follows
        from, or that it is timeless by declaration, or that its time is not established and why. Each side of a period is
        worded by its status in the contract, so a side that is not known never reads as one that is unbounded. An end day
        is the first day the state no longer holds, and says so."""
        if record["status"] == "timeless": return f"time: timeless (declared by rule {rule})"
        if record["status"] == "not_established": return f"time: not established ({reason_text(record)})"
        names, day, t, o = record["premises"], self._day, p.valid_time, p.occurred
        basis = f"while {' and '.join(names)} all hold, rule {rule}" if record["mode"] == "while_all" else f"the time of {names[0]}, rule {rule}"
        if o is not None:
            if o.earliest is None: when = f"event by {day(o.latest)}"
            elif o.latest is None: when = f"event no earlier than {day(o.earliest)}"
            elif o.earliest.date() == o.latest.date(): when = f"event on {day(o.earliest)}"
            else: when = f"event between {day(o.earliest)} and {day(o.latest)}"
            return f"time: {when}; {basis}"
        start = {"exact": lambda: f"from {day(t.start)}", "within": lambda: f"from between {day(t.start)} and {day(t.start_latest)}",
                 "no_later_than": lambda: f"from no later than {day(t.start_latest)}", "no_earlier_than": lambda: f"from no earlier than {day(t.start)}",
                 "unknown": lambda: "start not known", "unbounded": lambda: "with no stated beginning"}[t.start_status.value]()
        end = {"exact": lambda: f"to {day(t.end)} (end exclusive)", "within": lambda: f"to between {day(t.end_earliest)} and {day(t.end)} (end exclusive)",
               "no_later_than": lambda: f"to no later than {day(t.end)} (end exclusive)", "no_earlier_than": lambda: f"to no earlier than {day(t.end_earliest)} (end exclusive)",
               "unknown": lambda: "end not known", "unbounded": lambda: "still going"}[t.end_status.value]()
        return f"time: holds {start} {end}; {basis}"

    def explain(self, reasoning: Reasoning) -> list[str]:
        """Plain lines: the strategy and the zone calendar days were read in, each conclusion with its decision, the time it holds for when its rule declares one, the facts under it and its other derivations (each fact with its Engram state, how it was
        sent and its dates, a `time:` line saying what is stated and what is only first said, then its sentences), every fact sent
        with its `time:` line, conflicts, what is unknown, and every fact left out and why."""
        r, props, request = reasoning.result, {p.id: p for p in reasoning.result.propositions}, reasoning.adapted.request
        zone = reasoning.adapted.day_zone
        lines = [f"strategy {reasoning.orchestration.selected_strategy.strategy_id}@{reasoning.orchestration.selected_strategy.version}, "
                 f"status {r.status.value}, as of {reasoning.adapted.request.as_of.date().isoformat()}, overall {reasoning.evaluation.overall_decision.value}, "
                 f"zone {zone}"]
        for ev in reasoning.evaluation.evaluations:
            lines.append(f"conclusion: {self._claim(props[ev.conclusion_id])} -> {ev.decision.value} ({', '.join(ev.reasons)})")
            producing = [s for s in r.inference_steps if ev.conclusion_id in s.output_proposition_refs]
            record = producing[0].parameters.get("conclusion_time") if producing else None
            if record: lines.append(f"  {self._conclusion_time_line(props[ev.conclusion_id], record, producing[0].rule_id)}")
            for leaf in ev.premise_coverage.leaf_premise_ids:
                lines.append(f"  because: {self._claim(props[leaf])}")
                if leaf.startswith("fact:"): lines.append(f"    {self._state_line(props[leaf], request)}")
                if leaf.startswith("fact:"): lines.append(f"    {self._time_line(props[leaf], request, zone)}")
                lines += [f"    {s}" for s in self._sentences(leaf)]
            for d in ev.derivations[1:]:
                own = next(s for s in producing if s.id in d.step_ids)
                lines.append(f"  also derived by rule {own.rule_id} ({d.decision.value}) from: " + "; ".join(self._claim(props[l]) for l in d.leaf_premise_ids))
            if "ALTERNATIVE_DERIVATIONS_TRUNCATED" in ev.limitations: lines.append("  further derivations were not examined (limit 64)")
        for p in request.propositions:
            lines.append(f"fact: {self._claim(p)}; {self._state_line(p, request)}")
            lines.append(f"  {self._time_line(p, request, zone)}")
        for c in reasoning.orchestration.contradictions:
            lines.append(f"{c.certainty.value} contradiction: {self._claim(props[c.left_id])} / {self._claim(props[c.right_id])}")
        for u in r.uncertainty:
            if u.kind.value != "missing_premise": lines.append(f"uncertain: {u.description}")
        for l in reasoning.adapted.left_out:
            s = l.state
            lines.append(f"left out: fact {l.fact_id} ({l.reason}; status {s['status']}, validation {s['validation_status']}, "
                         f"source {s['source_type']}; needs {l.needs})")
        return lines
