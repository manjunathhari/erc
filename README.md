# Engram

A layered memory architecture modelled on how the brain separates storage from retrieval. Content stays in a permanent record, a small index holds pointers, and reads call no model until the final answer.

This repository holds the Engram engine, ported from `manjunathhari/Engram` (main at `ee68079`), with its layers added around it one at a time. The engine's code is unchanged apart from the two layer steps described under "How layers attach". Each layer depends on the engine; the engine imports no layer. Layers so far:

- **P1, the knowledge store** (`engram_knowledge/`, `engram_records.py`), taken from the same commit.
- **P2, learning from sentences** (eight more files in `engram_knowledge/`), from the same commit. It uses P1; P1 uses nothing from P2.
- **P3 to P5, state over time** (seven more files in `engram_knowledge/`), from main's state engine rather than the separate P3, P4 and P5 packages, which do the same work under other names. They use P1 and P2; neither uses them.
- **P6, learning from use** (`engram_p6/`, and the feedback bridge `engram_knowledge/feedback.py`), from the same commit, still in shadow mode: it learns scores, but search does not read them.
- **P7, carrying learned intelligence between installations** (`engram_p7/`), from the seven P7.1 to P7.7 packages of the consolidated bundle, joined into one package.
- **ERC, the reasoning core** (`engram_erc/`), ERC-4.0 General Core (package 0.4.1; it holds ERC 1.x, 2.x and 3.x with the general names), and **the overlay that connects it** (`erc_overlay/`), which reads P1 to P5 and stores nothing.

This is a research prototype. Do not put patient or other personal information in it: it has no access control or deletion.


## Opening a memory

```python
from engram_memory import open_memory
memory = open_memory("my_memory.db")
```

This uses the design that passed the LoCoMo final test and the LongMemEval test: four small channel networks trained only on LoCoMo conversations 0 to 4, stored as plain numbers with a checksum in `engram_networks.npz`, read by `engram_networks.py` (no pickle, so loading cannot run code). It gives the model exactly the same text as the tested runs. `design="light"` is the older search with no extra libraries; it did worse. `ChatMemory` on its own is unchanged.

## Layout

- `engram_knowledge/`: the knowledge layers (P1 to P5). See below.
- `engram_p6/`: learning from use (P6).
- `engram_p7/`: carrying learned intelligence between installations (P7).
- `engram_erc/`: the reasoning core, ERC-4.0 General Core (standard library only; its own README, release notes and integration notes).
- `erc_overlay/`: ERC over the knowledge layers.

- `engram.py`: the memory system.
- `vps_kit.py`, `bench.py`, `final_config.json`: the test kit, run on the server next to Gemma.
- `sync_results.sh`: sends `results/` to GitHub and fetches kit updates.
- `results/`: the recorded benchmark outputs the regression tests replay; new test outputs from the server also go here.
- `kit_tools/`: a stand-in model for checking the kit, and the blind scoring sheet.

## Set up on the server

    sudo apt install -y python3-numpy git
    ssh-keygen -t ed25519 -f ~/.ssh/engram_deploy -N "" -C engram-vps
    cat ~/.ssh/engram_deploy.pub

Add that public key at GitHub: repository Settings, Deploy keys, Add deploy key, and tick "Allow write access". The key reaches this repository only.

    GIT_SSH_COMMAND="ssh -i ~/.ssh/engram_deploy" git clone git@github.com:manjunathhari/erc.git
    cd erc
    git config core.sshCommand "ssh -i ~/.ssh/engram_deploy"
    git clone --depth 1 https://github.com/snap-research/locomo.git

## Run the tests

If Ollama runs on the server itself, leave out `--url`. If it runs in Docker, find its internal address first, using your container's name:

    OLLAMA=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' YOUR_OLLAMA_CONTAINER)

Then:

    python3 vps_kit.py check --url http://$OLLAMA:11434/v1 --model gemma3:4b --tag g3
    ./sync_results.sh
    nohup python3 vps_kit.py answers --url http://$OLLAMA:11434/v1 --model gemma3:4b --tag g3 --sample 120 > answers.log 2>&1 &

To send results every 15 minutes while it runs:

    (crontab -l 2>/dev/null; echo "*/15 * * * * $PWD/sync_results.sh >> $PWD/sync.log 2>&1") | crontab -

