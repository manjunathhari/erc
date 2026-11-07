# Engram Reasoning Core — ERC-1.8

ERC-1.8 is cumulative through ERC-1.7. It adds **context-aware, advisory strategy adaptation** using explicitly adjudicated outcomes or scores supplied by an external experience system.

## What ERC-1.8 adds

- Deterministic ranking of strategies that have already passed the existing `StrategyCatalog` eligibility gates. `orchestrate(..., strategy_ref_override=...)` can execute the selected eligible strategy and rechecks the gates before honoring it.
- Context matching by task type and an exact set of context tags; an explicitly flagged task-level fallback can be enabled.
- Minimum adjudicated sample threshold (default: 5). If no strategy meets it, ERC abstains from adaptation and preserves catalog priority.
- Ranking explanations, score origin, support count, context used, fallback status and source/event references and an explicit uncertainty note.
- Optional external score contract (`StrategyExperienceScore`) for a thin adapter over existing Engram P6.3 experience scoring. ERC does not duplicate P6's scorer or persistence.
- `StrategyCatalog.eligible(...)` exposes the canonical eligibility gate; `rank_catalog_strategies(...)` applies adaptation only after that gate.

## Public API

```python
from engram_erc import (
    AdaptationPolicy, FeedbackLedger, StrategyCatalog,
    rank_catalog_strategies, StrategyExperienceScore, orchestrate,
)

report = rank_catalog_strategies(
    request,
    catalog,
    has_rules=ruleset is not None,
    context_tags=("robotic", "colorectal"),
    feedback=existing_adjudicated_feedback_ledger,
    policy=AdaptationPolicy(
        min_adjudicated_events=5,
        allow_task_level_fallback=True,
        require_context_match=False,
    ),
)

print(report.status, report.selected_strategy_ref)

# Optional execution: orchestrate re-checks eligibility before honoring the choice.
result = orchestrate(
    request, ruleset=ruleset, catalog=catalog,
    strategy_ref_override=report.selected_strategy_ref,
)

for item in report.rankings:
    print(item.rank, item.strategy_ref, item.score,
          item.sample_size, item.context_used, item.explanation)
```

For an existing P6.3 score, the integration layer can map its already-computed value into `StrategyExperienceScore`:

```python
score = StrategyExperienceScore(
    strategy_ref="rule_reasoning@1.0",
    context_key="surgical_case_review|colorectal&robotic",
    score=0.82,                 # normalized upstream score in [0, 1]
    sample_size=24,             # upstream effective adjudicated support
    source_ref="p6-policy-score-ref",
    uncertainty_note="Provided by P6 adapter",
)
```

Pass it in `external_scores=(score,)`. ERC accepts the upstream score as an opaque advisory input; the P6 adapter remains responsible for mapping its uncertainty and sample-size semantics correctly. External exact-context scores take precedence over ERC feedback for that strategy/context. Multiple matching external scores are resolved deterministically by largest sample size, then source reference.

## Decision and safety semantics

1. **Eligibility first.** A strategy that fails task-type, evidence, or ruleset requirements cannot be promoted by historical performance. `rank_catalog_strategies` enforces this ordering.
2. **No evidence-driven strategy creation.** ERC ranks only supplied catalog strategies; it does not invent strategies or alter their definitions.
3. **Context discipline.** Exact context-tag-set matches are preferred. If they do not meet the threshold, task-level fallback is optional and explicitly marked. No partial-tag blending is performed.
4. **Abstention.** With fewer than the configured minimum adjudicated observations, no adaptive preference is made. The original catalog priority and deterministic tie-break are retained.
5. **Outcome discipline.** Only `verified_supported` and `contradicted` events enter the descriptive rate and support count. `inconclusive` and `superseded` do not count as successes or failures.
6. **No causal or clinical prediction.** The observed fraction is historical descriptive feedback, not a calibrated probability, causal estimate, patient-level risk prediction, or proof that a strategy caused an outcome.
7. **No automatic mutation.** Ranking does not change P6 policies, rules, evidence reliability, registry records, or strategy priorities. Human/domain governance remains outside this module.

## Important integration boundary

