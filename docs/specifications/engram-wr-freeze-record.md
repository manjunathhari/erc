# Freeze record: Engram writing layer contract, version 1

| Item | Value |
|---|---|
| Frozen document | `claude/engram-wr-contract-v1.md` (Draft 3.3: Draft 3 with Amendments 1, 2 and 3) |
| SHA-256 | `1f4ca01964498769dd727c2ec8f3715782ea06f59cce494fd4e1a9ae97a243d6` |
| Frozen on | 13 November 2026, on Manj's word at 17:15 IST |
| His words | "four clarifications, reconcile the baseline, and then freeze the contract" |
| Done in that order | (1) the reviewer's four clarifications written in as Amendment 3 (3R1 permitted endpoints; 3R2 idempotent relationships; 3R3 vocabulary governance, no bulk import; 3R4 injection detection as a separate gate); (2) the baseline reconciled by a run, `claude/engram-baseline-inventory-r1.md`; (3) this freeze |
| Line of drafts | Draft 1 `f4ec5e1d…15c3de`; Draft 2 `c051df2a…a6f4c8`; Draft 3 `c2ff83e2…4b0c69`; Draft 3.1 `940228e4…ca7300`; Draft 3.2 `59339814…5573cb2`; version 1 (Draft 3.3) above |
| Reviews it absorbed | Reviewer's audit of Draft 3 (16:34; A1 to A10); Manj's R1 to R4 (16:44); reviewer's four clarifications passed on by Manj (17:15). A reviewer's view is a recommendation; each change entered on Manj's word |
| Repository | Unchanged at `1396805a183733fbffdc146e637f104299858589`. Nothing committed, pushed or tagged |

## What the freeze means

- The text above is fixed. Any change is a numbered amendment, with Manj's own word, recorded here and in `claude/engram-wr-record.md`.
- The freeze authorises nothing to be built. Tests in the repository, implementation, commit, push and tag each need his separate word, step by step, in the order of the contract's section 6.
- The real-model check stays before WR-C is built (it is not authorised yet). If its result means WR-C's rules must change, that change is a numbered amendment to this contract with his word.
- When the branch exists and push access is granted, the frozen file is committed to `docs/specifications/` with this record, byte for byte, as for B2a to B5, on his word.

## Tag details for later (he creates tags himself)

To be used once the frozen file is committed on `engram-core-redesign`; the commit is not yet made, so the commit line is left open.

| Field | Value |
|---|---|
| Tag name | `engram-wr-contract-v1` |
| Commit | the documentation commit that adds `docs/specifications/engram-wr-contract-v1.md` (to be filled in) |
| Title | Engram writing layer contract, version 1 (frozen) |
| Notes | Frozen 13 November 2026. Sentence-to-fact contract for the base 2 writer filing through the classic back end; additions-only store reservation (relationships table with nine permitted endpoint combinations, vocabulary table with governance columns); injection scan reserved as a separate gate, not claimed until built; canonical baseline 1,875 passed, 4 known failures, 3 skipped, 14 expected-fail. SHA-256 1f4ca01964498769dd727c2ec8f3715782ea06f59cce494fd4e1a9ae97a243d6 |
