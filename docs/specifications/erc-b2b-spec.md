# B2b — Open-end adapter transition: Stage 1 audit and specification, Draft 5, freeze candidate (Claude, 10 November 2026, 23:10)

**Status: Draft 5, freeze candidate, not frozen. OP-1 to OP-12 are accepted by Manj as his decisions (10 Nov 23:07). Inspection and measurement only.** No test written, no source file changed, no commit, push or tag. The clone is clean at `8eb4853` (`8eb485363aea0d7b149a4d6ce54e08bd70ab2b4b`). Every measurement was made in a throwaway copy of that commit outside the clone. Nothing here is authorised beyond being read: the freeze, the tests and the implementation each need Manj's own word. A reviewer's recommendation is recorded as a recommendation.

**Draft history.** Draft 1 (sent before 22:16, SHA-256 `100100893e6d5ca2e169ddaceb6eb01b18ea7e0f8e0b24d570c4e90ab7c371af`) was reviewed by the second reviewer (received 22:16 the same evening): proceed to Draft 2, do not freeze. Draft 2 (sent before 22:43, SHA-256 `edc6661d25fd79a7e41cc422965d5c41f558690f18ef1a3dd4f4be3fb0cbf852`) answered the ten items of that review and was reviewed in turn (received 22:43): design accepted, all twelve open points recommended for acceptance, three specification issues and one measurement to settle before the freeze. Draft 3 (sent before 22:55, SHA-256 `561a0f12176ff53bb6c588a9e2d4a3800da1a3dd1edb2041c29376d8068fed67`) made those amendments and was reviewed (received 22:55): all twelve open points accepted, two clarifications and one measurement qualification before the freeze. Draft 4 (22:58, SHA-256 `9e06ff5cc7a3b674da55babb2ae4517203e1a45c83f6fd4fcbd2c3a427dd9b16`) made those three changes and was reviewed (received 23:07): hashes verified, one freeze blocker, the definition of a day's first instant. **Draft 5 makes that one correction and nothing else** (section 2.8). Manj accepted OP-1 to OP-12 as his decisions in the same message and holds the freeze only for this correction. Every decision, the scope, the permitted files, the scenario matrix and the test gates stand as they were.

**Correction to the record.** Drafts 1 to 3 carried times of writing in their titles (22:30, 23:10, 23:45) that were estimates and were wrong: each draft was sent before the review of it was received, at the times given above. The times of receipt are the user's message times and are reliable. The SHA-256 of each draft is unaffected and identifies it. Each review item was checked by probe before being accepted; where the probe gave a different answer from the review, or from an earlier draft, it is said so.

## 1. Purpose and scope
B2a added what Engram knows beside what the adapter already sent. B3 taught ERC's comparison to read it. B2b is the step that **changes what the adapter sends**, so that it stops stating things Engram does not hold.

| ID | Today (`8eb4853`) | B2b |
|---|---|---|
| B2B-01 | A state still going is given an end the day after `as_of` | Sent as still going: `end_unbounded=True`, no end date |
| B2B-02 | The day a value was first said is sent as its exact start | No exact start; the said day is the **latest** the state can have begun (`start_latest` alone) |
| B2B-03 | A closing or replacing date taken from when a sentence was said is sent as an exact end | A closing or replacing date that was only said is an upper bound, not an exact end |
| B2B-04 | An event is sent as an interval with a start and no end | An event is sent as an occurrence (`Proposition.occurred`), with no validity interval |
| B2B-05 (F18) | An end at or before the start is pushed to one day after the start | No date is ever manufactured to make an interval valid |
| B2B-06 (TAD-04) | Calendar days are read in UTC, undeclared | The zone is a declared setting of each adapter, and is reported |

**In scope:** `erc_overlay/` only. **Out of scope:** any change to `engram_erc/` (ERC stays 0.6.0; B3's comparison is not touched), any change to `engram_knowledge/`, rules and time (B4), conclusions and time (B5), removing the guards (B6), the request fingerprint (step 4), the three documents that still say 0.5.0 (Manj's separate decision).

**First acceptance criterion (carried from B3):** S02, S03, S04, S17, S19 definite again; S06, S07, S08, S15, S16, S21 still potential.

## 2. Existing temporal data flow, and what the audit found
### 2.1 Baseline, re-run in a fresh clone at `8eb4853` (Python 3.13.18)
| Check | Result | Handover figure |
|---|---|---|
| Full suite | 1,454 passed, 4 failed (the four recorded), 3 skipped, 1 expected-fail | the same |
| Adapter tests | 172 passed | the same |
| Breakages `--suite adapter` | 42 of 42 | the same |
| Breakages `--suite erc` | 54 of 54 | the same |
| Working tree after all runs | clean | — |

### 2.2 How a date travels today
1. Engram's state engine (`state_engine.py`, `_build`) plays one slot's observations in date order and produces periods: `start` (stated, or none), `first_said`, `end`, `end_kind` (open, stated, closed, replaced), the ids of the facts in the period and the speakers.
2. The adapter (`knowledge.py`, `_periods`) copies `(start or first_said, end, open?, start_basis, end_kind)` for each state fact. Events are dated separately from their own sentence (`_event_date`).
3. `_interval` turns that into a `TimeInterval`. Three inventions happen here, in four lines (264 to 267): the stand-in end (`as_of + 1 day`), the said day used as a start, and the one-day minimum.
4. `_facts` applies the guards to the interval **as sent** (lines 186 to 191): left out when `start > as_of`, and when `end <= as_of`.
5. `request_for` gives any fact whose interval is absent the qualifier `valid_time: unknown` and a qualifying state record (lines 301 to 307), whatever its state. That is the existing "unknown time: provisional" guard.
6. `reasoner.py` prints the interval in `explain()`.

