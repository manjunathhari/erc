# ERC 0.8.0 — Conclusion Temporal Propagation (increment B5)

**Package version:** 0.8.0  
**Status:** Implemented, tested locally and on GitHub Actions, signed off at `bcaf863` (tag `erc-temporal-b5`); the implementation commit is `1874316`.  
**Baseline:** `4f476fd` (code as at `a950c94`, tag `erc-temporal-b4`; package 0.7.0). Specification: frozen Draft 1.4 revision 2 (SHA-256 `ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581`) with Amendment 1 revision 2 (`bcbcf020b818f993dc5cab990a9534ba301bd8617301f6c550fd7e10a81cb38d`) and Amendment 2 revision 1 (`eeffe7ad745f1bbe5ba42a36f547897a63c59558f5560fe6e721935dba1783a2`).

## What 0.8.0 changes

Until now a derived conclusion carried no time, whatever the times of its premises. A rule may now say what time its conclusion takes.

```python
RuleDefinition(
    "works_in_city", "1",
    (PropositionPattern(X, "works_at", C, name="job"), PropositionPattern(C, "located_in", Y, name="place")),
    ConclusionTemplate(X, "works_in_city", Y),
    temporal=(TemporalConstraint("overlaps", "job", "place"),),
    conclusion_time=ConclusionTime("while_all", ("job", "place")),
)
```

| Kind | Names | The conclusion takes |
|---|---|---|
| `while_all` | two or more premises, each pair under a declared `overlaps` requirement | the period all of them share. States only |
| `as_premise` | exactly one premise | that premise's time unchanged: a period, or an event window |
| `timeless` | none | no time: the rule states that the conclusion has no temporal limit |

**The shared period.** Earliest start: the latest of the stated earliest starts. Latest start: the latest of the latest starts. Earliest end: the earliest of the earliest ends. Latest end: the earliest of the stated latest ends. It is never bolder and never looser than the premises: checked against every concrete history on 26,329 groups of two to five states.

**Three statuses, recorded on the inference step** (`parameters["conclusion_time"]`), not on `Proposition`: `timed`, `timeless`, `not_established`. A bare proposition with empty time fields does not say which it is; read the producing step.

| Rule | Behaviour |
|---|---|
| Declares nothing | Exactly as in 0.7.0: no time, no status, the same duplicate handling |
| Declares requirements and no conclusion time | Fires as in 0.7.0. Status `not_established` (`no_conclusion_time_declared`); the conclusion is at most **provisional** |
| Declares both, or a conclusion time alone | The conclusion carries the declared time, or is timeless, or `not_established` when `as_premise` names a premise with no time (`premise_carries_no_time`) or an unknown time (`premise_time_unknown`) |

**Alternative derivations.** Two derivations with different periods give two conclusions, never merged, including periods that touch. Two derivations with the same claim, time and status give one conclusion and one inference step each (trace status `derived_alternative`, code `ALTERNATIVE_DERIVATION_RECORDED`). A stated proposition never absorbs a derivation of a rule that declares.

**Evaluation.** Each derivation is decided on its own stated propositions; support is never pooled. The conclusion takes the outcome of its best derivation (accepted, provisional, withheld, conflicted, rejected, in that order). `ConclusionEvaluation.derivations` lists every evaluated derivation, best first, as `DerivationEvaluation(step_ids, decision, leaf_premise_ids, reasons)`; it is empty when there is one. A time not established anywhere in a derivation caps accepted at provisional (`CONCLUSION_TIME_NOT_ESTABLISHED`).

**The limit.** At most 64 derivations of one conclusion are evaluated, chosen by what they say and never by an id; derivations identical in content are kept or left out together. When any is left out (`ALTERNATIVE_DERIVATIONS_TRUNCATED`) no outcome against the conclusion is reported from the incomplete search: a withheld, conflicted or rejected result becomes provisional, unless a definite contradiction involves the conclusion itself.

**Through `orchestrate` only:** one uncertainty item per conclusion whose time is not established (`uncertainty_conclusion_time_<n>`, kind `TEMPORAL_AMBIGUITY`).

**Contradictions** now see a conclusion's period: two values of a one-valued predicate derived from disjoint periods no longer conflict, and from overlapping periods conflict definitely.

New public names (four): `ConclusionTime`, `ConclusionTimeKind`, `ConclusionTimeStatus`, `DerivationEvaluation`. How a time is worked out is not public.

