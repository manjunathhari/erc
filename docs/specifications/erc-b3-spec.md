# B3 — Temporal comparison and compatibility: Stage 1 audit and implementation specification — DRAFT 4, proposed for freeze (Claude, 10 November 2026, 20:35)

**Status: DRAFT 4, proposed for freeze. Not frozen.** The second reviewer recommends approval of every open point (review of Draft 3, 10 Nov 20:26) and both of its clarifications are resolved here. **What is still needed: Manj's approval of OP-1 to OP-7 and of the freeze.** A reviewer's approval is a recommendation to Manj, not authorisation; Manj's column in section 6 is blank until he fills it. Nothing is built. No test is written, no source file is changed, no commit, tag or branch change has been made, and nothing of B2b is started. The repository is unchanged at `103d2fd`. Seven points in section 6 need Manj's decision before a freeze; one of them (OP-1) decides what B3 is.

**Changes in Draft 4 (after the reviewer's review of Draft 3):** (A) OP-3's implementation boundary is made exact: new section 3.4 states which field marks an event, where the comparison is dispatched and every outcome, measured; the statement that B3 "changes one function" is corrected, since with OP-3 it changes two functions in the one file and adds two private helpers. (B) The open-end measurement is shown to have changed nothing but the end of open states (section 2.5). The reviewer's six requirements for the named limitation are written into section 7 and the release gate (new test R13). The reviewer's recommendations are recorded against every open point. A correction of record: the clock times written on Draft 2 (20:20), Draft 3 (20:55) and on the Stage 1A report (20:50) were estimates and ran ahead of the real clock; by the message times they were issued at about 20:08 and 20:22. Their SHA-256 digests identify them. No rule, value or finding of Draft 3 changed.

**Changes in Draft 3 (after the reviewer's review of Draft 2, and Stage 1A):** the reviewer objected to the temporary tolerance (OP-1 b) and asked for the executable sketch, its raw output and one more measurement. All supplied in `claude/erc-b3-stage1a-op1.md` and its files. Result: **Claude's suggestion on OP-1 changes from (b) to (a), the plain rule with no exception**; the tolerance is withdrawn. Six probes added (S16 to S21) and Engram's own view recorded beside each (section 2.5); findings F18 and F19 added; a new section 3.3 on the stand-in end; tests and breakages that depended on the tolerance rewritten for (a); the reviewer's positions on OP-2 to OP-7 recorded. The comparison rule of section 3.1 is unchanged from Draft 1.

**Changes in Draft 2:** the second reviewer's Stage 1 audit (received 10 Nov 20:03) was checked claim by claim (new section 13); its positions are recorded in the last column of section 6, each marked as given before the reviewer had seen the probe results of section 2.4; one test added from it (R12, fingerprint) and its worked example added to R1 (row 19). No finding, rule or value of Draft 1 changed.

Measurements were made in throwaway copies of the commit (`git archive 103d2fd`), never in the clone. The sketch used for them measures compatibility; it is not the implementation.

## 1. What B3 is, in plain language
Since B2a the adapter tells ERC how precisely each date is known ("from 2021" now arrives as "began some time between 1 January and 31 December 2021"). ERC does not read that yet. Its comparison still treats "from 2021" as "from 1 January 2021 exactly".

That comparison answers one question about two facts: **do their time periods certainly overlap, certainly not overlap, or is it not known?** The answer decides whether two different values of a one-value fact (two homes, two employers) are a *definite* contradiction, a *potential* one, or none.

B3 teaches the comparison to read the precision. Its rule, in one sentence: **two periods certainly overlap only if the part of each that is certain shares some time.** The certain part of a period runs from the latest it could have begun to the earliest it could have ended.

B3 changes one file in ERC, `primitives/comparison.py`: the function that compares two periods, and, if OP-3 is approved, the function that calls it, so that two events are compared as events (section 3.4). It changes nothing in the adapter, nothing in Engram, and nothing about rules, conclusions, `as_of` or evidence (those are B4 to B6).

## 2. Stage 1: what the live inspection found
### 2.1 Repository state (fresh clone, 10 Nov 19:55)
| Item | Handover value | Found |
|---|---|---|
| Branch, HEAD | `erc-adapter-1`, `103d2fd` | `103d2fd7fc256ac1902b3523175eaed87650522b` ✔ |
| Tags | `erc-temporal-b1`, `erc-temporal-b2a`, `erc-adapter-step1a`, `engram-base-1` | all four present ✔ |
| ERC version | 0.5.0 | `engram_erc/VERSION` = 0.5.0 ✔ |
| Working tree | clean | clean before and after the inspection ✔ |

### 2.2 Baseline tests run at `103d2fd` (Claude's workspace, Python 3.13.18)
| Check | Result |
|---|---|
| Full suite | 1,413 passed, 4 failed (the four in the recorded list), 3 skipped, 1 expected-fail ✔ |
| ERC package tests | 556 passed ✔ |
| ERC temporal contract tests | 93 passed ✔ |
| Adapter tests | 152 passed ✔ |
| Breakages, `erc` | 35 of 35 ✔ |
| Breakages, `adapter` | 42 of 42 ✔ |

### 2.3 Findings from the source
| # | Finding | Evidence |
|---|---|---|
| F1 | One function decides the temporal relation: `_temporal_relation` in `engram_erc/primitives/comparison.py` (17 lines). It reads `start` and `end` only. It returns `overlap`, `disjoint` or `unknown` | source |
| F2 | Its only caller is `compare_propositions`, whose only caller is the contradiction finder (`primitives/contradiction.py`). `disjoint` → no contradiction; `overlap` → definite; `unknown` → potential | source |
| F3 | The contradiction finder is called from four places: orchestration (twice: before rules and again after), evaluation, recovery, and the old bridge (`engram_erc_bridge.py`). None reads the relation itself, only definite or potential | `orchestration.py:211, 273`; `evaluation.py:169`; `recovery.py:192`; bridge `:179, :303` |
| F4 | What a definite contradiction does: the run's status is `conflict`, inference is halted where the strategy says so, and a conclusion touching it is `conflicted`. A potential one: status `indeterminate`, an uncertainty item is recorded, and a conclusion touching it is at most `provisional` | `orchestration.py`, `evaluation.py:219, 247` |
| F5 | `comparison.py` and `contradiction.py` are both held to their ERC 0.4.0 bytes by the pin test. Editing `comparison.py` fails `test_erc_1x_files_are_byte_identical_to_0_4_0[primitives/comparison.py]` until its release-pin entry is added | `test_domain_profiles.py:596–636`; confirmed in the sketch |
| F6 | A table of 36 pairs of plain intervals, recorded at `f175f03`, pins today's answers (`RELATION_AT_F175F03`). `test_comparison_does_not_read_the_new_fields_in_b1` is the test marked "deliberately temporary: B3 revises it" | `test_temporal_contracts.py:329–359` |
| F7 | **For any two intervals that use none of the six B1 fields, the rule in section 3 gives exactly today's answer.** Checked on all 484 ordered pairs built from five dates and "missing"; the 36 pinned pairs pass unedited | sketch, exhaustive |
| F8 | **"Certainly not overlapping" does not change at all, for any input.** B1 defined `start` as the earliest possible start and `end` as the latest possible end, and those are exactly what today's disjoint test compares. Checked on 2,000 random enriched pairs: disjoint before if and only if disjoint after | sketch |
| F9 | What can change is only between `overlap` and `unknown`, in both directions: an answer becomes *less* certain where a coarse date was being read as exact, and *more* certain where a new field states something the old reading could not (still going; began no later than; ended no earlier than) | section 3.2 |
| F10 | **Across the whole test suite the comparison is called 307 times; 181 of those calls carry B2a's enriched intervals. With the section 3 rule, 306 answers are identical.** The one that differs is inside the temporary B1 test, on the "still going" pair it was written to pin. Full suite with the sketch: the same four known failures, plus exactly two expected ones (the byte pin of F5 and the temporary test of F6) | sketch + call log |
| F11 | **But inputs no test has do change (the B2a lesson, applied).** Fifteen partial and coarse shapes were probed through the real adapter. Six give a different contradiction result under the plain rule. They fall in two classes: section 2.4 | probe |
| F12 | Today ERC cannot recognise two still-going states as overlapping: `TimeInterval(2019, end_unbounded=True)` against `TimeInterval(2021, end_unbounded=True)` is `unknown` → potential. This is why B2b cannot send honest open ends until B3 is in (the roadmap's point P2) | probe |
| F13 | A proposition carrying `occurred` (an event, B1) has no `valid_time`, so comparison answers `unknown` whatever the dates: two moves dated 2022 and 2023 are a potential contradiction; the same move affirmed and denied at one instant is only potential. The adapter sends no `occurred` yet (B2b) | probe |
| F14 | Events are sent today as `TimeInterval(date, None)`. Two such intervals with the same start compare `unknown`, and that must stay: if a shared start were read as certain overlap, two events said on the same day would become a definite contradiction | pinned pairs `19-|19-`; probe S12 |
| F15 | Adding a file under `engram_erc/primitives/` or `engram_erc/tests/` trips no guard. The `erc` breakage suite runs one test file, named in the script; the workflow's breakage job calls the script, so a new test file needs one line in the script and nothing in `.github/` | `test_domain_profiles.py:524`; `check_base2_breakage.py:128`; `tests.yml` |
| F16 | `test_version_comes_from_version_file` asserts the literal `"0.5.0"` | `test_domain_profiles.py:830` |
| F17 | The duplicate check in `inference.py:219` compares whole intervals including the new fields. Not part of comparison; unchanged by B3; belongs to B5 | source |
| F18 | The adapter's one-day minimum produces a definite conflict Engram does not hold: a job with a stated end of "2021" and no start, first said in 2024, is sent as a one-day period in 2024 and collides with any value first said that day (S11). No B3 option changes it; it goes when first-said stops being a start (B2b) | probe S11 |
| F19 | **Engram's "conflict now" does not come from dates.** `get_current_state` flags two periods of a one-value slot whose `end_kind` is `open`. Its past-date check (`get_state_at`) does use dates, by whether spans touch: a possibility, not a certainty. The adapter turns "open" into an end the day after `as_of`; B1's spelling for open, `end_unbounded`, is not sent until B2b | `state_engine.py:206–256`; section 2.5 |

### 2.4 The six probes that change, and why (F11)
Each scenario is two values of a one-value fact, built in a made-up world and run through adapter and ERC. "Plain rule" is section 3 with nothing added.

**Class A — today's "definite" was an overstatement caused by reading a coarse date as exact.**
| Probe | Facts | Today | Plain rule |
|---|---|---|---|
| S15 | lived in Pune 2019 to "2021" (history); lives in Delhi from 10 Feb 2021; asked 1 Mar 2021 | definite | potential |
| S06, S07, S08 | worked at Apollo 2019 to "2021"; works at Manipal from "2021"; asked 1 Jun 2021 (as history, as two speakers, and as one speaker's ordinary replacement) | definite | potential |

Leaving Apollo some time in 2021 and joining Manipal some time in 2021 is an ordinary job change. Today it is reported as a definite contradiction because "to 2021" is read as "to 31 December" and "from 2021" as "from 1 January". S08 is the plainest case: one speaker, one ordinary change of job, reported as a conflict.

**Class B — the stand-in end (B2a's F11 artefact, decision OP-9).**
| Probe | Facts | Today | Plain rule |
|---|---|---|---|
| S02 | lives in Bengaluru from "2024"; lives in Mysore from "2024" (second speaker); asked 5 Mar 2024 | definite | potential |
| S03 | Bengaluru from "2022"; Mysore from "2024"; asked 5 Mar 2024 | definite | potential |
| S04 | Bengaluru from "March 2024"; Mysore, no date, said 5 Mar 2024; asked 5 Mar 2024 | definite | potential |

Here Engram itself holds both values as current and flags the conflict. The drop comes from the artefact: the adapter closes an open state the day after `as_of`, while the honest start bound runs to the end of the stated year, so the period has no certain part ("began by 31 Dec 2024, ended 6 Mar 2024"). S06 to S08 contain the same artefact on the Manipal side. With an honest open end (B2b) the plain rule gives **definite** again for S02 to S04 and keeps **potential** for class A: checked at ERC level (section 3.2, rows 6 and 7).

**Unchanged under every option:** S01 (G3: two values from years already past: definite), S05 (both first-said: definite), S09 and S10 (end with no start: potential), S11 (one-day minimum: definite), S12 (two moves: potential), S13 (different months of a past year: definite), S14 (coarse end window that still covers the overlap: definite).

### 2.5 Stage 1A: Engram's own view, and where the sequence ends up
Full report and raw output: `claude/erc-b3-stage1a-op1.md`. Twenty-one scenarios (the fifteen above and S16 to S21). The last column is the plain rule with open states sent as still going, measured in a throwaway copy only; it is not B2b.

| # | Scenario | Engram: conflict now | Today | (a) plain | (b) tolerance | (a) + honest open end |
|---|---|---|---|---|---|---|
| S02, S03, S04 | two open homes, one start coarse and reaching the asked-at date | yes | definite | potential | definite | definite |
| S17 | as S02, asked before either sentence was said | yes | definite | potential | definite | definite |
| S19 | a conclusion resting on one side of an S02-type conflict | yes | definite; inference halted | potential; conclusion derived, **provisional** | definite | definite; inference halted |
| S01, S05, S13, S18 | two open values, starts already past or only first said | yes | definite | definite | definite | definite |
| S06, S07, S08 | job change inside one year | **no** | definite | potential | **definite** | potential |
| S15 | coarse end against a day-exact start inside its window | no | definite | potential | potential | potential |
| S16 | genuinely closed end inside the stated start year | **no** | definite | potential | **definite** | potential |
| S21 | genuinely closed, day-exact end against a coarse start | **no** | definite | potential | **definite** | potential |
| S14 | a real past overlap of six months | no (Pune ended) | definite | definite | definite | definite |
| S11 | the one-day minimum (F18) | no | definite | definite | definite | definite |
| S09, S10, S12 | end with no start; two moves | no | potential | potential | potential | potential |
| S20 | control: one value, one conclusion | no | none; accepted | none; accepted | none; accepted | none; accepted |

**Check on the last column (asked by the reviewer).** The measurement sends an open state as `TimeInterval(start, start_latest=…, end_unbounded=True)`. To show it loses nothing, every proposition sent in all 21 scenarios was dumped in full, with and without the measurement, and compared (`erc_b3_open_end_check.py`): 44 propositions; 30 intervals differ, each an open state, each only in `end` (removed) and `end_unbounded` (set); `start`, `start_latest`, every qualifier including `start_basis` and `end_basis`, every evidence date and every left-out reason are identical. The adapter sets no other start field: `start_unbounded` and `start_is_lower_bound` are false on all 44 in both runs.

Read together: the tolerance keeps five definite conflicts Engram does not assert (S06, S07, S08, S16, S21); the plain rule lowers five that Engram does assert (S02, S03, S04, S17, S19), all through the artificial end; the plain rule with an honest open end agrees with Engram's "conflict now" in all nine scenarios where Engram says yes, and is definite elsewhere only for S14 (rightly) and S11 (F18).

## 3. The rule
### 3.1 Definition
For an interval, B1 already gives four instants, some of which may be absent:

| | Earliest possible | Latest possible |
|---|---|---|
| Start | `start` (none if unknown or unbounded) | exact: `start`. Window or "no later than": `start_latest`. Lower bound only, or unknown: none. Unbounded: "always" |
| End | exact: `end`. Window or "no earlier than": `end_earliest`. Upper bound only, or unknown: none. Unbounded: "never" | `end` (none if unknown or unbounded) |

The **certain part** of an interval runs from its latest possible start to its earliest possible end. It exists only when both are known (or unbounded) and the first is before the second.

| Answer | Rule | Changed from today? |
|---|---|---|
| `disjoint` | one interval's earliest possible start is at or after the other's latest possible end | **No. Identical for every input (F8)** |
| `overlap` | not disjoint, both intervals have a certain part, and the two certain parts share time | For plain intervals identical (F7). For enriched ones this is the new reading |
| `unknown` | everything else, including either side having no temporal statement | — |

The comparison stays symmetric (checked on 2,000 pairs) and reads no qualifier, no label and no evidence date. `start_basis` and `end_basis` remain unread by ERC.

### 3.2 What it gives, shape by shape (measured in the sketch)
| # | Left | Right | Today | B3 |
|---|---|---|---|---|
| 1 | still going from 2019 | 2020 to 2022 | unknown | **overlap** |
| 2 | still going from 2019 | still going from 2021 | unknown | **overlap** |
| 3 | still going from 2023 | 2020 to 2022 | disjoint | disjoint |
| 4 | always held | 2020 to 2022 | unknown | **overlap** |
| 5 | always held | time unknown | unknown | unknown |
| 6 | began in 2021, still going | began in 2021, still going | unknown | **overlap** |
| 7 | 2019 to some time in 2021 | from some time in 2021, still going | unknown | unknown |
| 8 | 2019 to some time in 2021 | 2020 to 2023 | overlap | overlap |
| 9 | 2019 to some time in 2021 | 10 Feb 2021 to 2023 | overlap | **unknown** |
| 10 | began no later than 2020, ended 2022 | 2021 to 2023 | unknown | **overlap** |
| 11 | began no later than 2020, ended 2022 | 2019 to 2020 | unknown | unknown |
| 12 | from 2019, ended no earlier than 2021 | 2020 to 2022 | unknown | **overlap** |
| 13 | began 2019 at the earliest, to 2022 | 2020 to 2021 | overlap | **unknown** |
| 14 | 2019 to 2022 at the latest | 2020 to 2021 | overlap | **unknown** |
| 15 | end with no start, to 2021 | 2019 to 2020 | unknown | unknown |
| 16 | end with no start, to 2021 | from 2022 | disjoint | disjoint |
| 17 | B2a's artefact: from "2026", stand-in end 2 Mar 2026 | 2025 to 2027 | overlap | **unknown** (see OP-1) |
| 18 | from 2019, ended at an unknown moment | the same | unknown | unknown (F14) |
| 19 | the reviewer's example: began 2019 to 2020, ended 2022 to 2023 | began 2021 to 2022, ended 2022 to 2024 | overlap | **unknown** (the second may have begun as the first ended) |

Of these shapes the adapter sends today only rows 8, 9, 15, 16, 17 and 18. Rows 1 to 7 and 10 to 14 use fields the adapter does not send until B2b.

### 3.3 The stand-in end: what B3 does and does not do about it
B1's contract has three spellings for an end: a real end (`end`, exact or with `end_earliest`), an end not known (no end), and still going (`end_unbounded`). The adapter today sends an open state with none of these: it sends an exact end the day after `as_of`. That artificial end has no spelling of its own and reaches ERC as an ordinary exact end. Only the adapter's label `end_basis: open` marks it, and the comparison reads no label.

B3 therefore reads the stand-in end as what it is given: an end. This is so for overlap (the interval has no certain part when a coarse start passes it) and for disjointness (a state beginning after it is disjoint, today and after B3). **B3 does not correct the stand-in end and does not claim to.** It is corrected where it is made, in the adapter, at B2b. B3's obligation is the one decided as OP-9: accept the shape, never repair it, never raise an error.

### 3.4 Events: how OP-3 is implemented, exactly (if approved)
| Question | Answer |
|---|---|
| Which field marks an event? | `Proposition.occurred` (B1). A proposition carries `occurred` or `valid_time`, never both (the contract refuses both) |
| Where is the comparison dispatched? | In `compare_propositions`, the one place that today passes `left.valid_time` and `right.valid_time` to `_temporal_relation`. `_temporal_relation` itself stays a comparison of two intervals and never sees an occurrence |
| The dispatch | Both carry `occurred` → compared as two occurrence windows. Exactly one carries `occurred` → `unknown`. Neither → `_temporal_relation`, as now |
| Does "one function changes" still hold? | **No.** Two existing functions change (`_temporal_relation`, `compare_propositions`) and private helpers are added, all in `primitives/comparison.py`. No public name is added; the signature and result type of `compare_propositions` are unchanged |

Both bounds of an occurrence belong to its window (B1). Outcomes, measured in the sketch (`erc_b3_occurrence_sketch.py`, `erc_b3_occurrence_cases.py`); today every row is `unknown` and, on a one-value predicate, a potential contradiction:

| # | Left event | Right event | Relation | Contradiction on a one-value predicate |
|---|---|---|---|---|
| E1 | exact instant in 2022 | exact instant in 2023 | `disjoint` | none |
| E2a | some time in 2022 | some time in 2023 | `disjoint` | none |
| E2b | some time in 2022 | some time in 2022 | `unknown` | potential |
| E2c | an exact instant in June 2022 | some time in 2022 | `unknown` | potential |
| E2d | 2021 to 1 Jan 2022 | 1 Jan 2022 to 2023 (one shared instant) | `unknown` | potential |
| E3a | an exact instant | the same exact instant, another place | `overlap` | definite |
| E3b | an exact instant, affirmed | the same instant, denied | `overlap` | definite (no list needed) |
| E4a | no later than 2021 | no earlier than 2022 | `disjoint` | none |
| E4b | no later than 2022 | no earlier than 2021 | `unknown` | potential |
| E4c | no bounds at all | an exact instant | `unknown` | potential |
| E4d | an event | a state | `unknown` | potential |
| E4e | an event | no temporal statement | `unknown` | potential |

Rule: `disjoint` when one window's latest is before the other's earliest; `overlap` only when both are exact and the same instant; otherwise `unknown`. Symmetric in every row. With this dispatch added, the full suite makes the same 307 comparison calls with the same answers as the plain rule alone: nothing existing sends an event as `occurred`.

**Boundary (the reviewer's condition).** B3 does not touch `primitives/contradiction.py` or the one-value list. The contradiction column above is what the unchanged contradiction layer makes of the relation. Whether event predicates belong on the one-value list at all is B6's decision (TAD-14).

## 4. What B3 does not change
| Item | Stays as it is | Changes at |
|---|---|---|
| Every answer for intervals without the new fields; the 36 pinned pairs | yes | — |
| "Certainly not overlapping", for every input | yes | — |
| `TemporalRelation` (three values), `ComparisonResult`, `Contradiction` and their texts | yes (OP-5) | — |
| `primitives/contradiction.py`, `inference.py`, `evaluation.py`, `orchestration.py`, `recovery.py`, `application.py`, `generalization.py`, `contracts.py` | not touched | B4 to B6 |
| Rules ignoring time; conclusions undated; `as_of` not enforced; evidence dates unread | yes | B4, B5, B6 |
| The duplicate check comparing whole intervals (F17) | yes | B5 |
| The adapter (`erc_overlay/`): no file touched; all 152 adapter tests unedited; 42 adapter breakages | yes | B2b |
| The adapter's three guards and the state table | yes, active | B6 |
| Engram (`engram_knowledge/`), `engram_erc_bridge.py`, `.github/`, main | not touched | — |

## 5. Engram boundary
B3 adds no date knowledge to ERC. The comparison works on the bounding instants B1 defined, does no calendar arithmetic, parses nothing, and reads no Engram label. Whether a boundary was stated or only said stays Engram's and the adapter's knowledge; ERC sees it only as the bounds it is given.

## 6. Open points for Manj's decision
| # | Point | Options | Claude's suggestion | Reviewer / Manj |
|---|---|---|---|---|
| **OP-1** | **What "existing contradiction results stay identical" means, given F10 and F11.** Every existing test gives the same result under the plain rule, but three classes of input the tests do not have would change | **(a) Plain rule.** Class A corrected now. Class B (S02 to S04, which Engram itself flags as conflicts) drops from definite to potential until B2b sends honest open ends. **(b) Plain rule plus one tolerance, marked temporary:** where an interval has an exact end and a start window that reaches or passes that end (the artefact), the comparison reads the start as it does today. Class B unchanged; S06 to S08 unchanged (still definite, as today, until B2b); only S15-type pairs change now. **(c) Gains only:** B3 reads the new fields only where they add certainty (rows 1 to 6, 10, 12) and never lowers an answer; reading windows waits for B2b. Nothing the adapter sends today changes | **(a), revised in Draft 3** (was (b)). Stage 1A measured that the tolerance also fires on genuinely closed ends and keeps five definite conflicts Engram does not assert, and that Engram's certainty in S02 to S04 comes from open-ness, for which B1 already has a spelling. The plain rule with an honest open end agrees with Engram in every comparable probe (section 2.5). The interval before B2b is recorded as a named limitation (release gate), with its cost measured: a conclusion resting on such a conflict is provisional, never accepted, where today the run halts (S19). Whether B2b should put the open end first, as its own step, is decided when B2b is specified. *Draft 2's reasoning for (b), kept for the record:* It keeps every result Engram itself asserts, which is what the agreed sequence asks ("B3 must tolerate this representation"), and still delivers the reading of precision. Its cost, stated plainly: the tolerance is keyed on a shape, so it also applies to a closed or replaced end that falls inside the stated start period, and it leaves the S06 to S08 false conflicts in place until B2b. It must be named in the release gate as temporary, with a test B2b revises, as B1 did. (a) is the cleaner rule but knowingly weakens three Engram-flagged conflicts for one increment. (c) is the safest but moves the real change into B2b, where the adapter changes at the same time and a changed result could not be attributed | **Reviewer (review of Draft 2): approve neither (a) nor (b) yet.** Objects to (b) as a shape-based exception that keeps false certainty (S08). Preferred direction: keep the mathematical rule and represent the upstream certainty correctly. Asked for the sketch, raw output, and whether Engram independently knows both values hold: supplied in Stage 1A (it does, by open-ness). **Reviewer (review of Draft 3, 20:26): approve (a)**, no tolerance, no gains-only exception, no adapter label read by ERC; and approve recording the interval as a named limitation (a-1), with B2b's internal order decided when B2b is specified. Manj: |
| OP-2 | **S15-type pairs change in B3 under (a) and (b)**: a coarse stated end against a start inside that end's window goes from definite to potential. This is reachable from today's adapter and no existing test has it | Accept as the intended correction, with a named test; or choose OP-1 (c) | Accept. It is the smallest honest case of the fault B3 exists to fix. Under (a) it is one of the named adapter-reachable changes (S06 to S08, S15, S16, S21 corrected; S02 to S04, S17, S19 lowered until B2b), and each class should be approved by name, not arrive unnoticed | **Reviewer: approve.** Manj: |
| OP-3 | **Events carried as `occurred` (F13).** B2b will move events there; comparison must have an answer ready first | (a) B3 compares two occurrences as windows: `disjoint` when the windows cannot meet, `overlap` only when both are the same exact instant, otherwise `unknown`; an event against a state is `unknown`. (b) Leave `occurred` unread until B2b | (a). No effect today (the adapter sends none; measured). Effect once B2b sends them: two moves at different known times stop being a potential contradiction; the same event affirmed and denied at one instant becomes definite. This settles part of TAD-14 (events and contradiction); whether event predicates should be on the one-value list at all stays with B6 | **Reviewer: accept (a)**, and this must not expand the one-value policy: whether two events contradict stays a B6 decision. Noted consequence: the contradiction layer and the one-value list are untouched, so once B2b sends occurrences, two events on a listed predicate at different known times give no contradiction and at one exact instant a definite one. Nothing reaches this today. **Reviewer (review of Draft 3): approve (a) with that boundary**, and asked for the implementation boundary to be made exact: section 3.4. Manj: |
| OP-4 | **Version** | (a) ERC 0.6.0, revising the literal in `test_version_comes_from_version_file` (F16) with the reason recorded; (b) stay 0.5.0 | (a). A public primitive's answers change for enriched inputs; a result made by 0.5.0 and one made by 0.6.0 should be tellable apart. `engine_version` reporting `0.1.8` stays a carried limitation | **Reviewer: accept (a)**, with the pin entry, the 0.4.0 digest preserved, the version test updated, and `engine_version` recorded as a separate limitation. **Approve.** Manj: |
| OP-5 | **Result types.** Should the comparison say *why* an answer is unknown (no statement, unknown bound, windows that may or may not meet)? | (a) No new field or enum value in B3; (b) add a reason now | (a). Nothing reads it until the explanation work in B5 and B6, and an unread field is where B2a's defect came from | **Reviewer: approve (a).** Manj: |
| OP-6 | **Helper questions B4 to B6 will need** (does a state certainly hold at an instant; the certain shared period of two premises) | (a) Not in B3; each arrives with the increment that calls it; (b) add them now as unused functions | (a). Their meaning depends on decisions that belong to B4 (TAD-05 to 07, TAD-11) and B6 (`as_of`, TAD-04) | **Reviewer: approve (a).** Manj: |
| OP-7 | **Where the code lives** | (a) inside `primitives/comparison.py` (one pinned file gets a release entry); (b) a new `primitives/temporal.py` plus the call in `comparison.py` | (a). One function grows; one pin entry; nothing new to export | **Reviewer: approve (a)**, with private helpers inside the file and no new public name. Manj: |

## 7. Tests first: acceptance criteria
New file `engram_erc/tests/test_temporal_comparison.py` for ERC; a small block appended to `tests/test_erc_overlay.py` for the end-to-end cases. No existing adapter test is edited. Each test is written and shown failing before implementation. Because a test that only asserts "unchanged" passes before any implementation, each such assertion sits in a test that also asserts a new answer beside it. Exact values follow sections 3.2, 2.4 and 2.5 and are written for OP-1 (a); they are fixed once section 6 is decided. Rows marked † depend on OP-3.

| # | Test (what it asserts) |
|---|---|
| R1 | Every row of section 3.2 (1 to 19), both ways round, exact answer |
| R2 | Still going: rows 1, 2 and 6 give `overlap`; through `find_contradictions` on a one-value predicate they are one **definite** contradiction (today potential) |
| R3 | Ended at an unknown moment is not still going: `TimeInterval(2019)` against `2020 to 2022` stays `unknown`, beside row 1's `overlap` |
| R4 | A start window lowers certainty only when the certain parts stop meeting: rows 8 and 9 side by side |
| R5 | One-sided bounds: rows 10 to 14 |
| R6 | End with no start (the B2a shape): rows 15 and 16; with `end_earliest` present and absent the answers are the same |
| R7 | Disjoint is untouched: for each enriched shape in R1, the answer is `disjoint` exactly when the plain `start`/`end` pair is |
| R8 | Symmetry: every pair in R1 gives the same answer both ways round |
| R9 | A window whose certain part is empty (row 17's shape, and "from 2021 to March 2021") never yields `overlap`, and the interval is accepted unchanged and raises nothing (OP-9) |
| R10 | The 36 pinned pairs: `RELATION_AT_F175F03` passes unedited (existing test), and the same 36 with `start_latest`/`end_earliest` set to values that do not move the certain part give the same 36 answers |
| R11 | Shared start, unknown ends (F14): `unknown`, beside R2's `overlap` for the same starts when still going |
| R13 | The honest spelling, at ERC level (the reviewer's requirement 4): the two intervals of S02 with `end_unbounded` in place of the stand-in end are `overlap` and one **definite** contradiction; the two of S16 (a genuinely closed end against an open first-said value sent as still going) stay `unknown` and potential. Not revised at B2b |
| R12 | Fingerprint (from the reviewer's audit): the snapshot fingerprint of a fixed request with enriched intervals equals the value recorded at `103d2fd`, asserted beside a comparison answer that B3 changes for the same request. Comparison changed; identity did not |
| E1 † | Section 3.4 rows E1, E2a, E4a: `disjoint`; no contradiction on a one-value predicate |
| E2 † | Rows E2b, E2c, E2d, E4b, E4c: `unknown` → potential. E2d pins that windows sharing one instant are not disjoint (bounds are inclusive) |
| E3 † | Rows E3a, E3b: `overlap` → definite |
| E4 † | Rows E4d, E4e, both ways round: `unknown`; and a state against a state still reaches `_temporal_relation` (one row of R1 repeated through `compare_propositions`) |
| E5 † | The dispatch reads `occurred` only: an event sent the old way, as `TimeInterval(date, None)`, is compared as an interval exactly as today (F14) |
| X1 | End to end through the adapter, S15: one **potential** contradiction, status `indeterminate` (today definite) |
| X2 | End to end, S02, S03, S04, S17: one **potential** contradiction (today definite). **Interval behaviour, marked for revision at B2b**, where the expected value becomes definite. Beside it, at ERC level: the same two intervals with `end_unbounded` in place of the stand-in end are one definite contradiction |
| X3 | End to end, S06, S07, S08, S16, S21: one **potential** contradiction (today definite). Not revised at B2b |
| X5 | End to end, S19: the conclusion is derived and its decision is `provisional` with reason `POTENTIAL_CONTRADICTION_REQUIRES_SCOPE_REVIEW`; it is never `accepted`. Beside it S20, the control: `accepted`. Marked for revision at B2b with X2 |
| X4 | End to end, unchanged beside X1: S01, S05, S11, S13, S14 definite; S09, S10, S12 potential |
| V1 | Version and pins: `comparison.py` listed in `ERC_1X_RELEASE_PINS` with release and reason; the 0.4.0 table's own digest unchanged; `contradiction.py` still byte-identical to 0.4.0 |

**Also required at build, reported and not kept as tests:** the call log of F10 repeated on the real implementation (307 calls; every difference listed and explained, expected: only those inside revised tests); the before-and-after recording of every adapter request and reasoning run across the 152 adapter tests (must be identical); 152 adapter tests pass with the file's existing lines unedited; ERC package tests 556 plus the new ones; a green GitHub Actions run with breakages.

## 8. Deliberate breakages (added to `--suite erc`; each must be caught)
1. Start window ignored: `start` read as exact (today's reading).
2. End window ignored: `end` read as exact.
3. Still going read as an unknown end.
4. An unknown end read as still going.
5. Lower-bound start read as exact.
6. Upper-bound end read as exact.
7. "No later than" start ignored.
8. "No earlier than" end ignored.
9. The disjoint test moved onto the window's inner bounds (it must stay on `start` and `end`).
10. An empty certain part accepted as certain (`<` weakened to `<=`).
11. A shared start with unknown ends read as overlap (F14).
12. A tolerance arriving unapproved: a start window that reaches or passes the interval's end read as an exact start.
13. † Occurrences compared as if they were periods; an event against a state answered other than `unknown`; the occurrence disjoint test made exclusive (`<` to `<=`); two different exact instants read as `overlap`.
14. A qualifier (`start_basis` or `end_basis`) read by the comparison.
15. A new public name exported from `engram_erc` or `engram_erc.primitives`.

The existing 35 `erc` and 42 `adapter` breakages must all still be caught; a moved target is re-pointed in the same commit and reported, never dropped. The `erc` suite's test list gains the new test file (one line in the script).

## 9. Release gate for B3
| Item | Entry |
|---|---|
| Tests expected to fail before implementation | Every new test in section 7 |
| Tests expected to pass after | The same, plus everything passing today |
| Assertions deliberately revised | (1) `test_comparison_does_not_read_the_new_fields_in_b1`: replaced, as B1 recorded it would be, with the reason "B3 teaches comparison the contract". (2) `ERC_1X_RELEASE_PINS` and `ERC_1X_FILES_CHANGED_SINCE_0_4_0`: `primitives/comparison.py` added with release and reason. (3) If OP-4 (a): the version literal. **Nothing else.** If any other existing assertion needs revising, B3 stops and the point returns to review |
| Guards that must remain active | Unknown time → provisional; ended before `as_of`; starts after `as_of`; the state table failing closed; no bridging through a left-out fact; the 36 pinned pairs |
| Behaviour that must not change | Section 4 |
| Deliberate breakages | 35 + new of `erc`, 42 of 42 `adapter`. One short of either total fails the gate |
| Limitations carried forward | **Named for B3 under OP-1 (a):** two open values of a one-value fact, one with a coarse stated start whose period reaches the asked-at date, are reported as a potential contradiction, and a conclusion resting on one of them as provisional, until the adapter sends open ends honestly (B2b). Tests X2 and X5 pin this and are the only B3 tests marked for revision at B2b, where their expected value becomes definite; R13 already proves the honest spelling gives definite. **B2b must not change** the corrections S06, S07, S08, S15, S16 and S21, which stay potential (X1, X3, R13). The stand-in end is still read as an end, for overlap and disjointness (section 3.3). Carried separately, and not part of the open-end limitation: the one-day minimum still yields a definite conflict Engram does not hold (F18, S11; B2b, with first-said). Rules still ignore time (B4); conclusions undated (B5); `as_of` not enforced, evidence dates unread, potential contradiction only when the one-value list is passed twice (B6); the duplicate check (B5); event predicates on the one-value list (B6); first-said still a start, stand-in ends, events as intervals, UTC undeclared (B2b); TAD-17; request id ignores dates (step 4); `engine_version` `0.1.8` |

## 10. Files
| File | Change |
|---|---|
| `engram_erc/primitives/comparison.py` | `_temporal_relation`: the rule of section 3.1. If OP-3 is approved: the dispatch in `compare_propositions` and the occurrence comparison (section 3.4). Private helpers only; no new public name |
| `engram_erc/VERSION` | 0.6.0, if OP-4 (a) |
| `engram_erc/tests/test_temporal_comparison.py` | new |
| `engram_erc/tests/test_temporal_contracts.py` | the one temporary test revised |
| `engram_erc/tests/test_domain_profiles.py` | pin entry; version literal if OP-4 (a) |
| `tests/test_erc_overlay.py` | end-to-end tests appended; no existing line edited |
| `kit_tools/check_base2_breakage.py` | new `erc` breakages; the suite's test list |

Not touched: `erc_overlay/`, `engram_knowledge/`, every other file in `engram_erc/`, `engram_erc_bridge.py`, `.github/`, main. One commit on `erc-adapter-1` on top of `103d2fd`. Tag after sign-off: `erc-temporal-b3`.

## 11. Against the reviewer's eight checks
| Check | Where answered |
|---|---|
| Repository accuracy | 2.1 to 2.4, every statement measured at `103d2fd` |
| Engram boundary | 5 |
| Backward compatibility | F7, F8, F10; section 4; OP-1 for the inputs no test has |
| Guard preservation | Section 4; adapter untouched; release gate |
| Version integrity | F5, F16; OP-4; V1 |
| Tests before implementation | Section 7 |
| Migration safety | No stored data; nothing to migrate. Result ids of existing runs are unaffected (the fingerprint is not touched) |
| Objective acceptance criteria | Sections 3.2, 7, 8, 9: exact answers |

## 12. For the reviewer's probe
1. **OP-1 is the decision the increment turns on.** With `erc_b3_sketch.py` and `erc_b3_probe_shapes_v2.py`, reproduce S02, S16 and S19 in the modes `today`, `plain` and `tolerance`. Check three claims: Engram's `get_current_state` flags S02 and not S16; the tolerance keeps S16 definite although its end is genuinely closed; under the plain rule S19's conclusion is provisional and never accepted.
2. **F8.** The claim that "certainly not overlapping" cannot change for any input rests on B1's definition of `start` and `end` as the outer bounds. A counter-example would be an interval the contract accepts whose `start` is not its earliest possible start.
3. **F14.** Two intervals with the same exact start and unknown ends both held at that first instant, strictly speaking. The specification keeps `unknown`, because events are still sent in that shape. Check that this is stated as a choice and tested (R11).

## 13. Check of the second reviewer's Stage 1 audit (received 10 Nov 20:03)
Each claim was checked in the clone or the sketch. The reviewer states that no test was run; the figures in this document are measured.

**Where the audit and this specification agree (confirmed by probe).**
| Reviewer's claim | Check |
|---|---|
| Branch head `103d2fd`, parent `e6e6a9d`, four files, main at `9578d38`, branch 11 commits ahead of main and none behind | ✔ all confirmed. The commit carries a signature (seen in the commit object); GitHub's "Verified" label itself was not checked, since the API is not open to this session |
| Tag `erc-temporal-b2a` is a lightweight tag on the sign-off commit | ✔ |
| The comparison reads only `start` and `end`; contradiction certainty follows it; fix the comparison, not the contradiction layer | ✔ F1, F2; `contradiction.py` stays untouched |
| The rule: certain overlap when the guaranteed parts meet; disjoint when the possible extents cannot; otherwise unknown; three relation values kept | ✔ the same rule as section 3, reached independently |
| The worked example (starts 2019 to 2020 and 2021 to 2022) is `overlap` today and should not be | ✔ measured: `overlap` → `unknown` (row 19). If the second state certainly began by June 2021 it stays `overlap` |
| Unknown is not unbounded | ✔ rows 1 to 5, test R3 |
| Occurrence comparison in B3, adapter's events untouched until B2b | ✔ the same as OP-3 (a) |
| Fingerprint already covers the new fields; do not redesign it; inference without time is B5 | ✔ F17; test R12 added |
| `temporal_patterns.py`, `temporal_external.py`, `compat.py` stay out | ✔ all three exist and none calls the comparison |

**Where the audit is different from, or says less than, what the probes show.**
| # | Reviewer's statement | What was found |
|---|---|---|
| C1 | For the stand-in end shape: return unknown; "backward-compatible contradiction detection" is listed as an expected result | Both cannot hold. Returning unknown lowers three results that Engram itself flags as conflicts (S02 to S04) from definite to potential, and lowers S06 to S08 and S15 as well. No existing test shows it (F10), which is why an audit by reading would not see it. This is OP-1, and it is the decision the increment turns on |
| C2 | "Never infer that the state actually ended on 2 March" | B3 cannot promise this. The disjoint test reads the stand-in end as an end today and still will: the same shape against a state beginning 2 March 2026, or 1 June 2026, is `disjoint` before and after. The adapter's guards keep such a pair from being sent, so it is not reachable today, but the stand-in end stops being read as an end only when B2b stops sending it |
| C3 | "I could not identify a separate ERC-specific deliberate-breakage script" | It is the same script with another suite: `python kit_tools/check_base2_breakage.py --suite erc` (the list `ERC`, lines 89 to 125; suite table at line 128). Run today: 35 of 35. B3 adds to that list (section 8) |
| C4 | "One documentation discrepancy": `claude/erc-b2a-spec.md` returns 404 on the branch | Correct as an observation, and expected: the specifications are project documents, not repository files (the repository has no `claude/` directory). The handover already records that the reviewer cannot see them, which is why each is sent as a file with its SHA-256. Whether the frozen specifications should also be committed to the repository is a fair question for Manj; it is outside B3 |
| C5 | Scope and baseline given as ERC 0.5.0, with no mention of the byte pins or the version | Editing `comparison.py` fails the 0.4.0 byte-pin test until its release entry is added in the same commit (F5), and one test holds the literal `0.5.0` (F16). Both are in the release gate (OP-4, V1) |
| C6 | `contradiction.py`: "adjust only if required" | Not required. It stays byte-identical to 0.4.0 (V1) |
| C7 | Fifteen proposed verification cases | All are covered by section 7. Missing from the audit's list and present here: the 36 pinned pairs, the shared-start case that keeps two same-day events from becoming a definite contradiction (F14, R11), disjoint-unchanged for every input (R7), symmetry (R8), and the end-to-end adapter cases (X1 to X4) |

**Nothing in the audit contradicts a finding of this specification.** The one real difference is C1.

## 14. The reviewer's review of Draft 2 (received 10 Nov 20:11)
Answered in full in `claude/erc-b3-stage1a-op1.md`. In short:

| Reviewer's point | Outcome |
|---|---|
| The sketch and its raw output were not among the files sent | Correct. Supplied: one sketch file with all three options, the exact tolerance predicate, 21 scenarios in each mode, and every comparison call of the full suite in each mode |
| Option (b) is an exception keyed on a shape and keeps false certainty | Confirmed by measurement (S06, S07, S08, S16, S21). Withdrawn |
| Is Engram's certainty in S02 to S04 independent of the old date reading? | Yes: it comes from both periods being open (F19) |
| Distinguish a real end, an unknown end and an artificial end | The first two and "still going" have spellings in B1's contract; the artificial end has none and cannot be seen by ERC. Section 3.3 states what B3 does about it: nothing beyond accepting it |
| Disjointness still reads the stand-in end | Agreed; stated in section 3.3 and in the release gate |
| OP-2 to OP-7 | Recorded in section 6 |
| Commit frozen specifications under `docs/specifications/` in a documentation-only commit | For Manj; outside B3 |

## 15. The reviewer's review of Draft 3 (received 10 Nov 20:26)
The reviewer verified the three digests, inspected the package, and recommends approval of OP-1 (a), the named limitation (a-1), and OP-2 to OP-7. The reviewer states that the measurements were found internally consistent and credible but were not independently re-run against the repository.

| Reviewer's point | Outcome in Draft 4 |
|---|---|
| A. OP-3 needs an exact implementation boundary; "one function changes" may not hold | Correct: it does not hold. Section 3.4, with measured outcomes; section 1 and section 10 corrected; tests E1 to E5 and breakage 13 made exact |
| B. Show the open-end measurement discards no start information | Shown: 44 propositions compared field by field; only the end of 30 open states differs (section 2.5) |
| Six requirements for the limitation: name it exactly; keep X2 and X5; mark them for B2b; an ERC-level test of the honest spelling; carry F18 separately; B2b must not undo the corrections | All six are in section 7 (X2, X3, X5, R13) and the release gate |
| C4: commit the frozen specifications under `docs/specifications/` in a documentation-only commit, after B3 is signed off, never touching the B2a commit or tag | For Manj. Outside B3; if approved it is its own authorised commit |
| Next: freeze, then separate authorisations for tests and for implementation | As the agreed method |

**Draft 4 is proposed for freeze. B3 remains unbuilt: no test and no source change until Manj approves the open points and the freeze, then gives an explicit go for the tests, and a further go for the implementation.**

---

## Freeze record and amendments
The text above this line is the frozen B3 specification, unchanged: it is Draft 4 byte for byte, SHA-256 `a94eb532e5d8bcfb4fb220bdac72a6875bd1515897656ddb56470aa2339e4c86` for the file as it stood before this section was added. Its own status lines ("proposed for freeze", the blank Manj column) are left as they were so that the digest both Manj and the reviewer hold stays valid; this record supersedes them. Amendments are appended here with date, reason and approval, and never edited into the frozen text.

### Freeze (10 Nov 2026, 20:40)
| Item | Record |
|---|---|
| Frozen text | Draft 4, SHA-256 `a94eb532e5d8bcfb4fb220bdac72a6875bd1515897656ddb56470aa2339e4c86` |
| Reviewer | Recommended acceptance of Draft 4 as the frozen specification and approval of every point (review received 10 Nov 20:38), having verified both digests and the Stage 1B package; states the measurements were checked for consistency and not independently re-run |
| **Manj (10 Nov 20:40)** | **Approved:** OP-1 (a), the plain rule with no exception; the interval limitation recorded as (a-1), "the limitation will be corrected in B2b"; OP-2; OP-3 (a) with the boundary of section 3.4; OP-4 (a), ERC 0.6.0; OP-5 (a); OP-6 (a); OP-7 (a); the freeze of Draft 4 |
| Outside B3, approved by Manj the same day | After B3 is implemented, tested and signed off: a separate documentation-only commit placing the frozen specifications under `docs/specifications/` (`erc-b2a-spec.md`, `erc-b3-spec.md`). The B2a commit and tag are not touched; it is never mixed with the B3 implementation commit; it needs its own go when the time comes |
| Tests | **Authorised by Manj, 10 Nov 20:40** ("proceed with test and freeze"). Tests only, written first and shown failing against the unchanged `103d2fd` |
| Implementation, commit, push, tag, B2b | **Not authorised.** Each needs its own explicit word from Manj |

### Amendment 1 (10 Nov 2026, 23:12): B3 tests revised at B2b
| Item | Record |
|---|---|
| What the frozen text says | Section 9: tests X2 and X5 "are the only B3 tests marked for revision at B2b" |
| What is amended | Two rows of test X4 (`test_b3_results_that_do_not_change`) are also revised at B2b: **S11** (the one-day minimum) and **S12** (two moves). X2 and X5 are revised as the frozen text foresaw. X1, X3 and R13 are not revised; S06, S07, S08, S15, S16 and S21 stay potential |
| Reason | Measured during B2b's Stage 1 at `8eb4853`. S11: once the adapter no longer manufactures a one-day period (F18), the job that ended in 2021 is left out as ended and no contradiction remains, which is what Engram holds; today the result is a definite contradiction. S12: once events are sent as occurrences, two moves at different known times cannot meet and give no contradiction; today a potential one. Both are consequences of correcting what the adapter sends. **B3's comparison rule and `primitives/comparison.py` are not changed** |
| Where specified | B2b specification, frozen 10 Nov 2026, SHA-256 `621314c573ecbffcd82cf5295e3a0b98597fe750164c220c1d4d17356f5589c7`: sections 10 and 12.2 (rows 21 to 27), decision OP-9 |
| Approval | Manj, 10 Nov 23:07 (OP-1 to OP-12 accepted as his decisions) and 23:12 (freeze of the B2b specification). Recommended by the reviewer in every review of B2b |
| Effect on this file | The frozen B3 text above is unchanged (`a94eb532e5d8bcfb4fb220bdac72a6875bd1515897656ddb56470aa2339e4c86`). With the freeze record this file was `9684762364696af40f03d5aaaa45b9c474eabe7a3e92741b64ea8e8a40058538`, which is still the copy in the repository at `docs/specifications/erc-b3-spec.md`; that copy is brought up to date by the documentation-only commit after B2b is signed off |
