"""reason() and explain(): ERC over the knowledge layers. Nothing is stored, so deleting a sentence needs no step here: the next
reason() simply no longer sees it. The engine and the layers are only read."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from engram_erc import DecisionPolicy, EvaluationReport, evaluate_conclusions, orchestrate
from engram_erc.orchestration import OrchestrationLimits, OrchestrationResult

from .knowledge import AdaptedRequest, KnowledgeAdapter


@dataclass(frozen=True)
class Reasoning:
    adapted: AdaptedRequest
    orchestration: OrchestrationResult
    evaluation: EvaluationReport

    @property
    def result(self):
        return self.orchestration.result


class Reasoner:
    def __init__(self, kb, *, catalog=None):
        self.kb = kb
        self.adapter = KnowledgeAdapter(kb)
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

    def explain(self, reasoning: Reasoning) -> list[str]:
        """Plain lines: the strategy, each conclusion with its decision and the sentences under it, conflicts and what is unknown."""
        r, props = reasoning.result, {p.id: p for p in reasoning.result.propositions}
        lines = [f"strategy {reasoning.orchestration.selected_strategy.strategy_id}@{reasoning.orchestration.selected_strategy.version}, "
                 f"status {r.status.value}, as of {reasoning.adapted.request.as_of.date().isoformat()}, overall {reasoning.evaluation.overall_decision.value}"]
        for ev in reasoning.evaluation.evaluations:
            lines.append(f"conclusion: {self._claim(props[ev.conclusion_id])} -> {ev.decision.value} ({', '.join(ev.reasons)})")
            for leaf in ev.premise_coverage.leaf_premise_ids:
                lines.append(f"  because: {self._claim(props[leaf])}")
                lines += [f"    {s}" for s in self._sentences(leaf)]
        for c in reasoning.orchestration.contradictions:
            lines.append(f"{c.certainty.value} contradiction: {self._claim(props[c.left_id])} / {self._claim(props[c.right_id])}")
        for u in r.uncertainty:
            if u.kind.value != "missing_premise": lines.append(f"uncertain: {u.description}")
        for fid, why in reasoning.adapted.left_out:
            lines.append(f"left out: fact {fid} ({why})")
        return lines
