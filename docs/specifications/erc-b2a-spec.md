# B2a — Adapter enrichment: implementation specification — FROZEN (Draft 3 with Manj's decisions, 10 November 2026, 17:50)

**Status: FROZEN. Approved for freeze by Manj, 10 Nov 17:50. Scope: additive-only. Sequence: B2a → B3 → B2b.** Every open point in section 6 is decided. **Tests: not yet authorised. Implementation: not yet authorised.** Nothing is built, no test is written, and the repository is unchanged at `e6e6a9d`. Writing the tests needs Manj's separate explicit go; implementing needs another. Any change to this document after the freeze is a recorded amendment with its reason, not a silent edit.

**Changes in Draft 3 (after the reviewer's probe of Draft 2):** the supersession note now also covers the engineering handover the reviewer holds, and says the principles stay valid and are deferred to B2b (section 1A); the inconsistency between OP-1 and section 3A is removed; the reviewer's recommendations for the seven remaining open points were recorded in section 6 and **approved by Manj (10 Nov 17:50)**; the breakage count is stated as a gate, not a baseline (section 9). No finding, test or value changed.

**Changes in Draft 2:** scope decision and Manj's decisions recorded (section 1A and the last column of section 6); a supersession note for the reviewer's Stage 1 document (section 1A); an interpretation rule for the new information (section 3A); pointers for the reviewer's probe (section 12). No finding, test or value changed.

Measurements in this document were made in throwaway copies of the repository (`git archive e6e6a9d`), never in the clone. The prototype used for them is a sketch to measure compatibility, not the implementation.

## 1. What B2a is, in plain language
Today the adapter tells ERC less about time than Engram knows. Three things are lost on the way:
1. **When a sentence was said.** Engram stores it; the adapter does not pass it on.
2. **How precisely a date is known.** "From 2021" is sent as "from 1 January 2021", as if the day were known.
3. **Whether a start date was actually stated.** When nobody said when something began, the adapter uses the day it was first mentioned and sends it as if it were the start.

B2a passes this information to ERC **alongside** what is sent today. It changes nothing that ERC currently reads: every start, every end, every fact sent, every fact left out and every decision stay exactly as they are. ERC begins to use the new information at B3; the adapter stops sending the old approximations at B2b.

## 1A. Scope decision and decisions recorded (Manj, 10 Nov 17:41)
**B2a stays strictly additive, as agreed on 10 November.** It enriches the adapter's output without changing anything ERC currently reads. B3 then teaches ERC to read the enriched fields. Only after that does B2b change the adapter's existing temporal representations. The measured failures (3 tests if first-said stops being a start, 6 if events move to `occurred`) show the consumer is not ready for those changes.

| Issue | Decision |
|---|---|
| Coarse date precision | Add B1 precision bounds; existing `start` and `end` preserved |
| First-said used as validity start | Current behaviour preserved; `start_basis` exposes the origin. Corrected in B2b |
| First-said used for a period's end | Current end preserved; Engram's `end_kind` exposed as `end_basis`; no precision bounds invented for closed or replaced ends |
| Events sent as intervals | Existing interval and `time_kind` preserved; provenance information only. Moved to `Occurrence` in B2b |
| Evidence observation date | Filled from the sentence date, not the fact's `recorded_at` |
| `Evidence.valid_time` | Left empty |
| Open-state end | Preserved exactly: `as_of + ONE_DAY` |
| Request id | Unchanged; temporal fingerprinting belongs to the later agreed step |
| Existing tests | All 111 adapter tests pass unchanged |

**Supersession.** Two earlier documents contain B2a requirements that conflict with the decision above. For B2a they are superseded by it:

| Document | Statements superseded for B2a |
|---|---|
| The second reviewer's Stage 1 inspection ("Stage 1 — Live source inspection", 10 Nov) | Its section 5 gap inventory ("Event date → `Occurrence`", "First observation: keep separate" as B2a requirements) and its section 7 conclusion (the corrections "a state must not acquire a validity start merely because it was first mentioned" and "an event must have occurrence semantics") |
| The engineering handover held in the reviewer's conversation | Its sections 5 and 8: that `first_said` must not be promoted to a validity start, and that events are mapped to `Occurrence`, the latter section listing both as protected architectural invariants. **As reported by the reviewer. This document has not been independently inspected, and its contents are not verified here.** It is not among the project docs; the project's own handover (claude/erc-adapter-handover.md) already places both corrections in B2b |

**The underlying principles remain valid.** A first mention is not a validity start, and an event is an occurrence, not a state. Only their implementation is deferred: both are corrected in **B2b**, after B3 has taught ERC to read the new fields. In B2a the adapter keeps today's representation and labels it (`start_basis`, `end_basis`, `time_kind`). Anyone implementing B2a follows this specification.

## 2. Stage 1: what the live inspection found
### 2.1 Repository state (checked in a fresh clone)
| Item | Handover value | Found |
|---|---|---|
| Branch, HEAD | `erc-adapter-1`, `e6e6a9d` | `e6e6a9da92f1f71f765d4b1f78252e3c2099143d` ✔ |
| Parent | `050668b` | `050668b9bcf1135ee8a6799564bcb6f65c8bff42` ✔ |
| `050668b` → `e6e6a9d` | two files in `.github/` | exactly `.github/workflows/tests.yml`, `.github/known-test-failures.txt` ✔ |
| Tag `erc-temporal-b1` | `050668b` | ✔ |
| main | `9578d38` | ✔ |
| ERC version | 0.5.0 | ✔ |
| Working tree | clean | ✔ |

### 2.2 Baseline tests run at `e6e6a9d` (Claude's workspace, Python 3.13.18)
| Check | Result |
|---|---|
| Full suite | 1,372 passed, 4 failed (the four in the recorded list), 3 skipped, 1 expected-fail ✔ |
| Adapter tests (`tests/test_erc_overlay.py`) | 111 passed ✔ |
| Adapter + state engine | 169 passed ✔ |

### 2.3 Findings from the source
| # | Finding | Evidence |
|---|---|---|
| F1 | ERC's reasoning path reads only `start` and `end` of a proposition's interval. It reads no qualifier, no evidence date and no evidence metadata | `primitives/comparison.py` `_temporal_relation`; `inference.py:219` (duplicate check compares the whole interval, but against a derived candidate that has none); `evaluation.py` and `primitives/evidence_assessment.py` read only `evidence_kind` and `reliability_score`. The only reader of the new fields is the snapshot fingerprint in `generalization.py` |
| F2 | The adapter fills neither `Evidence.observed_at` nor `Evidence.valid_time` | `erc_overlay/knowledge.py`, the one `Evidence(...)` construction for a sentence |
| F3 | Engram stores a sentence's date as text with a clock time and no time zone, for example `1:00 pm on 5 March, 2024`. Engram's own reader `said_on()` keeps the day and drops the clock time | `engram_knowledge/temporal.py`; observed in the test world |
| F4 | Engram's period keeps the stated start (`start`) and the first-said day (`first_said`) apart. The adapter merges them (`p.start or p.first_said`), as Engram's `get_state_at` does | `state_engine.py` `Period`; `knowledge.py` `_periods` |
| F5 | **New, not in the handover: the same problem exists at the end of a period.** When a period is closed by a statement with no date ("I left Apollo", said 5 March 2024) or replaced by a new value with no date, Engram sets the end from the day the sentence was said, and the adapter sends it as an exact end. Engram's period records how it ended (`end_kind`: open, stated, closed, replaced) but not whether the closing date was stated or only said | Probe: works_at Apollo from 2019 + undated left_job → period end `2024-03-05`, `end_kind closed`, sent as ending 6 March 2024 exactly. lives_in Pune from 2019 + undated lives_in Delhi → Pune ends `2024-03-04`, `end_kind replaced` |
| F6 | UTC is written into the adapter in one place for stated days (`_day`). `as_of` defaults to the current instant, which needs no zone decision | `knowledge.py:56`, `:221` |
| F7 | Two existing tests compare an **event's** whole interval with `TimeInterval(date, None)`. Adding precision bounds to event intervals fails both | Prototype: `test_an_opening_event_keeps_its_own_date_and_outlives_the_state_it_opened`, `test_an_opening_event_appended_to_an_existing_period_keeps_its_own_date_not_the_periods_start[started_job stated 2021]` |
| F8 | With bounds on **state** intervals only, an observation date on sentence evidence, and two new qualifiers: all 111 adapter tests pass unchanged; full suite 1,372 passed and the same four failed | Prototype |
| F9 | What ERC receives and decides is identical before and after, across every request and reasoning run made by the 111 adapter tests (70 requests, 33 reasoning runs): proposition kinds, starts, ends, evidence counts and kinds, link relations, left-out reasons, strategy, status, decisions with reasons, contradictions, uncertainty | Recorded in both copies and compared: identical |
| F10 | The request id is unchanged by the enrichment, and so is ERC's result id | Old and new adapter on one store, two `as_of` values: ids equal. The interim request fingerprint hashes fact fields only (handover's expectation, now verified) |
| F11 | An open state with a coarse start gets a `start_latest` later than its stand-in end. Example: lives_in from "2026", asked at 1 March 2026: start 1 Jan 2026, `start_latest` 31 Dec 2026, end 2 March 2026 (`as_of + 1 day`). The contract accepts it; it is an artefact of the stand-in end, which B2b removes | Prototype probe |
| F12 | One deliberate breakage ("walk expands through an excluded fact") goes stale if the line `eligible.append((x, rule, interval))` is edited: "pattern found 0 times", 27 of 28 | Prototype, `--suite adapter` |
| F13 | Adding separate lines to `explain()` (not altering existing lines) leaves all 111 tests passing | Prototype |

