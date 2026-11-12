# ERC B5 — Conclusion temporal propagation: specification, Draft 1.4, revision 2 (NOT frozen; all points decided)

12 November 2026. Branch `erc-adapter-1` at `4f476fd` (code = B4, `a950c94`; ERC package 0.7.0).

**Specification only. No test, no source file, no commit, push or tag. The clone is clean at `4f476fd`.** Everything measured below was measured with read-only runs, or in a throwaway copy of the repository carrying a throwaway sketch. The sketch is a measurement, never the implementation. Tools, the sketch as a diff and the fixed answer table are in `erc-b5-stage1-draft1_4-r2.zip` (SHA-256 `8ef2c5068cb8148c2d04a89e783f77525f2944fa3980f38e9145a071ae378cc3`) and are never committed. The zip also holds a copy of the ERC package with the sketch applied, so that every tool in it runs without a repository checkout. The freeze, the tests and the implementation each need Manj's own word.

**Basis.** The Stage 1 audit (`erc-b5-stage1-audit-r1.md`, `886f2347…5f39`, findings F53 to F68) and the reviewer's nine-point decision register relayed by Manj on 11 Nov at 21:30 with the instruction to prepare Draft 1. The register is the reviewer's recommendation. This draft is written on it; a point becomes decided only when Manj says so (sections 13 and 14).

**Draft history.** Draft 1 `b00ad65f…6fe6` (11 Nov, with `erc-b5-stage1-draft1.zip` `90e73291…a76e`). **Draft 1.1 (12 Nov), after the reviewer's review of Draft 1 (relayed by Manj at 07:51 with "I accept OP2 and DP1; but consider the changes recommended").** The reviewer verified both hashes and inspected the specification and the tools, and did not rerun them. Each point was checked against the code or the sketch before it was taken up; all nine were right. Changes: OP-2 and DP-1 recorded as decided; the twelve B4 tests classified one by one (F78, section 9); the sketch brought into line with B5-03's internal-fault rule (F82); `while_all` stated as states only (B5-01, B5-03, F79); the temporal status stated as derivation metadata, with what that means for B6 (B5-02, section 10); the 64-derivation limit no longer allows a definite outcome on an incomplete search (B5-05, F80, S21); four public names, the calculation helper internal (B5-10); the `explain()` wording (B5-08); groups of four and five premises validated and added to the table (F81, section 6). No decided point was changed. Draft 1.1 was `41bf50e3…0353` (with `erc-b5-stage1-draft1_1.zip` `e4066667…132e`).

**Draft 1.2 (12 Nov), after the reviewer's review of Draft 1.1 (relayed by Manj at 08:09 with "Good review from the auditor; just need those changes; I agree with the changes request").** One correction was asked for and it was right: Draft 1.1 ordered a conclusion's derivations by inference-step id, and a step id is made from the ids of its premises, so which 64 derivations were examined, and with it the decision, could change when the same facts were given different ids. Measured before changing anything (F83). Changes, all in B5-05, S23 to S26, A10, A21 and section 10: derivations are now ordered by their content and never by an id; derivations identical in content form a tie group that the limit never divides; the one case that cannot be made id-independent is stated and measured (F85); B6's duty to read the status from the inference step is written as a requirement on B6. The zip is now self-contained (F86). No formula, record, wording or decided point was changed. Draft 1.2 was `9810ecfc…770d`.

**Draft 1.3 (12 Nov 08:19): decisions recorded, nothing else.** Manj: "Accept OP-1, OP-3 to OP-9 and DP-2 to DP-8, which the auditor recommends accepting." Sections 13, 14 and 16 record it; a stale column label in section 13 is corrected. No rule, formula, record, wording, scenario or criterion differs from Draft 1.2, and the zip is the same file. Draft 1.3 was `04189f08…86be` (with `erc-b5-stage1-draft1_2.zip` `478921fc…717d`).

**Draft 1.4 (12 Nov), after the reviewer's assessment of Draft 1.2 (relayed by Manj at 08:25).** The reviewer verified the three hashes, ran the oracle and the named scenarios independently from a fresh unpack of the zip (both passed), could not finish the ordering test in the time available, and judged Draft 1.2 ready for independent audit, not for freezing. Three points were asked to be tightened, and the first turned out to matter: **the content key of Draft 1.2 included `source_refs`, and the Engram adapter fills that field with generated sentence ids** (F87). Changes, all in B5-05, S24, A21, sections 12 and 15: `source_refs` is out of the key; the key's canonical form is specified field by field; identifier exclusion, tie semantics and the unresolved-reference key are stated; A21 says what kind of guarantee it is; full id-independence inside tie groups is recorded as a design objective for a later increment; the ordering check has a short mode. No formula, record, wording, scenario outcome or decided point was changed. Draft 1.4 as first sent was `1ff7e0ea…90ec` (with `erc-b5-stage1-draft1_4.zip` `977ae245…0122`).

**Draft 1.4, revision 2 (12 Nov), after the independent review of Draft 1.4 (relayed by Manj at 08:48): paperwork only.** The review verified both hashes, ran the oracle, the scenarios and the short ordering check from a fresh unpack (all passed), judged the three substantive questions sound, and found one packaging defect, which was right and was the author's error: the zip's `README.txt` was a stale Draft 1.1 text (F91). Changes: the README rewritten with the exact commands, and the first line of `b5_order.py` corrected, hence a new zip and hash; section 15 records the independent runs; B5-05 says in words that nested objects in `object` and `qualifiers` are put in canonical form at every level, as the sketch already did. No rule, formula, record, scenario, criterion or decided point differs from Draft 1.4, and no tool, sketch, table or recorded output in the zip differs.

## 1. What B5 is, in plain language

B4 lets a rule say what it needs in time, and fires the rule only when that is established. But the conclusion that comes out carries no time at all, so "Asha works in Bengaluru", derived from a job that ran from 2019 to 2021, reads as true without limit.

B5 lets a rule also say **when its conclusion holds**, and ERC then writes that time on the conclusion, using the fields a conclusion already has. Every conclusion of a rule that declares anything about time ends in one of three states:

| State | Meaning | Example |
|---|---|---|
| **Timed** | The rule says how the time follows from the premises, and it could be worked out | works in Bengaluru, 2019 to 2021 |
| **Timeless by declaration** | The rule itself says its conclusion has no temporal limit | a definitional relationship |
| **Time not established** | The claim was derived, but the time it holds for could not be determined | the rule declares requirements but not the conclusion's time |

An empty date is never read as timeless. B5 also keeps every derivation of a conclusion, so that the decision no longer depends on the order of proposition ids.

B5 does not ask whether a conclusion applies at the asked-at moment. That is B6.

## 2. Scope, exclusions and the B4 baseline

**In scope:** a rule's declaration of its conclusion's time; computing and recording that time; alternative derivations in the engine and in the evaluator; reporting a time that is not established; showing the conclusion's time in `explain()`.

**Not in B5:** `as_of` in any form; the adapter's three guards; any change to `engram_knowledge/` or to what the adapter sends; any new temporal type or store; merging two periods of one claim; a time-aware counterfactual comparison; the overall-decision rule across several conclusions (unchanged, see B5-07); evidence dates; the request id (F49); a shipped rule set; "start of" or "end of" a premise as a conclusion time (section 12); B4's frozen relations, formulas, reasons and wording.

**Baseline at `4f476fd`, run in this session:** full suite 1,641 passed and the recorded 4 failed, 3 skipped, 1 expected-fail; ERC package 676; contract tests 93; adapter 258; adapter + state engine 316; breakages `erc` 118 of 118, `adapter` 93 of 93.

**B4 decisions that stand and are relied on:** only an established match fires; a derived premise with no time gives `derived_premise`; `temporal_requirements.py` and `primitives/comparison.py` keep their present bytes; a rule that declares nothing fires as it always did.

## 3. Findings added at this stage (numbering continues from the audit's F68)

