# Engram

A layered memory architecture modelled on how the brain separates storage from retrieval. Content stays in a permanent record, a small index holds pointers, and reads call no model until the final answer.

This repository holds the Engram engine, ported from `manjunathhari/Engram` (main at `ee68079`), with its layers added around it one at a time. The engine's code is unchanged apart from the two layer steps described under "How layers attach". Each layer depends on the engine; the engine imports no layer. Layers so far:

- **P1, the knowledge store** (`engram_knowledge/`, `engram_records.py`), taken from the same commit.

P2 to P7 and ERC are not included yet.

This is a research prototype. Do not put patient or other personal information in it: it has no access control or deletion.


## Opening a memory

```python
from engram_memory import open_memory
memory = open_memory("my_memory.db")
```

This uses the design that passed the LoCoMo final test and the LongMemEval test: four small channel networks trained only on LoCoMo conversations 0 to 4, stored as plain numbers with a checksum in `engram_networks.npz`, read by `engram_networks.py` (no pickle, so loading cannot run code). It gives the model exactly the same text as the tested runs. `design="light"` is the older search with no extra libraries; it did worse. `ChatMemory` on its own is unchanged.

## Layout

- `engram_knowledge/`: the knowledge layer (P1). See below.

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

The engine has two steps a layer can join, in `engram_chat.py`: `add_open_step(layer, step)` runs when a memory opens, and `add_forget_step(layer, step)` runs inside `forget_sentence`, before the commit, so a sentence and what rests on it are deleted together. The knowledge layer joins both when it is imported.

A layer also writes its name into the `engram_layers` table. If a memory holds a layer's data and that layer is not loaded, `forget_sentence` refuses and changes nothing, so a sentence can never be deleted while what rests on it stays. `tests/test_layers.py` checks this, and that the engine alone loads no layer and creates no layer tables.

Changes from the original, so the engine stays apart: the engine's three direct calls into the knowledge store became these steps; the knowledge store's delete step no longer clears P6 feedback and scores (P6 is not a layer here yet; it will add its own step); and `engram_knowledge/__init__.py` names only P1's parts. `state_reviews`, the decision table used by P5, stays in P1's version 2 schema, unchanged.

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
