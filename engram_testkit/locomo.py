"""LoCoMo dev loader. The file is read from a path given at run time, outside the repository.

Conversations 0 to 4 are the dev set. Conversations 5 to 9 are held out: they are refused unless the
gate flag is exactly True, and the refusal comes before the file is opened. LoCoMo text (CC BY-NC 4.0)
is never committed.
"""
import os
import re

from . import formats as F

ENV = "ENGRAM_LOCOMO"
DEV = (0, 1, 2, 3, 4)
HELD_OUT = (5, 6, 7, 8, 9)
FILE_NAME = "locomo10.json"

# LoCoMo's numbered categories, as the repository's bench.py names them.
CATEGORY = {1: "multi-hop", 2: "temporal", 3: "inference", 4: "single-hop", 5: "adversarial"}

CONSENT_BASIS = ("public research benchmark (LoCoMo, CC BY-NC 4.0); read at run time from outside the "
                 "repository; its text is never committed")


class HeldOutRefused(PermissionError):
    """A held-out conversation (5 to 9) was asked for without the gate flag."""


def path_from_env():
    """The LoCoMo file path from the environment, or None when it is not set."""
    return os.environ.get(ENV) or None


def gate(indices, held_out_gate=False):
    """Refuse held-out conversations unless the gate flag is exactly True. Opens nothing."""
    for i in indices:
        if not isinstance(i, int) or isinstance(i, bool) or i not in DEV + HELD_OUT:
            raise ValueError(f"LoCoMo conversation index must be 0 to 9, not {i!r}")
    held = sorted(i for i in indices if i in HELD_OUT)
    if held and held_out_gate is not True:
        raise HeldOutRefused(f"conversations {held} are held out (test set); pass held_out_gate=True to open them")


def load(path, indices=None, held_out_gate=False):
    """Load LoCoMo conversations as kit conversations and questions. Default: dev conversations 0 to 4."""
    indices = list(DEV if indices is None else indices)
    gate(indices, held_out_gate)
    data = _read(path)
    convs, qs = {}, []
    for i in indices:
        c, cq = convert(data[i], i)
        convs[c["id"]] = c
        qs.extend(cq)
    return F.build_set(list(convs.values()), qs)


def _read(path):
    if not path:
        raise FileNotFoundError(f"no LoCoMo file given: set {ENV} to the path of {FILE_NAME}, kept outside the repository")
    if not os.path.exists(path):
        raise FileNotFoundError(f"LoCoMo file not found at {path!r} (from {ENV} or the caller)")
    return F.read_records(path)


def _sessions(raw):
    nums = sorted(int(m.group(1)) for k in raw if (m := re.fullmatch(r"session_(\d+)", k)))
    return [(n, raw[f"session_{n}"], raw.get(f"session_{n}_date_time", "")) for n in nums]


def convert(sample, i):
    """One LoCoMo sample to (conversation, questions). Turns are passed whole; both speakers get role user."""
    raw = sample["conversation"]
    cid = f"locomo-{i}"
    turns = []
    for n, session, date in _sessions(raw):
        for t in session:
            turn = dict(id=t["dia_id"], session=n, speaker=t["speaker"], role="user", date=date,
                        text=t["text"], source=f"{FILE_NAME}#{i}/{t['dia_id']}")
            if t.get("blip_caption"):
                # Kept beside the text, not merged into it: the arm decides how to use it.
                turn["caption"] = t["blip_caption"]
            turns.append(turn)
    conv = dict(id=cid, title=f"LoCoMo conversation {i} ({raw.get('speaker_a')} and {raw.get('speaker_b')})",
                provenance="benchmark", consent=dict(basis=CONSENT_BASIS),
                source=dict(kind="benchmark", pointer=f"{FILE_NAME}#{i}"), turns=turns)
    ids = {t["id"] for t in turns}
    questions, left_out = [], 0
    for n, qa in enumerate(sample.get("qa", [])):
        cat = CATEGORY.get(qa.get("category"))
        ev = []
        for e in qa.get("evidence", []) or []:
            ev.extend(x for x in re.split(r"[;,\s]+", str(e)) if x)
        ev = [e for e in dict.fromkeys(ev) if e in ids]
        if cat is None or (not ev and cat != "adversarial"):
            left_out += 1
            continue
        gold = F.NOT_MENTIONED if cat == "adversarial" else str(qa.get("answer", "")).strip()
        if not gold:
            left_out += 1
            continue
        questions.append(dict(id=f"{cid}-q{n}", conversation=cid, question=qa["question"], gold=gold,
                              evidence=ev, category=cat))
    if left_out:
        conv["source"]["questions_left_out"] = left_out
    return conv, questions