Question types are interleaved, so a run can stop at any time and still leave a balanced set. Repeat the same command to continue.

Keep Ollama's port (11434) closed to the internet.

## Data and licence

Tests use [LoCoMo](https://github.com/snap-research/locomo) (Maharana et al., 2024), licensed CC BY-NC 4.0. The data is not stored here, but `results/` contains questions and short excerpts from it, under that licence. This repository's own code has no licence yet, so its rights stay with the author unless one is added.

## Regression tests

From the repository root:

    python3 -m pytest -m "not slow"

This takes under a second and needs no model. To also replay the benchmark and compare retrieval with the recorded baseline, clone `locomo` into the repository and install wordllama, spacy and scikit-learn, then run:

    python3 -m pytest

The baseline is in `tests/fixtures/retrieval_baseline.json`. If you deliberately change retrieval, rerun `python3 tests/record_baseline.py` and commit the new baseline with the change. Test data is made up or from the benchmark; never put personal data in the fixtures.

## How layers attach

The engine has two steps a layer can join, in `engram_chat.py`: `add_open_step(layer, step)` runs when a memory opens, and `add_forget_step(layer, step)` runs inside `forget_sentence`, before the commit, so a sentence and what rests on it are deleted together. The knowledge layer joins both when it is imported. Delete steps run in a stated order, lowest first: the knowledge layer at 10, P6 at 60, so P6 sees which facts the knowledge layer has just erased.

A layer also writes its name into the `engram_layers` table. If a memory holds a layer's data and that layer is not loaded, `forget_sentence` refuses and changes nothing, so a sentence can never be deleted while what rests on it stays. `tests/test_layers.py` checks this, and that the engine alone loads no layer and creates no layer tables.

Changes from the original, so the engine stays apart: the engine's three direct calls into the knowledge store became these steps; clearing P6 feedback and scores moved from the knowledge store's delete step into P6's own (`engram_p6/forget.py`), which clears what points at the deleted sentence and at every erased fact; `feedback.forget_refs` still names the same function; and `engram_knowledge/__init__.py` names only P1's parts. `state_reviews`, the decision table used by P5, stays in P1's schema (version 3), unchanged.

## Knowledge records

The knowledge store lives in `engram_knowledge/`: `models.py` (the records), `schema.py` (the tables), `database.py` (the store on Engram's own connection, and the integrity check), `entities.py`, `facts.py`, `evidence.py`, `migrations.py` and `serialization.py`. `engram_records.py` remains so older imports still work.

- **Checks in the database itself:** the tables refuse bad values and broken links even from code that skips the checks in `models.py`.
- **Values keep their type:** numbers, true or false and structured values come back as they went in.
- **Shared names:** two entities may have the same name or alias. A lookup then returns both, and nothing picks one.
- **Helper facts:** `link_helper_fact` gives a record the source sentences of a fact noted by `engram_facts.py`. The helper's text is never turned into a record.
- **Qualifying evidence:** a sentence can limit a fact without supporting or contradicting it. It never counts as support.
- **Export, import and backup** (`serialization.py`): an export holds personal content, so it is written for the owner only and never over a file; it carries a copy of each sentence its records cite and a checksum. Import adds everything together or nothing, and keeps a record only where the same sentence, word for word, is in the memory, so a sentence deleted after an export stays deleted. An export already made cannot be recalled. `backup` copies the whole memory, sentences included. The review queue is not exported.
- **Version 2:** an older database is brought up to date in one step, or left unchanged with the reason if its data breaks a new rule.

`engram_records.py` is a standard, typed record for knowledge, stored beside the sentences and always traceable to them. It is not used by search or answers, and nothing writes records automatically yet.

- **Four tables:** `entities`, `entity_aliases`, `knowledge_records`, `record_evidence`.
- **Names:** an entity is found only by its exact name or a stated alias, ignoring case and spacing. Similar names are never treated as the same. An alias needs a source sentence or must be marked manual.
- **Stated or inferred:** every fact must say which (`source_type`). There is no default, and answers about an entity show stated facts unless inferred ones are asked for. Accepting an inference does not turn it into a statement.
- **Status and checking are separate:** `status` is the record's life (active, superseded, disputed, retracted, needs_review, invalidated); `validation_status` is whether it was checked (pending, accepted, rejected).
- **Time:** `valid_from` and `valid_to` say when it was true; `recorded_at` says when Engram learned it.
- **Version check:** a database whose knowledge records are a different version is refused before anything in it changes.
- **Deletion:** if a source sentence is deleted, a fact with another supporting sentence is marked `needs_review`. A fact with no support left is `invalidated` and its content erased. Aliases from that sentence go too, and an entity nothing uses any more is removed.

## Entity resolution and fact validation

`engram_knowledge/` decides which entity a statement refers to and whether a candidate fact may be stored. Fixed rules decide; a language model can only propose. `engram_facts.py` is unchanged, and these records are not used by search or answers.

- **Accepted** goes to the knowledge store. **Uncertain** waits in the review queue, where it is not treated as knowledge. **Rejected** is not saved.
- **Names:** exact name or stated alias. "I" means the speaker. He, she and they are never guessed, and a similar name goes to review instead of being merged.
- **Checks:** the sentence holding the object must exist, contain its words, and use a word for that kind of fact. Possible negation, questions, hypotheticals, things said by the assistant, things reported by someone else and dates not in the source all go to review.
- **Deletion:** deleting a source sentence removes any review item that cites it.

These rules read words and cannot understand meaning, so accepted facts can still be wrong.

## Learning from sentences (P2)

- **Sentence pipeline** (`engram_knowledge/interpreter.py`, `learning.py`, `candidate.py`, `learning_queue.py`, from P2.1 to P2.3 with fixes): each stored message is split into sentences, each is labelled and judged (learn, review, ignore, or kept as said by the assistant), and kept sentences become envelopes tied to their sid and place in the message. Review envelopes join P1's one review queue. Nothing here writes a fact: that needs extraction (who, what and which), which is not built yet. On 200 held-out sentences labelled blind it agrees with the labels 146 times, against 78 for the original package; it still learns some small talk and sends too little to review (`results/p2_gate`).

P2 keeps no tables of its own: its review envelopes sit in P1's review queue, which P1's delete step clears, so P2 needs no open or forget step. `feedback.py` (P2.5) belongs to the P6 layer, since it writes to P6's event log.

## Temporal state and knowledge retrieval

`StateEngine` works out what is true of an entity, now and at any past date, from the stored facts each time. The state is never stored, so the facts and their sentences stay the only source of truth. The old `world_state` in `engram.py` is unchanged.

- A later value from the same speaker ends the earlier one. A different value from another speaker is a conflict with both kept, until one speaker updates or a person settles it.
- A correction marks the old fact superseded and keeps its evidence. A plan never becomes a state.
- An unstated date stays unknown; the date the sentence was said is shown separately as `first_said`.
- If a newer statement is waiting for review, the answer says so, because it may be out of date.

`KnowledgeRetriever` sits beside ordinary memory. Its router sends a question to the records, to `ChatMemory.find`, or to both, using fixed word rules, and every returned fact carries its original sentences. `context_for` does not use it, so answers do not change.

## Decisions (P5)

- **Decisions** (`StateEngine.settle`, from P5): a person's decision about two facts is recorded with reviewer, reason and the state before and after. An end date is never guessed. Version 3 of the store adds this table.

P3 to P5 keep only the decision table, `state_reviews`, which is part of P1's schema; P1's delete step removes a decision that quotes an erased fact, so these layers need no open or forget step. `kit_tools/knowledge_eval.py` is not brought over yet, because it reads an earlier research result that this repository does not hold.

## Learning from use (P6)

- **Feedback and learning from use** (`engram_knowledge/feedback.py`, `engram_p6/`): feedback goes into P6.1's event log only, without free text. P6 learns bounded scores from it, but nothing in search reads them yet (shadow mode). Deleting a sentence removes feedback and scores that point at it. P6 data is not part of the knowledge export; P6.6 has its own.

P6 writes its name into `engram_layers` whenever it creates its event or score tables. A memory holding P6 data therefore refuses a deletion unless P6 is loaded, so feedback can never outlive the sentence or fact it points at. Only the event log and the scores hold sentence or fact references; policy versions and saved bundles do not. P6's tests run on made-up data; it has not been measured on real use.

## Carrying learned intelligence (P7)

P7 moves what P6 has learned, never memories, facts or conversations: only context-level scores, as a checksummed package.

- **P7.1** packages a saved P6 bundle (`IntelligenceExporter`); **P7.2** turns it into portable context priors (`ContextPolicyTransfer`); **P7.3** checks it against the destination and never activates anything (`ModelCompatibilityValidator`); **P7.4** stages, activates, rolls back or deactivates it on the destination (`IntelligenceRestorer`); **P7.5** is a test harness for the whole move; **P7.6** applies an inherited prior with the destination's own scores, reordering candidates only (`DestinationIntelligenceAdapter`); **P7.7** compares rankings (`RetrievalBenchmark`).
- **First run on real data** (`tests/test_p7_end_to_end.py`): scores learned from real feedback in one memory, carried into a second and used there. The package holds no names, facts or sentence references; the destination's own sentences are unchanged; its P7 tables hold no sentence or fact references, so P7 needs no forget step; a prior for one context is not given to another. P7.3 passes with two warnings: the retrieval configuration is not applied, and the context key scheme is not verified.
- **What it does to search:** an inherited prior alone lifts every candidate by the same factor, so it changes no order. Order changes only when the destination has learned scores of its own. Nothing in search reads P7 yet.
- **One fix:** P7.1 and P7.4 set `row_factory` on the connection they are given, which is the engine's own, so after a restore every engine query returned named rows instead of tuples. They now read through `engram_p7/_rows.py`, which names columns per query and leaves the connection alone; a test checks this.
- The P7.5 and P7.6 tests loaded neighbouring stages by file path from the separate packages, including copies of P6; they now import from `engram_p7` and this repository's `engram_p6`. Their checks are unchanged.

## Reasoning (ERC overlay)

```python
from erc_overlay import Reasoner
reasoner = Reasoner(KnowledgeBase(memory.db))
reasoning = reasoner.reason("Asha", ruleset=rules, as_of=when)   # rules: an engram_erc RuleSet, or None for checks only
print("\n".join(reasoner.explain(reasoning)))
```

`engram_erc/` is ERC-4.0 General Core as delivered, with its 461 tests. It depends on nothing here. It contains every earlier ERC package: 1.1 to 1.9 built the reasoning, 2.0 to 2.9 judge and govern rule sets against adjudicated cases, and 3.0 to 3.9 apply governed knowledge to a case, watch events over time, compare with past cases and structure the options a reviewer decides between. `case_intelligence` runs those as one seven-stage pipeline. The 3.x and 4.0 layers are domain-general (case, activity, practitioner, reviewer); a field's own words come from a profile (`general` by default, `surgical` included), which never changes a decision. Every ERC 1.x file is byte-identical to 1.9, so the overlay works on it as it did on 1.9, and all repository tests give the same results as with 1.9. `erc_overlay/` is the only code that connects it:

- **`knowledge.py`** turns one entity's facts, and the facts about the entities they name, into an ERC request. Each fact takes its span from the state engine's own periods, so a conflict in P1 is a definite contradiction in ERC and a value replaced by the same speaker is history; a period still open is closed one day after `as_of`. Facts that start after `as_of` are left out. A text object becomes an entity id only when exactly one entity has that name. Stated facts are assertions, inferred ones hypotheses, and plans are left out. P1's single-valued slots are ERC's functional predicates. Each source sentence is one piece of evidence. The request id is a digest of the facts and rules used, so each result id is distinct.
- **`reasoner.py`** runs ERC's strategy and its evidence-aware evaluation, and `explain()` gives the result in plain lines with the original sentences under each conclusion.
- **Nothing is stored.** The overlay writes nothing to the database, so it needs no open or forget step: after a sentence is deleted, the next `reason()` does not see it. It leaves the engine's search results and connection as they were. `tests/test_erc_overlay.py` checks all of this, and the gaps found when ERC-1.9 was first fed real facts: `as_of` ignored, a P1 conflict seen only as a potential contradiction, text objects not joining their entities, and result ids that did not change with the rule set.
- **Not covered yet:** conclusions ERC derives carry no dates of their own, so a contradiction involving one stays potential; ERC applies only rules it is given, and none are written for real use; the overlay is not connected to Gemma or to answers, so nothing a user sees changes. The overlay uses only the ERC 1.x reasoning; feeding Engram's records into the 3.x/4.0 pipeline (`CaseIntelligenceRequest`) is the next adapter.