## Compatibility

- Every existing way of building a rule works and means what it meant. `conclusion_time` is keyword-only and defaults to none.
- A rule that declares nothing gives the same propositions, steps, trace and decisions as in 0.7.0.
- **A change for rules written for 0.7.0:** a rule with temporal requirements and no conclusion time still fires, and its conclusion is now provisional with "time not established" until the rule declares its conclusion's time.
- `ConclusionEvaluation` gains one field, `derivations`, after the existing ones. Two inference steps may now name the same output proposition, and one claim may appear as several conclusions with different periods.
- `Proposition` and the rest of `contracts.py` are unchanged, as are `temporal_requirements.py` and `primitives/comparison.py`.
- A changed declaration, `conclusion_time` included, needs a new rule version. This is not enforced.

## Known limitations carried forward

- The conclusion now carries its period, and is still accepted when asked about a moment outside it: `as_of` is not read (B6).
- A rule that declares nothing gives a conclusion with no time and no status.
- Three kinds only. "At the start of a premise" and "at the end of a premise" cannot be said.
- A timeless conclusion used under a later requirement is reported with the 0.7.0 words "carries no time yet".
- The overall decision is withheld when one of several periods of a claim is withheld.
- The counterfactual comparison is by claim alone: two periods of one claim count once there.
- Outside `orchestrate` a time that is not established is in the step and trace only.
- Periods of one claim are never merged, adjacent ones included.
- The status does not travel with a conclusion that is handed back in as a stated proposition.
- Beyond 64 derivations the search is incomplete: accepted or provisional, never definitely withheld.
- With more than 64 derivations of one conclusion identical in content, which of them are examined depends on step ids; the outcome is accepted or provisional only. Full independence from identifiers inside such a group is an objective for a later increment.
- What a caller puts in a claim is content: if subjects or objects are regenerated, the order of derivations can change.
- A rule that declares nothing and a rule that declares never share a conclusion. When both derive the same claim there are two conclusions, also where 0.7.0 gave one (a plain rule beside a rule with requirements only).
- A conclusion with alternative derivations cannot be evaluated when a stated proposition beneath it holds a number that is not finite (NaN or an infinity) in its object or qualifiers: `evaluate_conclusions` raises `ValueError` naming the conclusion and the proposition. A conclusion with one derivation is not affected, whatever else the result holds. A defined spelling for such numbers is left to a later increment.
- B6 must read a conclusion's temporal status from its producing inference step, and must never infer timelessness from empty time fields.

## Tests

`engram_erc/tests/test_conclusion_time.py` (117 cases, with the fixed answer table of 26,329 rows as compressed data), `engram_erc/tests/test_conclusion_time_amendment2.py` (62 cases, Amendment 2) and `tests/test_erc_overlay_conclusion_time.py` (38 cases, the `explain()` lines). `engram_erc/tests` alone: 855.

---

# ERC 0.7.0 — Rule Temporal Requirements (increment B4)

**Package version:** 0.7.0  
**Status:** Implemented and tested locally on branch `erc-adapter-1`. The commit, the GitHub runs, the sign-off and the tag are recorded when they are given.  
**Baseline:** `e2a6872` (code as at `ff2bfbb`, tag `erc-temporal-b2b`; package 0.6.0). Specification: `claude/erc-b4-spec.md`, frozen Draft 4 (SHA-256 of the frozen text `bea15c132a9f2eb02b665277f1cf087a549da375306f6028f7bd824d001b3f07`) with Amendments 1 and 2.

## What 0.7.0 changes

Until now a rule fired whenever its premises existed, whenever they were true. A rule may now say what it needs in time, and fires only on a match that establishes it.

```python
RuleDefinition(
    "works_in_city", "1",
    (PropositionPattern(X, "works_at", C, name="job"), PropositionPattern(C, "located_in", Y, name="place")),
    ConclusionTemplate(X, "works_in_city", Y),
    temporal=(TemporalConstraint("overlaps", "job", "place"),),
)
```

| Relation | Takes | Holds when |
|---|---|---|
| `overlaps` | two states | they hold at one and the same time. This is the 0.6.0 comparison itself, called and not copied |
| `before` | any two (left, right) | left is over before right begins. A state that ends at X is before what begins at X; an event must be strictly earlier |
| `during` | an event, then a state | the event happens while the state holds (start <= instant < end) |