## 3. What B2a adds
All test sentences are said on 5 March 2024. Instants below are written in UTC because that is what the adapter uses today (see OP-2 and E4).

| # | Addition | Today | After B2a | Read by ERC today? |
|---|---|---|---|---|
| E1 | **Observation date on sentence evidence** | `observed_at` empty | `observed_at` = the day the sentence was said, as an instant (OP-1). A sentence with no readable date: empty, never invented. The adapter's own `state:` control records: empty | No |
| E2 | **Precision bounds on a state's interval**, only where Engram holds a *stated* date coarser than a day | "from 2021" → start 1 Jan 2021 | start 1 Jan 2021 **and** `start_latest` 31 Dec 2021 23:59:59.999999. "to March 2021" (the fact's own stated end) → end 1 Apr 2021 **and** `end_earliest` (OP-3). `start` and `end` themselves do not move | No |
| E3 | **Where each boundary came from**, as two qualifiers | not sent | `start_basis`: `stated` or `first_said`. `end_basis`: Engram's own `end_kind`, word for word (`open`, `stated`, `closed`, `replaced`), or `adjusted` when the adapter applied its one-day minimum. Events carry `start_basis` only. A fact with no valid time carries neither | No |
| E4 | **One place for turning a day into an instant** | `_day` with UTC inline | Every instant the adapter makes from a stated day (start, stated end, both bounds, observation date) goes through one function and one named zone constant, still UTC. No second UTC literal. B2b then changes one line | — |
| E5 | **Explanation lines** (OP-8) | one state line per fact | the same lines, untouched and in the same order, plus one separate `time:` line per fact saying what is stated, what is only first-said and how precisely | — |

