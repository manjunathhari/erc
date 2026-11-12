# ERC B5 — Conclusion Temporal Propagation: specification freeze record

**Revision 4 of this record. 12 November 2026.** Revision 1 (`e09f6271…12c1`) recorded the freeze and Record 1. Revision 2 (`ba546d12…7c86`) appended Amendment 1. Revision 3 (`05e6104c…97ea`) appended Amendment 2 beneath it. Revision 4 adds three rows to the Amendment 2 table (the reviewer's formal recommendation, Manj's formal approval by hash, and the state of the build); the approved text of the specification and of both amendments is unchanged, and nothing else is changed except this line.

## What is frozen

| Item | Value |
|---|---|
| Frozen specification | `erc-b5-spec-draft1_4-r2.md` (Draft 1.4 revision 2), 76,858 bytes |
| SHA-256 of the specification | `ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581` |
| Supporting package | `erc-b5-stage1-draft1_4-r2.zip` |
| SHA-256 of the package | `8ef2c5068cb8148c2d04a89e783f77525f2944fa3980f38e9145a071ae378cc3` |
| Fixed expected table | `b5_expected_table.tsv`, 26,329 rows, SHA-256 `5cb865c2247eaae83dfe296bdd4d42ae693c40cfe6fb7e9603056ef36876f40e` |
| Frozen by | Manj, in his own words, 12 Nov 2026 08:57 IST: "accept the F85 exception and freeze B5 Draft 1.4 revision 2" |
| Repository at the freeze | `manjunathhari/erc`, branch `erc-adapter-1`, head `4f476fdcebf29ae4d11c527632d34b46e18cafac`, working tree clean |
| Project copy | `claude/erc-b5-spec.md` and `claude/erc-b5-spec-part2.md`; removing the one note line at the top of each and joining them gives the frozen file |

Both hashes were recomputed from the files at the time of this record and match the values sent with revision 2.

The frozen text is not edited. Any later change is an amendment recorded beneath this record with its own approval, as was done for B4.

## Record 1: the F85 exception

Section 14 of the frozen specification says the exception of F85 is "expressly left for the independent auditor". That sentence is now out of date and is superseded by this record. It is not corrected in the frozen file, because the file was frozen as it stands.

| Point | Record |
|---|---|
| The exception | With more than 64 derivations of one conclusion identical in content, which 64 are examined depends on step ids |
| Measured effect | 10 of 65 decisions change with the ids (scenario S26) |
| Bound | The change is between accepted and provisional only. No withheld, conflicted or rejected outcome can come from the incomplete search |
| Decision | **Accepted as a bounded B5 limitation** |
| Decided by | Manj, as project owner, 12 Nov 2026 08:57 IST |
| Reviewer's position on file | The note relayed at 08:25 recommended accepting it on condition that the content key was tightened in three ways. Those three were made in Draft 1.4. The independent review of Draft 1.4 reproduced the exception and its bound with the short ordering run |
| What is not on file | A statement from the independent auditor, in the auditor's own words, accepting F85. None was given to me. The acceptance recorded here is Manj's own. If such a statement exists it can be added beneath as Record 2 |
| Carried forward | Full independence from identifiers, including inside a tie group, remains a design objective for a later increment (section B5-05 of the frozen text) |

## What the freeze authorises, and what it does not

| Step | State |
|---|---|
| Stage 1: inspection and specification | Complete and frozen |
| Tests first | Not authorised. Waits for Manj's word |
| Implementation | Not authorised |
| Local commit | Not authorised |
| Push | Not authorised |
| Tag | Not authorised |

Nothing in the repository was changed by the freeze. `main`, `fable-erc-adapter`, `engram_erc_bridge.py` and `engram_knowledge/` are untouched. No test and no implementation code for B5 exists in the repository; the sketch used for measurement is a throwaway copy outside it.

## Amendment 1 (approved 12 November 2026)

