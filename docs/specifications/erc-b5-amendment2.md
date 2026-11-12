# ERC B5 — Amendment 2 to the frozen specification (draft for review, revision 1)

12 November 2026. Drafted after the reviewer's findings on the build report, relayed by Manj at 17:39 (BP-2: decision required; BP-3: correction required; proposed step 1: "Agree and freeze Amendment 2 covering BP-2 and BP-3").

**Status: draft for review. It takes effect when Manj approves it.** It is then appended beneath the freeze record after Amendment 1. Until then no source file and no test is changed.

**The frozen text is not edited.** Frozen specification: Draft 1.4 revision 2, SHA-256 `ec3d333a2621754d6a6ca1dc8aa63662207a906572349d4f08019ea24d993581`. Amendment 1 revision 2 (`bcbcf020b818f993dc5cab990a9534ba301bd8617301f6c550fd7e10a81cb38d`) stands unchanged.

**Scope.** One row of the table in B5-04 (when a conclusion is already present), one paragraph of B5-05 (when the order of derivations is worked out), two new acceptance criteria and two limitations. **Not reopened:** the shared-period formula, the three statuses, the content key and its canonical form, the order of derivations, the limit of 64, the tie-group rule, the F85 exception, every decided point OP-1 to OP-9 and DP-1 to DP-8, and Amendment 1.

## A2-1. B5-04: a rule that declares nothing and a rule that declares never share a conclusion (BP-2)

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

## A2-2. B5-05: the order of derivations is worked out only where there is a choice (BP-3)

**What was found.** The content key is canonical JSON with no non-finite numbers. The contract accepts a non-finite number (NaN, infinity) in a proposition's object or qualifiers, and such a proposition cannot be given a key. The build worked out keys for every stated proposition of a result as soon as any proposition in the result had two producing steps. The reviewer showed that an unrelated conclusion with one derivation, resting on a fact with a non-finite number, then failed to evaluate. That is wider than the limitation reported, and it is a regression against 0.7.0 for that conclusion.

**The rule, added to B5-05.**

> The order of derivations is worked out for a conclusion only if that conclusion has a choice: the conclusion itself, or a derived proposition beneath it, has more than one producing step. Keys are built only for the stated propositions beneath such a conclusion. A conclusion with no choice has exactly one derivation and is evaluated as in 0.7.0, without any key being built, whatever else the result contains.

**Non-finite numbers, where an order is needed.** No new spelling for such numbers is introduced in B5. If a stated proposition beneath a conclusion that has a choice holds a non-finite number in its object or its qualifiers, at any depth, `evaluate_conclusions` raises `ValueError` with exactly this message:

> `Alternative derivations of conclusion <conclusion id> cannot be ordered: proposition <proposition id> holds a number that is not finite.`

When several propositions offend, the one whose id sorts first is named. The check is made deliberately before any key is built; it does not rely on the JSON writer's own error. Nothing else raises: the run itself (`execute_rules`, `orchestrate`) is not affected, and a result evaluates normally when no such proposition lies beneath a conclusion that has a choice.

## A2-3. Acceptance criteria added

| # | Criterion | Check |
|---|---|---|
| A27 | A plain rule and a declaring rule deriving one claim give two conclusions in both orders of their rule ids: with a timeless rule, with a rule that has requirements only, and with an `as_premise` rule over an event. Neither match is a no-op and neither is an alternative derivation of the other. A plain rule's match is still a no-op against a stated proposition (S16c) and against an earlier conclusion of another plain rule | Tests, each in both orders |
| A28 | (a) A conclusion with one derivation evaluates as in 0.7.0 although another conclusion in the same result has alternative derivations and although its own fact holds a non-finite number. (b) A non-finite number beneath a conclusion that has a choice raises `ValueError` with the exact message, naming the conclusion and the first offending proposition. (c) The same number in a result with no alternatives raises nothing, for a plain rule and for a declaring rule | Tests |

A2 (the before-and-after recording for rules that declare nothing) is repeated after the correction. New breakages are added for each rule above.

## A2-4. Limitations added

- A plain rule and a declaring rule that derive the same claim give two conclusions, also where 0.7.0 gave one.
- A conclusion with alternative derivations cannot be evaluated when a stated proposition beneath it holds a non-finite number: `ValueError`, as worded above. A defined spelling for such numbers is left to a later increment.

## What does not change

No rule of B5-01 to B5-03 or B5-06 to B5-10. No number in section 6. No scenario's stated result. The four public names, the version (0.8.0, not yet released) and Amendment 1.

## What approval of this amendment would authorise

Nothing by itself. The correction of the two points in the source, the added tests and breakages, the repeat of the full suite, the recording and the breakage suites each need Manj's word, as before.