### 2.3 Findings (numbered on from F18)
| # | Finding | Evidence |
|---|---|---|
| F19 | **Sending open states as still going restores all five limitation cases and moves none of the six corrections.** | Section 10 |
| F20 | **"Start unknown" is the wrong spelling for a first-said start.** It makes S04 and S05 potential although Engram is certain of both. "No later than the said day" keeps both definite. | Section 4 |
| F21 | **The one-day minimum fires in three shapes, not one:** (a) an open state whose start is after `as_of + 1 day`; (b) a first-said start with a stated end at or before the said day (F18, S11); (c) a period whose stated start is at or after its stated end. | Section 8 |
| F22 | Shape (c): Engram refuses a single fact whose end precedes its start, but two facts for the same value merge into one period. "Lives in Delhi from June 2023 to March 2024" and "lives in Delhi, to 2021" give a period 2023-06 to 2021. | Section 8 |
| F23 | **A closed end's provenance can be worked out in the adapter.** A closed period lists its closing fact among its `fact_ids`; that fact either has a stated date or it does not. | Section 5 |
| F24 | **A replaced end's provenance can also be worked out, but not from the successor period.** (Corrected from Draft 1, which said it could not.) The replacing fact is found among the slot's own facts. In 586 replaced periods: exactly one candidate 575 times, several agreeing 7 times, several of which one stated the date 4 times, none 0 times. The reviewer's suggested route through the successor period's `start` and `first_said` fails in 59 of the 586, because the replacing statement had merged into an existing period. | Section 5 |
| F25 | **The guards read the interval that is sent.** Once an open or first-said state carries no end and no start, they must be stated on Engram's dates to keep their outcomes. | Section 9 |
| F26 | A start known only as "no later than" can never be shown **not** to overlap something earlier. | Section 8 |
| F27 | `explain()` reads `valid_time.start` for events and prints "to ?" for a missing end. | Section 11.2 |
| F28 | 14 of the 42 adapter breakages mutate code that B2b rewrites (13 in the time code, 1 in `explain()`). Each must be re-pointed, none dropped. | Section 13 |
| F29 | `ReasoningRequest.constraints` and `.options` exist and nothing in ERC's reasoning path reads them. | Section 7 |
| F30 | **Shapes (b) and (c) can never be eligible once the guards read Engram's dates.** If a period's end is not after its start, every `as_of` is either before the start or at or after the end. Today they are sent only inside the invented one-day window. Measured over 2,500 paired runs: shape (b) 23 times sent today and left out by the candidate; shape (c) 30 times, of which 28 were already left out and 2 were sent. No other difference in which facts are left out. | Sections 8, 9 |
| F31 | The code already separates an undated fact from an open one: a fact with neither start nor end gets no interval (line 263); only a fact with a start and no end is treated as open. | Section 3 |
| F32 | Every event predicate in Engram's vocabulary is a completed happening (started_job, moved_to, got_married, bought, adopted, started_hobby, joined, left_job, divorced, sold, lost, gave_away, stopped_hobby, left_group). A plan is a separate fact type and is left out before any date is read. | Section 6 |
| F33 | One existing test sets the module's `DAY_ZONE` before building an adapter. A per-adapter zone whose default is read from `DAY_ZONE` when the adapter is built keeps that test unedited: measured, 172 of 172 pass in a throwaway copy with the per-adapter zone and the UTC default. | Section 7 |
| F34 | **Two times in the same zone are compared by Python on the clock, not as instants.** The two occurrences of a repeated hour compare as equal. Against the day boundaries the adapter makes, this gives a wrong answer only in zones whose clock change touches midnight: 0 of 1,542,720 comparisons in New York, Kolkata, London and Lord Howe; 44 to 88 in each of Havana, Cairo, Santiago, Beirut and Apia (2009 to 2030, every half hour, both occurrences). Some of those are clock times that do not exist on the day, and the Santiago ones come through the last instant of F35; the count shows the comparison cannot be relied on, not how often a real question would be answered wrongly. | Section 7 |
| F35 | **"The first instant plus 23:59:59.999999 on the clock" is not always a day's last instant.** Where the clock goes back at midnight the last hour happens twice and that arithmetic lands in its first occurrence: wrong on 13 days in Cairo, 21 in Santiago, 22 in Beirut over the same years; right every day in the other six zones. "One microsecond before the next day's first instant" is right on every day tested. | Section 7 |
| F36 | A calendar day can be missing from a zone altogether: Apia, 30 December 2011; Kiritimati, 31 December 1994 (the only two found in twelve zones, 1990 to 2030). Such a day has no instants. | Section 7.1 |
| F38 | **Local midnight can be missing on a day that exists.** Where the clock goes forward at midnight the day begins at 01:00 (Santiago, 11 October 2009: 01:00 -03:00; likewise Cairo, Beirut, Havana). Across all 498 IANA zones, 2000 to 2030: 482 such days in 56 zones, and 2 days missing altogether. Python will still build a time labelled 00:00 with the old offset; passed through UTC and back it becomes the true first instant. The rule "build midnight, pass it through UTC and back into the zone, accept it only if it is still on the requested date" gave a correct, ordered, gap-free result on every one of 5,638,854 zone-days: no day out of order, no day's last instant on another date. | Section 7 |
| F37 | **Made into an instant today, a missing day silently becomes the next day.** In the throwaway zone copy, "works at Apollo from 30 December 2011" in `Pacific/Apia` is sent with a start that is the first instant of 31 December. Nothing reports it. A missing day can be recognised exactly: its first instant, read back in the zone, is not on that calendar day. | Section 7.1 |

### 2.4 Effect on the existing tests, measured
Each change was switched on in a throwaway copy and the 172 adapter tests run.

| Change switched on | Adapter tests affected | Of which |
|---|---|---|
| B2B-01 open end alone | 15 | 10 written before B3 + 5 B3 tests (X2 four times, X5) |
| + B2B-05 no one-day minimum | 18 | + the two B2a tests of the adjusted end and X4's S11 row |
| + B2B-02 first-said as "no later than" | 18 | none new: its tests already assert the stand-in end |
| + guards on Engram's dates (section 9) | 18 | none new |
| + B2B-03 closing provenance | 19 | + one B2a test (closed end "gets no bound") |
| + B2B-03 replacement provenance | 19 | none new (the one B2a test of a replaced end does not assert the flag and passes unedited; a new test asserts it) |
| + B2B-04 events as occurrences | **29** | + 9 event tests and X4's S12 row |

The 29 are named one by one in section 12.2. **143 adapter tests pass unedited under the full candidate.** No test in `engram_erc/` can be affected: no file there changes.

### 2.5 What the review changed, and what the probes changed in the review
| Review item | Outcome in Draft 2 |
|---|---|
| OP-4 replaced ends: probe the successor period | Probed. Provenance **is** recoverable, by fact, not by successor period (F24). Draft 1 was wrong to say it could not be read. Replaced ends that were only said become upper bounds (section 5) |
| OP-5 events only said: a semantic rule, not a substitution | Stated as a rule with its conditions (section 6); F32 shows the conditions hold for Engram's event vocabulary |
| OP-7 inconsistent period: no invented qualifying record | Withdrawn in favour of exclusion. F30 shows such a period is never eligible under the two existing guards, so no new eligibility rule and no record is needed; it is left out with its own reason (section 8). For the record, the mechanism Draft 1 relied on does exist (section 2.2, item 5), but exclusion is simpler and safer |
| OP-8 exact guard inequalities | Read from the code and stated (section 9); 2,500 paired runs including exact boundary instants show no unnamed difference |
| 3A undated is not open | Already so in the code (F31); now stated. **One point not accepted:** a slot period Engram calls open whose start is unknown stays "time unknown" (section 3, OP-12) |
| 3B zone configuration contract | Section 7 |
| 3C fingerprint limitation | Section 11.3 |
| 3D complete reachability table | Appendix A |
| Name the 29 tests | Section 12.2 |
| Record the limits of the measurements | Appendix B |

### 2.6 What the second review changed (Draft 2 to Draft 3)
| Review item | Outcome in Draft 3 |
|---|---|
| OP-4: all replacement candidates considered together, never the first found; test the mixed case | Stated as an aggregation rule (section 5); tests and a breakage added |
| OP-6: IANA name or `ZoneInfo`; stable reported name; refuse what cannot be identified | Section 7. An arbitrary `tzinfo` is refused |
| OP-6: compare as absolute instants; test both occurrences of a repeated hour | Section 7. **The probe refines the proposed test:** in New York the two occurrences give the same answers either way, because no day boundary falls inside the repeated hour. Differences appear only in zones whose clock change touches midnight (F34, F35), so the test uses one of those as well as New York |
| Found by the same probe, not raised by the review | A day's last instant must be made from the next day's first instant, not by clock arithmetic (F35). Today's code uses clock arithmetic; it is exact in UTC, which is the only zone used so far |
| Request id: not an audit or deduplication key across zones | Section 11.3 |
| Inconsistent period: period-level, not fact-level | Section 8 |
| Vocabulary pin fails on any new event predicate | Section 6 |
| Zone probe attached | Appendix B; results in section 7 |
| OP-12 | The second review accepts Draft 2's position |