| Item | Value |
|---|---|
| Approved text | `erc-b5-amendment1-r2.md` (Amendment 1, revision 2), SHA-256 `bcbcf020b818f993dc5cab990a9534ba301bd8617301f6c550fd7e10a81cb38d` |
| Approved by | Manj, in his own words, 12 Nov 2026 11:13 IST: "approve Amendment 1, revision 2, as written. Append Amendment 1 revision 2 beneath the existing freeze record, preserving the original frozen specification and its hash." |
| Frozen specification | Unchanged: `erc-b5-spec-draft1_4-r2.md`, SHA-256 `ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581` |
| Review findings relayed with the approval | A1-1 to A1-6 each accepted. B1 semantics remain authoritative: the difference between an unknown boundary and an explicitly unbounded one is preserved, and the amendment does not alter B1, B3 or B4. TP-2 is resolved |
| Point left open in the amendment's text | The "point for Manj's decision" in A1-1 (whether to adopt the review's other meaning for an unknown side) is **decided by this approval: not adopted; the contract's meaning stands** |
| Tests written against it | `erc-b5-tests-first-r2.patch`, SHA-256 `99021b08ca49442383bb32e463b911054f74d33a2c178d11cdb91b17df1a9a3e`, unchanged by the approval |
| Authorises | Nothing further. Implementation, local commit, push and tag each still wait for Manj's own word |

The approved text follows word for word, with its headings set one level lower. Where it says "draft for review", that was its status when written; it is approved as of the table above.


12 November 2026. Drafted on Manj's instruction of 10:24 ("Proceed with a narrowly scoped B5 specification amendment"), after the auditor's review of the tests-first package (relayed with that instruction).

**Revision 2 (12 Nov, 11:20), after the review relayed at 11:08.** One paragraph of A1-1 is rewritten (the meaning of an unknown side), and A1-6 now says which tests go through `Reasoner.reason()`. No printed wording, no rule and no test changed, so the test patch is unchanged (`99021b08…9a3e`). Revision 1 of this amendment was `3d4ea201…d4ec`.

**Status: draft for review. It takes effect when Manj approves it.** It is then appended beneath the freeze record (`claude/erc-b5-freeze-record.md`) as Amendment 1.

**The frozen text is not edited.** Frozen specification: Draft 1.4 revision 2, SHA-256 `ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581`.

**Scope.** Section B5-08 (the wording of `explain()`), two details of the records in B5-04 and B5-05, one sentence of B5-10, and criteria A17 and A22. **Not reopened:** the shared-period formula, the three statuses, the rule kinds, the order of derivations, the content key, the limit of 64, the F85 exception, and every decided point OP-1 to OP-9 and DP-1 to DP-8.

### A1-1. B5-08: words for every boundary a conclusion can carry (TP-1)

**Why.** `as_premise` copies the named premise's period unchanged, so the conclusion can carry any period the contract accepts. The frozen table words four kinds of start and four kinds of end. The contract (`BoundaryStatus`, ERC 0.5.0) has six of each. Three had no words: a start that is only a lower bound, an end that is only an upper bound, and a side of which nothing is stated. The adapter sends two of them today: an end that is only an upper bound (a closing date that was only said) and a period with an end and no start.

**The rule.** The words for each side are chosen by that side's status as the contract derives it (`TimeInterval.start_status`, `TimeInterval.end_status`). The table below replaces the two-column wording table of B5-08. Rows marked *frozen* are word for word as frozen; rows marked *added* are new.

| Status of the side | Start | End | |
|---|---|---|---|
| exact | `from D` | `to D (end exclusive)` | frozen |
| within | `from between D1 and D2` | `to between D1 and D2 (end exclusive)` | frozen |
| no later than | `from no later than D` | `to no later than D (end exclusive)` | start frozen; **end added** |
| no earlier than | `from no earlier than D` | `to no earlier than D (end exclusive)` | **start added**; end frozen |
| unknown (nothing is stated for that side) | `start not known` | `end not known` | **both added** |
| unbounded (explicitly no boundary) | `with no stated beginning` | `still going` | frozen |

