# Hard 100 with an answer model in the loop (10 November 2026)

Generator: `kit_tools/synth_hard100.py`. Memory: real `ChatMemory` (light search) + base 3 structure layer + `engram_erc_adapter`.
**Answer model: Claude Haiku** (ten batches of ten, prompt in the generator: answer only from the excerpts, later date wins,
"not mentioned" if absent). **Judge: Claude Fable 5.1** — automatic SubEM first, then every disagreement read against the
context the model saw. Per-question records: `judged_final.json` (run 1 answer, judge verdict, run 2 answer).

## The set (100 questions, built to break the unit)

| cat | kinds (4 each unless noted) |
|---|---|
| single / temporal (40) | same-day conflict; update inside one month then "in May 2024"; three versions, ask the middle month; **"before moving to X" with no date**; count update inside a multi-valued relation (2 cats → 3 cats); never stated → "not mentioned"; **look-alike names** (Rhea / Rhea Kapoor); Pune → Delhi → Pune restated; three employers, ask current; paraphrased question |
| multi-hop (30) | plain 3-hop; hop-2 updated; **both hops updated**; 4-hop to state with update; question names no entity ("my brother's employer"); chain with a missing link → "not mentioned" |
| preference (30) | retract then re-like; retract + **a second speaker likes the retracted thing**; **double negation** ("I don't think I will ever stop liking"); stated 3× vs 1×; like + dislike, "what to avoid"; 15 indirect recommendations; 5 "only a retraction stands" → "no" |
| noise | 600 small-talk lines across 18 months |

Ingest: 849 sentences, 249 filed, 245 accepted, 4 uncertain (the four look-alike full names — the resolver would not merge
them with the short names, which is the right call). Mean context handed to the model: 674 tokens.

## Results

| | run 1 | run 2 (after two fixes) |
|---|---|---|
| automatic SubEM | 87 / 100 | — |
| after judging | **91 / 99** (1 excluded) | **99 / 99** |
| single / multi / pref (run 1, judged) | 32+4 / 29 / 30 → 36/40, 29/29*, 30/30 | 40/40, 29/29*, 30/30 |
| stale sentence in any context | 4 (all look-alikes, correct different-person sentences) | 0 of concern |

\* #50 excluded: the generator gave the user five "My brother is …" statements; ERC kept the latest, so the question has no
single gold. Not a unit failure — the same trap the 500-run generator fell into twice.

Judge overrides of SubEM (run 1): #71 "Upma", #80 "Strong filter coffee", #85 "Small hatchback", #96 "badminton" are all
preferences the user holds and fit the question; gold was too narrow. Counted correct.

## The eight real misses and what they were

| # | kind | model said | cause | fix |
|---|---|---|---|---|
| 12–15 | before-no-date | not mentioned | **Adapter**: history was opened only by a dated question; "before moving to Pune" has no date, so the superseded value was withheld (R6 working as specified, too narrowly) | `asks_history()`: before / previously / used to / earlier / formerly / first switch on an "Earlier versions" block for the reached groups, each with the dates it held |
| 24–27 | look-alike | the look-alike's city | **Context layout + small model**: the unit was right (two entities, both lines present, ERC kept them apart), but the raw search excerpt "Rhea Kapoor lives in Pune" sat unlabelled under the facts and Haiku applied "later date wins" across two people | Excerpt block now headed "raw excerpts, not checked facts; a different name is a different person" |

Run 2 re-asked exactly these eight with the new contexts: 8/8.

## What held under attack (no misses)

Same-day conflicts (newest recorded wins); update inside the month and the month asked for; middle period of three versions;
count update inside `owns` (the count rule); never-stated → "not mentioned"; restatement after an intervening value;
three employers; paraphrased questions; every multi-hop kind including both hops updated and the hub-relation question;
retract → re-like; a second speaker's taste did not leak into the user's profile; double negation was not read as a
retraction; repetition ranking; "what to avoid"; all five "only a retraction stands" → no.

## Caveats

Haiku through this lab's sub-agents, not the API with temperature 0, so run-to-run variation is possible; the writer is
the generator (perfect filing); light search design. The unit's behaviour, which is what was under test, is deterministic.