Bounds are inclusive, as B1 fixed: a year's `start_latest` is its last instant, not the first instant of the next year. The adapter computes every bound with Engram's `span()`; it parses no date itself.

## 3A. The new information must not silently change interpretation
- `observed_at` (the first instant of the said day, per OP-1 (a)) is a **representative date anchor**. It is not a statement that the sentence was spoken at midnight. `observed_latest` travels with it, always, so the day-long uncertainty is preserved for whichever later increment reads it. Neither is set without the other.
- Year and month bounds are added beside the old endpoints. They never move `start` or `end`, and the adapter's own guards keep reading `start` and `end` only, so every guard decision is the same as today (tests G1, G2).
- `start_basis` and `end_basis` describe where a boundary came from. In B2a nothing decides anything from them.

## 4. What B2a does not change
| Item | Stays as it is | Changes at |
|---|---|---|
| `start` and `end` of every interval, including first-said used as a start | yes | B2b |
| Open state closed at `as_of + 1 day` | yes | B2b |
| Events sent as `TimeInterval(date, None)` with `time_kind: event`; no bounds on events (F7) | yes | B2b (`occurred`) |
| Which facts are sent, which are left out, and every left-out reason | yes | — |
| The three guards: unknown time → provisional; ended before `as_of` → left out; starts after `as_of` → left out | yes, active | B6 |
| `STATE_RULES`, the walk, periods built from active, accepted, explicit observations only | yes | — |
| Request id recipe | yes | step 4 |
| ERC (`engram_erc/`): no file touched, version stays 0.5.0, no pin entry needed | yes | B3 |
| Engram (`engram_knowledge/`): no file touched | yes | see OP-5 |
| `Evidence.valid_time` | stays empty (OP-7) | — |
| Evidence provenance other than the date (kind, reliability, metadata) | yes | remaining step 2 |