For each match, each constraint is **established** (true in every history consistent with what is stated), **disproved** (true in none) or **indeterminate** (anything else). All constraints must be established for the rule to fire; one disproved makes the match disproved; otherwise one indeterminate makes it indeterminate. The answer may be more cautious than those definitions, never bolder.

| Match | The rule fires | What is recorded |
|---|---|---|
| Established | yes | the inference step's `parameters["temporal"]` lists each constraint and its outcome |
| Disproved | no | a trace entry, status `temporal_requirement_disproved` |
| Indeterminate | no | a trace entry, status `temporal_requirement_indeterminate`, with the reason; and, through `orchestrate`, one uncertainty item (`uncertainty_temporal_requirement_<n>`, kind `TEMPORAL_AMBIGUITY`) worded for the relation and the reason |

Reasons for an indeterminate constraint, looked for in this order: `derived_premise` (the premise is a derived conclusion, which carries no time yet), `no_temporal_statement`, `wrong_kind` (an event where a state is needed, or the reverse), `bounds_do_not_settle`.

The uncertainty item is worded from a second run of the check on the same rule and the same matched premises. That run must agree with the trace entry in every constraint, field and order; if it does not, `orchestrate` raises `RuntimeError` and builds no item (Amendment 2).

New public names (five): `TemporalConstraint`, `TemporalRequirementKind`, `TemporalOutcome`, `TemporalCheck`, `check_temporal_requirements`. `TemporalRelation` keeps its name, its three values and its meaning.

## Compatibility

- A rule that declares nothing (`temporal=None`, the default) or declares that it needs nothing (`temporal=()`) runs exactly as before. Measured on the existing suite: all 1,192 calls of `execute_rules` (79 tests, 1,188 firings) give the same propositions, inference steps and trace as at 0.6.0.
- `name` on a pattern and `temporal` on a rule are keyword-only. A name plays no part in matching.
- A match that does not fire is recorded once, is not looked at again in later rounds, and counts toward no firing limit.
- `execute_rules` called directly (as `recovery.py` and `counterfactual.py` do) records the trace entries; only `orchestrate` builds uncertainty items.
- `engine_version` on a result is now the package version. It was the fixed text `0.1.8`.
- Code files changed: `rules.py`, `inference.py`, `orchestration.py`, `__init__.py`; new: `temporal_requirements.py`. `primitives/comparison.py` keeps its 0.6.0 bytes. The release-pin table now has five entries; the other nine ERC 1.x files are still held to their 0.4.0 bytes.
- The Engram adapter (`erc_overlay/`) is not changed, and its 258 tests pass unedited. No rule set ships with ERC, and the adapter's test rules declare nothing, so no existing conclusion changes.

## Known limitations carried forward

- A conclusion still carries no time (B5). A declared rule over a premise that is itself a derived conclusion therefore stops at indeterminate.
- `as_of` is still not enforced inside ERC (B6). B4 alone does not correct the case in which a job that has ended and an employer's present location, which did overlap, give a conclusion accepted for today: that needs B5 and B6. Until then the adapter's guards hold it off.
- A rule that declares nothing still ignores time (decision TAD-11), until B6.
- The answers are cautious in one known class of shapes: each boundary is read on its own, and the fact that a state's start precedes its end is not used. Never a wrong definite answer on the enumerated shapes (54,264 pairs, and 216,766 on a second grid).
- ERC cannot tell a fact that makes no temporal statement from one the adapter marks `valid_time: unknown` only in a qualifier; under a declared requirement both are indeterminate.
- A rule whose temporal declaration is changed must be given a new version. This is not enforced, and the adapter's request id covers a rule's id and version, not its content.
- Outside `orchestrate`, a match that could not be established is visible only in the trace. `recovery.py` then reports an executed run with nothing derived, `counterfactual.py` a complete replay, and `to_reasoning_result` (which wraps a direct engine run, and which nothing in ERC or the adapter uses) a complete result with no uncertainty item.
- Alternative derivations of one conclusion are still collapsed into one (B5). B4 guarantees only that a match which does not fire is never recorded as a derivation and never suppresses another match.

## Tests