| # | Finding | Evidence |
|---|---|---|
| F69 | **The reviewer's OP-4 point is right.** A conclusion carrying `TimeInterval()` (time unknown) is read by B4's check as a timed premise whose dates do not settle (`bounds_do_not_settle`); a conclusion carrying nothing gives `derived_premise`. Using `TimeInterval()` for "not established" would change the reason B4 reports | `b5_table.py`, last lines: measured both |
| F70 | **The shared-period formula of B5-03 is exact on every enumerated case.** Against a brute-force oracle (every concrete history consistent with what each premise states): never a bound the premises do not support, and never a bound looser than they allow | Section 6.2. Grid 1: 155 shapes, 695 pairs, 1,748 triples. Grid 2: 315 shapes, 2,698 pairs. 0 bolder, 0 looser, 0 declined. The oracle's own test: 5 of 5 deliberately wrong formulas caught |
| F71 | **What the sketch changes in the existing suite: 17 tests, in two groups.** (a) 5 by design: the 0.4.0 byte pin of `evaluation.py`, the release pins of `inference.py`, `orchestration.py`, `rules.py`, and B4's version test. (b) **12 of B4's own tests, all for one reason: OP-2.** They build rules that declare requirements and no conclusion time, and expect *accepted*; under OP-2 the conclusion's time is not established and it is *provisional* | Sketch run: 21 failed = the recorded 4 + 17; 1,624 passed. The 12: `test_a6_named_scenario` D1, D4, D8, E1, E4, E6, E9, O1; `test_a6_the_city_rule…[P1]`; `test_a11…` both orderings; adapter `test_b4_a_declared_rule_over_two_dated_overlapping_facts…`. All 258 adapter tests in `test_erc_overlay.py` pass unedited |
| F72 | **No existing test depends on the evaluator's "every derivation is required" rule.** The sketch replaced it with "any one complete derivation" and nothing else failed | Same run |
| F73 | **The graph already accepts two inference steps that derive one proposition.** No change to `graph.py` or `contracts.py` is needed | Scenario S6; the graph's own dependency-order validation passes |
| F74 | **A conclusion declared timeless, used by a later rule that has requirements, is reported by B4 as "a derived conclusion and carries no time yet".** The outcome (the later rule does not fire) is right; the word "yet" is inexact for a timeless conclusion. B4's wording is frozen, so this is carried as a limitation | Scenario S13b |
| F75 | **Counterfactual counts two periods of one claim as one conclusion**, because it compares claims only | Scenario S18: 2 timed conclusions, 1 signature |
| F76 | **With one period accepted and another withheld, the overall decision is withheld**, by the existing aggregation, which B5 does not change | Scenario S5b |
| F77 | **Changing `as_of` changes nothing in the sketch**: propositions and steps are identical for 2020 and 2030 | Scenario S19 |
| F78 | **DP-1, the twelve B4 tests classified.** Every one of the twelve exists to check that B4 fires, or does not fire, a rule correctly; none exists to check what a missing conclusion-time declaration does. Given a declaration that fits its relation (`while_all` for `overlaps`, `as_premise` of the event for `during`, `as_premise` of the later premise for `before`), **each of the twelve passes with its original decision.** The consequence of OP-2 itself is then checked by new B5 tests (S9), not by weakening these | Sketch with the twelve so revised: 9 failed = the recorded 4 + the 5 pin and version tests; 1,636 passed. The revised tests are in `b5_sketch.diff` |
| F79 | **An event can never reach the `while_all` calculation through the engine.** `while_all` requires an `overlaps` requirement on the same premises; B4 answers `wrong_kind` for an event there and the rule does not fire. Only a direct call of the calculation could meet one, and that is the internal fault of B5-03 | S20 (not applied, B4's own uncertainty item); S22 (direct call raises) |
| F80 | **The reviewer's objection to Draft 1's 64 limit is right, and measured.** With 81 derivations and only one beyond the first 64 supported, Draft 1's rule reports *withheld* although a fully supported derivation exists | S21c. With the rule of B5-05 as now drafted: provisional, `ALTERNATIVE_DERIVATIONS_TRUNCATED` |
| F81 | **The formula is also exact for four and five premises, and for triples on the second grid** | Section 6.2: 6,384 groups of four, 17,502 of five, 14,298 triples on grid 2; 0 bolder, 0 looser |
| F82 | **Draft 1's sketch disagreed with Draft 1's own text**, as the reviewer found: the text made an uncertain shared period after an established overlap an internal fault, while the sketch returned "not established" with a reason the specification did not list. The text stands; the sketch now raises | `b5_sketch.diff`, `conclusion_time.py`; S22 |
| F83 | **The reviewer's ordering objection to Draft 1.1 is right, and measured.** A step id is a hash that includes the ids of the step's premises. With 81 derivations of one conclusion and the same facts given twelve different id assignments, Draft 1.1's sketch examined a different 64 each time, and for **62 of the 81** ways of supporting exactly one derivation the decision changed with the ids (accepted under some, provisional under others). Draft 1.1's criterion A21 ("the same 64 whichever proposition ids are used") was therefore false as drafted | `b5_order.py` against Draft 1.1's sketch: `order_output_draft1_1.txt`, FAIL |
| F84 | **Ordered by content, the choice and the decision no longer depend on ids.** The same twelve id assignments: the same 64 derivations examined every time, and 0 of 81 decisions change. With one fact present twice (two ids, identical content) the limit would fall inside a pair of identical derivations; the pair is left out whole, 63 are examined, again the same every time, 0 of 81 change. At exactly 64 nothing is left out | `b5_order.py`, S23, S24, S25: PASS, exit code 0 |
| F85 | **One case cannot be made id-independent, and is bounded.** If more than 64 derivations of one conclusion are identical in content (which needs more than 64 stated propositions identical in every field but their id), the first 64 of them are taken in step-id order. Measured with 65: 10 of 65 single-support decisions change with the ids, between *accepted* and *provisional* only; the rule of point 7 still forbids a definite outcome against the conclusion | `b5_order.py`, S26 |
| F86 | **The reviewer could not run the oracle from Draft 1.1's zip**: it needs the ERC package, which the zip did not contain, and the reviewer has no repository checkout. The zip now carries the sketched package (source only, standard library only); from a fresh unpack the oracle, the id-order check, the scenarios and the table generator all run, and the regenerated table has the stated hash | `README.txt` in the zip; run from a fresh unpack in this session |
| F87 | **The reviewer's question about `source_refs` exposed a real defect in Draft 1.2's key.** `source_refs` is not semantic content: the Engram adapter fills it with the ids of the sentences a fact came from (`erc_overlay/knowledge.py`, `source_refs=tuple(dict.fromkeys(sids))`), and those ids are generated. With each test proposition given a generated source reference, as the adapter's are, Draft 1.2's key no longer treats two identical facts as a tie group; the limit divides them by id, and 2 of 81 decisions change with the ids | `b5_order.py` against Draft 1.2's sketch: `order_output_draft1_2.txt`, S24 FAIL |
| F88 | **With `source_refs` out of the key and the key in canonical form, the check passes again** with the generated source references present: S23 0 of 81, S24 0 of 81 (63 examined), S25 0 of 64. The full suite on the sketch is unchanged (the recorded 4 and the 5 pin and version tests fail; 1,636 pass) | `b5_order.py`: PASS, exit code 0; `order_output.txt` |
| F89 | **What else the adapter places in a proposition.** Subject and object are Engram entity ids or values; qualifiers are fixed labels (status, validation, source type, fact type, time kind, start and end basis) and hold no id. So for the adapter the key contains Engram's entity ids, as part of what a fact claims, and no proposition, sentence, step or evidence id | `erc_overlay/knowledge.py`, `request_for` |
| F90 | **The ordering check now has a short mode** (4 id assignments, every sixth support; about 5 seconds here) beside the full run (12 assignments, every support; about one minute here), because the reviewer's full run did not finish in the time available | `b5_order.py --quick`; `README.txt` |
| F91 | **The README in the zips of Drafts 1.2 and 1.4 was stale**, as the independent review found: it carried the Draft 1.1 label and told the reader to run against a repository copy, although the tools run from the zip alone; `b5_order.py` named Draft 1.2 in its first line. The rewrite made at Draft 1.2 was never written to the file, and the author's statement that the README gave the commands was wrong. The README now lists the five commands with the short and full ordering checks set apart; the rebuilt zip differs from the first Draft 1.4 zip in those two files only | Fresh unpacks of both zips compared file by file; every command in the README run from the new one |

## 4. Specification

### B5-01 Declaring the conclusion's time

A rule may carry one declaration: `RuleDefinition(…, conclusion_time=ConclusionTime(kind, premises))` (keyword-only, default `None`).

| `kind` | `premises` | Meaning |
|---|---|---|
| `while_all` | two or more premise names | The conclusion is a state that holds while every named premise holds: their shared period |
| `as_premise` | exactly one premise name | The conclusion takes the time of that premise unchanged: a period if the premise is a state, an event window if it is an event |
| `timeless` | none | The rule states that its conclusion has no temporal limit |

`kind` is a `ConclusionTimeKind` (`WHILE_ALL`, `AS_PREMISE`, `TIMELESS`; the text values are accepted). Premise names are the names B4 introduced on `PropositionPattern`.

Refused when the rule is built (`ValueError`): an unknown kind; `premises` that is not a tuple of non-empty names; a name used twice; the wrong number of names for the kind; a name no premise carries; `conclusion_time` that is neither `None` nor a `ConclusionTime`; and **`while_all` over two premises for which the rule does not also declare an `overlaps` requirement** (every pair of the named premises must be covered).

That last rule is what makes `while_all` safe: the rule fires only when B4 has established that the named states overlap, so their shared period certainly exists. `while_all` names its premises explicitly; it never means "all premises of the rule".

**`while_all` is for states only.** Its named premises are states carrying `valid_time`, and its conclusion is a state. Whether a premise is a state or an event is a property of the matched proposition, not of the rule, so it cannot be refused when the rule is built; it is settled at the match, by B4: an event under the required `overlaps` gives `wrong_kind`, the rule is not applied, and B4's uncertainty item says so (F79). A conclusion that is an event comes from `as_premise` over an event premise.

`as_premise` and `timeless` need no temporal requirement. Every existing way of building a rule keeps working and means what it meant.

### B5-02 The four kinds of rule

| | Declares requirements (B4) | Declares the conclusion's time (B5) | Behaviour |
|---|---|---|---|
| **A. Declares nothing** | no (`None` or `()`) | no | **Exactly as in 0.7.0**: propositions, steps, trace, duplicate handling and decisions byte for byte. No status is recorded and no uncertainty is added (OP-6) |
| **B. Requirements only** | yes | no | Fires as in B4. The conclusion carries no time; its status is *time not established*, reason `no_conclusion_time_declared` (OP-2) |
| **C. Both** | yes | yes | Fires as in B4. The conclusion's time and status follow B5-03 |
| **D. Conclusion time only** | no | `as_premise` or `timeless` | Fires as a rule always did. The conclusion's time and status follow B5-03 |

"A rule that declares" below means B, C or D.

**Where the status lives.** The three states of section 1 (`timed`, `timeless`, `not_established`) are **derivation metadata**: they are recorded on the inference step that produces the conclusion (B5-04) and are read from the result's inference steps. They are not a field of the `Proposition` contract, which is unchanged. Three consequences, each intended and each tested:

- Every step that produces a given conclusion carries the same status (the merge rule of B5-04 guarantees it), so a conclusion has exactly one status.
- A bare proposition with empty time fields does not say whether it is timeless, not established, a rule A conclusion or a stated fact with no temporal statement. Anything that needs the difference (the evaluator, `explain()`, and B6) must read the producing step.
- A derived conclusion handed back to ERC later as a stated proposition keeps its time, if it has one, and loses its status: a timeless or not-established conclusion fed back in is then a stated fact with no temporal statement. B5 provides no way to carry the status across requests (section 12).

### B5-03 Working out the time

The check runs once per firing match, after B4's check has established the match and before the conclusion is built.

**`timeless`.** No time is written. Status `timeless`.

**`as_premise(n)`.** If the premise named *n* carries a period or an event window with at least one bound stated, the conclusion carries that same value, field for field, in `valid_time` or `occurred` respectively. Status `timed`. If the premise carries neither `valid_time` nor `occurred`: status `not_established`, reason `premise_carries_no_time`. If it carries `TimeInterval()` or `Occurrence()` (a time of which nothing is known): status `not_established`, reason `premise_time_unknown`. In both cases the conclusion's time fields stay empty (OP-4).

**`while_all(n1, n2, …)`.** Every named premise is a state carrying `valid_time` (B4's `overlaps` established it; an event or a premise with no time never gets this far, B5-01). For a state write, exactly as B4 does, S⁻ and S⁺ for the earliest and latest it could have begun and E⁻ and E⁺ for the earliest and latest it could have ended; "always" is earlier than every instant, "never" later than every instant; a quantity is *absent* when the contract gives nothing for it.

*Reference meaning.* A state with stated bounds stands for every concrete history (s, e) with s < e that is consistent with them. Given one history per premise, the conclusion holds from the latest of the starts to the earliest of the ends. The conclusion's stated bounds must admit every such result (never bolder) and nothing wider than their range (never looser).

*Formula.* Over the named premises:

| Conclusion's quantity | Value |
|---|---|
| Earliest possible start | the latest of the premises' stated S⁻ instants; absent if no premise states one |
| Latest possible start | the latest of the premises' S⁺ instants; "always" if every premise has an unbounded start |
| Earliest possible end | the earliest of the premises' E⁻ instants; "never" if every premise has an unbounded end |
| Latest possible end | the earliest of the premises' stated E⁺ instants; absent if no premise states one |

A premise whose start is unbounded or whose S⁻ is absent contributes no instant to the first row; likewise for the end and the last row. Once B4 has established the overlaps, every S⁺ and E⁻ is known and the latest possible start is earlier than the earliest possible end.

*Written in the contract:*

| Start | Fields | End | Fields |
|---|---|---|---|
| every premise unbounded | `start_unbounded` | every premise unbounded | `end_unbounded` |
| earliest absent | `start_latest` only (no later than) | latest absent | `end_earliest` only (no earlier than) |
| earliest = latest | `start` (exact) | earliest = latest | `end` (exact) |
| earliest < latest | `start` and `start_latest` (within) | earliest < latest | `end_earliest` and `end` (within) |

Status `timed`. The result never carries `start_is_lower_bound` or `end_is_upper_bound`: a premise with such a bound cannot establish an overlap.

If, after an established match, a named premise carries no `valid_time` or the formula finds no certain shared part, that is an internal fault and not a property of the data: `RuntimeError`, message exactly `Conclusion time for rule <rule_id>@<version>: the shared period of an established overlap is not certain.` No conclusion is built.

**Read:** `Proposition.valid_time` and `Proposition.occurred` of the named premises, and nothing else. No qualifier, no evidence date and no `as_of` is read. A premise that is itself a derived conclusion is read exactly like a stated one.

### B5-04 What the engine does

| Step | Rule A | Rules B, C, D |
|---|---|---|
| Conclusion id | as today (from rule, version, premises, bindings) | as today |
| Conclusion's fields | as today | as today, plus `valid_time` or `occurred` when the status is `timed`. Qualifiers and source references stay empty |
| Already present? | as today: any proposition with the same claim and the same `valid_time` makes the match a recorded no-op | **Only a conclusion derived earlier in this run** with the same claim (subject, predicate, object, polarity), the same `valid_time`, the same `occurred` and the same status counts as the same conclusion. A stated proposition never absorbs a derivation (OP-5), and a conclusion of a rule A never merges with one of a rule that declares |
| When it is the same conclusion | no step | **A new inference step is recorded whose output is the existing conclusion: an alternative derivation.** It counts as a firing |
| When it is not | new proposition and step | new proposition and step |

Consequences, each intended:

- Two derivations with different periods give two conclusions. They are never merged, including when the periods touch.
- Two derivations with the same claim, period and status give one conclusion and two steps, each with its own premises.
- A conclusion's time is fixed when the conclusion is created and is never revised. A match that did not fire is therefore still not tried again in that run (F65).
- A later rule that declares requirements reads a timed conclusion with B4's own formulas. Over a conclusion with no time (rule A, `timeless`, or not established) B4 still answers `derived_premise`.

**Exact records.**

| Record | Content |
|---|---|
| Inference step, rule A | as today, no new key |
| Inference step, rules B, C, D | as today, plus `parameters["conclusion_time"]`: `status` (`timed`, `timeless`, `not_established`); `mode` (`while_all`, `as_premise`, `timeless`, or null for rule B); `premises` (the names, in declared order); `reason` when not established; and, when timed, `valid_time` (each stated field of the interval: instants as ISO text, flags as true) or `occurred` (`earliest`, `latest`) |
| Trace entry, new conclusion | as today (`rule_execution`, status `derived`, code `RULE_PREMISES_MATCHED`), plus the same `conclusion_time` mapping in `details` for rules B, C, D |
| Trace entry, alternative derivation | `rule_execution`; status `derived_alternative`; code `ALTERNATIVE_DERIVATION_RECORDED`; `output_refs` the existing conclusion; the same details |

Reasons for `not_established`, a closed list: `no_conclusion_time_declared` (rule B), `premise_carries_no_time` and `premise_time_unknown` (`as_premise` only). `while_all` never gives `not_established`: it gives a time or raises the internal fault.

`execute_rules` records these and nothing else; `recovery.py` and `counterfactual.py` therefore get the same conclusions, times and records, with no code change.

### B5-05 Evaluating a conclusion with several derivations

A **derivation** of a conclusion is one way of tracing it to stated propositions: for the conclusion and for every derived proposition beneath it, exactly one of the steps that produced it is chosen. A conclusion with one step at every level has exactly one derivation, and its stated leaves are those the evaluator finds today.

**Order of derivations: by content, never by id.** Every derivation has a key, built from what it says:

| Thing | Key |
|---|---|
| A stated proposition (a leaf) | what it claims: subject, predicate, object, polarity, kind, `valid_time`, `occurred`, qualifiers. **Not** its id, and **not** its `source_refs` |
| A derivation through a step | the step's rule (the step's `rule_id` text, which carries the rule's id and version), then the keys of the derivations chosen for the step's premises, in the step's input order |
| A reference that cannot be resolved | one fixed key |

A conclusion's derivations are taken in ascending order of key.

**Canonical form.** A key is a sequence of text parts and nested keys, compared part by part from the left; text is compared by Unicode code point. The first part is a tag: `0` for a stated proposition, `1` for a derivation through a step, `2` for an unresolved reference, so a stated proposition sorts before a derived one and an unresolved reference last. A stated proposition's second part is one JSON text of exactly these members, with member names sorted, no insignificant spaces, non-ASCII characters escaped, and no non-finite numbers:

| Member | Value |
|---|---|
| `subject`, `predicate` | the text |
| `object` | the JSON value as given; where it is or contains an object, that object's member names are sorted, at every level of nesting |
| `polarity` | true or false |
| `kind` | the kind's text value |
| `valid_time` | null, or an object of `start`, `start_latest`, `end_earliest`, `end` (each null or an instant) and the four flags `start_unbounded`, `end_unbounded`, `start_is_lower_bound`, `end_is_upper_bound` (each true or false) |
| `occurred` | null, or an object of `earliest` and `latest` (each null or an instant) |
| `qualifiers` | the mapping, member names sorted at every level of nesting |

The canonical form is applied recursively: every object inside `object` or `qualifiers`, however deeply nested, is written with its member names sorted, and lists keep their given order. An instant is written in UTC, ISO 8601, with microseconds, so one instant has one spelling whatever zone it was given in. Nothing in a key depends on the order in which a mapping was filled, on an object's printed form, or on a hash that differs between runs.

**Identifier exclusion.** No proposition id, inference-step id or evidence id is part of a key, directly or through another field. `source_refs` is left out for that reason: it names where a proposition came from, not what it claims, and for the Engram adapter it holds generated sentence ids (F87). The evaluation does not read `source_refs` either. What a caller places in the claim itself is content: the adapter's subjects and objects are Engram's entity ids (F89), and they are part of the key because they are part of what is claimed. If a caller regenerates those, the order of derivations can change with them; with more than 64 derivations of one conclusion that can change which are examined, within the bound of point 7 (accepted or provisional).

**Tie groups: what equal keys mean.** Two derivations have equal keys exactly when they apply the same rules, in the same arrangement, to stated propositions that are equal in every member listed above. They can then differ only in which of several such identical propositions they rest on, and so in the evidence linked to those propositions and in their source references. Evidence is deliberately not part of the key: it is what the evaluation weighs, separately, for each derivation. That is why a tie group is kept whole and not reduced to one representative: every member is evaluated on its own evidence. Within a tie group the order is by step ids; this decides nothing except which of two identical derivations is listed first.

**An unresolved reference** is a premise that names a proposition absent from the result, or a derived proposition that no inference step produces, or one that depends on itself. The engine never produces one; it can occur only in a result assembled by hand. All unresolved references share one fixed key, which contains no id. This is safe because a derivation containing an unresolved reference has an incomplete lineage and is never accepted, by the existing decision procedure, whichever reference is missing; two derivations that differ only in which reference is unresolved receive the same outcome for the same reason, and being one tie group they are kept or left out together.

1. The evaluator lists the derivations of the conclusion in that order.
2. **Each derivation is decided on its own leaves alone**, by the existing decision procedure, unchanged: the same coverage, counts, contradictions, reasons and policy. Alternatives are never added together.
3. A contradiction that involves the conclusion itself applies to every derivation, as it does today.
4. **Time not established.** If the conclusion, or any derived proposition in the derivation, has status `not_established`, an *accepted* outcome for that derivation becomes *provisional*, escalation *review*, reason `CONCLUSION_TIME_NOT_ESTABLISHED`; the limitation `CONCLUSION_TIME_NOT_ESTABLISHED` is listed in any case.
5. **The conclusion takes the outcome of its best derivation**, in the fixed order accepted, provisional, withheld, conflicted, rejected; among equals, the earliest in the order of derivations. (Two derivations of one tie group with the same outcome are identical in content, so which of them is named changes no decision.) Its coverage, counts, reasons and limitations are that derivation's.
6. **Every evaluated derivation stays visible.** `ConclusionEvaluation` gains `derivations`: empty when there is one, otherwise one `DerivationEvaluation` per evaluated derivation, best first, with its step ids, decision, leaf ids and reasons.
7. **At most 64 derivations of one conclusion are evaluated: the first 64 in the order above, and the limit never divides a tie group.** If the 64th and 65th derivations belong to one tie group, that whole group is left out and fewer than 64 are evaluated. (The single exception: when the very first tie group alone has more than 64 members, its first 64 are evaluated; see the last paragraph of this section.) When any derivation is left out, the limitation `ALTERNATIVE_DERIVATIONS_TRUNCATED` is listed, and no definite outcome against the conclusion is reported from the incomplete search:

| Best outcome among the 64 evaluated | Conclusion's outcome |
|---|---|
| accepted | accepted (one fully supported derivation is enough) |
| provisional | provisional, with that derivation's own reasons |
| withheld, conflicted or rejected | **provisional**, escalation *review*, reason `ALTERNATIVE_DERIVATIONS_TRUNCATED` |
| any, when a definite contradiction involves the conclusion itself | as point 3: it applies to every derivation, examined or not, so the outcome stands |

The limit counts complete derivations, so alternatives at different levels multiply: nine ways to one premise and nine to another are 81 derivations of the conclusion that needs both (S21).

**The outcome depends on which derivations exist and what supports them, never on an id.** The derivations examined are chosen by content, whole tie groups at a time, so giving the same facts different ids changes neither which derivations are examined nor the decision (F84, S23 to S25).

**The one exception, stated so that it is not found later.** If more than 64 derivations of one conclusion are identical in content, the limit has to divide that group, and it does so by step id. This needs more than 64 stated propositions that are identical in every field but their id. The effect is bounded by point 7: the conclusion is *accepted* if a supported one is among the 64 taken and *provisional* otherwise, never withheld, conflicted or rejected (F85, S26). It fails on the cautious side: uncertainty can rise, a definite rejection cannot be claimed. It is carried as a limitation, and **full independence from identifiers, including inside a tie group, is recorded as a design objective for a later increment**; it is not attempted in B5, where it would mean removing the limit or weighing evidence inside the ordering.

The rule this replaces ("require the premises of every recorded derivation") was unreachable from the engine and is depended on by no existing test (F58, F72).

### B5-06 Reporting a time that is not established

Through `orchestrate` only (as with B4's uncertainty items): one uncertainty item per conclusion whose status is `not_established`, in the order of their first inference step, after B4's items.

| Field | Value |
|---|---|
| id | `uncertainty_conclusion_time_<n>` (n from 1) |
| kind | `TEMPORAL_AMBIGUITY` |
| affected_refs | the conclusion's id |
| description | `Conclusion of rule <rule_id>@<version>: the time for which it holds is not established (<reason text>).` |
| resolution hint | `Declare how the conclusion's time follows from its premises, or supply the missing times.` |

| Reason | Reason text |
|---|---|
| `no_conclusion_time_declared` | `the rule declares temporal requirements but not the time of its conclusion` |
| `premise_carries_no_time` | `<name> carries no time` |
| `premise_time_unknown` | `the time of <name> is not known` |

The item is worded from the step's recorded `conclusion_time`; nothing is evaluated a second time. The result's status follows the existing rule: a rule fired, so *complete*, with the uncertainty listed.

### B5-07 Contradictions and the overall decision

No code changes. The contradiction scan after rule execution already compares conclusions like any proposition; it now finds their times. Named changes in outcome, for conclusions of rules that declare a time:

| Case | 0.7.0 | B5 |
|---|---|---|
| Two values of a one-valued predicate, derived from disjoint periods | potential; both provisional | none; both accepted |
| The same with overlapping periods | potential; both provisional | **definite; status conflict, both conflicted** |
| The same, one period's start not known well enough | potential | potential (unchanged) |
| A stated denial in a period disjoint from the conclusion's | potential; provisional | none; accepted |
| A stated denial overlapping the conclusion's period | potential; provisional | **definite; conflict** |

**The overall decision is unchanged:** it is still worked out over all conclusions by the existing rule. With one period of a claim accepted and another withheld, the overall decision is *withheld* (F76). Each conclusion's own decision and period stay visible. Changing this is not part of B5 and is recorded as a carried limitation.

### B5-08 `explain()` (adapter, `erc_overlay/reasoner.py` only)

Under each conclusion line, for a conclusion of a rule that declares (B, C, D), one added line; every existing line is unchanged, and a conclusion of a rule A gets no added line.

| State | Line |
|---|---|
| Timed, a period | `  time: holds <start> <end>; <basis>` |
| Timed, an event | `  time: event on D` / `event between D1 and D2` / `event by D` / `event no earlier than D`, then `; <basis>` |
| Timeless | `  time: timeless (declared by rule <rule_id>@<version>)` |
| Not established | `  time: not established (<reason text of B5-06>)` |

| Start known as | Words | End known as | Words |
|---|---|---|---|
| exact | `from D` | exact | `to D (end exclusive)` |
| within | `from between D1 and D2` | within | `to between D1 and D2 (end exclusive)` |
| no later than | `from no later than D` | no earlier than | `to no earlier than D (end exclusive)` |
| unbounded | `with no stated beginning` | unbounded | `still going` |

`<basis>` is `while <n1> and <n2> … all hold, rule <rule_id>@<version>` or `the time of <n>, rule <rule_id>@<version>`. Days are written as the existing fact lines write them (`2019-01-01`).

**The end is exclusive, and the line says so.** A period's end is the first day on which the state no longer holds, so every printed end day carries `(end exclusive)`. Examples:

- `  time: holds from 2019-01-01 to 2021-01-01 (end exclusive); while job and place all hold, rule works_in_city@1`
- `  time: holds from between 2021-02-01 and 2021-03-31 to between 2023-01-02 and 2024-01-01 (end exclusive); while job and place all hold, rule works_in_city@1`
- `  time: holds from 2022-02-01 still going; the time of next, rule moved@1`
- `  time: timeless (declared by rule city@1)`
- `  time: not established (the rule declares temporal requirements but not the time of its conclusion)`

The existing fact lines are not changed in B5; they keep their present wording.

**Alternative derivations.** When a conclusion has more than one evaluated derivation, after the `because:` lines of the chosen one, one line for each other derivation, in the evaluator's order: `  also derived by rule <rule_id>@<version> (<decision>) from: <claim>; <claim> …`, naming the rule of the conclusion's own producing step in that derivation, that derivation's decision, and its stated facts as the `because:` lines print them. The conclusion's claim is not repeated. When derivations were left out by the limit: a last line `  further derivations were not examined (limit 64)`.

A conclusion whose time is not established is never shown as timeless.

### B5-09 Recovery and counterfactual

No code change. `run_guarded_recovery` and the counterfactual replay call `execute_rules` and so produce the same conclusions, times and step records as `orchestrate` for the same input; B5 tests this directly on the produced propositions. The counterfactual comparison stays by claim alone (OP-8): two periods of one claim count as one conclusion there, and a change of period alone is not detected by it (F75). Outside `orchestrate`, a time that is not established is in the step and trace only, with no uncertainty item (the same class as B4's R-1).

### B5-10 Version, pins, names

ERC goes to **0.8.0**. Release-pin entries with release and reason for `rules.py`, `inference.py`, `orchestration.py` and `evaluation.py` (which leaves the 0.4.0 byte-identical set for the first time; the 0.4.0 table itself is not edited). `temporal_requirements.py` and `primitives/comparison.py` keep their present bytes. The public-name pin is revised once, 305 to 309: `ConclusionTime`, `ConclusionTimeKind`, `ConclusionTimeStatus` (`TIMED`, `TIMELESS`, `NOT_ESTABLISHED`), `DerivationEvaluation`. **The calculation itself is not public:** it lives in `engram_erc/conclusion_time.py`, is called by the engine, and is not exported from the package, so that how a time is calculated can change without breaking a caller. Package README and release notes in the same commit.

## 5. Files

| File | Change |
|---|---|
| `engram_erc/rules.py` | `ConclusionTimeKind`, `ConclusionTime`; `conclusion_time` on a rule; validation |
| `engram_erc/conclusion_time.py` (new) | the status type, the shared-period formula, the calculation (internal), the step record |
| `engram_erc/inference.py` | the call; time on the conclusion; alternative derivations; records |
| `engram_erc/evaluation.py` | derivations decided one by one; the cap for a time not established; `DerivationEvaluation` |
| `engram_erc/orchestration.py` | the uncertainty item |
| `engram_erc/__init__.py`, `VERSION`, `README.md`, `RELEASE_NOTES.md` | exports; 0.8.0; documentation |
| `erc_overlay/reasoner.py` | the added `explain()` lines |
| `engram_erc/tests/test_conclusion_time.py` (new), `engram_erc/tests/data/b5_expected_table.tsv.gz` (new) | B5's tests and the fixed table |
| `tests/test_erc_overlay_conclusion_time.py` (new) | the adapter half |
| `engram_erc/tests/test_temporal_rules.py`, `tests/test_erc_overlay_temporal_rules.py` | the 12 B4 tests of F71 revised by name as classified in section 9, each with its reason |
| `engram_erc/tests/test_domain_profiles.py`, `test_temporal_comparison.py` | pins, version, public names |
| `kit_tools/check_base2_breakage.py` | new breakages; the new test files added to the suites |

Untouched: `engram_knowledge/`, `erc_overlay/knowledge.py`, `tests/test_erc_overlay.py` (all 258 pass unedited), `engram_erc/contracts.py`, `graph.py`, `temporal_requirements.py`, `primitives/`, `recovery.py`, `counterfactual.py`, `fable-erc-adapter`, `engram_erc_bridge.py`, `main`.

## 6. Validation of the formula

### 6.1 What was checked

For every group of states that B4 establishes as overlapping, the oracle lists every combination of concrete histories, works out the true shared period of each, and compares the range of true starts and of true ends with what the formula's result states.

### 6.2 Results (`b5_oracle.py`, exit code 0 only when every line below holds)

| Run | Shapes | Groups established | Timed | Bolder than the premises | Looser than the premises | Declined |
|---|---|---|---|---|---|---|
| Grid 1 (instants 2, 4, 6; unknown bounds over 0 to 8), pairs | 155 | 695 | 695 | 0 | 0 | 0 |
| Grid 2 (instants 1, 3, 5, 7; unknown bounds over 0 to 9), pairs | 315 | 2,698 | 2,698 | 0 | 0 | 0 |
| Grid 1, triples | 155 | 1,748 | 1,748 | 0 | 0 | 0 |
| Grid 1, groups of four | 155 | 6,384 | 6,384 | 0 | 0 | 0 |
| Grid 1, groups of five | 155 | 17,502 | 17,502 | 0 | 0 | 0 |
| Grid 2, triples | 315 | 14,298 | 14,298 | 0 | 0 | 0 |

The shape counts (155, 315) and the 695 established pairs equal B4's frozen figures, obtained here from an independently written generator.

**The oracle's own test.** Five deliberately wrong formulas, each caught:

| Wrong formula | Caught as |
|---|---|
| A start window read as exact | bolder, 137 pairs |
| The earliest start taken from the wrong premise | looser, 54 pairs |
| An end known only as "no earlier than" read as still going | bolder, 160 pairs |
| An end window read as its latest instant | bolder, 137 pairs |
| The first premise's own period copied | bolder 314, looser 117 |

### 6.3 The fixed answer table

`b5_expected_table.tsv` in the zip (SHA-256 `5cb865c2247eaae83dfe296bdd4d42ae693c40cfe6fb7e9603056ef36876f40e`; 26,329 rows: the 695 pairs, 1,748 triples, 6,384 groups of four and 17,502 groups of five of grid 1). Each row gives the exact contract fields of every premise, the conclusion's fields the implementation must produce, and the oracle's four ranges.

**What this is and is not.** Exhaustive for the listed shapes on two finite grids: strong validation, not a mathematical proof for every interval. The formula uses only order comparisons between stated instants, so a wrong answer would need an ordering of instants that neither grid contains; the named real-date scenarios of section 7 are there for that reason. `as_premise` copies a value and has no formula to validate. The specification sets no maximum on the number of premises `while_all` may name; the formula takes the latest and the earliest over any number, and is exercised here up to five. Not yet run by a second party.

## 7. Named scenarios (all run against the sketch; `b5_scenarios.py`)

Rule unless stated: works at C (`job`) + C located in Y (`place`) → works in city Y; requires `overlaps(job, place)`; conclusion time `while_all(job, place)`; all facts supported; asked 1 June 2024.

| # | Facts | Expected |
|---|---|---|
| S1 | Job 2019 to 2021; employer in the city since 2010 | One conclusion, **1 Jan 2019 to 1 Jan 2021**, timed, accepted |
| S2 | Job from "2021" (year only), still going; employer in the city from 2022, still going | From exactly 1 Jan 2022, still going; accepted |
| S3 | Job began between 1 Jan and 31 Mar 2021 and ended between 2 Jan 2023 and 1 Jan 2024; employer in the city from 1 Feb 2021 | From between 1 Feb and 31 Mar 2021, to between 2 Jan 2023 and 1 Jan 2024 |
| S4 | Job first said on 5 Mar 2024 (start not stated), still going; employer in the city since 2010 | From between 1 Jan 2010 and 5 Mar 2024, still going. (The job cannot have counted before the employer was there) |
| S4b | Job 2019, end only said (by 6 Mar 2024); employer since 2010 | B4: indeterminate, rule not applied. No conclusion (unchanged from 0.7.0) |
| S5a | Two stints, 2015 to 2017 and 2022 to 2025 | **Two conclusions**, one per period, both accepted, in either id order |
| S5b | The same, only the old stint supported | 2015 to 2017 accepted, 2022 to 2025 withheld, in either id order; overall withheld |
| S5c | The same, only the current stint supported | 2022 to 2025 accepted, 2015 to 2017 withheld, in either id order; overall withheld |
| S6a | Two employers, both in the city, both jobs 2019 to 2021 | **One conclusion, two derivations**, accepted; trace `derived_alternative` |
| S6b, S6c | The same, only one derivation fully supported (either) | Accepted through the supported one; the other shown as withheld; in either id order |
| S6d | The same, neither fully supported (one fact from each) | Withheld; both shown as withheld. Support is not pooled across derivations |
| S7a | Chain: "city has a metro from 2023" with `overlaps(incity, metro)` | Second rule **disproved** (0.7.0: indeterminate, `derived_premise`) |
| S7b | Chain, metro from 2020 | Second conclusion 1 Jan 2020 to 1 Jan 2021, accepted |
| S8 | Three levels: pass sold from 1 Jul 2020 to 2022 | Third conclusion 1 Jul 2020 to 1 Jan 2021; **identical** when the second conclusion is fed in as a stated fact with its time |
| S9 | Requirements declared, no conclusion time (rule B) | Conclusion with no time, `not_established` / `no_conclusion_time_declared`, **provisional**, one uncertainty item |
| S10 | `during(visit, job)`, `as_premise(visit)`: visit on 1 Jun 2021, job 2019 to 2022 | An event on 1 Jun 2021, accepted |
| S10b | The same, visit known only between 1 Mar and 30 Sep 2021 | An event between 1 Mar and 30 Sep 2021 |
| S11 | `before(left, next)`, `as_premise(next)`: left on 10 Mar 2021; next job from 1 Feb 2022, still going | A state from 1 Feb 2022, still going |
| S12 | `as_premise(job)`, no requirements, job carries no time | No time, `not_established` / `premise_carries_no_time`, provisional, uncertainty item |
| S12b | The same, job carries `TimeInterval()` | No time, `not_established` / `premise_time_unknown`, provisional |
| S13a | `timeless`, no requirements | No time, status timeless, accepted, no uncertainty item |
| S13b | A rule with requirements over that timeless conclusion | Not applied: B4's `derived_premise` (F74) |
| S14a | Two cities from disjoint jobs, predicate one-valued | No contradiction; both accepted |
| S14b | Two cities from overlapping jobs | Definite contradiction; status conflict; both conflicted |
| S14c | Two cities, the second job's start only first said | Potential contradiction; both provisional |
| S15a | Stated "does not work in the city" from 2023 | No contradiction; accepted |
| S15b | Stated "does not work in the city" from 2020 | Definite contradiction; conflicted |
| S16a | The same claim also stated, with no time | The stated one stays; the conclusion is derived beside it with 2019 to 2021 |
| S16b | The same claim also stated, with the same time | Both kept |
| S16c | S16a with a rule that declares nothing | As 0.7.0: no conclusion, recorded no-op |
| S17 | A rule that declares nothing, timed premises | As 0.7.0: conclusion with no time and no status, accepted |
| S20 | The `while_all` rule with the job supplied as an event | Not applied: B4's `wrong_kind`, its uncertainty item, no conclusion. The calculation is never reached |
| S21a | Nine ways to one derived premise and nine to another, joined by one rule: 81 derivations; nothing supported | 64 evaluated, all withheld; conclusion **provisional**, `ALTERNATIVE_DERIVATIONS_TRUNCATED` |
| S21b | The same, exactly one of the evaluated derivations supported | Accepted; the limitation is listed |
| S21c | The same, only a derivation beyond the first 64 supported | **Provisional**, `ALTERNATIVE_DERIVATIONS_TRUNCATED` (Draft 1's rule: withheld) |
| S21d | Eight ways and eight ways: exactly 64; nothing supported | All 64 evaluated; withheld; no truncation |
| S22 | The calculation called directly with an event under `while_all` | `RuntimeError`, the internal-fault message of B5-03 |
| S23 | S21's 81 derivations with the same facts under twelve different id assignments; each of the 81 single-derivation supports tried under each | The same 64 derivations examined under every assignment; 0 of 81 decisions change (64 accepted, 17 provisional). Draft 1.1: 62 of 81 changed |
| S24 | The same with one fact present twice (identical content, two ids, and two different generated source references): 81 derivations, the limit falling inside a pair of identical ones | The pair is left out whole: 63 examined, the same under every assignment; 0 of 81 decisions change. Draft 1.2's key, which read the source references: 2 of 81 changed |
| S25 | Eight ways and eight ways, twelve id assignments | All 64 examined; 0 of 64 decisions change; no truncation |
| S26 | 65 derivations identical in content (65 copies of one stated fact) | The documented exception: the first 64 by step id; decisions change with the ids for some supports, between accepted and provisional only |
| S18 | S5a through `execute_rules`, `orchestrate` and recovery | The same two timed conclusions on every path; counterfactual sees one claim |
| S19 | S1 asked in 2020 and in 2030 | Identical propositions and steps |

## 8. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | Every existing way of building a rule works unchanged; each refusal of B5-01 raises `ValueError`; `conclusion_time` is keyword-only |
| A2 | Rule A: propositions, steps and trace identical to 0.7.0 for every `execute_rules` call of the existing suite (before-and-after recording, with the recorder's own self-test) |
| A3 | `while_all` reproduces the `expected` column of the fixed table exactly, all 26,329 rows, including the groups of four and of five |
| A4 | No row's result is bolder or looser than the oracle's ranges |
| A5 | `as_premise` gives the named premise's `valid_time` or `occurred` equal field for field, for every one of the 155 interval shapes and 13 occurrence shapes that state at least one bound |
| A6 | Scenarios S1 to S26 give the stated results through `execute_rules` and `orchestrate` |
| A7 | The step and trace records of B5-04 are exactly as specified for each status, mode and reason; a rule A step has no `conclusion_time` key |
| A8 | Different periods: two conclusions, never merged, including two periods that touch at one instant |
| A9 | Same claim, period and status: one proposition, one step per derivation, trace `derived_alternative`; the graph shows each step deriving it |
| A10 | S5 and S6 give the same decisions when the proposition ids are exchanged; in general, for any conclusion with no tie group of more than 64, the decision and every listed derivation's content are the same under any assignment of proposition ids to the same facts |
| A11 | Each derivation is decided on its own leaves; support is never pooled (S6d); a contradiction on the conclusion applies to every derivation |
| A12 | `ConclusionEvaluation.derivations` lists every derivation with its own decision, in the specified order; it is empty for a single derivation, and every other field is then identical to 0.7.0 |
| A13 | A status `not_established` anywhere in a derivation caps accepted at provisional with the stated reason; a `timeless` or `timed` status never does |
| A14 | The uncertainty item of B5-06 has exactly the specified id, kind, refs, wording and hint for each of the three reasons, once per conclusion; `execute_rules`, recovery and counterfactual produce none |
| A15 | A rule with requirements over a timed conclusion is established, disproved or indeterminate by B4's formulas (S7a, S7b); over a conclusion with no time it gives `derived_premise` (S13b); three levels agree with the fed-in form (S8) |
| A16 | The five rows of B5-07 give the stated outcomes; the overall decision is computed as in 0.7.0 |
| A17 | `explain()` prints exactly the specified line for each state and each boundary wording; no line is added for rule A; a not-established time is never printed as timeless |
| A18 | `execute_rules`, recovery, counterfactual and `orchestrate` give the same conclusions and times for the same input |
| A19 | No qualifier, evidence date or `as_of` changes any proposition, step or decision |
| A20 | The internal-fault error of B5-03 is raised, with its exact message, when the formula is made to disagree with an established overlap and when the calculation is given an event or an untimed premise under `while_all`; no conclusion is built. `while_all` never yields `not_established` |
| A21 | **The 64 limit.** (a) Order: derivations are evaluated in ascending order of the content key of B5-05; no id enters a key. (b) With 65 direct alternatives and with nested alternatives that multiply past 64 (S21, S23): the 64 evaluated are the same derivations, by content, under at least twelve different assignments of ids to the same facts, and every single-derivation support gives the same decision under all of them. (c) A tie group is never divided: when the limit falls inside one, the whole group is left out, under every id assignment (S24). (d) Each row of the table in B5-05 point 7 gives the stated outcome; at exactly 64 nothing is truncated (S21d, S25). (e) No withheld, conflicted or rejected outcome is ever reported for a conclusion whose derivations were truncated, except through a definite contradiction on the conclusion itself. (f) The documented exception: with more than 64 derivations identical in content, the first 64 by step id are evaluated, and the outcome is accepted or provisional only (S26). (g) The key's form: two propositions equal in every listed member have equal keys whatever their ids and `source_refs`; an instant given in two zones has one spelling; the order in which qualifiers were filled changes nothing; a difference in any listed member gives different keys. (h) **What kind of guarantee this is:** the algorithm of B5-05, in which no identifier enters a key, together with the listed cases under the listed id assignments. It is a tested guarantee over those cases and the stated algorithm, not a proof over every possible graph or assignment of identifiers |
| A22 | Version 0.8.0; release pins for each changed file; the 0.4.0 table untouched; `temporal_requirements.py` and `primitives/comparison.py` at their present bytes; the public-name pin exactly the four listed names, and the calculation not exported |
| A23 | All 258 tests of `tests/test_erc_overlay.py` pass unedited; the full suite fails only the recorded four |
| A24 | Every step producing one conclusion carries the same status; the status is found on the steps and nowhere on the `Proposition`, whose contract and fields are unchanged |
| A25 | An event supplied to a `while_all` rule: the rule is not applied, with B4's `wrong_kind` record and uncertainty item, and no conclusion (S20) |
| A26 | A timeless or not-established conclusion fed back as a stated proposition is read as a stated fact with no temporal statement; a timed one keeps its time (S8) |

## 9. Release gate

- **Fail before, pass after:** every test in the two new files; each "this stays as it is" test also checks the new behaviour beside it.
- **Deliberately revised, each by name with its reason:** the 12 B4 tests of F71, as classified below (DP-1, decided); the release pins; the version test; the public-name pin. Nothing else is foreseen. Any further test that changes is reported, not absorbed.

| B4 test | What it is there to check | Revision | Expected decision |
|---|---|---|---|
| `test_a6_named_scenario` O1 | B4 establishes an overlap | rule also declares `while_all(left, right)` | accepted, as before |
| `test_a6_named_scenario` D1, D4, D8 | B4 establishes `during` | rule also declares `as_premise(left)` (the event) | accepted, as before |
| `test_a6_named_scenario` E1, E4, E6, E9 | B4 establishes `before` | rule also declares `as_premise(right)` (the later premise) | accepted, as before |
| `test_a6_the_city_rule…[P1]` | The city rule fires when its requirement is established | rule also declares `while_all(job, place)` | accepted, as before |
| `test_a11…` (both id orders) | A failed match never suppresses another | rule also declares `while_all(job, place)` | accepted and withheld, as before |
| adapter `test_b4_a_declared_rule_over_two_dated_overlapping_facts…` | A declared rule gives the same conclusion as a plain one | rule also declares `while_all(job, place)`; the `explain()` comparison allows the one added `time:` line | accepted, as before |

  None of the twelve is changed to *provisional*: none was written to check a missing declaration. That consequence of OP-2 is checked by new B5 tests (S9, A13, A14). The reason recorded on each revised test: "B5 (0.8.0): a rule with requirements and no conclusion time now gives a provisional conclusion (OP-2); this test is about B4's firing, so its rule declares its conclusion's time and the original decision is kept." The scenarios of that parametrised test that do not fire are unaffected by the added declaration.
- **Unedited and passing:** `tests/test_erc_overlay.py` (258); every other ERC test.
- **Before-and-after recording** of every `execute_rules` call of the existing suite for rule A.
- **Guards that stay:** the adapter's three; the four recorded failures.
- **Breakages:** all 118 `erc` and 93 `adapter` still caught, re-pointed where a refactor makes one stale, never dropped; a new one for every B5 rule, including each bound of the formula read too boldly, each merge condition, pooling of support across derivations, and each `explain()` state.
- **The measurement tools carry their own mutation tests** (done for the oracle at this stage).
- **Limitations carried forward:** section 12.

## 10. How B5 prepares B6

After B5 every proposition ERC holds, stated or derived, either carries a time in the one shared contract or is in a named state (timeless by declaration, time not established, or a rule A conclusion). B6 can ask one question of all of them: does this cover the asked-at moment? B5 reads no `as_of` (A19) and drops or downgrades nothing because of it.

**A requirement on B6, recorded here so that it is not discovered late.** For a conclusion, the difference between timeless, not established and a rule A conclusion is in the producing inference step, not in the proposition (B5-02). **B6's specification must read a conclusion's temporal status from its producing inference step, and must never infer timelessness from empty time fields.** B6 must therefore work on a result with its inference steps, not on bare propositions. If B6 needs that difference to survive a conclusion being handed back in as a stated fact, a way of carrying it has to be designed then; B5 deliberately does not add one, and does not change the `Proposition` contract to hold it.

## 11. What changes for someone using ERC today

| Today's use | After B5 |
|---|---|
| Rules that declare nothing | Nothing changes |
| Rules with B4 requirements and no conclusion time | Still fire; the conclusion is now *provisional* with "time not established" until the rule declares its conclusion's time |
| Code reading `ConclusionEvaluation` | Every existing field as before; one added field |
| Code reading a result's propositions | A conclusion may now carry `valid_time` or `occurred`, and one claim may appear as several conclusions with different periods |
| Code reading inference steps | Two steps may now name the same output proposition |

## 12. Limitations carried forward

- The Asha conclusion now carries 2019 to 2021 but is still accepted when asked about 2024: B6.
- Rule A conclusions carry no time and no status until B6 (OP-6).
- The conclusion-time vocabulary has three entries. "At the start of a premise" and "at the end of a premise" (for example, an event at the moment a job began) are not expressible.
- A timeless conclusion used under a later requirement is reported with B4's words "carries no time yet" (F74).
- The overall decision is withheld when one of several periods is withheld (F76).
- Counterfactual compares claims only (F75).
- Outside `orchestrate`, a time not established is in the step and trace only.
- Periods of one claim are never merged, including adjacent ones.
- The temporal status is derivation metadata: it does not travel with a proposition that is fed back in as a stated fact (B5-02, A26).
- Beyond 64 derivations of one conclusion the search is incomplete: the conclusion can be accepted or provisional, never definitely withheld (B5-05).
- With more than 64 derivations of one conclusion identical in content, which of them are examined depends on step ids; the outcome is accepted or provisional only (F85, S26). Full independence from identifiers inside a tie group is a design objective for a later increment.
- The key treats what a caller puts in a claim as content. For the Engram adapter that includes Engram's entity ids as subjects and objects; if those are regenerated, the order of derivations can change (B5-05, F89).
- B4's limitations stand: cautious answers; a changed declaration needs a new rule version (now including `conclusion_time`), not enforced; F43; F49.

## 13. Points raised by the drafting

| # | Point | As drafted | Reviewer | Manj |
|---|---|---|---|---|
| DP-1 | OP-2 changes 12 of B4's own tests (F71) | Accepted consequence. The twelve are classified one by one (section 9): each is about B4's firing, gets a conclusion-time declaration and keeps its decision; OP-2's consequence is checked by new tests | Accept; classify each test, do not weaken | **Accepted, 12 Nov 07:51** |
| DP-2 | OP-5 applies to every rule that declares (B, C, D); rule A keeps today's duplicate handling | Unchanged from Draft 1 | Accept (both reviews) | **Accepted, 12 Nov 08:19** |
| DP-3 | `while_all` is refused unless the rule also requires `overlaps` between each pair of the named premises | Unchanged; states-only now explicit (B5-01) | Accept (both reviews) | **Accepted, 12 Nov 08:19** |
| DP-4 | `as_premise` over a premise whose time is wholly unknown | Not established, fields empty | Accept (both reviews) | **Accepted, 12 Nov 08:19** |
| DP-5 | A time not established anywhere beneath a conclusion caps it at provisional | Unchanged | Accept (both reviews) | **Accepted, 12 Nov 08:19** |
| DP-6 | The limit of 64 derivations | **Changed as the reviewer asked, twice:** 64 kept; no definite outcome against a conclusion from an incomplete search (Draft 1.1); the 64 chosen by content and never by id, tie groups kept whole, id-permutation scenarios and criterion (Draft 1.2: B5-05, S23 to S26, A21) | Draft 1: modify. Draft 1.1: accept with the ordering correction. Draft 1.2: ready for audit; the exception to be decided explicitly by the independent auditor; the key to be clarified (done in Draft 1.4) | **Accepted, 12 Nov 08:19** (Draft 1.2, which states the exception) |
| DP-7 | New public names | **Changed as the reviewer asked:** four names; the calculation is internal (B5-10) | Draft 1: modify. Draft 1.1: accept | **Accepted, 12 Nov 08:19** |
| DP-8 | The `explain()` wording | **Changed as the reviewer asked:** every printed end says `(end exclusive)`; alternatives name their rule, decision and facts (B5-08). One difference from the reviewer's examples: days stay in the form the existing fact lines use (`2019-01-01`), not `1 Jan 2019`, so that one explanation does not show two date styles | Draft 1: modify. Draft 1.1: accept | **Accepted, 12 Nov 08:19** |

## 14. Decision register

| # | Recommended decision (reviewer; accept recommended again on Draft 1.1, OP-3 subject to the ordering correction) | How the draft implements it | Manj |
|---|---|---|---|
| OP-1 | Each rule declares how its conclusion gets its time, from a small fixed vocabulary; named premises; no universal formula | B5-01, B5-03 | **Accepted, 12 Nov 08:19** |
| OP-2 | Requirements without a conclusion-time declaration: derive the claim, time unestablished, recorded, nothing inferred | B5-02 rule B, B5-05 point 4, B5-06 | **Accepted, 12 Nov 07:51** |
| OP-3 | One conclusion per distinct period; same claim and period share one proposition with every derivation kept; accepted when at least one complete derivation satisfies the evidence policy; each derivation evaluated independently, no pooling | B5-04, B5-05 | **Accepted, 12 Nov 08:19** |
| OP-4 | Time cannot be established: keep the claim, leave `valid_time` and `occurred` empty, record it, at most provisional; no `TimeInterval()` | B5-03, B5-05, B5-06; F69 | **Accepted, 12 Nov 08:19** |
| OP-5 | Stated and derived propositions kept apart even when identical | B5-04 | **Accepted, 12 Nov 08:19** |
| OP-6 | Rules with no B5 declaration and no B4 requirements keep exactly their 0.7.0 behaviour | B5-02 rule A; A2 | **Accepted, 12 Nov 08:19** |
| OP-7 | `explain()` shows the conclusion's time, with the corrections of the review of Draft 1 | B5-08 | **Accepted, 12 Nov 08:19** |
| OP-8 | Counterfactual stays claim-only; temporal outputs tested independently; limitation documented | B5-09; A18; section 12 | **Accepted, 12 Nov 08:19** |
| OP-9 | ERC 0.8.0 | B5-10 | **Accepted, 12 Nov 08:19** |

**Decisions recorded (Manj).**

| Date | Point | Decision | Basis |
|---|---|---|---|
| 12 Nov 2026, 07:51 | OP-2 | Accepted: a rule with temporal requirements and no conclusion-time declaration derives its claim with the time not established; nothing is inferred | "I accept OP2 and DP1"; the reviewer's recommendation; F71 |
| 12 Nov 2026, 07:51 | DP-1 | Accepted: the consequence for B4's twelve tests, revised by name with the reason recorded | The same message; F78 |
| 12 Nov 2026, 08:09 | The reviewer's change request on Draft 1.1 | Agreed: prepare Draft 1.2 resolving the derivation-ordering issue for the 64 limit, with id-permutation tests, all accepted decisions preserved and no repository change | "Good review from the auditor; just need those changes; I agree with the changes request"; F83 |
| 12 Nov 2026, 08:19 | OP-1, OP-3 to OP-9; DP-2 to DP-8 | Accepted, each as recorded in the registers above and as Draft 1.2 implements it (OP-3 and DP-6 with the ordering correction of Draft 1.2) | "Accept OP-1, OP-3 to OP-9 and DP-2 to DP-8, which the auditor recommends accepting"; the reviewer's recommendations on Drafts 1 and 1.1 |
| 12 Nov 2026, 08:25 | Relayed, not a new decision: the reviewer's assessment of Draft 1.2, with a recommendation to accept the exception of F85 on conditions | Taken up in Draft 1.4: the key clarified in the three ways asked; full id-independence recorded as a later design objective | The relayed note: "I would not block B5 over this exception, provided we tighten one detail in the specification" |

**All nine OP points and all eight DP points are decided. No point is open.** The decisions settle the design; they are not the freeze. The reviewer has now seen the ordering correction (Draft 1.2) and judges it to answer the objection.

**One matter is expressly left for the independent auditor: the exception of F85** (more than 64 derivations identical in content). Manj accepted DP-6 on Draft 1.2, which states it. The note relayed at 08:25 recommends accepting it for B5 because it fails on the cautious side, with full id-independence as a later objective, and says it should not be accepted silently. It is therefore listed here for the auditor's explicit decision, and is not presented as harmless.

**The reviewer's nine corrections to Draft 1, and where each is met:** (1) decisions recorded: this section; (2) DP-1 classification: section 9, F78; (3) `shared_period_not_certain`: B5-03, B5-04 (closed list of reasons), F82, A20; (4) `while_all` states only: B5-01, B5-03, F79, S20, A25; (5) status as derivation metadata and B6: B5-02, section 10, A24, A26; (6) the 64 limit and nested alternatives: B5-05 point 7, F80, S21, A21; (7) the calculation helper: B5-10; (8) exclusive end and alternative provenance in `explain()`: B5-08; (9) four or more premises: F81, section 6, A3.

**The reviewer's points on Draft 1.1, and where each is met:** the derivation ordering: B5-05 (order by content, tie groups, the stated exception), F83 to F85, S23 to S26, A10, A21; B6 must consume the inference-step metadata: section 10, stated as a requirement on B6; the four- and five-premise results: unchanged, still described as validation and not proof; the oracle could not be run from the zip: F86.

**The three points on Draft 1.2, and where each is met:** (1) `source_refs` in the key: removed, with the reason and the measurement (B5-05 "Identifier exclusion", F87, F88, S24, A21 g); canonical representation: B5-05 "Canonical form"; identifier exclusion: B5-05, F89; tie semantics and the unresolved-reference key: B5-05; (2) the ordering tests are bounded: A21 (h), section 15; (3) the exception needs an explicit decision: section 14, B5-05, section 12.

## 15. What has not been done or verified

- The sketch is a measurement. It now includes the internal-fault error and the 64 limit with its outcome rule. It does not include the `explain()` lines or the public exports; those are specified, not measured.
- The 65-direct-alternatives case of A21 was not run with distinct facts; the nested case was (S21, S23) and the identical-content case was (S26). The id-order check used twelve seeded id assignments, not every permutation. A26's timeless and not-established halves were not run; its timed half was (S8).
- The before-and-after recording for rule A (A2) has not been run; the evidence so far is that every existing test outside the 17 of F71 passes on the sketch.
- The breakage suites were not run against the sketch.
- **Run independently, as reported by the reviewers (not by the author):**

| Package | Tool | Reported result |
|---|---|---|
| Draft 1.2's zip | Oracle | Exit code 0; all six runs passed; all five wrong formulas caught |
| Draft 1.2's zip | Named scenarios | Ran; the reported outcomes reproduced |
| Draft 1.2's zip | Ordering check, full | Not completed: exceeded the reviewer's time |
| Draft 1.4's first zip | Oracle | Exit code 0; all six runs passed; all five wrong formulas caught |
| Draft 1.4's first zip | Named scenarios | Exit code 0 |
| Draft 1.4's first zip | Ordering check, short mode | Exit code 0, about 7 seconds: S23 the same 64 under four id assignments, 0 changes among 14 sampled supports; S24 63 examined, the tie group left out whole, 0 changes; S25 exactly 64, no truncation; S26 the documented exception present, varying between accepted and provisional only |

  **Not yet run by anyone but the author:** the full ordering check (12 id assignments, every support), from which the specification's figures come; the table generator; and anything in the revision 2 zip, which differs from the first Draft 1.4 zip only in `README.txt` and the first line of `b5_order.py`. These runs validate the tools on the throwaway package; they do not validate a B5 implementation, because none exists.
- The canonical form of the key (A21 g) is implemented in the sketch; its individual properties (zones, qualifier order, each member) were not each tested separately at this stage.
- GitHub's run list was not re-read. The handover and the ERC Adapter Board have not been edited in this session.

## 16. What happens next

1. This Draft 1.4 goes to the independent auditor with its SHA-256 and the zip, to audit in particular: the content key (its members, canonical form and identifier exclusion), the exception of F85 and whether to accept it, and whether A21 describes the guarantee accurately; and, as before, the formula and the acceptance criteria.
2. Any finding is answered in a further draft. Then Manj's own word for the freeze, naming the SHA-256 of the text to be frozen. A reviewer's approval is a recommendation, not the freeze.
3. Nothing else happens until then: no freeze, no tests, no source change.