## 5. Engram boundary
B2a copies nothing new into ERC that Engram owns. ERC receives bounding instants and two short labels; it receives no date text and no precision word, and does no calendar arithmetic. The first-said day reaches ERC only as the evidence observation date, which is what it is. The adapter keeps no state and writes nothing.

## 6. Decisions on the open points
**All twelve points are decided.** OP-4 to OP-7 and OP-11 on 10 Nov 17:41; OP-1, OP-2, OP-3, OP-8, OP-9, OP-10 and OP-12 on 10 Nov 17:50, after the reviewer's probe of Draft 2.

| # | Point | Options | Claude's suggestion | Reviewer / Manj |
|---|---|---|---|---|
| OP-1 | A sentence's day has no clock time the adapter may use (Engram's reader drops it, F3) and no zone. `observed_at` must be one exact instant. Which instant? | (a) first instant of the said day; (b) last instant; (c) leave `observed_at` empty until the zone is declared at B2b and carry nothing | (a), with the last instant of the day also carried in the evidence metadata as `observed_latest`, so B6 can take the cautious reading without another adapter change. (a) matches how the adapter already dates a fact by its said day. The adapter does not parse the stored clock time itself: date reading is Engram's | **Decided (Manj, 10 Nov 17:50): (a).** First instant of the sentence date as `observed_at`; last instant as `observed_latest`. Source: the sentence date, not `recorded_at` |
| OP-2 | A day-precision stated date ("5 March 2021"): exact, or a window of that day? | (a) exact in B2a, as today; (b) window to the day's last instant now | (a). A day's window is exactly what the time-zone decision (TAD-04, B2b) defines; adding it now would write UTC into new values. Year and month bounds are added now | **Decided (Manj, 10 Nov 17:50): (a).** Day-precision dates remain exact in B2a |
| OP-3 | `end_earliest` for a coarse stated end. Engram's `valid_to` "2021" means the last day it held lies in 2021; the end boundary is the first instant it no longer holds | (a) the day after the period's first day (2 Jan 2021 00:00), with `end` 1 Jan 2022 00:00; (b) the period's first instant (1 Jan 2021 00:00) | (a): it follows from "last day held is in 2021" and the half-open rule | **Decided (Manj, 10 Nov 17:50): (a).** For an end stated as 2021: earliest exclusive end 2 January 2021; latest exclusive end 1 January 2022 |
| OP-4 | **TAD-15.** How the adapter states "said on a day, start unknown" | B2a: interval unchanged, qualifier `start_basis: first_said`. B2b: the interval becomes "started no later than the said day" (`start_latest` only, no `start`) | As listed. From B2b the adapter's wording will differ from Engram's `get_state_at`, which treats first-said as the start. Accept and document: Engram's lookup is unchanged; ERC is told only what was said | **Decided for B2a (Manj, 10 Nov):** interval unchanged, `start_basis` added. The B2b form and the TAD-15 wording are settled in the B2b specification |
| OP-5 | The end-side version of the same problem (F5). Engram's period does not record whether a closing date was stated or only said | (a) B2a sends `end_basis` = Engram's `end_kind` and adds no bounds to `closed` or `replaced` ends; the stated-or-said question is settled in the B2b specification. (b) B2a works it out now from the closing fact. (c) a small default-preserving field on Engram's `Period` | (a). (b) repeats Engram's period logic in the adapter; (c) touches Engram and deserves its own decision. Propose recording this as **TAD-17** | **Decided (Manj, 10 Nov): (a).** Current end preserved, `end_basis` = `end_kind`, no bounds on closed or replaced ends. Stated-or-said basis of a closing date: B2b specification (TAD-17) |
| OP-6 | Events: no precision bounds in B2a | (a) none, only `start_basis`; (b) add bounds and revise the two tests in F7 | (a). B2a's rule is that the 111 tests pass unchanged, and events move to `occurred` at B2b, where their bounds belong | **Decided (Manj, 10 Nov): (a).** Interval and `time_kind` preserved; `start_basis` only |
| OP-7 | `Evidence.valid_time` | (a) leave empty; (b) fill from the fact's stated period | (a). One sentence can support several facts with different periods, so a sentence has no single validity period. The period is already on each proposition | **Decided (Manj, 10 Nov): (a).** Left empty |
| OP-8 | `explain()` | (a) add separate `time:` lines, existing lines untouched (F13); (b) leave `explain()` alone until B2b | (a): the explanation should show what is stated and what is only first-said as soon as the adapter knows it | **Decided (Manj, 10 Nov 17:50): (a).** Separate `time:` lines; all existing explanation lines unchanged and in their original order |
| OP-9 | The artefact in F11 (`start_latest` later than the stand-in end on an open, coarse-dated state) | (a) send the honest bound and record the artefact as a fact the B3 specification must handle; (b) drop `start_latest` when it passes the stand-in end | (a). (b) hides knowledge to tidy an approximation that B2b removes. Sequence is B2a → B3 → B2b, so B3 will meet this shape | **Decided (Manj, 10 Nov 17:50): (a).** Send the honest precision bound, even when it extends beyond the temporary open-state end. B3 must tolerate this representation |
| OP-10 | Qualifier names and values in E3 | as listed, or other names | As listed. `end_basis` reuses Engram's words so no second vocabulary appears | **Decided (Manj, 10 Nov 17:50).** `start_basis` and `end_basis`, with the specified values |
| OP-11 | Request id | (a) unchanged in B2a (F10); (b) add the new fields now | (a). The complete fingerprint is remaining step 4. Carried limitation: the id still ignores a fact's dates, as before B2a | **Decided (Manj, 10 Nov): (a).** Unchanged |
| OP-12 | Version | ERC stays 0.5.0; the adapter has no version number of its own | No version change. An adapter version belongs with the step 4 fingerprint | **Decided (Manj, 10 Nov 17:50).** No version change. ERC remains 0.5.0 |

