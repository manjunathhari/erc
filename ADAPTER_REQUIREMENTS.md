# Engram → ERC adapter: requirements (second pass, 9 November 2026)

## Why this document exists

The MemoryAgentBench test (arms A–E, 32K) showed C − B = +1 on single-hop and −3 on multi-hop, which the
protocol read as "ERC adds no value". A second pass over the code and the per-question logs found that ERC's
verdicts were correct wherever ERC was given a well-formed input, and that the bridge (`engram_erc_bridge.py`)
failed it in three places. This document fixes those three as requirements, adds the two things the bridge
never attempted (always-on preferences, real dates), and defines how the unit is tested.

Findings the requirements rest on (all reproducible from `kit_tools/mab_cr.py` output and the writer cache):

| # | Fault in the bridge | Evidence | Requirement |
|---|---|---|---|
| F1 | Version key = sentence template with the object blanked. Any wording difference splits one fact into two groups, so ERC never sees the conflict. | 49 of 100 single-hop questions had a one-version group although a second version existed (e.g. "power forward → basketball" and "→ rugby" in different groups). Regrouping by (entity, relation) raised ERC-current-equals-gold from 67 to 93 of 100. | R1, R2 |
| F2 | The whole noun phrase is the subject ("The capital of Italy"), so the graph has no edge from `Italy`. | Multi-hop: gold reachable from the question's entities 31/100 with the bridge schema, 73/100 with entity/relation/value, same facts. 20 of 41 both-wrong questions had no answer in context. | R1, R5 |
| F3 | ERC marks a fact superseded; the bridge then appends Engram's raw search excerpts, which contain the superseded sentence. The `clean=True` filter exists but only arm E uses it. | 17 of 100 multi-hop arm-C replies cite a superseded fact; 12 of them are wrong. 33 of 100 on single-hop. | R6 |
| F4 | Serial numbers stand in for time; intervals are open, so ERC can only ever say `POTENTIAL`. | `_temporal_relation` returns UNKNOWN for open intervals by design. P1 already stores `valid_from`/`valid_to`. | R3 |
| F5 | Preferences are ordinary records found by search; search cannot find them because they rarely resemble the question. | LongMemEval preference 9/28. `profile_section()` exists in the bridge but never entered the measured path. | R7 |

ERC itself: 461/461 own tests; 23 adversarial cases (disjoint intervals, polarity flips, non-functional
predicates, duplicates, unicode, 2,300 ungrouped propositions in 3.8 s, cycles, dangling edges, naive datetimes)
all behaved by design. ERC does **not** normalise strings and treats open intervals as unknown; both are the
adapter's responsibility.

Findings from building and breaking the unit (adapter + `tests/test_erc_adapter.py`, 21 cases, all pass):

| # | Finding | Effect | Where it is handled |
|---|---|---|---|
| F8 | Base 1: `ChatMemory.find()` raises `ZeroDivisionError` (`engram.py:358`, `avg_ep`) when chats have been closed but none indexed yet (`ep_dates` set, `ep_len` empty). | Any search on a memory whose chats were all closed with `sleep=False` crashes. | Engine fix: guard `len(self.ep_len) == 0`. Not an adapter matter. |
| F9 | P1's forget cascade invalidates the deleted fact but does not reinstate the fact it had superseded. | Forget "Asha lives in Delhi" → "Asha lives in Pune" stays `superseded`; nothing is current. | Adapter: a P1-superseded fact whose `replaced by` rival is gone is reinstated (logged `p1_supersession_reinstated`). Base 2 should un-supersede on cascade. |
| F10 | Base 2 files a restated sentence as extra evidence on the existing fact, so the fact keeps its first date. | "I like jazz" → "no longer" → "I like jazz" again: the June restatement is swallowed and the April retraction wins. | Adapter reasons per **statement**: one ERC Proposition per supporting sentence with that sentence's date; a fact is current when any of its statements is. This also makes "Pune → Delhi → Pune again" come out right. |

Consequence for R3/R4 below: propositions are per statement, not per fact, and the adapter derives each fact's validity
**intervals** from ERC's pairwise verdicts rather than trusting P1's `valid_to` (which F6 and F10 both make unreliable).

## Scope

