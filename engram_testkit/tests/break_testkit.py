"""Deliberate breakages: each mutation is applied to a temporary copy of engram_testkit and the
kit's tests are run there. Every mutation must make the suite fail; the unmutated copy must pass.

  python engram_testkit/tests/break_testkit.py [--out results.txt]
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)

# Build r1 (25 Nov 2026): anchors moved to the text of the built modules. Each breakage keeps its ID and
# breaks the same rule as in the accepted revision 2 list.
MUTATIONS = [
    ("BK-01", "held-out conversations 5 to 9 let through without the gate flag", "locomo.py",
     "    if held and held_out_gate is not True:", "    if False:"),
    ("BK-02", "conversation 5 moved into dev", "locomo.py",
     "DEV = (0, 1, 2, 3, 4)\nHELD_OUT = (5, 6, 7, 8, 9)", "DEV = (0, 1, 2, 3, 4, 5)\nHELD_OUT = (6, 7, 8, 9)"),
    ("BK-03", "the gate checked after the file is opened", "locomo.py",
     "    gate(indices, held_out_gate)\n    data = _read(path)", "    data = _read(path)\n    gate(indices, held_out_gate)"),
    ("BK-04", "real provenance accepted before access control exists", "formats.py",
     '        allowed = access_control is True and ACCESS_CONTROL_AVAILABLE is True', '        allowed = access_control is True'),
    ("BK-05", "consent no longer required", "formats.py",
     '    if not isinstance(consent, dict) or not isinstance(consent.get("basis"), str) or not consent["basis"].strip():',
     '    if False:'),
    ("BK-06", "reserved slot D can be bound", "arms.py",
     '        if SLOTS[key].status == "reserved":', "        if False:"),
    ("BK-07", "call cap off by one (one call past the cap)", "runner.py",
     "        if self.used >= self.cap:", "        if self.used > self.cap:"),
    ("BK-08", "retries not counted against the cap", "runner.py",
     "            self.budget.spend()\n            rec = dict(", "            if attempt == 1:\n                self.budget.spend()\n            rec = dict("),
    ("BK-09", "state not saved when the cap stops the run", "runner.py",
     "        except CapReached as e:\n            return self.save_state(True, str(e))",
     "        except CapReached as e:\n            return dict(stopped=True, reason=str(e))"),
    ("BK-10", "each question answered once, not twice", "runner.py", "    runs: int = RUNS", "    runs: int = 1"),
    ("BK-11", "adversarial questions sent to the judge", "runner.py",
     '        if pred is not None and q["category"] != "adversarial":', "        if pred is not None:"),
    ("BK-12", "adversarial answers scored by the judge, not the fixed rule", "scoring.py",
     '    if row["category"] == "adversarial":\n        ok = adversarial(row["pred"])',
     '    if row["category"] == "adversarial":\n        ok = generous(row["judge"])'),
    ("BK-13", "strict rule credits 'not mentioned'", "scoring.py",
     "    if not isinstance(pred, str) or says_not_mentioned(pred):", "    if not isinstance(pred, str):"),
    ("BK-14", "latency not recorded on calls", "runner.py",
     "            rec.update(ok=True, reply=text, error=None, secs=round(time.perf_counter() - start, 6),",
     "            rec.update(ok=True, reply=text, error=None, secs=None,"),
    ("BK-15", "arm B silently skips an adversarial question", "runner.py",
     "                        if (key, q[\"id\"], run) not in self.done:\n                            self.ask(key, arm, q, run)",
     "                        if (key, q[\"id\"], run) not in self.done and not (key == 'B' and q['id'] == 'q04'):\n                            self.ask(key, arm, q, run)"),
    # Revision 2: the label (R2-B) and the settled decisions.
    ("BK-16", "report drops the label", "report.py",
     '    simulated = not (state.get("simulated", True) is False and summary.get("simulated", True) is False)', "    simulated = False"),
    ("BK-17", "run records written without the label", "runner.py",
     "        if self.label:\n            record = dict(record, label=self.label)", "        if False:\n            record = dict(record, label=self.label)"),
    ("BK-18", "stub arms not seen as simulated", "label.py",
     "    return any(_arm_is_simulated(a) for a in arms)", "    return False"),
    ("BK-19", "an arm that says nothing counts as real", "label.py",
     '    return getattr(arm, "simulated", None) is not False', '    return getattr(arm, "simulated", None) is True'),
    ("BK-20", "stripped labels in records accepted by the summary", "scoring.py",
     "        raise LabelMissing(\"run records of simulated arms must all carry the label\")", "        pass"),
    ("BK-21", "scoring-sheet header without the label", "scoring.py",
     '        header["label"] = summary["label"]', "        pass"),
    ("BK-22", "results written inside a git repository", "runner.py",
     "        if inside_repository(self.out):", "        if False:"),
    ("BK-23", "run starts without a gold-answer audit", "audit.py",
     "    if not audit:\n        raise AuditMissing", "    if not audit:\n        return questions\n        raise AuditMissing"),
    ("BK-24", "dropped questions still asked", "audit.py",
     '    return [q for q in questions if entries[q["id"]]["status"] != "dropped"]', "    return list(questions)"),
    ("BK-25", "resume asks done rows again", "runner.py",
     '        done = {(r["arm"], r["qid"], r["run"]) for r in read_jsonl(self.answers_path)}', "        done = set()"),
    ("BK-26", "resume resets the cap count", "runner.py",
     "        return done, len(read_jsonl(self.calls_path)), old.get(\"sessions\", 1) + 1", "        return done, 0, old.get(\"sessions\", 1) + 1"),
    ("BK-27", "callable not matched to the freeze", "runner.py",
     '        if freeze[kind]["model"] != fn.model:', "        if False:"),
    ("BK-28", "judge token limit not taken from the freeze", "runner.py",
     '        max_tokens = self.freeze[kind]["max_tokens"]', "        max_tokens = 10 if kind == \"judge\" else 60"),
    ("BK-29", "bootstrap seed not fixed", "scoring.py",
     "    rng = random.Random(seed)", "    rng = random.Random()"),
    ("BK-30", "asked_on not passed to the arm", "runner.py",
     '        got = arm.retrieve(q["question"], conversation=q["conversation"], asked_on=q.get("asked_on"))',
     '        got = arm.retrieve(q["question"], conversation=q["conversation"])'),
    ("BK-31", "the floor reported inside A to D", "scoring.py",
     "    floor = out.pop(FLOOR, None)", "    floor = out.get(FLOOR)"),
    ("BK-32", "answer prompt no longer the vps_kit text", "runner.py",
     "Answer the question using only them, in as few words as you can.", "Answer the question using only them, briefly."),
    # Build revision 2 (25 Nov 2026): the strict freeze, and the boundary gaps from the review.
    ("BK-33", "temperature and reasoning not passed to the callable", "runner.py",
     "                text, usage, reported = fn(prompt, **settings)",
     "                text, usage, reported = fn(prompt, max_tokens=max_tokens)"),
    ("BK-34", "a callable that cannot take the settings is not refused at run start", "runner.py",
     "        if not takes_settings(fn):", "        if False:"),
    ("BK-35", "a used setting that differs from the freeze is accepted", "runner.py",
     "        if want != got or isinstance(want, bool) != isinstance(got, bool):", "        if False:"),
    ("BK-36", "a call that reports no settings is accepted", "runner.py",
     '        return ["no effective settings reported"]', "        return []"),
    ("BK-37", "a report missing a setting is accepted", "runner.py",
     '            out.append(f"{f}: not reported")', "            pass"),
    ("BK-38", "the settings used are not recorded on the call record", "runner.py",
     '            rec["effective"] = effective', '            rec["effective"] = None'),
    ("BK-39", "the mismatched call is not saved before the run stops", "runner.py",
     "                self._write(self.calls_path, rec)\n                raise EffectiveMismatch",
     "                raise EffectiveMismatch"),
    ("BK-40", "a mismatched call does not stop the run", "runner.py",
     "                raise EffectiveMismatch(f\"the {kind} callable did not use the frozen settings: {'; '.join(differ)}\")",
     "                return None, rec"),
    ("BK-41", "resume does not check the settings of earlier sessions' calls", "runner.py",
     "        self._same_settings(read_jsonl(self.calls_path))\n", ""),
    ("BK-42", "the run does not check conversations itself (a real one passed straight in)", "runner.py",
     "        for c in self.conversations.values():\n            F.validate_conversation(c)\n", ""),
    ("BK-43", "conversations checked after questions (real data refused only incidentally)", "runner.py",
     "        for c in self.conversations.values():\n            F.validate_conversation(c)\n        for q in self.all_questions:\n            F.validate_question(q, self.conversations)\n",
     "        for q in self.all_questions:\n            F.validate_question(q, self.conversations)\n        for c in self.conversations.values():\n            F.validate_conversation(c)\n"),
    ("BK-44", "a conversation with the consent key removed is accepted", "formats.py",
     '    consent = c.get("consent")', '    consent = c.get("consent", {"basis": "not given"})'),
    ("BK-45", "a worktree's .git file not counted as a repository", "runner.py",
     '        if os.path.exists(os.path.join(here, ".git")):', '        if os.path.isdir(os.path.join(here, ".git")):'),
    ("BK-46", "only the output folder and its parent checked for a repository", "runner.py",
     "        if up == here:\n            return False", "        if up == here or here != os.path.abspath(path):\n            return False"),
    ("BK-47", "an audit entry with a blank reason is accepted", "audit.py",
     '        if not isinstance(e.get("reason"), str) or not e["reason"].strip():', '        if not isinstance(e.get("reason"), str):'),
    ("BK-48", "an audit with a malformed date is accepted", "audit.py",
     '    if not is_iso_day(audit.get("date")):', '    if not audit.get("date"):'),
    ("BK-49", "corrected questions not recorded in the state", "audit.py",
     '                corrected=[k for k, e in entries.items() if e["status"] == "corrected"])', "                corrected=[])"),
    ("BK-50", "resume does not compare the question set", "runner.py",
     '        self._same(old, "question_set", self.question_set)\n', ""),
    ("BK-51", "resume does not compare the freeze", "runner.py",
     '        self._same(old, "freeze", self.freeze)\n', ""),
    ("BK-52", "resume does not compare the arms", "runner.py",
     '        self._same(old, "arms", [k for k, _ in self.arms])\n', ""),
    ("BK-53", "resume does not compare the number of runs", "runner.py",
     '        self._same(old, "runs", self.cfg.runs)\n', ""),
    ("BK-54", "resume does not compare the asked questions", "runner.py",
     '        self._same(old, "asked", [q["id"] for q in self.asked])\n', ""),
    ("BK-55", "a callable without a model name not refused up front", "runner.py",
     "        if not isinstance(model, str) or not model:\n            raise CallableRefused",
     "        if False:\n            raise CallableRefused"),
    ("BK-56", "the runner does not enforce asked_on on returned turns", "runner.py",
     '        if q.get("asked_on"):\n            self.check_asked_on(key, q, turn_ids)', '        if False:\n            self.check_asked_on(key, q, turn_ids)'),
    ("BK-57", "under asked_on, turns from outside the conversation are accepted", "runner.py",
     '        late = [t for t in turn_ids if t not in turns or (F.turn_day(turns[t]["date"]) or "9999") > q["asked_on"]]',
     '        late = [t for t in turn_ids if t in turns and (F.turn_day(turns[t]["date"]) or "9999") > q["asked_on"]]'),
]


def run_tests(root):
    env = dict(os.environ, PYTHONPATH=root)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "--rootdir", root,
                        "-c", os.path.join(root, "pytest.ini"), os.path.join(root, "engram_testkit", "tests")],
                       cwd=root, env=env, capture_output=True, text=True)
    out = [x for x in r.stdout.strip().splitlines() if x.strip()]
    failed = [x.split("::", 1)[1].split(" ")[0] for x in out if x.startswith("FAILED ")]
    tail = out[-1] if out else r.stderr.strip()[-200:]
    return r.returncode, tail + ("; failing: " + ", ".join(failed) if failed else "")


def copy_kit(tmp):
    shutil.copytree(PKG, os.path.join(tmp, "engram_testkit"), ignore=shutil.ignore_patterns("__pycache__"))
    # Read-only references some tests compare against (vps_kit texts, judge_sheet.py's scoring). Copied, never changed.
    repo = os.path.dirname(PKG)
    for rel in ("vps_kit.py", os.path.join("kit_tools", "judge_sheet.py")):
        if os.path.exists(os.path.join(repo, rel)):
            os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
            shutil.copy(os.path.join(repo, rel), os.path.join(tmp, rel))
    with open(os.path.join(tmp, "pytest.ini"), "w") as f:
        f.write("[pytest]\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    lines, ok = [], True
    with tempfile.TemporaryDirectory() as tmp:
        copy_kit(tmp)
        code, tail = run_tests(tmp)
        lines.append(f"UNMUTATED  exit {code}  {tail}")
        ok &= code == 0
    for mid, what, fname, old, new in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            copy_kit(tmp)
            path = os.path.join(tmp, "engram_testkit", fname)
            src = open(path).read()
            if src.count(old) != 1:
                lines.append(f"{mid}  NOT APPLIED (text found {src.count(old)} times)  {what}")
                ok = False
                continue
            open(path, "w").write(src.replace(old, new))
            code, tail = run_tests(tmp)
            caught = code != 0
            ok &= caught
            lines.append(f"{mid}  {'CAUGHT' if caught else 'MISSED'}  {fname}: {what}  [{tail}]")
    caught = sum("CAUGHT" in x for x in lines)
    lines.append(f"\n{caught} of {len(MUTATIONS)} breakages caught; unmutated copy {'passes' if lines[0].split()[2] == '0' else 'FAILS'}")
    lines.append("Each line lists every failing test for that breakage.")
    text = "\n".join(lines) + "\n"
    print(text)
    if a.out:
        open(a.out, "w").write(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