## 7. Tests first: acceptance criteria
New tests are **appended** to `tests/test_erc_overlay.py`; none of the 111 existing tests is edited. Each is written and shown failing before implementation. Values follow the decisions in section 6 and are fixed.

| # | Test (what it asserts, exact values) |
|---|---|
| A1 | Sentence evidence for a fact said on 5 March 2024 has `observed_at == 2024-03-05T00:00:00+00:00` and metadata `observed_latest == "2024-03-05T23:59:59.999999+00:00"` |
| A2 | A sentence with no readable date gives `observed_at is None` and no `observed_latest` |
| A3 | A `state:` control record has `observed_at is None` |
| A4 | One sentence supporting two facts yields one evidence record with one `observed_at` |
| B1 | works_at from "2021", open: `start == 2021-01-01T00:00Z`, `start_latest == 2021-12-31T23:59:59.999999Z`, `start_status` WITHIN; `end == as_of + 1 day`, `end_earliest is None` |
| B2 | works_at from "2021-04": `start_latest == 2021-04-30T23:59:59.999999Z` |
| B3 | works_at from "2021-04-10": `start_latest is None`, `start_status` EXACT |
| B4 | from "2019", stated end "2021-03": `end == 2021-04-01T00:00Z`, `end_earliest == 2021-03-02T00:00Z`, `end_status` WITHIN |
| B5 | stated end "2021": `end == 2022-01-01T00:00Z`, `end_earliest == 2021-01-02T00:00Z` |
| B6 | stated end to the day: `end_earliest is None` |
| C1 | Slot fact with no stated date: `start == 2024-03-05T00:00Z` (unchanged), `start_latest is None`, `start_basis == "first_said"` |
| C2 | Stated start: `start_basis == "stated"` |
| C3 | `end_basis` equals Engram's `end_kind` for an open, a stated, a closed and a replaced period (four cases, each compared with `get_history`) |
| C4 | Closed and replaced ends carry no `end_earliest`, including the two cases of F5 |
| C5 | A fact with no valid time: `valid_time is None`, and neither `start_basis` nor `end_basis` is present |
| C6 | The one-day minimum: `end_basis == "adjusted"`, no bounds. **Not yet reproduced**: no input reaching this adjustment was found during inspection. If none exists the test records that, and the value is not added |
| D1 | Event with stated date "2022": interval `== TimeInterval(2022-01-01T00:00Z, None)` exactly, `start_basis == "stated"`, no `end_basis` |
| D2 | Event dated only by its sentence: interval `== TimeInterval(2024-03-05T00:00Z, None)`, `start_basis == "first_said"` |
| G1 | Guard, coarse date: a fact from "2026" asked at 1 March 2026 is still **sent** (today's behaviour, a known limitation until B2b/B6); a fact from "2027" is still left out as "starts after as_of" |
| G2 | Guard: a fact whose stated end "2021" has passed is still left out as "ended before as_of" at 1 June 2022, and still sent at 1 June 2021 |
| G3 | Two values of a one-value predicate held at once, both with coarse stated starts: ERC still reports one definite contradiction, as today |
| I1 | The request id equals a digest recomputed in the test from the documented recipe (entity, `as_of`, task, fact fields, rule set): the recipe did not change |
| I2 | Every qualifier present before B2a is still present with the same value (`status`, `validation_status`, `source_type`, `fact_type`, `time_kind`, `valid_time`) |
| Z1 | With the adapter's zone constant set to +05:30 for the test, every day-derived instant moves with it (start, stated end, `start_latest`, `end_earliest`, `observed_at`): nothing bypasses the one function |
| X1 | `explain()`: the `time:` line for a first-said fact, a year-stated fact and an event, exact text; and every line that is not a `time:` line equals the line produced today for the same case |

**Also required at build, reported not kept as tests:** the before/after comparison of F9 repeated on the real implementation (must be identical); 111 existing adapter tests pass with the file's existing lines unedited; full suite 1,372 + new tests passed and the same four failed; ERC package tests 556 unchanged; green GitHub Actions run.

## 8. Deliberate breakages (added to `--suite adapter`; each must be caught)
1. `observed_at` not set on sentence evidence.
2. `observed_at` set on the `state:` control record.
3. A date invented for a sentence with no readable date.
4. `start_latest` set to the first instant of the next period (exclusive instead of inclusive).
5. Bounds added to a first-said start.
6. Bounds added to an event's interval.
7. `end_earliest` added to a closed or replaced end.
8. `start_basis` always `stated`.
9. `end_basis` not taken from Engram's `end_kind`.
10. A day-to-instant conversion that bypasses the one function.
11. **B2b arriving early:** a first-said start sent with no `start` (the existing tests already catch 3 such failures; the new suite must name it).
12. An existing qualifier dropped or renamed.

The existing 28 must still be caught. If the implementation edits a line an existing breakage targets (F12), that breakage is re-pointed in the same commit and reported, not dropped.

## 9. Release gate for B2a
| Item | Entry |
|---|---|
| Tests expected to fail before implementation | The new tests in section 7, in full (C6 subject to its note) |
| Tests expected to pass after | The same, plus everything passing today |
| Assertions deliberately revised | **None.** If any existing assertion needs revising, B2a stops and the point returns to review |
| Guards that must remain active | Unknown time → provisional; ended before `as_of`; starts after `as_of`; the state table failing closed; no bridging through a left-out fact; B1's `test_comparison_does_not_read_the_new_fields_in_b1` |
| Behaviour that must not change | Section 4 |
| Deliberate breakages | Every breakage in `--suite adapter` must be caught after implementation: the existing 28 and the new ones in section 8. **28 of 28 today is the baseline, not a tolerance: 27 of 28 after implementation fails the gate.** A breakage whose target line moved is re-pointed in the same commit and reported |
| Limitations carried forward | First-said still sent as a start (B2b); open states still closed at `as_of + 1 day` (B2b); events still intervals (B2b); the step 1A date-precision note stays open (B2b, then B6); UTC still the undeclared zone, now in one place (B2b, TAD-04); day-precision dates carry no window (B2b); closed and replaced ends carry no bounds and their stated-or-said basis is undecided (TAD-17, B2b); the F11 artefact (B3 must handle, B2b removes); request id ignores dates (step 4); `engine_version` still `0.1.8`; nothing in ERC reads the additions until B3 |

## 10. Files
| File | Change |
|---|---|
| `erc_overlay/knowledge.py` | E1–E4 |
| `erc_overlay/reasoner.py` | E5 |
| `tests/test_erc_overlay.py` | new tests appended |
| `kit_tools/check_base2_breakage.py` | new breakages; re-point if needed |

Not touched: `engram_erc/`, `engram_knowledge/`, `engram_erc_bridge.py`, `.github/` (the workflow already runs this test file and must stay green with the same known-failure list), main.

One commit on `erc-adapter-1` on top of `e6e6a9d`. Tag after sign-off: `erc-temporal-b2a` on the sign-off commit.

## 11. Against the reviewer's eight checks
| Check | Where answered |
|---|---|
| Repository accuracy | 2.1–2.3, every statement measured at `e6e6a9d` |
| Engram boundary | 5; OP-5 keeps period logic in Engram |
| Backward compatibility | F8–F10; section 4 |
| Guard preservation | Section 4; tests G1–G3; release gate |
| Version integrity | OP-12; no pinned ERC file touched |
| Tests before implementation | Section 7 |
| Migration safety | Additive only; no stored data; nothing to migrate |
| Objective acceptance criteria | Sections 7–9, exact values |

## 12. For the reviewer's probe
Two places deserve the closest look.
1. **The end-of-period case (F5, OP-5, tests C3 and C4).** Reproduce: works_at Apollo from "2019", then an undated left_job Apollo said on 5 March 2024. Engram's period ends `2024-03-05` with `end_kind closed`; the adapter sends an end of 6 March 2024. Second case: lives_in Pune from "2019", then an undated lives_in Delhi; Pune ends `2024-03-04`, `end_kind replaced`. Check that B2a labels these and adds no bounds, and that nothing else about them moves.
2. **The breakage-script update (F12, section 8).** At `e6e6a9d`, `python kit_tools/check_base2_breakage.py --suite adapter` gives 28 of 28. The breakage "walk expands through an excluded fact" finds its target by the text of the line `eligible.append((x, rule, interval))`; if B2a edits that line the script prints "pattern found 0 times" and reports 27 of 28. The build must either leave the line alone or re-point the breakage in the same commit, and report which.

**The specification is frozen. B2a remains unbuilt: no test and no source change until Manj's explicit go for the tests, and a further go for the implementation.**

---

## Amendments after the freeze
The text above this line is the frozen specification, unchanged: SHA-256 `a8ab8577eda9dbbe8653705c2cb986c3d5ce44fcdd01bee0c0452af76ad47bbd` for the file as it stood before this section was added. Amendments are appended here with their reason and never edited into the frozen text.

### Amendment 1 — test C6, the one-day minimum (approved by Manj, 10 Nov 18:28; recommended by the reviewer)
**Replaces** the note on test C6 in section 7 ("Not yet reproduced … If none exists the test records that, and the value is not added").
**Reason:** an input reaching the adjustment was found while writing the tests.
**Now reads:** a job first said on 5 March 2024 with a stated end of "2021" and no stated start. Engram's period: start none, first said `2024-03-05`, end `2021`, `end_kind stated`. The stated end falls before the first-said start, so the adapter's one-day minimum applies and the end sent is 6 March 2024. Test C6 asserts the interval is exactly today's (5 March 2024 to 6 March 2024, no bound), `start_basis == "first_said"` and `end_basis == "adjusted"`. The value `adjusted` is therefore part of B2a. The design is unchanged.

### Amendment 2 — wording of the `time:` lines and the name of the zone constant (approved by Manj, 10 Nov 18:28; recommended by the reviewer)
**Adds** to E5 / OP-8 and E4, which decided that the lines and the constant exist but not their exact text or name.
**Reason:** a test needs exact text and a name.

| Case | Line |
|---|---|
| Start stated to a year or month | `time: start stated, between 2021-01-01 and 2021-12-31; end open` |
| Start stated to the day | `time: start stated 2021-04-10; end open` |
| Start only first said | `time: start not stated (first said 2024-03-05); end open` |
| End stated to a year or month | `…; end stated, between 2021-03-02 and 2021-04-01` |
| End stated to the day | `…; end stated 2021-03-16` |
| End closed or replaced | `…; end closed 2024-03-06` / `…; end replaced 2024-03-05` |
| One-day minimum | `…; end adjusted 2024-03-06` |
| Event, date stated | `time: event stated 2022-01-01` |
| Event, date only first said | `time: event not stated (first said 2024-03-05)` |
| No valid time | `time: not known` |

An end is shown as the first day the state no longer holds, as the existing "valid … to …" line does. The line sits directly under the state line it describes: indented four spaces under a premise, two under a `fact:` line.

**Zone constant:** `DAY_ZONE` in `erc_overlay/knowledge.py`, default UTC, read by the one day-to-instant function `_day`. Test Z1 sets it to +05:30 only to prove that every day-derived instant goes through that function; it is not a decision to change the zone, which stays with B2b (TAD-04).

### Amendment 3 — a known end with no start (approved by Manj and by the reviewer, 10 Nov 19:14)
**Adds** to E3 (the boundary labels) and to the wording table of amendment 2.
**Reason:** the reviewer's check of the first build (`bd6d977`) found that Engram can hold a stated end with neither a stated start nor a readable first-said day. The adapter sends that as an interval with no start, as it did before B2a. The first build attached a start label with nothing behind it and made `explain()` fail for such a fact. Corrected in `103d2fd`.

**Rule:** `start_basis` is present only when the interval has a start. No new label value is introduced; an absent boundary gets no label. `end_basis` and the end's bound are unaffected.

| Case | Line |
|---|---|
| Known end, no start at all | `time: start not known; end stated, between 2021-01-02 and 2022-01-01` |

"Not known" is the wording amendment 2 already uses for a fact with no valid time. This clarifies the B2a contract; it does not change its architecture.
