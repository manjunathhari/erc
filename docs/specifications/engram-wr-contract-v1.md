# ENG-WR-02 to ENG-WR-06 and ENG-WR-08: Engram writing layer contract, version 1 (Draft 3.3)

Draft 3.3, 13 November 2026: Draft 3 with Amendment 1 (A1 to A10), Amendment 2 (R1 to R4) and Amendment 3 (3R1 to 3R4).

**Status: FROZEN on Manj's word, 13 November 2026, 17:15 IST ("four clarifications, reconcile the baseline, and then freeze the contract").** This text is fixed; any change is a numbered amendment with his own word. Freezing authorises nothing to be built: tests, implementation, commit, push and tag each still need his separate word. The freeze record, with this file's SHA-256, is `claude/engram-wr-freeze-record.md`.

| Item | Value |
|---|---|
| Authorised by | Manj, 13 Nov 15:10: "carry WordNet, Wikidata and LOINC into Draft 3 as sources for the vocabulary, together with the outside-code column"; his answers D1 to D10 and WP-1 to WP-15 (14:09 to 15:34); and, for Amendment 1, the reviewer's audit of Draft 3 (received 16:34, a recommendation only) with his decision on A1 (16:39). All recorded in `claude/engram-wr-record.md` |
| Replaces | Draft 3.2 (`claude/engram-wr-spec-draft3-2.md`, SHA-256 `59339814…5573cb2`), kept as its record. Before it Draft 3.1 (`940228e4…ca7300`), Draft 3 (`c2ff83e2…4b0c69`) and Draft 2 (`c051df2a…a6f4c8`) |
| Amendment 1 | A1 to A10 from the review, each checked against the code at `1396805`. A1 is his decision; A2 to A10 are precision rules and tests that decide nothing new. A4 and A8 were already covered (section 1.5; the classic back end's existing rule) and are now stated as tests. Every change is marked **[A1]** to **[A10]** in the text |
| Amendment 2 | Manj, 16:44: R1 to R4. R1: the original predicate wording and the outside-vocabulary marker are stored separately. R2: an explicit RELATES_TO provenance test. R3: date ranges tested through to the stored record. R4: the boundary of the migration comparison stated. Each marked **[R1]** to **[R4]** in the text, and "Am. 2" in the test table, so they are not confused with the correction rules R1 to R5 in section 4 |
| Amendment 3 | Manj, 17:15, passing on a reviewer's four clarifications as his instruction: 3R1 an explicit table of permitted endpoints for each relationship (section 1.5.1); 3R2 relationships written idempotently (1.5.2); 3R3 vocabulary governance columns and no bulk import (1.6); 3R4 injection detection as a separate security gate (2.1). Marked **[3R1]** to **[3R4]** |
| Baseline | Reconciled 13 Nov, about 17:20, by running both suites from fresh copies of `1396805`: see section 6.3 and `claude/engram-baseline-inventory-r1.md` |
| What changed from Draft 2 | Every open point is now a decision (sections 0 and 8); the vocabulary table is specified with its outside-code column and its sources (section 1.6); the dating rules are renumbered TD1 to TD8, with TD9 (WP-6) and TD10 (WP-8) added, so they are not confused with decisions D1 to D10; WP-13 is stated precisely; the helper's notes leave the "noted fact" label (K6); ownership and order (D8, D9) are in section 6 |
| What the freeze does not do | Authorise anything to be built. Tests in the repository, implementation, commit, push and tag each need Manj's own separate word |
| Repository | Unchanged at `1396805a183733fbffdc146e637f104299858589` |

## 0. Decisions this draft rests on

| No. | When (IST) | Decision |
|---|---|---|
| Requirement 1 | 13 Nov 13:03 | The contract reserves the place where typed relationships are stored and names all eight. The code that fills them comes after the writer fix |
| Requirement 2 | 13 Nov 13:13 | The contract names, as one of the writer's checks, a scan of each new entry for injected instructions before saving. Reserved now, built later |
| D1 | 14:09 | The 10 November decision is amended for the writing layer: three **additions** to the store may be reserved (relationships, vocabulary as data, point-in-time measurements). Nothing existing in the store is changed or removed. The engine is not reopened |
| D2 | 14:47 | Base 2's front end is the only way facts are filed; the classic writer's back half (checker, vocabulary, date reader, knowledge records, state engine) is the one back end. Nothing is deleted; the classic writer stays the control in the end-to-end test |
| D3 | 14:48, 14:49 | Branch `engram-core-redesign`, from `1396805a…` |
| D4 | 14:50 | The end-to-end test is the branch's first commit, alone |
| D5 | 14:50 | Draft 2 prepared (done) |
| D6 | 15:10 to 15:29 | WP-1 to WP-15 decided, as written into the sections below |
| D7 | 15:27 | The helper's notes become a chat handover summary only (WP-11) |
| D8 | 15:33 | The Engram track owns the two adapter changes (the event list; reading the vocabulary table), made on `engram-core-redesign` with ERC's adapter breakage suite run on every change |
| D9 | 15:33 | WR-A and WR-B, then the store reservation and WR-C; ERC B6 stays paused until WR-C is signed off and gate 1 has passed |
| D10 | 15:34 | Nothing for ERC B6 is frozen; the reviewer's "B6.2 is frozen" enters no plan unless the frozen document is produced |

**Governing rule (D1).** Every store change in this specification is an addition: a new table, or a new optional key. No existing table, column, check or allowed value is altered. Existing databases are brought up through the store's existing migration steps (`engram_knowledge/migrations.py`; the store is at version 3), with their data left as it is.

## 1. ENG-WR-02: the sentence-to-fact contract

### 1.0 The store today (read from `engram_knowledge/schema.py` at `1396805`)

| Table | What it holds | Relevant limits |
|---|---|---|
| `sentences` (engine) | Every sentence word for word, with speaker and said date | Layer 1. Never edited by this work |
| `entities`, `entity_aliases` | People, places, things, and their other names | |
| `knowledge_records` | One fact: subject, predicate, object, type, status, `valid_from`, `valid_to`, metadata | `fact_type` allowed: attribute, relationship, event, preference, plan, observation |
| `record_evidence` | The link from a sentence to a fact | `evidence_role`: supports, contradicts, qualifies. Source is always a sentence |
| `review_queue`, `review_sources` | Proposals held for review | No reader today |
| `state_reviews` | Reviewed changes of state | |

The 31-word vocabulary is in code (`PREDICATE_TYPES`, `PREDICATE_CUES` in `engram_knowledge/normalizer.py`; single-valued, opening and closing words in `engram_knowledge/transition.py`). The adapter counts as events only the 14 opening and closing words (`EVENTS` in `erc_overlay/knowledge.py`); the vocabulary types 17 words as events, and the three left out (`attended`, `visited`, `completed`) are sent as states. That is the end-to-end test's C12.

### 1.1 What goes in

| Input | Source | Note |
|---|---|---|
| One stored sentence: id, speaker, said-date text, exact words | `sentences` | Unchanged |
| The people in the chat | The caller | New to base 2's gate (S1) |

### 1.2 What the writer proposes

A sentence yields **zero, one or several** proposals (WP-2). Each holds one thing only (S6).

| Field | Rule |
|---|---|
| line | The id of the sentence |
| subject | Copied from the sentence; "I" for the speaker |
| word | One word from the vocabulary, or "other" |
| object | Copied word for word; one thing only |
| dates **[A2]** | Up to two dates found in the sentence, each with its role: at most one with role start and at most one with role end; or a single date with role event. None if the sentence states none |

**[A2] One fact, both ends.** "I worked at Manipal from January 2020 to March 2024" is **one** proposal with a start (January 2020) and an end (March 2024), stored as one record with both `valid_from` and `valid_to`; it is never split into two facts. The classic back end today accepts one stated time only (the end-to-end test's classic C04 fails for that reason); WR-B extends it to carry an end. That is a code change in the back end, not a store change: the columns already exist.

No proposal from a sentence is abstention, and is a correct outcome.

### 1.3 What is stored

| Field | Rule |
|---|---|
| Predicate | The vocabulary word. For "other": the sentence's wording, marked as outside the vocabulary; such a record is stored but kept out of the state engine and ERC rules (WP-1) |
| Wording and marker **[R1]** | Kept in separate places, never folded into one another. The `predicate` column holds only the vocabulary word, or for "other" base 2's wording exactly as it makes it today (`version_key`: the sentence with the object taken out); it never carries a prefix or tag such as "other:". Two new optional keys in the record's existing `metadata` (an addition, allowed by D1; today's keys `checked_by` and `said_on` are unchanged): `wording`, base 2's wording for **every** record, so a vocabulary record still keeps how it was said; and `vocabulary`, either `in` or `outside`. The state engine, the adapter and ERC tell an outside record by `vocabulary = outside`, never by reading the predicate's text |
| Start date | Only a date the sentence states, or one that resolves from the said day, with role start or event. **Never the said day** |
| End date | A date with role end |
| No date in the sentence | No start and no end are stored; the said day stays in the record's metadata and on the sentence, as today (WP-7). A stored "true by the day it was said" bound is added only at the step where a later statement can end a fact |
| Type | From the vocabulary word. **[A1] For "other": the type base 2's gate assigns today, from the kind of content it saw** (`FACT_TYPE` in `engram_structure.py`; claim → observation, plan → plan, and so on; observation when the gate gives no kind). Kept because the store accepts only its six types and refuses an empty one (D1 forbids changing that), and the gate's kind is a fixed rule, not a model's judgement. The record is still marked as outside the vocabulary and stays out of the state engine and ERC rules (WP-1) |
| The same fact said again **[A8]** | The classic back end's existing rule (`fact_validator.py`): same subject, same word and the same object after its tidying (`normalize_name`) → the new sentence is added as evidence to the existing record. Anything else → a new record, left to the state engine as a replacement or a conflict. There is no approximate matching, so no case is merged on a guess |
| Stated or inferred | Only stated facts are stored for now; an inference is not stored (WP-5) |
| About another person | A fact the user states about another person is stored under that person, with the user's sentence as its source (WP-4); the description is scoped to the speaker (I1) |

Filing goes through the classic back end (D2).

### 1.4 Guarantees

| No. | Guarantee | Holds today? |
|---|---|---|
| C1 | Every stored fact has at least one supporting sentence; deleting the sentence reaches the fact, and (once filled) every relationship resting on it | Yes for facts |
| C2 | The object is in the sentence, word for word | Yes |
| C3 | No stored date is absent from the sentence and the said day together | No on base 2 |
| C4 | A said day is never stored as a start or an end | No on base 2 |
| C5 | An unknown date is left empty | Yes where no date exists |
| C6 | The same fact said twice is one record with two sources | No on base 2 |
| C7 | A doubtful proposal is held, never stored | Yes |
| C8 | No model judges its own output | Yes |
| C9 | The writer only adds to the store; it never changes or removes what is there, and never edits layer 1 | Yes; to be kept |
| C10 | Every stored relationship names its type from the list of eight and rests on a sentence or on facts already stored | Nothing stored yet |
| C11 **[A1]** | A record outside the vocabulary always carries one of the six types, taken from the gate, and never reaches the state engine or an ERC rule | Type: yes. Exclusion: to be kept |
| C14 **[R1]** | Every record written by the corrected writer carries `metadata.wording` and `metadata.vocabulary`; the predicate never encodes the marker | New |
| C12 **[A4]** | A link from a sentence to a fact of kind supports, contradicts or qualifies exists only in `record_evidence`, never also in the new relationships table | Nothing stored yet |
| C13 **[A3]** | No relationship points at a sentence, fact or entity that does not exist, or at a fact whose content has been erased | Nothing stored yet |

**[Review point C1] Two different uses of the word "relationship".** `fact_type = relationship` says what kind of fact a record is (for example, married to). `record_relations.relation` is a link between two stored things. They are never interchangeable.

### 1.5 The reserved place for typed relationships (requirement 1; WP-13)

One new table, provisionally `record_relations`, added through a migration step, created empty. No code writes to it until the graph-extension step after the writer fix.

| Column | Meaning |
|---|---|
| relation_id | Stable id |
| relation | One of the eight, enforced by the store: `supports`, `updates`, `extends`, `contradicts`, `derives`, `qualifies`, `mentions`, `relates_to` |
| from_kind, from_id | A sentence, a fact or an entity |
| to_kind, to_id | A sentence, a fact or an entity |
| basis_sentence | The sentence the relationship rests on, when one exists |
| method, version | What made it (writer, rule, review) and its version |
| created_at | When it was recorded |

**One home for each kind of link (WP-13).** A link from a sentence to a fact of kind supports, contradicts or qualifies lives only in `record_evidence`, which is not altered. Every other link lives only in the new table. So the new table can carry all eight names, including a contradiction between two facts, but never a sentence-to-fact supports, contradicts or qualifies.

| Relationship | From → to | Home |
|---|---|---|
| SUPPORTS | sentence → fact | `record_evidence` |
| SUPPORTS | fact → fact | new table |
| CONTRADICTS | sentence → fact | `record_evidence` |
| CONTRADICTS | fact → fact | new table |
| QUALIFIES | sentence → fact | `record_evidence` |
| QUALIFIES | fact → fact | new table |
| UPDATES | fact → fact | new table. Never means the older sentence or fact is deleted; the superseded status stays as today |
| EXTENDS | fact → fact | new table |
| DERIVES | fact(s) → fact | new table. Not filled while inferences are not stored (WP-5) |
| MENTIONS | sentence → entity | new table |
| RELATES_TO | fact → fact; entity → entity | new table |

The graph is the existing store extended; no second graph is built, and ERC's graph is not duplicated.

**[A3] Keeping links valid.** The table's ends point at three different tables, so an ordinary database link cannot check them; the rules are enforced in code, in the same transaction as the write, and tested.

| Event | What happens to relationships | Follows the existing rule for |
|---|---|---|
| Writing a relationship | Refused unless `from_kind` and `to_kind` are each sentence, fact or entity, and both ends exist; refused if either end is a fact whose content has been erased (status `invalidated`); refused if it is a sentence-to-fact supports, contradicts or qualifies (C12) | — |
| A sentence is deleted | Every relationship with that sentence as an end or as its basis sentence is deleted, in the same step as today's `forget_sentence` | `record_evidence` rows of that sentence, deleted today |
| A fact's content is erased (its last supporting sentence deleted) | Every relationship with that fact as an end is deleted | Its `state_reviews`, deleted today |
| A fact is superseded, retracted, disputed or sent for review | Relationships stay. An UPDATES link is exactly what records a supersession; the older fact and its sentences are never deleted | Facts are never deleted today, only re-statused |
| An entity is deleted (today: only when nothing uses it any more) | Every relationship with that entity as an end is deleted, and a relationship counts as a use, so an entity still linked is not deleted | Entity clean-up in `forget_sentence` |
| A dangling relationship | Never permitted. A check of the whole table (like the store's existing link check after a migration) reports any, and the tests require zero |

**[A5] What each relationship must rest on.** No relationship is stored because a model judged two things related.

| Relationship | Must name |
|---|---|
| Any relationship with a sentence as an end (MENTIONS; any fact-to-fact link made because a sentence said so, such as UPDATES from "I have moved to Chennai") | The sentence, as `basis_sentence` |
| A fact-to-fact link made by a rule or by a person's review (for example, an UPDATES recorded when the state engine's supersession is approved) | Both facts, which must be stored and not erased; `method` names the rule or the review; `basis_sentence` names the sentence that triggered it, if one did |
| DERIVES | Not written while inferences are not stored (WP-5) |
| RELATES_TO | Only from a stated sentence, with that sentence as `basis_sentence`. Never from similarity alone |

#### 1.5.1 [3R1] Permitted endpoints

Checking that both ends exist is not enough: the combination must be one this table permits. Every other combination is refused. The permitted combinations are enforced twice: by a check in the new table's own definition (allowed by D1, since the table is new) and by the writing code, and both are tested.

| Relationship | Permitted from → to | Stored in |
|---|---|---|
| SUPPORTS | sentence → fact | `record_evidence` only (C12) |
| SUPPORTS | fact → fact | new table |
| CONTRADICTS | sentence → fact | `record_evidence` only (C12) |
| CONTRADICTS | fact → fact | new table |
| QUALIFIES | sentence → fact | `record_evidence` only (C12) |
| QUALIFIES | fact → fact | new table |
| UPDATES | fact → fact (newer → older) | new table |
| EXTENDS | fact → fact (newer → the one it adds to) | new table |
| DERIVES | fact → fact, one row per premise (premise → derived fact) | new table; not written while WP-5 holds |
| MENTIONS | sentence → entity | new table |
| RELATES_TO | fact → fact; entity → entity | new table |

So the new table's check admits exactly these nine (relation, from, to) combinations: SUPPORTS, CONTRADICTS, QUALIFIES, UPDATES, EXTENDS, DERIVES and RELATES_TO fact → fact; MENTIONS sentence → entity; RELATES_TO entity → entity. Anything with a sentence as the target, an entity as the source of anything but RELATES_TO, or a link from a thing to itself is refused.

#### 1.5.2 [3R2] Writing a relationship twice

Re-processing the same sentence must never create a second copy of a link. The rule follows `record_evidence`'s existing one (one row per fact and source sentence):

| Point | Rule |
|---|---|
| What makes a link the same | The same relation, the same two ends (kind and id, in the same direction), the same basis sentence and the same method. A missing basis sentence counts as a value in this comparison, so two rule-made links without one are still one row |
| Enforced by | A uniqueness rule on those fields in the new table, and a link id computed from them (not random), so writing it again finds the existing row and changes nothing |
| The same link stated by a second sentence | A second row, with the second sentence as its basis: two pieces of evidence for one link, as two sentences supporting one fact are two `record_evidence` rows today |
| Test | Filing the same sentence twice leaves the relationships table exactly as after the first time; a second sentence stating the same link adds exactly one row |

### 1.6 The reserved vocabulary table (WP-3; Manj 15:10)

One new table, provisionally `vocabulary`, added in the same migration step as 1.5, created empty. The first writer steps keep using the 31 words in code. Loading the 31 words as its first rows, and making the code read from it, is its own later step; its adapter part follows D8.

| Column | Meaning |
|---|---|
| word | The vocabulary word, e.g. `works_at` |
| domain | `general` for the 31; a domain name for later lists (e.g. `surgical`) |
| fact_type | One of the store's six types |
| time_kind | `state` or `event` |
| cardinality | `single` (one value at a time, e.g. one employer) or `many` |
| opens, closes | Which state word it opens or closes, if any (e.g. `left_job` closes `works_at`) |
| cue_words | Words a sentence would normally use for it |
| outside_system, outside_code | The code of the same meaning in an outside system: `wikidata` (e.g. a property id), `loinc`, `snomed`; empty if none |
| source, source_version | Where the row came from (hand-written, WordNet, Wikidata, LOINC, SNOMED) and that source's release (e.g. LOINC 2.82) **[3R3]** |
| vocabulary_version **[3R3]** | The release of Engram's own vocabulary in which this row was added or last changed |
| status **[3R3]** | `active` or `deprecated`. A deprecated word is never deleted and stays readable for the records that carry it; it is no longer offered to the writer |
| owner **[3R3]** | Who answers for the row's domain (for `general`, the Engram track; for a later `surgical` list, whoever Manj names) |
| state_engine_approved **[3R3]** | Yes or no. Only a word marked yes is used by the state engine and ERC rules; a new word starts at no and is switched on by a reviewed step |

**Sources for the vocabulary (Manj 15:10).**

| Source | Licence | Used for |
|---|---|---|
| WordNet (Princeton) | BSD-style, free | Cue words (synonyms) and entity types (word families). It does not say state or event, opens or closes |
| Wikidata properties | CC0 | Relation types and their outside codes; its start time, end time and point-in-time model matches TD rules here |
| LOINC | Free worldwide under its own licence | Measurements (e.g. haemoglobin), with WP-9 |
| SNOMED CT | Free in India through NRCeS (India a member since April 2014); fees outside member countries | Procedures, findings, disorders. **Caution: whether its content may be committed to a public repository is to be checked before any use** |

The rules attached to each word (time_kind, cardinality, opens, closes) are written by hand and reviewed; outside sources supply words and codes, not those rules. The writer is offered a small core list to choose from, not a whole outside source. **[3R3] No outside vocabulary is imported in bulk:** rows from WordNet, Wikidata, LOINC or SNOMED enter one at a time, each reviewed, with its rules written by hand.

**[A7] Moving from the code list to the table.**

| Stage | Source of truth |
|---|---|
| WR-A, WR-B, WR-C, the adapter event list (4a) | The 31 words in code. The table exists but is empty, and nothing reads it |
| The vocabulary step (its own increment) | The 31 words are loaded into the table. A test requires every column of every row to agree with the code's lists (type, single or many, opens, closes, event or state); any disagreement fails the step |
| After that step's sign-off | The writer, state engine and adapter read the table; the code's lists are kept only as the source of the first load and the agreement test, and are never read at run time again. There is never a time when both are read |

## 2. ENG-WR-03: entailment, attribution and abstention

| No. | Rule | Baseline |
|---|---|---|
| S1 | The gate is told who the people are | T2: 0 of 20 |
| S2 | Kept as they are: negation, "used to", wish, question, the assistant's words, another person's fact given to the speaker, an invented object | Caught |
| S3 | New: a conditional ("if … will") is held | Stored |
| S4 | New: a near miss ("almost") is held | Stored |
| S5 | New: a passing state ("today", "now", "so tired of") is held | Stored |
| S6 | New: an object must be one thing; a list is refused and the writer proposes each part | Stored |
| S7 | New on base 2: an opinion about something else is held | Stored on base 2 |
| S8 | A fact about a third person named in the sentence is stored when the user says it (WP-4) | Base 2: stored |
| S9 | An inference is not stored (WP-5) | All marked explicit |
| S10 | Before saving, each new entry is scanned for injected instructions (requirement 2). Reserved: named now, built later | No check today |

### 2.1 The injected-instruction scan (requirement 2; WP-14, WP-15)

| Point | Contract text |
|---|---|
| Where | In the writer's list of checks, on every proposal, after S1 to S9, before anything is stored |
| What it looks at | The proposal's subject and object, and any text later shown to an answering model. Not the sentence store |
| First version (WP-14) | A fixed, testable list of patterns: text addressed to an assistant or system, requests to ignore or change instructions, role markers. A separate checking model may follow; it is never the writer model (C8) |
| A caught entry (WP-15) | Held in the review queue with its reason; never shown as a fact. The sentence stays word for word in layer 1; only the structured record is held back |
| A separate gate **[3R4]** | The scan is its own security gate, not part of the writer's ordinary correctness checks: built in its own increment, with its own tests, deliberate breakages and sign-off, and reported on its own line in every build report. No record carries any mark saying it was screened until that increment is signed off; no such mark is added to the store before then |
| Until built **[A6]** | **Injection scanning is a required control that is not implemented in the first writer steps. Until it is implemented and tested, no injection protection is claimed, and no stored entry is described as screened.** The check's place in the list exists in code but does nothing; no test may count it as passing a security check, and every build report states that it is not built. A test that passes because a feature is missing is not evidence that the feature works |

## 3. ENG-WR-04: temporal interpretation

| No. | Rule | Baseline |
|---|---|---|
| TD1 | Dates are read by the existing reader, given the said day | T13: 17 of 20, not called by base 2 |
| TD2 | "Since", "from": start. "Until", "to" after "from": end. "From A to B": start and end | T14: 0 of 20 |
| TD3 | A date on an event word is the event's date | 0 |
| TD4 | A relative expression resolves from the said day ("yesterday", "last Friday", "three days ago"), by the existing reader's rules. **[Review point C5]** "Last <weekday>" is the most recent such day strictly before the said day (said on Thursday 12 June 2025 or on Friday 13 June 2025, "last Friday" is 6 June). The 20 expressions in `wr_probe.py` part T, with their fixed answers, are the tests; an expression outside them that the reader cannot settle gives no date (TD6) | Read, not used (17 of 20 right) |
| TD5 | More than one date and no role that settles them: no date is stored | n/a |
| TD6 | A vague expression gives no date | Correct today |
| TD7 | The said day is never a start or an end | Fails |
| TD8 | Short month names are read ("Mar 2021") | Fails |
| TD9 | A month or day with no year gives no date; the year is never guessed (WP-6) | Refused by the classic checker today |
| TD10 | Clock time and zone are out of this work (WP-8). They stay word for word in the said-date text (32 of 32 clock times, 1 of 1 zone, ETA-1), so a later step can read them without loss. B2b's whole-day dating in a named zone is not reopened | Not read |

## 4. ENG-WR-05: entity identity, corrections, measurements

| No. | Rule | Baseline |
|---|---|---|
| I1 | A description ("my sister", "the hospital") belongs to the speaker who said it | Two speakers' "my sister" are one entity |
| I2 | A bare first name matching more than one known person is held | Correct on base 2 |
| I3 | "We", "he", "she", "they" stay unresolved | Correct |
| I4 | A registered alias resolves | Correct |
| R1 | "I meant X, not Y": the fact with value Y in the same slot is corrected to X through the existing correction function | 0 of 2 |
| R2 | "Actually, I don't …": the matching fact is retracted | 0 of 2 |
| R3 | A corrected date replaces the date, not adds evidence | Lost |
| R4 | A correction with no single matching fact is held | Held |
| R5 | A later statement is a correction only when it carries correction words; otherwise a different value is a replacement or a conflict, handled by the state engine (WP-10) | n/a |
| M1 | A point-in-time measurement ("haemoglobin 9.2 on 13 January") is stored with the existing fact type `observation`, the measured day as its event time, the number and unit in its object **[A9] exactly as said** ("9.2 g/dL" stays "9.2 g/dL"; no unit is converted and no value normalised unless a separately authorised step adds it). No new table or column. Built after WR-C, with a vocabulary entry and the adapter sending it as a point in time (WP-9) | Stored as a state today |

## 5. ENG-WR-06: chat integration and routing

| No. | Rule | Baseline |
|---|---|---|
| K1 | The writer runs when a chat closes, through a hook the layer registers; the engine imports no layer | No close hook |
| K2 | A failure of the writer changes nothing and can be retried | Holds for the helper |
| K3 | Facts are shown to the answering model as their original sentences with dates, never as paraphrase | Benchmark only |
| K4 | A question the router sends to the state path is answered from the state engine, with the sentences beside it | No caller |
| K5 | A question with a date and no slot goes to ordinary memory | 11 of 12 |
| K6 | The helper's notes are a chat handover summary only, never shown under the label "noted fact" (WP-11). Facts reach the answering model only through the writer and the shared checker | Fails (H2, H3) |
| K7 | Chat starts using the structured facts only after the fair-data test (WP-12) | n/a |

## 6. ENG-WR-08: steps and order

Each step is one increment in the B1 to B5 manner: specification section frozen, tests first, deliberate breakages, one commit, Manj's sign-off. **None is authorised.** All on `engram-core-redesign`, after the end-to-end test commit (D4) and the workflow commit that makes GitHub test the branch.

| Order | Step | Content | Moves | Touches | End-to-end cases expected to turn (forecast) |
|---|---|---|---|---|---|
| 0 | Real-model check (read-only, before WR-C is built; not authorised) | A small labelled set; a real writer model proposes the word and the dates with their roles; count how often each is right. A WordNet-widened cue list can be measured in the same run (`wr_probe.py` part M) | New measure | Nothing in the repository | None |
| 0 | Freeze | Done 13 Nov 17:15 in the Project. Committed to `docs/specifications/` with its freeze record on the branch, on his word, once push access exists | | Documentation | None |
| 1 | WR-A | The gate is told who the people are (S1) | T2: 0 to 20 | `engram_structure.py` | None |
| 2 | WR-B | Dating: TD1 to TD9; one fact may carry a start and an end **[A2]** | T6: 0 to 17 of 22; T7: 30 to 40; T8: 7 to 1 | `engram_structure.py`; the classic back end's proposal and checker (`fact_validator.py`), to carry an end | C02, C03, C04 (base 2), C06b |
| 3 | Store reservation | One migration step adding the two empty tables (1.5, 1.6). Nothing writes to them. **[A10]** see below | None (structure only) | `engram_knowledge/schema.py`, `migrations.py` | None |
| 4 | WR-C | The proposal gains a word; several proposals per sentence; the record carries the word; filed through the classic back end | T9: 2 of 11 upward; T10: 0 to 3 | Writer prompt, `StructureLayer.file` | C01, C05, C08, C09, C10, C11 |
| 4a | Adapter event list (D8) | The adapter counts every vocabulary word typed as an event; ERC adapter breakage suite run | C12 | `erc_overlay/knowledge.py` | C12 (base 2 and classic) |
| — | Gate 1, then ERC B6 resumes (D9) | `engram-core-redesign` and `erc-adapter-1` merged into a temporary integration branch; full suite, all breakage suites, end-to-end test and probes. Never into `erc-adapter-1` or `main` | | | |
| 5 | WR-D | Checker additions S3 to S6. The injected-instruction scan S10 is **its own increment** after WR-D **[3R4]** | T4 down | `fact_validator.py`, shared | None expected |
| 6 | WR-E | Corrections R1 to R5 wired to the existing function | T12: 0 upward | Writer, state engine caller | None |
| 7 | Measurements (M1); vocabulary table filled (1.6) | Each its own step, after WR-C | | Vocabulary, adapter (D8) | None |
| 8 | WR-F | Chat integration K1 to K7, after the fair-data test | T16, T17 | `engram_chat.py` hook; reading path | None |
| — | Graph extension | Filling the relationships table (1.5), only after the writer is stable (requirement 1; order agreed 13 Nov 13:03). Not moved forward | | Its own specification step | None |

### 6.1 [A10] The migration in step 3

It follows the store's existing mechanism (`migrate` in `engram_knowledge/migrations.py`), which already behaves as follows; the step adds one entry to it.

| Point | Rule | Already true of the mechanism? |
|---|---|---|
| Versions | From version 3 to version 4. The step only creates the two new tables and their indexes | New step |
| Existing database **[R4]** | Every pre-existing table, row, check and index is unchanged. **What is compared:** for every table and index that existed before the step, its definition as stored in `sqlite_master` (text compared exactly), and every row of every such table, read in primary-key order and compared value by value; the layer-1 tables (`sentences`, `chats`) are included. **The one allowed difference:** `knowledge_meta.schema_version` goes from 3 to 4. **Not compared:** the database file's raw bytes, page layout and free space, which SQLite may change without changing any data; only the two new tables and their indexes may be new objects | To be tested |
| Fresh database | Created directly at version 4 with all tables | Yes, from the schema |
| Run twice | The second run does nothing: the stored version is already 4 | Yes |
| Fails part-way | The whole step is one transaction; on any failure nothing is changed, the version stays 3, and the reason is given | Yes |
| Recovery | Forward only: there are no backward steps. A copy of the database taken before the step is the way back, as for every earlier step | Yes |
| Newer database than the code | Refused before anything is changed | Yes |

### 6.2 Tests added by Amendments 1, 2 and 3

| For | Test |
|---|---|
| A1 | A sentence whose word is "other" stores a record with the gate's type and the outside-vocabulary mark; the state engine and an ERC rule never see it |
| A2 | **[R3] Checked in the stored record itself, not only in the proposal:** after filing, the `knowledge_records` row is read back and its `valid_from` and `valid_to` compared with the expected days, and the request the adapter builds is checked too (a stated start and end labelled stated). "From A to B" gives one record with both dates; "since A" a start only; "until B" an end only; "from A" with no end a start and no end; "on D" (an event word) an event date. Forecast: classic C04 in the end-to-end test turns once its hand-written proposal carries the stated end |
| A3 | Writing a link to a missing or erased end is refused; deleting a sentence, erasing a fact and deleting an unused entity each remove exactly the links resting on them; a supersession leaves its UPDATES link and both facts; the whole-table check finds zero dangling links |
| A4 | Filing a supporting sentence creates one `record_evidence` row and no relationships row; writing a sentence-to-fact supports link to the new table is refused |
| A5 | A relationship with no basis sentence and no rule or review named is refused |
| Am. 2 R1 | A vocabulary record: `predicate` is the word, `metadata.vocabulary = in`, `metadata.wording` is base 2's wording. An outside record: `predicate` is base 2's wording, `metadata.vocabulary = outside`, `metadata.wording` the same wording. No predicate starts with or contains a marker. The state engine and the adapter skip the outside record because of `vocabulary = outside`: a deliberate breakage that makes them read the predicate instead must be caught |
| Am. 2 R2 | RELATES_TO provenance, explicitly: one with a stated sentence as `basis_sentence` is accepted; one with no basis sentence is refused; one whose `method` names a model judgement or a similarity score, with or without a sentence that does not state the link, is refused; deleting its basis sentence deletes it |
| Am. 3 3R1 | Every one of the nine combinations permitted in the new table is accepted; every other (relation, from, to) combination is refused, by the table's own check and by the code, each shown by a deliberate breakage that removes one of the two |
| Am. 3 3R2 | As in 1.5.2 |
| Am. 3 3R3 | A deprecated word stays readable on old records and is not offered to the writer; a word with `state_engine_approved = no` never reaches the state engine or an ERC rule |
| Am. 3 3R4 | No record carries a screened mark before the scan's increment is signed off |
| A6 | The scan's place is present and does nothing; no test names it as passing; the build report's line on it is checked |
| A7 | At the vocabulary step, every row agrees with the code's lists; one deliberate disagreement fails the step |
| A8 | "I work at Manipal" then "I work at Manipal" again: one record, two evidence rows. A different object: two records |
| A9 | "9.2 g/dL" is stored exactly as said |
| A10 | Each row of 6.1 |

### 6.3 The canonical baseline [reviewer's open point: 1,858 against 1,875]

Both numbers are right; they are two different states. Run on 13 November 2026 from two fresh copies of `1396805` (Python 3.13.18, without wordllama, spaCy or openai), with the per-test lists compared line by line:

| State | Passed | Failed | Skipped | Expected-fail | Tests listed |
|---|---|---|---|---|---|
| `1396805` as it is (`erc-adapter-1`) | 1,858 | 4 | 3 | 1 | 1,865 |
| `1396805` plus the end-to-end test (`engram-core-redesign` after its first commit, D4) | 1,875 | 4 | 3 | 14 | 1,895 |
| Difference | +17 | 0 | 0 | +13 | +30 |

All 30 extra entries are in `tests/test_engram_to_erc_end_to_end.py` (17 pass, 13 marked expected-fail); no other test changed result. The four failures are the same four in both, and are exactly the four in `.github/known-test-failures.txt`. **Canonical baseline:** for `erc-adapter-1`, the first row; for `engram-core-redesign`, the second row, from its first commit on. Every later build report on the branch is measured against the second row.

## 7. Not proven

- Every measurement so far used ideal hand-written proposals; none shows how a real writer model chooses the word.
- Whether ERC improves answers for a real user is unmeasured.
- SNOMED CT's terms for a public repository are unchecked.

## 8. What still needs Manj's word

| Item | Status |
|---|---|
| D1 to D10, WP-1 to WP-15 | Decided |
| Amendment 1 (A1 to A10) | A1 decided by him (16:39); A2 to A10 written as precision rules and tests |
| Amendment 2 (R1 to R4) | Given by him (16:44); written in |
| Amendment 3 (3R1 to 3R4) and the baseline | Given by him (17:15); written in; baseline reconciled by a run |
| The real-model check | Not authorised. Kept before WR-C is built: if its result needs WR-C's rules changed, that is a numbered amendment with his word |
| Push access for this session to `manjunathhari/erc` | Not granted |
| Creating the branch (handover step 4), the test commit (step 5), the workflow commit (step 6) | Each needs his word |
| Freeze of this draft | **Given, 17:15** |