The adapter sits between P1 (the knowledge store, where base 2's structure layer files facts) and ERC. It reads
P1 and the sentences; it writes nothing (same contract as `erc_overlay`). Its output is the text handed to the
answer model. The engine (base 1), the structure layer (base 2) and ERC are unchanged.

```
sentences (P0) ──► structure layer (base 2) ──► P1 records ──► ADAPTER ──► ERC ──► ADAPTER ──► context
                                                                     ▲                        │
                                                        Engram search hits (sids) ─────────────┘  (gated, R6)
```

## Requirements

### R1 — Proposition schema: entity / relation / value
Every P1 fact becomes one ERC `Proposition` with
`subject = entity` (the thing the fact is about), `predicate = relation` (a short canonical name: `capital`,
`lives_in`, `likes`), `object_value = value`. Never a noun phrase as subject, never a sentence template as predicate.
The relation comes from a fixed table of sentence patterns (writer output → relation); an unmatched sentence keeps
base 2's version key as its relation, so nothing is lost, it is only less linkable. The table is data, versioned,
and grows with observed misses. The value is copied from the sentence (base 2 rule) and then normalised (R2).

### R2 — Normalisation is the adapter's job
Before anything reaches ERC: lower-case, strip punctuation and diacritics, drop articles, strip the pattern's
own carrier words from the value ("the country of Italy" → "italy"). Entities are resolved through P1's
`entities`/`entity_aliases` so "Asha", "asha" and a stated alias are one subject. ERC compares strings exactly;
anything the adapter does not normalise is a missed conflict.

### R3 — Real time, closed intervals
`valid_time.start = valid_from` (the day the sentence was said, from P1), `valid_time.end = valid_to` when P1 has
it. For a fact still active at query time, the adapter closes the interval at `as_of` (the question's date, or
now) exactly as `erc_overlay/knowledge.py` does, so two live values overlap and ERC reports `DEFINITE`. Serial
numbers are never used as time. Two facts said on the same day with different values are a conflict; the one
with the later `recorded_at` is newer, and the adapter says so in the context rather than hiding one.

### R4 — Grouping and functional predicates
Propositions are grouped by (entity, relation); `find_contradictions` runs per group with that relation declared
functional. A relation is functional unless listed as multi-valued (`likes`, `speaks`, `owns`, `visited`, `works_on`
and the preference relations). Multi-valued relations still get polarity checks (R7). From ERC's contradictions
the adapter derives `superseded[old] = newest` within each group. P1's own `status='superseded'` is merged in for
**functional** relations. For **multi-valued** relations it is overridden and logged, because of finding F6 below:
base 2's version key ("i like _") treats "I like coffee" and "I like tea" as two versions of one fact and supersedes
the first. Until base 2 learns which relations are multi-valued, the adapter is the only thing standing between
that rule and a vanished preference.

Two further base-2 findings from the adapter's smoke test (both reproducible in `tests/test_erc_adapter.py`):

| # | Finding | Effect | Where it is handled |
|---|---|---|---|
| F6 | Structure layer supersedes by sentence template, so a second preference replaces the first in P1 (`status='superseded'`). | "I like filter coffee" said twice disappears when the user says "I like window seats". | Adapter R4 override; base 2 should take a multi-valued list. |
| F7 | A negated sentence ("I no longer like X") is sent to the review queue by P2's negation rule, so a retraction never becomes a fact. | Preferences can be added but never retired. | Adapter reads polarity-false review items as `polarity=False` propositions (shown to no one; used only so ERC can retire the earlier claim). Base 2 should file retractions as facts with polarity. |

### R5 — The walk is over ERC's graph
Current facts (not superseded, not invalidated, not needs-review) become `KnowledgeEdge(entity → value,
provenance=relation)` in ERC's `DomainKnowledgeGraph`. The walk starts from entities named in the question (longest
match first) and from entities of facts whose sentence Engram's search returned (seeds), follows edges up to
`hops` (default 4), and never expands a hub (the speaker) wholesale. Values that are also entities continue the
walk; literal values (numbers, dates) stop it. Each reached fact is shown as its **original sentence with its date**,
never a paraphrase.

