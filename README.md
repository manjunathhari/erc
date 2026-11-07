# Engram

A layered memory architecture modelled on how the brain separates storage from retrieval. Content stays in a permanent record, a small index holds pointers, and reads call no model until the final answer.

This repository holds the Engram engine only, ported unchanged from `manjunathhari/Engram` (main at `ee68079`). The knowledge, learning and reasoning layers (P1–P7, ERC) are not included; they are to be added later as separate layers around this engine. The one change from the original: `engram_chat.py` no longer calls the knowledge store (three lines removed), so the engine imports nothing from any layer.

This is a research prototype. Do not put patient or other personal information in it: it has no access control or deletion.


## Opening a memory

```python
from engram_memory import open_memory
memory = open_memory("my_memory.db")
```

This uses the design that passed the LoCoMo final test and the LongMemEval test: four small channel networks trained only on LoCoMo conversations 0 to 4, stored as plain numbers with a checksum in `engram_networks.npz`, read by `engram_networks.py` (no pickle, so loading cannot run code). It gives the model exactly the same text as the tested runs. `design="light"` is the older search with no extra libraries; it did worse. `ChatMemory` on its own is unchanged.

## Layout

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
