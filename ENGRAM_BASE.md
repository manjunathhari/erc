# Engram base 1 (frozen 8 November 2026)

The memory side of Engram is frozen at commit 41ea34a. Later work (the ERC structure layer) is measured against this base and must not change it.

## What is frozen
- **Search:** the tested design, `open_memory(path)` on main (four-channel network search, saved networks trained on LoCoMo only).
- **Memory budget:** 4,000 tokens (`Settings(retrieved_tokens=4000)`).
- **Answer prompt:** v2, `vps_kit.ANSWER_V2`, with up to 400 reply tokens. Only the text after the last "Answer:" is the answer (`vps_kit.final_answer`).
- **Answer model for benchmarks:** GPT-4o (gpt-4o-2024-08-06), temperature 0, seed 7. The judge is GPT-4o with the official LongMemEval prompts.

Reproduce on LongMemEval:

    python kit_tools/lme_gpt4o.py --data longmemeval_s_cleaned.json --save results --start 100 --n 0 --context-tokens 4000 --prompt v2

## Measured (LongMemEval-S cleaned, GPT-4o answers and judge)
- Held-out questions 101–470, 4,000 tokens, prompt v1: **79.2%** (95% interval 74.9–83.2). That is ahead of Zep (71.2%) and level with Supermemory (81.6%), which use far less context (about 1.6K and 720 tokens).
- Development questions 1–100: prompt v1 76.0% → **prompt v2 82.0%** (paired, won 8, lost 2). Temporal went from 23 to 27 of 33.
- Preference: 9 of 28 with v2 (Zep about 57%). The prompt can't fix this, so it is left to the ERC layer.
- v2 has not yet been run on all of 101–470; the 79.2% held-out score is for v1.

## Known weaknesses left for the ERC layer
- Preference: the user's stated tastes rarely sound like the later question, so search misses them. The fix is an always-on profile.
- Remaining temporal and counting errors where every answer line was shown.
- Later pieces of multi-part answers rank low (search coverage; a reranker is the Engram-side idea).