### R6 — The gate: ERC's verdict governs everything the model sees
No sentence whose fact ERC (or P1) marked superseded reaches the context, by any route: not from the walk, not
from Engram's excerpts, not from the profile. The excerpt step filters by sentence id against the superseded set
before budgeting (this is arm E's `is_superseded_ref`, made unconditional). Exception: a question that asks about
the past ("in 2024", "before", "used to") sets `as_of` to that time and the gate evaluates against that date, so
history is reachable on request and only on request. A sentence that carries no fact (small talk, unparsed) is
never filtered — the gate only acts on facts it knows about.

### R7 — Preferences: always-on profile, not search
Facts with `fact_type='preference'` (and plans/goals, as a separate block) form a profile slice placed **first** in
the context, selected by recency and category, never by similarity to the question. Rules:
- polarity: "no longer / stopped / don't anymore" is the same claim with `polarity=False`; ERC's
  `OPPOSITE_POLARITY_SAME_CLAIM` retires the earlier one (R4 still applies: multi-valued, so no value conflict);
- repetition is evidence weight: a preference stated n times ranks above one stated once (count of P1 evidence rows);
- a preference is never superseded by a different value (liking tea does not end liking coffee);
- the slice has a fixed token budget (default 15% of the context); when it overflows, lowest weight drops first;
- the slice is omitted entirely when the memory holds no preferences, so there is no empty header.

### R8 — Budget and order
Context = [profile slice (R7)] + [current linked facts from the walk (R5), as sentences] + [gated Engram excerpts
(R6)], in that order, within one total token budget (default 4,000, same as base 1). The facts section has its own
cap (default 50% of total) so excerpts always get room. When the walk reaches nothing and there are no preferences,
the context is byte-identical to base 1's — the adapter can only add, never subtract from base 1 except through R6.

### R9 — Explainability and logging
For every fact shown, the adapter can return: entity, relation, value, source sentence ids, valid interval, and if
superseded, by which fact and on what grounds (ERC reason code). For every fact *withheld* by R6, the same plus the
newer fact that replaced it. This is the material for a review UI and for arm-level diagnostics; the test harness
records per question: facts shown, facts withheld, superseded facts that leaked (must be 0), tokens per section.

### R10 — Writes nothing, deletes nothing
The adapter never writes to the database. It needs no open or forget step: after `forget_sentence`, P1's cascade
invalidates the record and the next adapter call does not see it. Supersession is computed, never persisted by the
adapter (P1's structure layer already persists its own). This keeps the adapter restart-safe and keeps the
"nothing stated is ever thrown away" guarantee where it is enforced today.

### R11 — Model-free until the last step
The adapter calls no model. The writer (sentence → entity/relation/value proposal) runs at chat close in the
structure layer, under base 2's rules; ERC and the adapter are deterministic. Same memory + same question + same
`as_of` ⇒ byte-identical context.

### R12 — Failure behaviour
A record with no resolvable entity, no parsable date, or a relation not in the table degrades gracefully: it keeps
base 2's key as relation, gets `valid_time=None` (ERC then says POTENTIAL, which the adapter treats as supersession
only when `recorded_at` order is unambiguous), and is still shown. The adapter never raises on data; it raises only
on a schema version it does not know.

## Acceptance tests

1. **Unit (combo, no model):** three dated versions of one fact → context shows the newest only; `as_of` between
   versions shows that version only; `forget_sentence` on the newest → the previous becomes current again on the next
   call without any adapter state. Polarity flip retires a preference; two different preferences coexist. Same-day
   conflict is shown with both values and "newer" marked. Alias and case variants are one entity. A sentence with
   no fact passes the gate untouched. Superseded sentences from search never appear (assert leak count = 0 over the
   whole benchmark).
2. **Regression:** on `mab_facts_gpt-4o-mini_32k.json`, single-hop ERC-current-equals-gold ≥ 93/100 (2 benchmark
   gold conflicts excluded); multi-hop gold reachable from question entities ≥ 70/100 before excerpts.
3. **Synthetic 500 (this repository's lab):** 150 preference, 150 multi-hop (2–4 hops), 200 single-hop/temporal
   with updates and distractors, ingested through a real `ChatMemory` and the structure layer. Report per category:
   gold in context, stale version leaked, mean tokens — adapter path vs bridge path on the same memory.
4. **Live (needs an answer model):** LongMemEval preference 9/28 → ≥ 20/28; MAB MH 32K answer-in-context 79% → ≥ 90%;
   arms E and D on MH. Only after 1–3 pass.

## Out of scope for this adapter

ERC rules and derivation (`derives` in Supermemory's terms), the review UI, write-back of ERC verdicts to P1,
and changing base 2's writer. Each is a separate decision once the adapter's numbers are in.