The line is still `  time: holds <start> <end>; <basis>`. Examples of the added words:

- `  time: holds from no earlier than 2019-01-01 to no later than 2024-03-06 (end exclusive); the time of job, rule works_in_city@1`
- `  time: holds start not known to 2021-01-01 (end exclusive); the time of job, rule works_in_city@1`
- `  time: holds from 2019-01-01 end not known; the time of job, rule works_in_city@1`

**An unknown side is never worded as an unbounded one, and the reverse.** The meaning of each word is the contract's, unchanged (ERC 0.5.0, `engram_erc/contracts.py`, signed off at B1):

| Words | Status | What it says, in the contract's own terms |
|---|---|---|
| `start not known` | unknown | Nothing is given for the start. The contract: "the boundary exists and nothing is known about it" |
| `with no stated beginning` | unbounded | `start_unbounded`: "explicitly no boundary in that direction" |
| `end not known` | unknown | Nothing is given for the end. The contract: "an interval with a start and no end *ended at a moment not known*" |
| `still going` | unbounded | `end_unbounded`: "only `end_unbounded` says it has no end so far" |

The explanation line adds nothing to these meanings and takes nothing away: it prints which of the two statuses the period carries.

**A point for Manj's decision, not settled by this amendment.** The review relayed at 11:08 proposed defining `start not known` as "the record does not establish whether the period has a beginning" and `end not known` as "does not establish whether the period is ongoing or has a finite end". That is a different meaning from the contract's, quoted above: in ERC a missing side is a boundary that exists and is not known, and "ongoing" has its own spelling (`end_unbounded`). B3's comparison and B4's requirements are built on that reading. Adopting the proposed definition would change the meaning of the B1 contract, which is outside a wording amendment to B5-08, so it is not made here. Revision 1's sentences ("began at some moment that is not stated", "ended, or will, at a moment that is not stated") are replaced because they paraphrased the contract loosely; the contract's own words now stand in their place.

**No end day, no "(end exclusive)".** The words `(end exclusive)` follow every printed end day, as frozen. `end not known` and `still going` print no day and carry no such words.

**Choice of words, for the reviewer.** The auditor recommended using the existing fact-line vocabulary where possible, and saying explicitly that an absent bound is not stated. The existing fact lines already say `start not known` for this case, and "unknown" is the contract's own name for the status, so the amendment uses `start not known` and `end not known`. "Not stated" was not used because it reads too close to the frozen `with no stated beginning`, which means the opposite thing.

**`while_all` is unchanged.** Its result can only be exact, within, no later than (start), no earlier than (end) or unbounded, as frozen. The added rows arise only through `as_premise`.

**Events are unchanged.** The four frozen wordings (`event on D`, `event between D1 and D2`, `event by D`, `event no earlier than D`) already cover every event window that states a bound.

**The existing fact lines are not changed**, as frozen.

### A1-2. B5-04: an unstated side of an event is omitted from the step record (TP-3)

The frozen text says the record carries, when timed, "`valid_time` (each stated field of the interval …) or `occurred` (`earliest`, `latest`)". It did not say what is written for an event known on one side only.

**Now:** `occurred` carries only the stated sides, exactly as `valid_time` carries only the stated fields. An event known only as "by D" is recorded as `{"latest": …}`; one known only as "no earlier than D" as `{"earliest": …}`. Nothing is written as null. The same holds for the copy of the record in the trace entry.

### A1-3. B5-05: the names of the derivation record (TP-3)

The frozen text says each `DerivationEvaluation` carries "its step ids, decision, leaf ids and reasons". The names are now fixed:

`DerivationEvaluation(step_ids, decision, leaf_premise_ids, reasons)`

- `step_ids`: the inference steps chosen in that derivation. The step that produces the conclusion itself is among them.
- `decision`: that derivation's own decision.
- `leaf_premise_ids`: its stated propositions.
- `reasons`: its own reasons.

In the step record (`parameters["conclusion_time"]`), `premises` is always a list, empty for a rule with requirements only and for `timeless`; `mode` is null for a rule with requirements only. This is as frozen and is restated here because the tests fix it.