`engram_erc/tests/test_temporal_rules.py` (new, 99 cases) with `engram_erc/tests/data/b4_expected_table.tsv.gz` (the frozen answer table); `tests/test_erc_overlay_temporal_rules.py` (new, 2 cases through the adapter). `engram_erc/tests/test_domain_profiles.py`: three release pins and the version assertion 0.7.0. `engram_erc/tests/test_temporal_comparison.py`: version, changed-file set, and the public-name pin 300 to 305. ERC package: 676 tests. Deliberate breakages: `python kit_tools/check_base2_breakage.py --suite erc`, 118 of 118 caught (the 54 earlier and 64 for B4).

---

# ERC 0.6.0 — Temporal Comparison (increment B3)

**Package version:** 0.6.0  
**Status:** Implemented, tested locally and on GitHub Actions, signed off at `e57c7c1` (tag `erc-temporal-b3`).
**Baseline:** `103d2fd` (tag `erc-temporal-b2a`). Specification: `docs/specifications/erc-b3-spec.md` (frozen text SHA-256 `a94eb532e5d8bcfb4fb220bdac72a6875bd1515897656ddb56470aa2339e4c86`, with Amendment 1).

## What 0.6.0 changes

The temporal comparison now reads the 0.5.0 contract. It is the first reasoning behaviour that does.

| Case | Result |
|---|---|
| Two states | They certainly overlap only if the certain part of each (its latest possible start to its earliest possible end) shares time |
| Two states that certainly do not overlap | Unchanged for every input |
| Two intervals that use none of the 0.5.0 fields | Compared exactly as before |
| Two events (`occurred`) | Compared by their occurrence windows |
| An event against a state | Unknown |

No qualifier is read. No public name is added, and the three relation values are kept.

## Compatibility

- One code file changes: `primitives/comparison.py`. `VERSION` goes from 0.5.0 to 0.6.0. `contradiction.py`, the rule engine, evaluation and orchestration are untouched.
- The release-pin table now has two entries: `contracts.py` (0.5.0) and `primitives/comparison.py` (0.6.0). The other 12 ERC 1.x files are still held to their 0.4.0 bytes.
- Every comparison the earlier test suite makes gives the same answer, except the one test 0.5.0 marked as temporary.

## Known limitations carried forward

- Every result still reports `engine_version` `0.1.8` (hard-coded in `orchestration.py`, which this increment does not touch).
- The rule engine still ignores time (B4), a derived conclusion still has no time (B5), and `as_of` is still not enforced inside ERC (B6).

## Since 0.6.0, outside this package

The package itself has not changed since 0.6.0. The Engram adapter (`erc_overlay/`) has: at increment B2b (`ff2bfbb`, tag `erc-temporal-b2b`) it began sending open states as `end_unbounded`, a first-said day as `start_latest`, a date that was only said as an upper bound, and events as `occurred`. That corrected the limitation B3 named, in which two open values with a coarse start reaching the asked-at date were reported as a potential contradiction. The statement in the 0.5.0 notes below that the adapter sends none of the new fields describes the adapter as it was at 0.5.0.

## Tests

`engram_erc/tests/test_temporal_comparison.py` (new). `engram_erc/tests/test_domain_profiles.py`: release pin for `primitives/comparison.py`; version assertion 0.6.0. ERC package: 577 tests. Deliberate breakages: `python kit_tools/check_base2_breakage.py --suite erc`, 54 of 54 caught.

---

# ERC 0.5.0 — Temporal Contract Foundation (increment B1)

**Package version:** 0.5.0  
**Status:** Implemented and locally tested. Types and validation only; **no reasoning behaviour changes**.
**Baseline:** `f175f03` (tag `erc-adapter-step1a`). Specification and decisions: `claude/erc-b1-spec-validation.md`.

## What 0.5.0 adds

ERC could hold a state with two exact, known ends and nothing else. It could not tell apart a time that is unknown, a state that is still going, a date known only to a month or year, or the moment an event happened. 0.5.0 lets a caller *say* each of these. Nothing in ERC *reads* the additions yet: comparison, contradiction detection, rules and evaluation behave exactly as in 0.4.1. Later increments (B3 to B6) use them.

| Addition | Where | What it says |
|---|---|---|
| `TimeInterval` keyword-only fields `start_latest`, `end_earliest`, `start_unbounded`, `end_unbounded`, `start_is_lower_bound`, `end_is_upper_bound` | `contracts.py` | Each boundary can be exact, within a window, bounded on one side only, unknown, or explicitly unbounded |
| `TimeInterval.start_status`, `.end_status` and `BoundaryStatus` | `contracts.py` | The status of a boundary, derived from the fields and never stored, so contradictory combinations cannot be built |
| `Occurrence(earliest, latest)` | `contracts.py` | When an event happened: one instant, exact when the two are equal |
| `Proposition.occurred` (keyword-only) | `contracts.py` | An event carries `occurred`; a state carries `valid_time`; never both |

