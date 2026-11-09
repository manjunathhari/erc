# Engram → adapter → ERC: 500-question lab run (9 November 2026)

Generator and runner: `kit_tools/synth500.py`. Adapter: `engram_erc_adapter.py`. Spec: `ADAPTER_REQUIREMENTS.md`.
Unit tests: `tests/test_erc_adapter.py` (21). Raw rows per question: `seed7/rows.json`, `seed11/rows.json`.

## What was measured

500 questions per seed: **150 preference** (stable / retracted / repeated), **150 multi-hop** (2, 3 and 4 hops, half with a
mid-chain update), **200 single-hop** (current value after 0–3 updates, value at a past month, never-updated fact).
1,530 sentences per run (1,020 facts, 510 small-talk distractors) over 18 months of dated chats, ingested through a real
`ChatMemory` and filed through the base-2 structure layer by a deterministic writer that knows each sentence's subject and
object. No answer model: a question **passes** when the gold answer is in the context handed to the model **and** no stale
sentence is (for 270 of the 500 questions a stale sentence exists: the old city, the old employer, the retracted preference).

Three contexts are built on the same memory for every question:

| arm | what the model would read |
|---|---|
| base1 | `ChatMemory.context_for` — search only (the frozen base 1) |
| base2 | structure-layer walk, every version, + excerpts, no gate (what MAB arm B did) |
| adapter | `Adapter.context_for` — ERC verdicts govern profile, linked facts and excerpts |

## Base 3 rerun (10 November 2026)

Same generator, base 3 filing (`base3_seed7/`, `base3_seed11/`): ingest 1,020 filed / **1,020 accepted / 0 uncertain** (base 2:
970 / 50 uncertain — the retractions), adapter **100% / 100% / 100%**, stale 0/270, mean 2,596 tokens; base1 and base2 arms unchanged.

## Results, pass 2 (light search design; seeds 7 and 11 identical to the point)

| | base1 | base2 | adapter |
|---|---|---|---|
| **All 500** — pass | 19.6% | 27.4% | **100.0%** |
| gold in context | 186 | 355 | 500 |
| stale sentence shown (of 270 with one) | 113 | 220 | **0** |
| mean tokens | 131 | 1,390 | 2,589 |
| **Preference 150** — pass | 4.7% | 4.7% | **100%** |
| **Multi-hop 150** — pass | 13.8% | 50.0% | **100%** |
| **Single-hop 200** — pass | 36.3% | 26.3% | **100%** |

By kind (pass %): current 34 / 12 / **100**; temporal 6 / 0 / **100**; hop2 11 / 100 / **100**; hop2-updated 12 / 0 / **100**;
hop3 22 / 100 / **100**; hop3-updated 30 / 0 / **100**; hop4 4 / 100 / **100**; hop4-updated 4 / 0 / **100**; stable 47 / 49 / **100**;
repeated 6 / 6 / **100**; retracted 0 / 0 / **100**.

## How to read 100%

This is a **ceiling test of the unit's logic**, not a field estimate. The writer is perfect (it is the generator), the
sentences follow the relation table's patterns, and the pass criterion is "right fact present, stale fact absent", not an
answer model's accuracy. What it establishes:

- Given well-formed facts, the Engram store + P1 + adapter + ERC resolves versions, answers about the past on request,
  follows 2–4 hop chains through updates, keeps preferences always-on, retires them on retraction, and lets a restatement
  revive them — with **zero** stale sentences across 540 opportunities on two seeds.
- The same memory read by the arm-B path shows the stale sentence 81% of the time it exists; the base-1 path 42%.
- Base 2's walk reaches 100% on un-updated chains and 0% on updated ones: it has coverage but no verdict. The adapter has both.

What it does not establish: writer quality on real chat (the P2 gate and a 4B model), search quality (the tested design
needs WordLlama weights that this lab could not download), and answer-model behaviour. Acceptance test 4 in the
requirements (LongMemEval preference, MAB MH arms D/E) is the field test and still needs an API key.

## Things that broke on the way (all fixed in the adapter or logged against base 1/2)

See F6–F10 in `ADAPTER_REQUIREMENTS.md`: template key supersedes "I like X" with "I like Y" (F6); retractions never become
facts (F7); `find()` divides by zero when no chat is indexed (F8); forget does not reinstate the superseded fact (F9);
a restatement is swallowed as evidence and loses its date (F10). F8 is the only one the adapter cannot work around.