- Existing Engram P6 remains the authoritative experience/adaptation system. ERC-1.8 defines an adapter contract; it does **not** claim a live P6 connection or write to P6.
- Existing registry outcomes remain authoritative. The registry/adjudication adapter must explicitly decide when an outcome is mature enough and which strategy it can legitimately be attributed to.
- The caller remains responsible for passing the actual context and for mapping P6 score/sample semantics. Do not create a second feedback database or duplicate event store.
- This release does not modify `engram.py`, `engram_chat.py`, registry persistence, or P6 internals.

## Test suite

```bash
PYTHONPATH=. python -m unittest discover -s engram_erc/tests -v
```

The cumulative test suite covers contracts, graph construction, primitives, bounded inference, orchestration, evidence-aware evaluation, outcome feedback, and contextual adaptation.

---

# ERC-1.9 — Reasoning Trace Learning

ERC-1.9 is cumulative through ERC-1.8. It adds **descriptive, outcome-linked analysis of the inference lineage** behind an adjudicated conclusion.

## What ERC-1.9 adds

- Reconstructs the inference steps that contributed to a specific conclusion by following `InferenceStep.output_proposition_refs` back through `input_refs`.
- Builds a reasoning-path signature from the ordered operation/rule sequence.
- Builds a privacy-conscious root-premise signature from predicate and polarity descriptors. It deliberately does not copy proposition object values or raw source text into learning metrics.
- Aggregates outcome associations for both complete paths and individual steps, partitioned by task type and explicit context tags.
- Keeps verified, contradicted, inconclusive and superseded counts visible. Only verified/contradicted events enter the descriptive success-rate denominator.
- Applies a minimum adjudicated sample threshold (default: 5) before marking a path or step eligible for comparison.
- Reports unmatched adjudications (missing result, conclusion not in result, or no recorded inference lineage) rather than fabricating a trace.

## Public API

```python
from engram_erc import (
    FeedbackLedger, TraceLearningPolicy, learn_reasoning_traces,
)

report = learn_reasoning_traces(
    feedback_ledger,
    reasoning_results,
    policy=TraceLearningPolicy(
        min_adjudicated_events=5,
        include_context_tags=True,
    ),
)

for pattern in report.patterns:
    print(
        pattern.path_signature,
        pattern.root_premise_signature,
        pattern.context_key,
        pattern.counts,
        pattern.eligible_for_comparison,
    )

for step in report.steps:
    print(step.rule_id, step.operation, step.context_key, step.counts)
```

## Learning semantics and guardrails

1. **Outcome-to-trace linkage.** A feedback event must identify the exact `result_id` and `conclusion_ref`. ERC reconstructs that conclusion's recorded lineage; it does not guess which output was adjudicated.
2. **Association, not causation.** If a conclusion is contradicted, every step in its lineage is associated with that outcome for descriptive analysis. This does not prove that each step, rule, premise or source caused the error.
3. **Premise signatures are descriptors.** They use predicate and polarity, not patient-specific object values or source text. They are structural grouping aids, not semantic equivalence claims.
4. **No unsupported learning.** Missing results, missing conclusions and absent inference lineage are reported as unmatched. They are not converted into negative examples.
5. **Small samples abstain.** Path/step metrics below the minimum adjudicated count are marked ineligible for comparison. The module does not rank, penalize or promote rules from sparse observations.
6. **No automatic mutation.** ERC-1.9 does not rewrite rules, change strategy priorities, update evidence reliability, modify P6, or write to the surgical registry.
7. **No clinical prediction.** Observed frequencies are descriptive historical summaries, not calibrated probabilities, causal estimates, patient-level predictions or measures of clinical effectiveness.
8. **Authoritative storage stays external.** The caller supplies the existing feedback ledger and reasoning results. ERC creates no second database or duplicate event store.

## Integration direction

The intended production adapter should retrieve the adjudicated outcome and its exact reasoning result from existing Engram/registry records, then call `learn_reasoning_traces`. Clinical outcome interpretation and the decision that a reasoning conclusion was correct or incorrect remain explicit adjudication responsibilities. A postoperative complication, for example, must not automatically label the reasoning trace as wrong.

ERC-1.9 produces analysis for review. A later milestone may introduce human-reviewed trace diagnostics and controlled rule-improvement proposals, but those proposals must remain separate from automatic rule mutation.

## Test suite

The cumulative test suite covers contracts, graph construction, primitives, bounded inference, orchestration, evidence-aware evaluation, feedback, contextual adaptation, and trace learning.