One spelling for each case:

| Case | Spelling |
|---|---|
| No temporal statement (every caller before 0.5.0) | `valid_time=None` and `occurred=None` |
| A time that is unknown | `TimeInterval()` |
| Still going | `TimeInterval(start, end_unbounded=True)` |
| Ended at a moment not known | `TimeInterval(start)` — unchanged from 0.4.1 |
| Began some time in 2021 | `TimeInterval(1 Jan 2021, start_latest=31 Dec 2021 23:59:59.999999)` |
| Had begun by 5 March 2024, start not known | `TimeInterval(start_latest=5 Mar 2024)` |
| Happened at an exact moment | `Occurrence(t, t)` |

Bounds are inclusive everywhere: a window includes both of its instants, on `TimeInterval` and on `Occurrence` alike. A boundary known only to a period has as its latest instant the last instant of that period, never the first instant of the next. The end boundary of a state is still the first instant at which it no longer holds, so the interval itself stays half-open.

ERC holds only bounding instants. It holds no original date text and no precision label, and it parses no dates: the system that owns the facts computes the bounds.

## Compatibility

- `TimeInterval(start, end)`, `.start`, `.end`, equality and hashing of existing values are unchanged. The new fields are keyword-only, so no positional call changes meaning.
- A non-datetime passed as a boundary is now refused with a clear `ValueError` (it used to fail with an internal `AttributeError`).
- `engram_erc/generalization.py`: the snapshot fingerprint includes a new field only when it is set. Every fingerprint computed before 0.5.0 is unchanged; two intervals that differ only in a new field no longer share one. This covers a proposition's validity, its occurrence, and evidence validity. Known gap, older than 0.5.0 and left as it was: plain start/end evidence validity has never been part of the fingerprint, so two pieces of evidence that differ only in plain validity still share one; closing it would change existing fingerprints and needs its own decision.
- **`contracts.py` is no longer byte-identical to 0.4.0.** The 0.4.0 hash table is kept unedited as a historical record (its own digest is pinned). A separate release-pin table lists each file changed since 0.4.0 with the release and the reason; `contracts.py` is its only entry. The other 13 ERC 1.x files are still held to their 0.4.0 bytes.
- The deprecated 0.4.0 names (`compat.py`) are **kept** in 0.5.0. The 0.4.1 notes planned their removal "in the next release"; that removal is not part of this increment.

## Known limitations carried forward

- Every result still reports `engine_version` `0.1.8` (hard-coded in `orchestration.py`, which this increment does not touch). To be corrected in the first increment that changes that file.
- Nothing reads the new fields yet. In particular the rule engine still ignores time, a derived conclusion still has no time, and `as_of` is still not enforced (increments B3 to B6).
- The Engram adapter (`erc_overlay/`) is unchanged: it does not yet send any of the new fields.

## Tests

`engram_erc/tests/test_temporal_contracts.py` (93 tests). `engram_erc/tests/test_domain_profiles.py`: the byte-pin guard split into historical record and release pins; version assertion 0.5.0. Deliberate breakages: `python kit_tools/check_base2_breakage.py --suite erc`.

---

# ERC-4.0 General Core — General-Domain Case Intelligence

*Naming: this release was built as "ERC-4.1" to the spec `claude/erc-4-1-general-domain-spec.md` and relabelled ERC-4.0 General Core. "0.4.0" below means the earlier surgical release that carried the 4.0 label.*

**Package version:** 0.4.1  
**Status:** Implemented and locally tested. 461 tests (367 ported from 0.4.0, 94 new).

## What changed

ERC-3.0 through the 0.4.0 surgical release were already domain-neutral in their logic; only names, docstrings, examples and a few fixed lists were surgical. The General Core makes the core general and moves the surgical words into a profile.

Rules this release keeps:

1. **ERC 1.x files are byte-identical to 0.4.0** (`contracts.py`, `graph.py`, `inference.py`, `orchestration.py`, `evaluation.py`, `rules.py`, `validation.py`, `feedback.py`, `adaptation.py`, `trace_learning.py`, `primitives/`). A test checks their SHA-256 hashes.
2. **No logic changes.** A differential check (`tools/diff_check/`, re-runnable) ran every 0.4.0 test under 0.4.0 and the ported test under General Core, recording the output of every public core function (23,538 calls in 319 test cases). After mapping old names to new, every status, code, reference, count, ordering and fingerprint was identical. Limitation texts differ in wording only (same count and order).
3. **The core names no field.** No core identifier, enum value, docstring, default, message or limitation text says surgical, surgeon, clinician, clinical, patient, procedure, contraindication, complication, anatomy, operative or drain. A test parses every core module to enforce this. Exempt: `profiles/surgical.py`, `compat.py`, the `surgical_intelligence.py` alias module, examples, tests, and the frozen ERC 1.x files (`trace_learning.py` still says "patient" and "clinical" in two strings; it cannot change under rule 1).
4. **Old names keep working for one release**, with a `DeprecationWarning`. Removal is planned for the next release.

## Rename table

### Classes and functions

| 0.4.0 | General Core | Module |
|---|---|---|
| `SurgicalContext` | `CaseContext` | application |
| `SurgicalReasoningPolicy` / `Report` / `SurgicalTaskStatus` | `CaseReasoningPolicy` / `Report` / `CaseTaskStatus` | task_orchestration |
| `SurgicalTrajectory` | `CaseTrajectory` | temporal_patterns |
| `SurgicalPatternSummary` | `CasePatternSummary` | longitudinal_learning |
| `SurgicalKnowledgeGraph` | `DomainKnowledgeGraph` | knowledge_graph |
| `SurgicalIntelligenceRequest` / `Report` | `CaseIntelligenceRequest` / `Report` | case_intelligence |
| `ClinicianDecision` / `Ledger` / `Disposition` | `ReviewerDecision` / `Ledger` / `Disposition` | decision_support |
| `orchestrate_surgical_reasoning` | `orchestrate_case_reasoning` | |
| `compare_surgical_experience` | `compare_case_experience` | |
| `build_surgical_knowledge_graph` | `build_knowledge_graph` | |
| `execute_surgical_intelligence` | `execute_case_intelligence` | |
| `record_clinician_decision` | `record_reviewer_decision` | |
| module `surgical_intelligence` | module `case_intelligence` | (old module re-exports, warns on import) |

### Fields

`procedure_ref`→`activity_ref`, `distinct_procedures`→`distinct_activities`, `min_distinct_procedures`→`min_distinct_activities`, `require_same_procedure`→`require_same_activity`, `procedure_match`→`activity_match`, `surgeon_ref`→`practitioner_ref`, `distinct_surgeons`→`distinct_practitioners`, `surgeon_action_refs`→`practitioner_action_refs`, `surgeon_perception_tags`→`practitioner_perception_tags`, `clinician_ref`→`reviewer_ref`, `surgical_context`→`case_context`, `contraindication_refs`→`exclusion_refs`, `clinical_outcome`→`case_outcome`, `complication` (outcome counts)→`adverse_event`, `independent_of_local_registry`→`independent_of_local_records`.

### Enum values

| 0.4.0 | General Core |
|---|---|
| `OptionAssessmentStatus.CONTRAINDICATED` / `"contraindicated"` | `EXCLUDED` / `"excluded"` (same blocking: needs an explicit `OVERRIDDEN` disposition) |
| `DecisionSupportStatus.READY_FOR_CLINICIAN_REVIEW` | `READY_FOR_REVIEW` / `"ready_for_review"` |
| `EpisodeOutcome.COMPLICATION` | `ADVERSE_EVENT` / `"adverse_event"` |
| `KnowledgeNodeKind.ANATOMY` / `PROCEDURE` | `ENTITY` / `ACTIVITY`, with the profile word kept as the node's `subtype` |
| `EvidenceClass.SURGICAL_EXPERIENCE` | `PRACTITIONER_EXPERIENCE` (local experience; never independent external evidence) |
| `EvidenceClass.REGISTRY_ANALYSIS` | `RECORDS_ANALYSIS` |
| `OBSERVATIONAL_STUDY`, `RANDOMIZED_TRIAL` | `PUBLISHED_STUDY`, with the profile word kept as `evidence_label` |
| `GUIDELINE` | `STANDARD_OR_GUIDELINE`; `EXPERT_OPINION` is new |