### A1-4. B5-10 and A22: where the names live is not part of the contract (TP-3)

The frozen B5-10 says the calculation "lives in `engram_erc/conclusion_time.py`", and section 5 lists that file. That stays as the plan for the implementation, and is **not** a tested contract.

**The contract is:** the four names `ConclusionTime`, `ConclusionTimeKind`, `ConclusionTimeStatus` and `DerivationEvaluation` are importable from the package root; the public names are the 305 of 0.7.0 and exactly these four; the calculation is not among them. Which module defines each name is an implementation detail.

A22 is read accordingly: "the public-name pin exactly the four listed names, and the calculation not exported". No test asserts a file or module location.

### A1-5. A17: the order of the lines under a conclusion (TP-4)

The frozen text gives the lines and says the alternatives come "after the `because:` lines of the chosen one". The exact order is now fixed:

1. `conclusion: …`
2. `  time: …` (rules B, C and D only; nothing for a rule that declares nothing)
3. the chosen derivation's `  because:` lines, each with its own indented lines as today
4. one `  also derived by rule … (…) from: …` line for each other evaluated derivation, in the evaluator's order
5. `  further derivations were not examined (limit 64)`, last, when any were left out

### A1-6. A17: how it is tested (TP-2)

- **Every shape the adapter can actually send is tested through the public path:** facts are written to Engram, `Reasoner.reason()` adapts and reasons over them, and `Reasoner.explain()` prints the result with the normal fact lines (`test_b5_a17_through_engram_…`, eleven cases; no `AdaptedRequest` or `Reasoning` is built by hand in them). The shapes: a start stated to the year, a start and an end stated to the day, an end stated to the month, a start that was only first said, **a closing date that was only said**, an end with no start, and an event stated to the day, stated to the year, and only said.
- **Shapes the adapter never sends** are tested at the explanation layer only: `explain()` is handed a `Reasoning` built by hand from ERC propositions (the helper `explained()`), which does not pass through the adapter. For four of them (an end that is only "no earlier than", an end that is not known, a period of which nothing is known, an event with only an earliest day) the existing fact lines cannot print the fact, so those cases leave the `fact:` lines out and check the lines under the conclusion exactly.

### What does not change

No rule of B5-01 to B5-07 or B5-09. No number in section 6. No scenario's stated result. The release gate, the limitations carried forward and the requirement on B6 stand as frozen.

## Amendment 2 (approved 12 November 2026)

| Item | Value |
|---|---|
| Approved text | `erc-b5-amendment2-r1.md` (Amendment 2, revision 1), SHA-256 `eeffe7ad745f1bbe5ba42a36f547897a63c59558f5560fe6e721935dba1783a2` |
| Approved by | Manj, in his own words, 12 Nov 2026 17:46 IST: "approved Amendment 2," |
| Frozen specification | Unchanged: `erc-b5-spec-draft1_4-r2.md`, SHA-256 `ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581` |
| Amendment 1 | Unchanged: revision 2, SHA-256 `bcbcf020b818f993dc5cab990a9534ba301bd8617301f6c550fd7e10a81cb38d` |
| What it settles | BP-2 and BP-3 of the build report (`erc-b5-build-report-r1.md`), as the reviewer recommended in the findings relayed at 17:39. The change for a mixed run against 0.7.0 (a plain rule and a rule with requirements only, deriving one claim, now give two conclusions) was set out in the amendment and in the reply that carried it |
| State of the build when approved | The implementation of the build report, uncommitted, does not yet follow this amendment: it has the order dependence of BP-2 and the global ordering of BP-3 |
| Reviewer's formal recommendation | Relayed by Manj, 12 Nov 2026, after the approval of 17:46: "Formal recommendation Recommended for approval I find no reason to reopen Amendment 1, the temporal formula, statuses, canonical key, derivation limit, F85 or other previously settled decisions." A recommendation only; the approval is Manj's |
| Formal approval for this record | Manj, in his own words, 12 Nov 2026 18:48 IST: "I approve approve Amendment 2 revision 1, SHA-256 eeffe7ad745f1bbe5ba42a36f547897a63c59558f5560fe6e721935dba1783a2, as written, for addition beneath Amendment 1 in the B5 freeze record" |
| State of the build at revision 4 of this record | The corrections were authorised by Manj at 17:53 and made. Build report revision 2 (`erc-b5-build-report-r2.md`, SHA-256 `82276ef14490c9b6f4fd5737b10fa919f04078735ee5fb3651ab65323317b287`): 4 failed (the recorded four), 1,858 passed; uncommitted; run by Claude only |
| Authorises | Nothing further, by its own last section. The corrections, the added tests and breakages, and the repeat of the suite, the recording and the breakage suites each wait for Manj's own word; so do the commit, the push and the tag |