### 2.7 What the third review changed (Draft 3 to Draft 4)
| Review item | Outcome in Draft 4 |
|---|---|
| A date that does not exist in the zone must fail safely, by a stated rule | Section 7.1, with the probe that shows the silent change of date today (F37) |
| Public zone contract against the legacy `DAY_ZONE` test override | Section 7, rows "What may it be?" and "Default": the override is a test seam, not a supported configuration |
| The zone copy used clock arithmetic for the day's end, so it does not verify F35 | Correct, and recorded (Appendix B, limit 4). The corrected last instant and the Santiago test through the adapter's own guard are acceptance requirements (section 12.1, item 9) |

### 2.8 What the fourth review changed (Draft 4 to Draft 5)
| Review item | Outcome in Draft 5 |
|---|---|
| "The first instant of a day is local midnight" is not always true: midnight can be skipped on a day that exists | Confirmed by probe and found to be common (F38). Section 7 now defines the first instant as the earliest instant whose local date is that day, sent in a valid local form; section 7.1 applies only when the whole day has no instant. Test and breakage added |

## 3. Open-ended states (B2B-01)
**Rule.** A period whose `end_kind` is `open`, and which has a start or a first-said day, is sent with `end_unbounded=True` and no `end`.

| Engram holds | Sent today | Sent at B2b |
|---|---|---|
| slot period, open, start stated to the day | `(5 Mar 2024, as_of + 1 day)` | `TimeInterval(5 Mar 2024, end_unbounded=True)` |
| slot period, open, start stated "2024" | `(1 Jan 2024, as_of + 1 day, start_latest=…)` | `TimeInterval(1 Jan 2024, start_latest=31 Dec 2024 23:59:59.999999, end_unbounded=True)` |
| slot period, open, only first said | `(said day, as_of + 1 day)` | `TimeInterval(start_latest=last instant of the said day, end_unbounded=True)` (section 4) |
| fact outside every slot, `valid_from` given, no `valid_to` | stand-in end, labelled `open` | `end_unbounded=True`, labelled `open` |
| fact outside every slot, neither date | no interval: time unknown | **unchanged**: time unknown |
| slot period, open, no stated start and no readable said day | no interval: time unknown | **unchanged**: time unknown (OP-12) |

On the last row the review recommends using Engram's open classification "even if its start is unknown". I suggest not, for B2b. Sent as an interval with nothing but `end_unbounded`, the fact would leave the "unknown time: provisional" guard, and it would gain nothing in comparison: with no start bound B3 answers unknown either way. Keeping it under the guard is the conservative reading and changes nothing that is sent today. Put to Manj as OP-12.

Consequences of the rule: no interval sent depends on `as_of`; the shape "`start_latest` later than `end`" can no longer come from an open state; `end_basis` stays `open`.

## 4. First-said starts (B2B-02, TAD-15)
**Rule.** When Engram holds no stated start, the day the value was first said is not a start. It is evidence that the state had begun by then. Sent as `start_latest` = the last instant of the said day (or of the said month, when the sentence is dated only to a month), with no `start`. `start_basis` stays `first_said`.

| Scenario | Engram: conflict now | First-said as "no later than" | First-said as "unknown" |
|---|---|---|---|
| S04 (from "March 2024" / first said 5 Mar) | yes | definite | **potential** |
| S05 (both only first said) | yes | definite | **potential** |