Other literal codes that changed with the words: the failed-condition code `task_or_procedure_mismatch` is now `task_or_activity_mismatch`, and the synthesis outcome-count key `complication` is now `adverse_event`.

## New in General Core

- **`DomainProfile`** (`engram_erc/profiles/`): immutable and versioned. `case_label`, `activity_label`, `practitioner_label`, `reviewer_label`, `exclusion_label`, `adverse_event_label`; `evidence_classes` (profile word → core `EvidenceClass`); `node_subtypes` (profile word → core `KnowledgeNodeKind`); `label(core_value)` for display. `register_profile` / `get_profile` / `registered_profiles`.
- **`CaseIntelligenceRequest.profile_id` / `profile_version`** (default `"general"` / `"1.0.0"`), carried onto the report.
- **`CaseIntelligenceReport.replay_fingerprint`**: a SHA-256 over the profile and every decision-bearing output (statuses, stage order and results, option statuses, blocking signals, reviews, source refs, limitations). 0.4.0 had no report-level fingerprint; this one is new.
- **`KnowledgeNode.subtype`** (optional): a profile's word for the node kind. It may not be the value of a different core kind, and within one graph a subtype names one kind only, so the fingerprint stays unambiguous. The graph fingerprint uses it when present, so a surgical graph built as `ACTIVITY` + `subtype="procedure"` keeps **exactly its 0.4.0 fingerprint** (tested against a value computed with 0.4.0). Traversal never reads it.
- **`evidence_label`** (optional) on `EvidenceLinkRecord`, `ExternalEvidence` and `EvidenceSynthesisItem`: the profile's own evidence word. Rules read only the core class.
- `__version__` now comes from the `VERSION` file.

## Compatibility layer (`engram_erc/compat.py`, removed in the next release)

- Old class and function names import from the package and from their 0.4.0 module, with a `DeprecationWarning`, and return the same object as the new name.
- Old enum members are true aliases of the new ones, by attribute and by name (`KnowledgeNodeKind["ANATOMY"]`), and are never iterated. Old enum values (`"contraindicated"`, `"complication"`, `"randomized_trial"` …) are accepted by the enum constructors with a `DeprecationWarning`, for stored 0.4.0 data.
- Old field names: use `<Class>.from_legacy(**kwargs)` (on every dataclass with a renamed field) or `profiles.surgical.legacy_kwargs(**kwargs)`. `from_legacy` converts a node kind or evidence class only on classes that have `subtype` / `evidence_label`, so unrelated `kind` fields are left alone. A 0.4.0 evidence class string keeps its word as `evidence_label`; a 0.4.0 node kind `"anatomy"`/`"procedure"` keeps its word as `subtype`, which preserves the 0.4.0 graph fingerprint.

Not supported, by design or by Python:

- Reading an old attribute name on a General Core object (`report.procedure_ref`). Frozen slotted dataclasses can't hold two names for one field.
- `from module import *` does not bring in the old names (star-imports never call module `__getattr__`). Import them by name. (Listing old names in each module's `__all__` would make every star-import, including new code's, emit warnings, so General Core doesn't.)
- Accessing an old enum member by attribute (`OptionAssessmentStatus.CONTRAINDICATED`) does not warn: Python enum aliases can't. Old enum values do warn.
- `hasattr(module, "SurgicalContext")` raises when DeprecationWarnings are turned into errors, because the lookup warns. It returns `True` normally.
- Using the old enum alias directly (`KnowledgeNodeKind.PROCEDURE`) gives `ACTIVITY` with no subtype, so that graph's fingerprint changes. Use `from_legacy` or set `subtype` to keep it.
- Code that compares enum values to 0.4.0 strings (`status.value == "contraindicated"`) must change; compare members instead.

## Housekeeping in this release

- Folder name matches version (`ERC_4_0_General_Core/`; it was built as `ERC_4_1/`), both VERSION files say 0.4.1, and the zip carries no `__pycache__` or `.pytest_cache`. (The VERSION bump went in with the rename commit rather than a separate housekeeping commit.)
- pytest is the stated test runner (see top-level README).
- The ERC-1.9 core gaps (`ReasoningRequest.as_of`/`constraints`/`options`/`context_refs` ignored, no `valid_time` on derived propositions, `engine_version` hard-coded as 0.1.8, result id independent of rules and facts) are **still open**. Fixing them touches ERC 1.x files, so they belong in their own release.