The approved text follows word for word, with its headings set one level lower. Where it says "draft for review", that was its status when written; it is approved as of the table above.


12 November 2026. Drafted after the reviewer's findings on the build report, relayed by Manj at 17:39 (BP-2: decision required; BP-3: correction required; proposed step 1: "Agree and freeze Amendment 2 covering BP-2 and BP-3").

**Status: draft for review. It takes effect when Manj approves it.** It is then appended beneath the freeze record after Amendment 1. Until then no source file and no test is changed.

**The frozen text is not edited.** Frozen specification: Draft 1.4 revision 2, SHA-256 `ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581`. Amendment 1 revision 2 (`bcbcf020b818f993dc5cab990a9534ba301bd8617301f6c550fd7e10a81cb38d`) stands unchanged.

**Scope.** One row of the table in B5-04 (when a conclusion is already present), one paragraph of B5-05 (when the order of derivations is worked out), two new acceptance criteria and two limitations. **Not reopened:** the shared-period formula, the three statuses, the content key and its canonical form, the order of derivations, the limit of 64, the tie-group rule, the F85 exception, every decided point OP-1 to OP-9 and DP-1 to DP-8, and Amendment 1.

### A2-1. B5-04: a rule that declares nothing and a rule that declares never share a conclusion (BP-2)

**What was found.** The frozen table says, for a rule that declares nothing: "as today: any proposition with the same claim and the same `valid_time` makes the match a recorded no-op". "Any proposition" includes a conclusion derived earlier in the same run by a rule that declares. The same table says a conclusion of a rule that declares nothing "never merges with one of a rule that declares". The two statements disagree when the declaring rule's conclusion comes first, and rules are applied in order of rule id, so the outcome depended on the rules' names. The reviewer reproduced it. Measured:

| Rules deriving one claim | Order by rule id | 0.7.0 | Build as it stands | With this amendment |
|---|---|---|---|---|
| Plain rule and a timeless rule | plain first | (not possible in 0.7.0) | 2 conclusions | 2 conclusions |
| | timeless first | | **1** (the plain rule's match a no-op) | 2 conclusions |
| Plain rule and a rule with requirements only | plain first | 1 | 2 conclusions | 2 conclusions |
| | requirements first | 1 | **1** | 2 conclusions |

A second form of the same fault: the plain rule's check compares `valid_time` only. A conclusion of a declaring rule that is an event (`occurred` set, `valid_time` empty) would also have suppressed an untimed conclusion of a plain rule.

**The rule, replacing the cell "Rule A / Already present?" of B5-04.**

> As in 0.7.0: a proposition with the same claim and the same `valid_time` makes the match a recorded no-op (`no_op_duplicate_conclusion`). **Conclusions derived in the same run by a rule that declares (kinds B, C and D) are not considered.** Considered, as before: every proposition given to the run, whatever its kind, and every conclusion derived earlier in the run by a rule that declares nothing.

The cell for rules B, C and D is unchanged: only a conclusion derived earlier in the run by a rule that declares, with the same claim, time and status, is the same conclusion.

**Consequences, stated so that they are decided knowingly.**

- A run whose rules all declare nothing is not affected: there are no such conclusions to leave out. The 1,226 recorded calls stay identical.
- **A mixed run changes against 0.7.0.** A plain rule and a rule with requirements only, deriving one claim from the same facts, gave one conclusion in 0.7.0. They now give two: the plain rule's, with no time and no status, decided as in 0.7.0; and the other rule's, with its time not established, at most provisional. The frozen text already produced this in one of the two orders; the amendment makes it the same in both.
- Two propositions may therefore say the same thing with the same empty time fields and differ only in what their producing steps record. That follows from the frozen principle that the status is on the step, and B6 must read it there.
- No existing test changes. Measured in a throwaway copy with the change made: the full suite gives the same results.

### A2-2. B5-05: the order of derivations is worked out only where there is a choice (BP-3)

**What was found.** The content key is canonical JSON with no non-finite numbers. The contract accepts a non-finite number (NaN, infinity) in a proposition's object or qualifiers, and such a proposition cannot be given a key. The build worked out keys for every stated proposition of a result as soon as any proposition in the result had two producing steps. The reviewer showed that an unrelated conclusion with one derivation, resting on a fact with a non-finite number, then failed to evaluate. That is wider than the limitation reported, and it is a regression against 0.7.0 for that conclusion.

**The rule, added to B5-05.**

> The order of derivations is worked out for a conclusion only if that conclusion has a choice: the conclusion itself, or a derived proposition beneath it, has more than one producing step. Keys are built only for the stated propositions beneath such a conclusion. A conclusion with no choice has exactly one derivation and is evaluated as in 0.7.0, without any key being built, whatever else the result contains.

**Non-finite numbers, where an order is needed.** No new spelling for such numbers is introduced in B5. If a stated proposition beneath a conclusion that has a choice holds a non-finite number in its object or its qualifiers, at any depth, `evaluate_conclusions` raises `ValueError` with exactly this message:

> `Alternative derivations of conclusion <conclusion id> cannot be ordered: proposition <proposition id> holds a number that is not finite.`

When several propositions offend, the one whose id sorts first is named. The check is made deliberately before any key is built; it does not rely on the JSON writer's own error. Nothing else raises: the run itself (`execute_rules`, `orchestrate`) is not affected, and a result evaluates normally when no such proposition lies beneath a conclusion that has a choice.

### A2-3. Acceptance criteria added

| # | Criterion | Check |
|---|---|---|
| A27 | A plain rule and a declaring rule deriving one claim give two conclusions in both orders of their rule ids: with a timeless rule, with a rule that has requirements only, and with an `as_premise` rule over an event. Neither match is a no-op and neither is an alternative derivation of the other. A plain rule's match is still a no-op against a stated proposition (S16c) and against an earlier conclusion of another plain rule | Tests, each in both orders |
| A28 | (a) A conclusion with one derivation evaluates as in 0.7.0 although another conclusion in the same result has alternative derivations and although its own fact holds a non-finite number. (b) A non-finite number beneath a conclusion that has a choice raises `ValueError` with the exact message, naming the conclusion and the first offending proposition. (c) The same number in a result with no alternatives raises nothing, for a plain rule and for a declaring rule | Tests |

A2 (the before-and-after recording for rules that declare nothing) is repeated after the correction. New breakages are added for each rule above.

### A2-4. Limitations added

- A plain rule and a declaring rule that derive the same claim give two conclusions, also where 0.7.0 gave one.
- A conclusion with alternative derivations cannot be evaluated when a stated proposition beneath it holds a non-finite number: `ValueError`, as worded above. A defined spelling for such numbers is left to a later increment.

### What does not change

No rule of B5-01 to B5-03 or B5-06 to B5-10. No number in section 6. No scenario's stated result. The four public names, the version (0.8.0, not yet released) and Amendment 1.

### What approval of this amendment would authorise

Nothing by itself. The correction of the two points in the source, the added tests and breakages, the repeat of the full suite, the recording and the breakage suites each need Manj's word, as before.