Consequences accepted knowingly:
- `start_basis` is present when the interval has a `start` **or** a `start_latest` (B2a's amendment 3 said "only when the interval has a start").
- Wording will differ from Engram's `get_state_at`, which treats the said day as the start. The adapter says less than Engram here, never more (TAD-15).

## 5. Closing and replacement dates (B2B-03, TAD-17)
What Engram does (`_build`): a closing statement ("left Apollo") ends the matching period at the statement's own date, stated or, failing that, the day it was said, and marks it `closed`. A new value from the same speaker ends the old one at the step before the new value's date (stated, or the day it was said) and marks it `replaced`.

**Rule.** The adapter establishes, from records it already reads, whether the date that ended a period was stated or only said. A date only said is never an exact end.

| Case | How the adapter knows | Sent today | Sent at B2b |
|---|---|---|---|
| Closed, closing date stated to the day | the closing fact in the period's `fact_ids` has a stated date | exact end | exact end (unchanged) |
| Closed, closing date stated to a year or month | the same | exact end at the period's close, no bound | the end with `end_earliest`, as B2a does for a stated end |
| Closed, closing statement only said | the closing fact has no stated date | exact end, the day after the said day | that instant with `end_is_upper_bound=True` |
| Replaced, replacing date stated | the replacing fact (below) has a stated date | exact end, label `replaced` | **unchanged**: exact, as Engram holds it |
| Replaced, replacing statement only said | the replacing fact has no stated date | exact end | that instant with `end_is_upper_bound=True` |

**Identifying the replacing fact: an aggregation, not a search.** The candidates are **all** facts of the same slot that are of another value, are not closing statements, share a speaker with the replaced period, and whose date (stated, else the earliest said day) is the step after the period's end. They are considered together; the result does not depend on the order in which facts are read, and no single candidate is selected.
- If **any** candidate states the date, the end is stated.
- If there are candidates and **none** states it, the end was only said.
- If there is **no** candidate, the end is treated as only said: the weaker claim.
 The adapter does not re-play the slot and does not alter any date; it reads the provenance of a date Engram has already set. No Engram field is added.

Measured (F24): 586 replaced periods in 1,500 random worlds with three speakers, coarse and day dates, month-only sentence dates and up to seven statements; the rule found a fact every time. Several candidates occurred 11 times, and in 4 of those one stated the date and another only said it: the mixed case is real and has its own test.

**Carried limitation.** A value replaced by one stated only to a year ("at Manipal from 2022") keeps the exact end Engram gives it (the close of 2021), although the change may have fallen anywhere in 2022. Widening it would make the adapter contradict Engram's own history, which holds the old value as not true in 2022. It is labelled `replaced` and recorded.

S16 (the genuinely closed end) stays potential with the upper bound: measured.

## 6. Events (B2B-04)
**Rule.** A fact whose predicate is an event carries `occurred` and no `valid_time`.

| Event's date | Sent today | Sent at B2b |
|---|---|---|
| Stated, any precision | `TimeInterval(first instant, None)` | `Occurrence(first instant of the period, last instant of the period)` |
| Not stated; a supporting sentence has a readable date | `TimeInterval(said day, None)`, label `first_said` | `Occurrence(latest = last instant of the said day)`, under the condition below |
| No date of any kind | time unknown | unchanged: time unknown |

**The condition for the upper bound (review item B).** A readable observation date may supply an occurrence's upper bound only when the fact itself asserts that the event has already happened. It is never the event's date. Concretely, all of:
1. the predicate is in Engram's event vocabulary, every member of which is a completed happening (F32);
2. the fact is not a plan (a plan is left out before this point, as today);
3. the sentence is linked to the fact as **supporting** evidence (the rule `_event_date` already applies).

If any of these fails, the occurrence time is unknown and the fact follows the "unknown time" guard. Engram stores a fact only as asserted; the adapter has no means of reading a sentence for "merely mentioned" beyond these three, and the specification does not pretend otherwise. That every event predicate is a completed happening is a property of today's vocabulary, not a guarantee. A test therefore pins the exact set of event predicates: it **fails when any predicate is added or removed**, so that a new one cannot receive the said-day bound without an explicit decision that it is a completed happening.

Measured consequence, foreseen in B3: two moves at different known times (S12) no longer produce a potential contradiction; they produce none, because the two windows cannot meet. Whether event predicates belong on the one-value list remains B6.

## 7. Day precision and the zone (B2B-06, TAD-04)
**Configuration contract.**
| Question | Answer |
|---|---|
| Where is the zone supplied? | A keyword argument when the adapter is built: `KnowledgeAdapter(kb, day_zone=…)`, passed through by `Reasoner(kb, …, day_zone=…)` |
| What may it be? **(the public contract)** | An IANA zone name (`"Asia/Kolkata"`) or a `ZoneInfo` object, and nothing else. Any other value given to `day_zone` is **refused** when the adapter is built: an unknown name, an empty name, a number, any other `tzinfo` including a fixed offset. Nothing is ever replaced silently by UTC |
| Default | When no zone is given: UTC, reported as `UTC`. It is held in the module's `DAY_ZONE` and read **when the adapter is built** (F33). The adapter never changes `DAY_ZONE` |
| The legacy test seam | One existing B2a test (`test_b2a_every_instant_made_from_a_day_follows_the_adapters_one_zone`) replaces `DAY_ZONE` with a fixed offset for its own duration. That keeps working, so the test stays unedited, and the zone is then reported by the offset's fixed name (`UTC+05:30`). **This is a compatibility exception for that test and not a supported configuration.** Production code sets the zone only through `day_zone`. A fixed offset cannot be passed to `day_zone`. A new test asserts both halves: the seam still works, and `day_zone` refuses a fixed offset |
| Can it change? | No. It is fixed for the life of the adapter. Two adapters with different zones do not affect one another; nothing process-wide is written |
| Is it ever inferred? | Never from the machine, the user's location or `as_of` |
| What does it apply to? | Every instant made from a calendar day: state boundaries and their bounds, occurrence windows, observation dates. One function makes them all, as now |
| How are periods bounded? | A day, month or year runs from the first instant of its first day to the last instant of its last day, **in the zone**. **The first instant of a calendar day is the earliest absolute instant whose local date in the zone is that day** (F38). It is usually local midnight; where a clock change skips midnight it is the first time that does occur (01:00, say). The adapter builds the candidate midnight, passes it through the absolute timeline and back into the zone, and confirms the local date is the requested one; the boundary it keeps and sends is that **valid local time**, never a label for a time that did not occur (Santiago, 11 October 2009: `01:00 -03:00`, not `00:00 -04:00`). If the local date is not the requested one, no instant maps to the day and section 7.1 applies; it applies in no other case. **The last instant of a day is one microsecond before the first instant of the next day, taken as an instant** (F35): not the first instant plus 24 hours, and not the first instant plus 23:59:59.999999 on the clock. The exclusive end of a state is the first instant of the next day. Where the next day is itself missing, "the next day" is the next day that has an instant |
| How is `as_of` compared? | **As an absolute instant.** `as_of` must carry an offset (as today) and it may be any offset or zone. Before a guard compares `as_of` with a boundary, both are put on one absolute timeline (UTC). The adapter never relies on comparing two times in the same zone object, which Python does on the clock (F34) |
| What is sent to ERC? | The boundary instants in the adapter's zone, as today, so that the calendar day shown by `explain()` is the day that was stated. ERC's comparison only compares these boundaries with one another; made as above they keep the same order on the clock as on the absolute timeline (measured: 8,035 days in each of nine zones, one exception, F36) |
| How is it reported? | By its stable name: the IANA key. On the adapted request (`day_zone`) and in the heading of `explain()` |

**Stated days.** A state stated to the day stays exact: states hold by whole calendar days in the declared zone, the convention B2a's bounds already follow. Giving a stated day its own window was measured in Draft 1 (2 more tests, no scenario of section 10 changes) and is not suggested for B2b. Carried as a limitation. An **event** stated to the day gets that day as its window (section 6).

**Measured in a throwaway copy with the per-adapter zone** (`probe_zone.py`; what is sent is otherwise today's):
| Check | Result |
|---|---|
| UTC default | identical to an explicit `"UTC"` and to today's instants; all 172 adapter tests pass |
| `Asia/Kolkata` | "from 2019" starts 2019-01-01 00:00 +05:30 (18:30 UTC the day before); "to March 2021" ends 2021-04-01 00:00 +05:30 |
| New York, clock-change days | 10 March 2024 is 23 hours long, 3 November 2024 is 25; each runs from its own midnight to one microsecond before the next. "First instant plus 24 hours" would be 01:00 the next day in March and 23:00 the same day in November |
| Two adapters, Kolkata and New York, used alternately | each keeps its own zone; the module default is untouched |
| `as_of` in another offset | at exactly the boundary instant, written in UTC or in the zone: the starting fact is kept and the ended one left out; one microsecond earlier, written in New York time: the reverse |
| Repeated hour, New York, 01:30 both occurrences | Python calls them equal in the same zone object; as instants they are an hour apart; the guards give the same answer for both, since no day boundary lies between them |
| Zones whose clock change touches midnight | F34, F35 |
| Invalid settings | an unknown name, an empty name, `IST+5`, a number and a fixed-offset `tzinfo` are each refused; a `ZoneInfo` is accepted and reported by its key |

### 7.1 A calendar day that does not exist in the zone (F36, F37)
**Rule.** If a required calendar day has no instant in the adapter's zone, the adapter makes no instant from it. It does not move the date to a neighbouring day and does not manufacture a boundary. The temporal statement that needed the day is treated as not established, under the existing unknown-time treatment, and the condition is reported. Engram's stored history is not touched.

| Term | Meaning |
|---|---|
| Required day | A day from which an instant must be made: the first or the last day of a date Engram holds as stated (a start, an end, a closing or replacing date, an event's date), or a said day. A day **inside** a stated month or year is not required: only the period's first and last days are |
| Has no instant | No instant has that calendar day as its local date: the candidate midnight, passed through the absolute timeline and back into the zone, falls on another date. **A day whose midnight is skipped but which otherwise exists is not such a day**; it has a first instant (section 7) and is dated normally |

| Where the missing day is needed | What the adapter does |
|---|---|
| Any boundary of a state's period | The state's whole time is not established. It is sent as today's undated fact is sent: no interval, `valid_time: unknown`, the existing qualifying state record, so at most provisional. No partial interval is sent from the other boundary |
| A superseded fact's end | As today for a superseded fact whose end is not known: left out, "superseded: end date unknown" |
| An event's date | No occurrence is sent; the same unknown-time treatment |
| The day a sentence was said | Treated as a said date that cannot be read: the sentence's evidence carries no observation date, and the day gives no first-said bound |
| Reporting | The state record's `qualified_for` carries "date not in zone" beside "valid time unknown"; `explain()` says the time is not known because the date does not exist in the named zone |

This adds no eligibility rule and no new record: it routes the fact to the guard that already exists for a time that cannot be established. The same date in a zone where it exists (UTC, for instance) is handled normally.

**Tests required:** 30 December 2011 in `Pacific/Apia` as a stated start, a stated end, a closing date, an event's date and a said day, each asserting that nothing dated 31 December is sent, that the fact is at most provisional or left out as the table says, and that the reason is shown; the same world in UTC, dated normally; December 2011 as a stated month in Apia, dated normally.

**For B6, recorded now:** when ERC itself begins to compare `as_of` with boundaries, it must compare instants.

**Tests required (acceptance requirements, not illustrations):** UTC default equal to today; a non-UTC zone; a 23-hour and a 25-hour day, asserting the first and last instants and that the last is one microsecond before the next day; a month end and a year end; an `as_of` in another offset at a boundary and one microsecond either side; both occurrences of a repeated hour in `America/New_York`, **and** in a zone whose clock goes back at midnight (`America/Santiago`), asserting the day's true last instant (F35), made as the next day's first instant on the absolute timeline less one microsecond, and asserting **the adapter's own guards**, through `request_for`, at both occurrences of the repeated hour (not a comparison of two datetimes on their own); **a day whose midnight is skipped (`America/Santiago`, 11 October 2009): the first instant sent is `01:00 -03:00` and not `00:00 -04:00`, the preceding day's last instant is `23:59:59.999999 -04:00` on 10 October, one microsecond before it, the day is not treated as missing, and the adapter's own guards, through `request_for`, give the right answer at that first instant, one microsecond before it and one microsecond after;** two adapters with different zones used in turn; each invalid setting refused; the reported name.

## 8. The one-day minimum (B2B-05, F18)
**Rule.** The adapter never moves a date to make an interval valid. The label `adjusted` is no longer produced.

| Shape (F21) | Today | At B2b |
|---|---|---|
| (a) open state starting after `as_of + 1 day` | one-day interval, then left out as "starts after as_of" | cannot arise: there is no stand-in end. Still left out by the guard |
| (b) first said at or after its own stated end ("worked at Apollo, to 2021", said 2024) | 5 to 6 March 2024, `adjusted`; sent when asked on the said day | **never sent** (F30). Asked before the said day: left out, "starts after as_of". Asked on or after it: left out, "ended before as_of". Both by the ordinary guards |
| (c) stated start at or after stated end (F22) | one day at the stated start, `adjusted`; sent when asked on that day | **never sent** (F30). Left out with its own reason, "period dates inconsistent", needs "resolution", checked before the two date guards so the reason is the true one |

**Period-level, not fact-level.** The reason "period dates inconsistent" is used only when the boundaries of the **period Engram assembled** are inconsistent: its stated start is at or after its end. It is never raised from one fact's own `valid_from` and `valid_to`. A fact dated by a period takes the period's dates; a fact outside every slot takes its own, and Engram already refuses such a fact if its end precedes its start. If the period is valid, no fact in it is excluded on this ground, whatever its own dates.

On (c), following the review: the exclusion covers **every state fact dated by that period**, because they share its dates; an event filed in the period keeps its own date and is unaffected; a fact left out this way is never a bridge, like any other left-out fact. No qualifying record is created and no fact is downgraded. The state table is not touched: this is a date guard, applied where the date guards are applied.

S11 then reads: Apollo ended by 2021, asked 2024, so Apollo is left out as ended and there is no contradiction, which is what Engram holds.

## 9. `as_of` guards and eligibility
The guards stay until B6. B2b changes **where they read their dates**, not what they decide. The inequalities are today's, read from the code:

| Guard | Left out when | At equality |
|---|---|---|
| Starts after `as_of` | the first instant of the earliest day the fact is known from is **later than** `as_of` | a fact known from exactly `as_of` is **kept** |
| Ended before `as_of` | the end Engram holds, as the first instant the state no longer held, is **at or before** `as_of` | a state whose end is exactly `as_of` has ended and is **left out** |

"The earliest day the fact is known from":
- a stated start: the first day of the stated period. **A coarse start uses its earliest day, as today, never its latest** ("from 2024" is eligible from 1 January 2024);
- no stated start: the first-said day. A fact first said after `as_of` does not answer that earlier question;
- an event: its stated date's first day, else the said day.

"The end Engram holds": a stated, closed or replaced end, at the instant sent today (including an end that is now an upper bound: it is the latest the state can have ended, so at or after it the state has certainly ended). **An open state never trips this guard.**

| Other guard | At B2b |
|---|---|
| Unknown time: provisional | unchanged (section 2.2, item 5) |
| Superseded with no end date | unchanged |
| Period dates inconsistent | new reason for facts that the two date guards already exclude at every `as_of` outside the invented one-day window (section 8) |

Unchanged and not open to change: the state table and its failing closed; no bridging through a left-out fact; plans left out; eligibility by status, validation and source type.

**Measured.** 2,500 paired runs (500 random worlds, each asked at five of thirteen dates that include exact start and end instants and the last microsecond of a day), today's adapter against the candidate in one process: the only differences in which facts are left out, or why, are shape (b) (23) and shape (c) (30). Across the 21 scenarios the only difference is S11.

The reason text "starts after as_of" is kept, although for a first-said fact it strictly means "not yet said at `as_of`". Rewording belongs with B6.

## 10. Scenario acceptance matrix (normative)
Run through the real adapter and ERC at `8eb4853`; the candidate columns in a throwaway copy. "Full candidate" is every rule of this draft.

| # | Engram: conflict now | Today | Open end only | Full candidate | Required at B2b |
|---|---|---|---|---|---|
| S01 | yes | definite | definite | definite | definite |
| **S02** | yes | potential | definite | definite | **definite** (Group A) |
| **S03** | yes | potential | definite | definite | **definite** (Group A) |
| **S04** | yes | potential | definite | definite | **definite** (Group A) |
| S05 | yes | definite | definite | definite | definite |
| **S06** | no | potential | potential | potential | **potential** (Group B) |
| **S07** | no | potential | potential | potential | **potential** (Group B) |
| **S08** | no | potential | potential | potential | **potential** (Group B) |
| S09 | no | potential | potential | potential | potential |
| S10 | no | potential | potential | potential | potential |
| S11 | no | definite | definite | **none** (Apollo left out as ended) | none (named change) |
| S12 | no | potential | potential | **none** | none (named change) |
| S13 | yes | definite | definite | definite | definite |
| S14 | no | definite | definite | definite | definite (a real six-month overlap) |
| **S15** | no | potential | potential | potential | **potential** (Group B) |
| **S16** | no | potential | potential | potential | **potential** (Group B) |
| **S17** | yes | potential | definite | definite | **definite** (Group A) |
| S18 | yes | definite | definite | definite | definite |
| **S19** | yes | potential; rule fires; conclusion provisional | definite; inference halted; nothing derived | the same | **definite, halted, no conclusion** (Group A) |
| S20 | no | none; accepted | none; accepted | none; accepted | none; accepted |
| **S21** | no | potential | potential | potential | **potential** (Group B) |

No rule of this specification may turn a Group B scenario definite. Under the full candidate ERC's answer matches Engram's current-conflict flag in every scenario except S14, where the difference is correct.

## 11. Backward compatibility
### 11.1 What must not change
| Area | Requirement |
|---|---|
| Eligibility | Which facts are sent and which are left out, and why: identical, except shapes (b) and (c) of section 8 |
| State table | Unchanged; fails closed |
| Bridging | A left-out fact never leads the walk anywhere |
| Engram | No file in `engram_knowledge/` changes. No stored fact, period or historical answer changes |
| ERC | No file in `engram_erc/` changes. Version stays 0.6.0. B3's comparison is used as it is |
| Evidence | Observation dates, links, state records: unchanged |
| Qualifiers | `start_basis` and `end_basis` keep their B2a values, less `adjusted`; `time_kind` unchanged |
| The two scenario groups | Separate tests, separate wording, as in B3 |

### 11.2 `explain()`
Every boundary says where it came from; a date that was only said is never shown as stated. Lines that must change, with the exact wording to be fixed by an appended amendment before the tests are written (as B2a did):

| Fact | Today | Needed |
|---|---|---|
| open state | `valid 2024-01-01 to 2024-03-06` | no invented end date: "still going" |
| first-said state | `valid 2024-03-05 to …` | begun by the said day, not from it |
| closed or replaced by a statement only said | `end closed 2024-03-06` | "no later than" |
| event | `event on 2024-03-05` / `time: event stated …` | the window, or "by" the said day |
| left out, inconsistent period | (the fact appeared under another reason) | "period dates inconsistent" |
| heading | strategy, status, as of, overall | plus the zone |

Tests compare `explain()` block by block, as now.

### 11.3 The request id
The id keeps its present form. It hashes fact fields and no dates, and B2b adds nothing to it. **Until step 4 the request id is not a unique semantic identity across zone settings:** two requests with the same facts and `as_of` but different zones carry different instants and the same id. It must not be used as a cache key, a deduplication key, or a unique audit correlation key across zones. A consumer that keeps the id must keep the zone beside it; the adapted request carries both. Step 4 must put the zone and every relevant temporal field into the canonical fingerprint; the dependency is recorded there and in the limitations.

## 12. Tests-first acceptance criteria
To be written only after the freeze and Manj's separate go. Every new test fails at `8eb4853` first; a test that says "this stays" also asserts a new behaviour beside it.

### 12.1 What the tests must establish
1. The matrix of section 10, Group A and Group B in separate tests. X2 and X5 revised to definite; X1 and X3 not edited.
2. Every reachable cell of Appendix A: the exact interval or occurrence sent, field by field, and its labels.
3. No interval sent depends on `as_of`.
4. No interval carries a date Engram does not hold: no stand-in end, no adjusted end.
5. Guards: the inequalities of section 9 at equality, each side, compared as instants; a coarse start eligible from its earliest day; a first-said fact not answering an earlier `as_of`; an open state never "ended"; shapes (b) and (c) left out with the stated reasons at dates before, on and after their boundaries; an inconsistent period excluded while a valid period containing a fact with unusual dates of its own is not; left-out lists otherwise identical to today's.
6. Replacement provenance: one candidate stated; one only said; several agreeing; **several of which one states the date and another only says it, asserted in both orders of entry**; and the fallback when none is found.
7. Events: stated to year, month and day; only said with a supporting sentence; a plan (left out); a sentence that is not supporting evidence (time unknown); the exact set of event predicates pinned, failing on any addition or removal.
8. `explain()`: the amended wording, exact.
9. The zone tests of sections 7 and 7.1, all of them. In particular: the last instant of F35 and the Santiago test through the adapter's own guard are required for acceptance, because no measurement in this stage verifies them (Appendix B, limit 4).
10. Before-and-after recording of every adapter request and reasoning run: every difference is one this specification names.

### 12.2 The 29 existing tests to be revised, by name
The change that affects each is given; the assertion revised and its reason go in the tests-first report. Nothing else is edited.

| # | Test (`tests/test_erc_overlay.py`) | Affected by |
|---|---|---|
| 1 | `test_a_disputed_closing_event_cannot_end_an_eligible_facts_period` | open end |
| 2 | `test_an_event_with_no_establishable_date_is_time_unknown_not_dated_from_the_period` | open end |
| 3 | `test_an_opening_event_appended_to_an_existing_period_keeps_its_own_date_not_the_periods_start[started_job dated only by its sentence]` | events |
| 4 | the same `[started_job stated 2021]` | events |
| 5 | `test_an_opening_event_keeps_its_own_date_and_outlives_the_state_it_opened` | events |
| 6 | `test_an_unaccepted_closing_event_cannot_end_an_accepted_facts_period_but_still_reaches_erc_as_a_hypothesis[needs_review]` | open end |
| 7 | the same `[pending]` | open end |
| 8 | `test_an_undated_closing_event_takes_its_date_from_its_sentence_not_from_the_period` | events |
| 9 | `test_as_of_2022_the_employment_is_out_and_the_2021_closing_event_is_available` | events |
| 10 | `test_b2a_a_period_closed_by_a_dated_statement_keeps_its_end_and_gets_no_bound` | closing provenance |
| 11 | `test_b2a_a_start_stated_to_the_year_keeps_its_start_and_gains_the_years_last_instant` | open end |
| 12 | `test_b2a_a_state_dated_only_by_when_it_was_said_keeps_that_start_gets_no_bound_and_is_labelled_first_said` | open end, first-said |
| 13 | `test_b2a_a_state_first_said_in_a_sentence_dated_only_to_the_month_gets_no_bound_from_the_sentences_precision` | open end, first-said |
| 14 | `test_b2a_an_event_dated_only_by_its_sentence_keeps_exactly_its_interval_and_is_labelled_first_said` | events |
| 15 | `test_b2a_an_event_with_a_stated_year_keeps_exactly_its_interval_and_is_labelled_stated` | events |
| 16 | `test_b2a_explain_adds_a_time_line_under_each_fact_and_every_other_line_is_exactly_as_before` | open end, first-said, events |
| 17 | `test_b2a_explain_time_line_for_each_kind_of_state_boundary[adjusted end]` | one-day minimum |
| 18 | `test_b2a_explain_time_lines_for_a_closed_period_its_closing_event_and_a_fact_with_no_time` | events |
| 19 | `test_b2a_guard_a_fact_from_this_year_is_still_sent_and_a_fact_from_next_year_is_still_left_out` | open end |
| 20 | `test_b2a_the_one_day_minimum_is_labelled_adjusted_and_gets_no_bound` | one-day minimum |
| 21 | `test_b3_named_limitation_a_conclusion_resting_on_such_a_conflict_is_provisional_and_never_accepted_until_b2b` **(X5)** | open end |
| 22 | `test_b3_named_limitation_two_open_values_with_a_coarse_start_reaching_the_asked_at_date_are_potential_until_b2b[S02 …]` **(X2)** | open end |
| 23 | the same `[S03 …]` **(X2)** | open end |
| 24 | the same `[S04 …]` **(X2)** | open end |
| 25 | the same `[S17 …]` **(X2)** | open end |
| 26 | `test_b3_results_that_do_not_change[S11 one-day minimum]` **(X4 row)** | one-day minimum |
| 27 | `test_b3_results_that_do_not_change[S12 two moves]` **(X4 row)** | events |
| 28 | `test_explain_shows_each_included_facts_state_and_kind` | open end |
| 29 | `test_explain_tells_an_event_from_a_state` | events |

Rows 21 to 27 are revisions of B3 tests. B3's frozen text names X2 and X5 only. If Manj approves OP-9, the two X4 rows are recorded as a **dated amendment appended to the B3 specification's record**; the frozen text is not edited.

## 13. Deliberate breakages
The 14 existing mutations in rewritten code (F28) are re-pointed. New ones, each to be caught:

| # | Mutation |
|---|---|
| 1 | an open state given an end at `as_of + 1 day` again |
| 2 | an open state sent with an end not known instead of still going |
| 3 | an undated fact sent as still going |
| 4 | a first-said day sent as an exact start |
| 5 | a first-said start sent with no bound at all |
| 6 | a stated start losing its `start` or its window |
| 7 | a closing date only said sent as an exact end |
| 8 | a stated closing date sent as an upper bound |
| 9 | a replacing date only said sent as an exact end |
| 10 | a stated replacing date sent as an upper bound |
| 11 | the replacement fallback reading "stated" when no fact is found |
| 12 | the one-day minimum restored |
| 13 | an inconsistent period sent |
| 14 | an event sent with a validity interval |
| 15 | an event sent with both an interval and an occurrence |
| 16 | an event only said given the said day as its exact time |
| 17 | the said-day bound given to an event without supporting evidence |
| 18 | a guard reading the sent interval instead of Engram's dates (each of the two) |
| 19 | a guard's inequality moved at equality (each of the two) |
| 20 | a coarse start made eligible only from its latest day |
| 21 | the zone taken from the machine |
| 22 | the zone written process-wide |
| 23 | a day's end made by adding 24 hours |
| 24 | a day made into an instant outside the one function |
| 25 | the replacing fact taken as the first candidate found instead of all together |
| 26 | a guard comparing on the clock instead of as instants |
| 27 | a day's last instant made by clock arithmetic |
| 28 | an unidentifiable zone accepted, or replaced silently by UTC |
| 29 | "period dates inconsistent" raised from a single fact's own dates |
| 30 | a day missing from the zone moved silently to the next day |
| 31 | a partial interval sent from the boundary that does exist |
| 32 | a fixed offset accepted by `day_zone` |
| 33 | a skipped midnight sent as a time that did not occur |
| 34 | a day whose midnight is skipped treated as a missing day |

## 14. Files permitted to change
`erc_overlay/knowledge.py`, `erc_overlay/reasoner.py`, `tests/test_erc_overlay.py`, `kit_tools/check_base2_breakage.py`. Nothing else. If the work shows another file is needed, it stops and an amendment is asked for. The frozen specification and the B3 amendment go into `docs/specifications/` in a separate documentation-only commit after sign-off, as was done for B2a and B3.

## 15. Release and sign-off gates
One specification, one tests-first stage, one implementation, one sign-off. As run for B2a and B3: freeze with SHA-256; separate go for tests; tests-first report and patch to the reviewer; separate go for implementation; one local commit; build report and full diff to the reviewer; push authorisation for the exact commit; GitHub push run and manual run with breakages, totals read from the logs; formal sign-off; only then the tag `erc-temporal-b2b`, the handover and the board.

Release gate to be recorded: tests expected to fail first; tests expected to pass after; the 29 revised assertions with reasons; guards that remain active; limitations carried forward (rules and time; conclusions undated; `as_of` not enforced in ERC; a value replaced by a coarse stated date keeps Engram's exact end; stated days exact for states; an open period with no start of any kind stays "time unknown"; the request id and the zone; `engine_version`).

## Appendix A. What is sent, combination by combination (full candidate)
Status: **R** reachable and sent; **N** reachable and never sent; **U** reachable, sent as time unknown; **X** not produced by Engram.

Starts: stated day; stated year or month; first said (no stated start, readable said day); none (no stated start, no readable said day).

| Start \ End | open | stated | closed, date stated | closed, only said | replaced, date stated | replaced, only said |
|---|---|---|---|---|---|---|
| stated day | **R** `(start, end_unbounded)` | **R** `(start, end[, end_earliest])`; **N** if the end is not after the start (inconsistent) | **R** `(start, end[, end_earliest])` | **R** `(start, end, end_is_upper_bound)` | **R** `(start, end)` | **R** `(start, end, end_is_upper_bound)` |
| stated year or month | **R** `(start, start_latest, end_unbounded)` | **R** `(start, start_latest, end[, end_earliest])`; **N** if inconsistent | **R** likewise | **R** `(start, start_latest, end, end_is_upper_bound)` | **R** `(start, start_latest, end)` | **R** `(start, start_latest, end, end_is_upper_bound)` |
| first said | **R** `(start_latest, end_unbounded)` | **R** `(start_latest, end[, end_earliest])`; **N** if the end is not after the said day | **R** `(start_latest, end[, end_earliest])` | **R** `(start_latest, end, end_is_upper_bound)` | **R** `(start_latest, end)` | **R** `(start_latest, end, end_is_upper_bound)` |
| none | **U** | **R** `(None, end[, end_earliest])` (B2a's "end with no start") | **X** | **X** | **X** | **X** |

Notes. `[, end_earliest]` is present when the end was stated to a year or month. "None" with a closed or replaced end is not produced: Engram plays an undated statement last and neither closes nor replaces with it (`_build`, the undated branch). Where a closed or replaced end falls at or before a first-said or stated start, the row's **N** rule applies. The tests must confirm each **X** by showing Engram does not produce it, and each **N** by showing the fact is left out at dates before, on and after its boundaries.

Events: stated date **R** `Occurrence(first, last)`; only said, supporting sentence dated **R** `Occurrence(latest)`; otherwise **U**.

## Appendix B. Measurement tools and their limits (never committed; sent as `erc-b2b-stage1-draft5.zip`)
`make_variant.py`, `make_variant2.py` (patch a throwaway copy so each change can be switched on by a letter; `ABCDGER` is the full candidate), `probe21.py` (the 21 scenarios), `fuzz.py` (shapes reaching the one-day minimum), `fuzz2.py` (today against the candidate, left-out facts compared), `probe_replaced.py` (the first review's OP-4 probe), `make_zone_variant.py` and `probe_zone.py` (the second review's zone probe, on a separate throwaway copy), `probe_zone_construction.txt` (F35), `probe_missing_day.py` (F36, F37), `probe_midnight_gap.py` (F38, every IANA zone), raw outputs. To reproduce: `git archive 8eb4853 | tar -x -C <copy>`; `python make_variant.py <copy>`; `python make_variant2.py <copy>`; `ERC_B2B=ABCDGER python probe21.py <copy>`.

**Limits, to be kept in the audit record:**
1. The random worlds are a discovery probe, not a proof. One person, at most six predicates, about a dozen dates. "Three shapes" and "a replacing fact was found every time" mean found in these runs.
2. `erc-b3-stage1a.zip` was not available. The 21-scenario probe was rebuilt from the scenario functions B3 committed (S01 to S16, S21) and from tests X2 and X5 (S17 to S20). Its "today" column reproduces B3's recorded results for all 21, which is reassuring and is not the same as replaying the original package.
3. The patched copies are measurements, not the implementation. Its replacement probe reads Engram's observation list directly; the implementation must reach the same result from the records the adapter reads, and a test must show it. Its `explain()` wording is a placeholder.
4. The zone was measured on a separate copy that changes nothing else, so the zone and the temporal changes have not been measured together. **That copy makes a day's last instant by clock arithmetic, as today's code does. It demonstrates the per-adapter zone; it does not verify the corrected last instant of F35**, which was checked only as standalone arithmetic (`probe_zone_construction.txt`). Nor does anything here exercise the rule of section 7.1: the missing-day probe shows today's behaviour, not the corrected one. Both rest on the tests of sections 7 and 7.1. Nine zones (2009 to 2030) were examined for clock changes and twelve (1990 to 2030) for missing days. The first-instant rule of F38 was checked as standalone arithmetic over all 498 zones for 2000 to 2030, not inside the adapter and not for earlier years, where zone histories are more irregular.
5. The 29 is the count under this candidate. A change of decision on any open point can change it.

## Appendix C. Decisions
**Decided.** Manj, 10 November 2026, 23:07: "I accept OP-1 through OP-12 as my decisions. The technical positions, scope and acceptance requirements are approved." All four reviews recommended acceptance. The freeze is held only for the correction of section 2.8 and needs Manj's separate word on the Draft 5 hash.

| # | Point | Position (OP-6 refined in Drafts 4 and 5; the rest as Draft 3) | Reviewer | Manj |
|---|---|---|---|---|
| OP-1 | Open states | `end_unbounded`, no end date | accept | **Accepted** |
| OP-2 | First-said start | `start_latest` alone | accept | **Accepted** |
| OP-3 | Closed end, provenance | from the closing fact; only said becomes an upper bound; no Engram change | accept | **Accepted** |
| OP-4 | Replaced end | all candidates considered together; any stated makes it stated; only said becomes an upper bound; none found falls back to only said; no Engram change | accept with the aggregation wording and the mixed test (both now in) | **Accepted** |
| OP-5 | Event only said | "no later than the said day", under the three conditions; vocabulary pinned | accept conditionally (conditions now in) | **Accepted** |
| OP-6 | Zone | per-adapter IANA name or `ZoneInfo`, default UTC, fixed, reported by key, instants compared absolutely; the first instant of a day defined by its local date; a missing day fails closed (7.1); the `DAY_ZONE` override is a test seam only; section 7 | accept the architecture with the refinements (now in) | **Accepted** |
| OP-7 | Inconsistent period | never sent; "period dates inconsistent"; period-level only; all state facts of the period; no new record | accept | **Accepted** |
| OP-8 | Guards | read Engram's dates; inequalities of section 9 | accept | **Accepted** |
| OP-9 | B3 tests revised | X2, X5 and the S11 and S12 rows of X4; appended as an amendment to B3's record | accept | **Accepted** |
| OP-10 | One increment or two | one | accept | **Accepted** |
| OP-11 | `explain()` wording | fixed by an appended amendment before the tests | accept | **Accepted** |
| OP-12 | Open slot period with no start of any kind | stays "time unknown" under the guard | accept | **Accepted** |

## Appendix D. Hash and freeze record
Not frozen. To be filled at the freeze.

---

## Freeze record and amendments
The text above this line is the frozen B2b specification, unchanged: it is Draft 5 byte for byte, SHA-256 `621314c573ecbffcd82cf5295e3a0b98597fe750164c220c1d4d17356f5589c7` for the file as it stood before this section was added. Its own status lines ("freeze candidate, not frozen", and Appendix D's "Not frozen") are left as they were so that the digest Manj and the reviewer hold stays valid; this record supersedes them. Amendments are appended here with date, reason and approval, and never edited into the frozen text.

### Freeze (10 Nov 2026, 23:12)
| Item | Record |
|---|---|
| Frozen text | Draft 5, SHA-256 `621314c573ecbffcd82cf5295e3a0b98597fe750164c220c1d4d17356f5589c7` |
| Measurement package | `erc-b2b-stage1-draft5.zip`, SHA-256 `45672e48dccde9daedd26e322919bd1786249244f48bdcde3689b00cc8fda7b4` (never committed) |
| Reviewer | Fifth review, received 10 Nov 23:12: both digests independently calculated and matched; the midnight-gap correction accepted; "Draft 5 passes my specification review. I recommend freezing it at the supplied SHA-256. No Draft 6 is needed." The reviewer states the live GitHub working tree was not independently checked |
| **Manj, decisions (10 Nov 23:07)** | "I accept OP-1 through OP-12 as my decisions. The technical positions, scope and acceptance requirements are approved." |
| **Manj, freeze (10 Nov 23:12)** | "I AGREE FREEZE B2b Draft 5 at SHA-256" (the digest above) |
| Repository at the freeze | `erc-adapter-1` at `8eb485363aea0d7b149a4d6ce54e08bd70ab2b4b`, working tree clean; nothing of B2b built |
| Consequence for B3's record | OP-9: the amendment naming the S11 and S12 rows of X4 is appended to the B3 specification's record in the project (`claude/erc-b3-spec.md`), frozen text untouched. The repository's copy under `docs/specifications/` is not changed now; it and this specification go in by a separate documentation-only commit after B2b is signed off, with its own go |
| Still to come before any test is written | The `explain()` wording amendment (section 11.2, OP-11), appended here with Manj's approval |
| Tests, implementation, commit, push, tag | **Not authorised.** Each needs its own explicit word from Manj |

### Amendment 1 (11 Nov 2026, 08:12): the wording of `explain()`
| Item | Record |
|---|---|
| What the frozen text says | Section 11.2 and OP-11: the lines of `explain()` that must change are listed, "with the exact wording to be fixed by an appended amendment before the tests are written" |
| What this amendment fixes | The exact wording, below |
| Order of events, for the record | Manj's go for tests (10 Nov 23:16) came before this amendment existed. The wording was drafted as a proposal and the `explain()` tests written against it, marked provisional. The auditor reviewed the phrases (11 Nov) and recommended all of them with one refinement, "valid from no later than" in place of "valid by", which Manj asked for (11 Nov 07:42). The reviewer recommended approval of the refined wording in the reviews of revisions 2 and 3 of the tests-first package |
| Approval | **Manj, 11 Nov 2026, 08:12: "I approve the explain wording"** |
| Effect | The `explain()` assertions in the tests-first package are no longer provisional. No other part of the specification changes. The frozen text above is unchanged (`621314c573ecbffcd82cf5295e3a0b98597fe750164c220c1d4d17356f5589c7`) |

Principle: change as few words as possible; a date that was only said is never shown as stated; no invented end is shown.

**The heading** gains the zone at its end: `strategy …, status …, as of …, overall …, zone UTC`.

**The state line** (the part after the last semicolon):
| Fact | Today | Approved |
|---|---|---|
| state still going, start stated | `valid 2021-01-01 to 2024-03-06` | `valid 2021-01-01, still going` |
| state still going, only first said | `valid 2024-03-05 to 2024-03-06` | `valid from no later than 2024-03-05, still going` |
| state only first said, with an end | `valid 2024-03-05 to 2026-01-01` | `valid from no later than 2024-03-05 to 2026-01-01` |
| state with an end Engram holds as stated | `valid 2019-01-01 to 2021-04-01` | unchanged |
| state whose closing or replacing date was only said | `valid 2019-01-01 to 2024-03-06` | `valid 2019-01-01 to 2024-03-06 at the latest` |
| state with no start of any kind | `valid ? to 2022-01-01` | unchanged |
| event stated to the day | `event on 2022-03-05` | unchanged |
| event stated to a year or month | `event on 2022-01-01` | `event between 2022-01-01 and 2022-12-31` |
| event only said | `event on 2024-03-05` | `event by 2024-03-05` |
| time unknown | `valid time unknown` | unchanged |

**The `time:` line:**
| Fact | Today | Approved |
|---|---|---|
| start stated to the day / to a year or month | `start stated D` / `start stated, between A and B` | unchanged |
| start only first said | `start not stated (first said 2024-03-05)` | unchanged. (For a sentence dated only to a month the date shown becomes the month's last day, the latest the state can have begun, where today it is the first.) |
| no start of any kind | `start not known` | unchanged |
| end open | `end open` | unchanged |
| end stated, closed or replaced on a stated day | `end stated D`, `end closed D`, `end replaced D` | unchanged |
| end stated to a year or month | `end stated, between A and B` | unchanged |
| closed by a statement stated to a year or month | `end closed 2022-01-01` | `end closed, between 2021-01-02 and 2022-01-01` |
| closed or replaced by a statement only said | `end closed 2024-03-06` | `end closed, no later than 2024-03-06`; `end replaced, no later than 2024-03-05` |
| adjusted end | `end adjusted D` | never produced |
| event stated to the day | `time: event stated D` | unchanged |
| event stated to a year or month | `time: event stated 2022-01-01` | `time: event stated, between 2022-01-01 and 2022-12-31` |
| event only said | `time: event not stated (first said D)` | unchanged |
| time unknown | `time: not known` | unchanged |
| a date that does not exist in the zone | — | `time: not known (date not in zone Pacific/Apia)` |

**A fact left out for an inconsistent period** uses the existing line with the new reason: `left out: fact … (period dates inconsistent; status …, validation …, source …; needs resolution)`.

As on the existing lines, an end is shown as the first day the state no longer holds.
