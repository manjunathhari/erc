"""Deliberate breakages of the Engram Retrieval Foundation package: the release gate that travels with it.

A standalone verification script. It is not part of the package's code and nothing in the package imports it.

V1 to I3 are the 40 defects of the accepted tests-first package, each pointed at the file where that defect would
live. A1 to A12 were added by Amendment 1. Each must be caught by at least one test in this folder.

Usage, from anywhere:
    python engram_retrieval/tests/rt_build_break.py                    all 52 in one go
    python engram_retrieval/tests/rt_build_break.py --part 1 --of 13   in parts: 13 runs of 4 breakages each
    python engram_retrieval/tests/rt_build_break.py --group V          one group: V, U, L, H, M, I or A
    python engram_retrieval/tests/rt_build_break.py --only V1,H6       named ones
    python engram_retrieval/tests/rt_build_break.py --list --of 13     show which breakages each part holds; runs nothing

Where one run must finish inside a time limit, use the parts. Every invocation runs the tests once unbroken and
then once per breakage, so a part of 4 is 5 test runs. --part 1 --of 13 up to --part 13 --of 13 covers all 52
exactly once, in order. Choose a larger --of for smaller parts: --of 26 gives 2 each, --of 52 gives 1 each.
--part and --of also divide a --group or an --only selection.

It copies the package into a scratch folder for every run and never changes the repository. It prints the time
each run took, and exits 0 only if every breakage it ran was caught.
"""
import argparse, math, os, re, shutil, subprocess, sys, tempfile, time

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
B = [
 ("V1", "stored vectors not made unit length", "vector.py", "out.append(vector / length if usable else None)", "out.append(vector if usable else None)"),
 ("V2", "equal vector scores not ordered by id", "_common.py", "key=lambda hit: (-hit.score, hit.id))[:k]", "key=lambda hit: -hit.score)[:k]"),
 ("V3", "vector remove reports but does not delete", "vector.py", 'removed = sum(self.db.execute("DELETE FROM units WHERE id = ?", (id,)).rowcount for id in ids)', 'removed = sum(self.db.execute("SELECT 1 FROM units WHERE id = ?", (id,)).fetchone() is not None for id in ids)'),
 ("V4", "the vector index keeps the text", "vector.py", "fingerprint(unit.text), vector.astype(np.float32).tobytes())", "fingerprint(unit.text) + unit.text, vector.astype(np.float32).tobytes())"),
 ("V5", "an index opens under another model or other settings", "_common.py", "if made_with != settings:", "if False:"),
 ("V6", "a unit with no day is returned in a dated search", "_common.py", "        if day is None:\n            return False", "        if day is None:\n            return True"),
 ("V7", "the last day of a range is left out", "_common.py", "if last and day > last:", "if last and day >= last:"),
 ("V8", "an id silently accepts different text", "_common.py", "elif held != mark:", "elif False:"),
 ("V9", "an unusable vector is stored", "vector.py", "usable = np.isfinite(length) and length > 0 and bool(np.all(np.isfinite(vector)))", "usable = True"),
 ("V10", "one bad text fails the whole batch", "vector.py", "return [self._unit_vectors([text])[0] for text in texts]", "return [None for text in texts]"),
 ("V11", "a wrong-shaped vector is accepted", "vector.py", 'if vector.shape == (self.dim,) else float("nan")', 'if True else float("nan")'),
 ("V12", "a question that cannot be embedded returns an empty answer", "vector.py", 'raise ValueError("the question could not be embedded")', "return []"),
 ("V13", "a refused batch is partly written", "vector.py", "        new, report = self.not_yet_held(list(units)), AddReport()\n        if not new:", '        units = list(units)\n        if units and not self.status(units[0].id):\n            self.db.execute("INSERT INTO units VALUES(?, ?, ?, ?, ?)", (units[0].id + "~", units[0].kind, units[0].day, "", b"")); self.db.commit()\n        new, report = self.not_yet_held(units), AddReport()\n        if not new:'),
 ("V14", "a unit already held is offered to the model again", "_common.py", "            if held is None:\n                seen[unit.id] = mark\n                new.append(unit)", '            if held is None or True:\n                seen[unit.id] = mark\n                new.append(unit)\n                self.db.execute("DELETE FROM units WHERE id = ?", (unit.id,))'),
 ("V15", "k is not a ceiling", "_common.py", "key=lambda hit: (-hit.score, hit.id))[:k]", "key=lambda hit: (-hit.score, hit.id))"),
 ("U1", "a unit accepts an unknown kind", "_common.py", "if self.kind not in KINDS:", "if False:"),
 ("U2", "a unit accepts a day that is not a date", "_common.py", "    datetime.date.fromisoformat(day)\n    return day", "    return day"),
 ("L1", "the older BM25 weight (can go negative)", "lexical.py", "rarity = math.log(1 + (count - len(rows) + 0.5) / (len(rows) + 0.5))", "rarity = math.log((count - len(rows) + 0.5) / (len(rows) + 0.5))"),
 ("L2", "length is ignored", "lexical.py", "self.b * length / average", "self.b"),
 ("L3", "keyword remove leaves the words behind", "lexical.py", 'self.db.execute("DELETE FROM postings WHERE id = ?", (id,))', "pass"),
 ("L4", "a word asked twice counts twice", "lexical.py", "for word in dict.fromkeys(words_of(text)):", "for word in words_of(text):"),
 ("L5", "the question is not lower-cased", "lexical.py", "for word in dict.fromkeys(words_of(text)):", "for word in dict.fromkeys(_WORD.findall(text)):"),
 ("L6", "the keyword index keeps the sentence", "lexical.py", "(unit.id, unit.kind, unit.day, fingerprint(unit.text), len(words))", "(unit.id, unit.kind, unit.day, fingerprint(unit.text) + unit.text, len(words))"),
 ("L7", "BM25 settings are ignored", "lexical.py", "self.k1, self.b = float(k1), float(b)", "self.k1, self.b = 1.2, 0.75"),
 ("L8", "a filter changes how rare a word is", "lexical.py", "            if not rows:\n                continue\n            # How rare", "            rows = [row for row in rows if allowed(row[3], row[4], kinds, first, last)]\n            if not rows:\n                continue\n            # How rare"),
 ("H1", "channel scores are not scaled before fusion", "hybrid.py", "return {hit.id: 1.0 if high == low else (hit.score - low) / (high - low) for hit in hits}", "return {hit.id: hit.score for hit in hits}"),
 ("H2", "the two weights are swapped", "hybrid.py", '(self.w_vector * parts["vector"] + self.w_lexical * parts["lexical"])', '(self.w_lexical * parts["vector"] + self.w_vector * parts["lexical"])'),
 ("H3", "the pool is ignored", "hybrid.py", "self.vector.search(text, pool,", "self.vector.search(text, 10**6,"),
 ("H4", "removing through the pair misses the keyword index", "hybrid.py", "        self.lexical.remove(ids)\n        return len(held)", "        return len(held)"),
 ("H5", "filters do not reach the keyword channel", "hybrid.py", "self.lexical.search(text, pool, kinds, day_from, day_to)", "self.lexical.search(text, pool)"),
 ("H6", "a channel with weight zero still adds its units", "hybrid.py", " if self.w_lexical > 0 else []", ""),
 ("H7", "negative weights accepted", "hybrid.py", "if w_vector < 0 or w_lexical < 0 or w_vector + w_lexical <= 0:", "if w_vector + w_lexical <= 0:"),
 ("H8", "the parts are not reported", "hybrid.py", "hits.append(Hit(id, kind[id], fused, parts))", "hits.append(Hit(id, kind[id], fused))"),
 ("H9", "a unit the model cannot embed is kept out of the keyword index too", "hybrid.py", "        self.lexical.add(units)\n        return report", "        self.lexical.add([unit for unit in units if unit.id not in report.failed])\n        return report"),
 ("M1", "recall divided by k", "measures.py", "/ len(relevant)", "/ k"),
 ("M2", "reciprocal rank off by one", "measures.py", "enumerate(ranked, start=1) if id in relevant", "enumerate(ranked, start=2) if id in relevant"),
 ("M3", "NDCG's ideal taken from the answer given", "measures.py", "sorted(gains.values(), reverse=True)[:k]", "sorted((gains.get(id, 0) for id in ranked[:k]), reverse=True)"),
 ("I1", "the package imports an engine module", "_common.py", "import datetime\n", "import datetime\ntry:\n    import engram_structure\nexcept ImportError:\n    pass\n"),
 ("I2", "an extra public name", "__init__.py", '"recall_at_k", "mrr", "ndcg_at_k"]', '"recall_at_k", "mrr", "ndcg_at_k", "KINDS"]'),
 ("I3", "an engine file names the package", None, None, None),
 ("A1", "an existing empty file is turned into an index", "_common.py", "        exists = os.path.exists(self.path)\n", "        exists = os.path.exists(self.path) and os.path.getsize(self.path) > 0\n"),
 ("A2", "a file that is not a database is not refused as a mismatch", "_common.py", "        except sqlite3.DatabaseError as error:", "        except KeyError as error:"),
 ("A3", "vectors are kept in working memory between searches", "vector.py", '        rows = self.db.execute("SELECT id, kind, day, vec FROM units").fetchall()\n', '        if getattr(self, "_kept", None) is None:\n            self._kept = self.db.execute("SELECT id, kind, day, vec FROM units").fetchall()\n        rows = self._kept\n'),
 ("A4", "the same id twice in one batch is not noticed", "_common.py", "held = held[0] if held else seen.get(unit.id)", "held = held[0] if held else None"),
 ("A5", "the keyword index keeps words in the order said", "lexical.py", [('"PRIMARY KEY(term, id)) WITHOUT ROWID;"', '"PRIMARY KEY(term, id));"'), ("for word in sorted(counts)])", "for word in dict.fromkeys(words)])")], None),
 ("A6", "BM25 settings are not checked", "lexical.py", "if not (math.isfinite(self.k1) and self.k1 >= 0) or not 0 <= self.b <= 1:", "if False:"),
 ("A7", "something that is not a unit is not refused", "_common.py", "if not isinstance(unit, Unit):", "if False:"),
 ("A8", "True is accepted as a number of results", "_common.py", "if isinstance(k, bool) or not isinstance(k, int) or k <= 0:", "if not isinstance(k, int) or k <= 0:"),
 ("A9", "True is accepted as a pool", "hybrid.py", "if isinstance(pool, bool) or not isinstance(pool, int) or pool <= 0:", "if not isinstance(pool, int) or pool <= 0:"),
 ("A10", "a keyword question that is not text is not refused", "lexical.py", '        if not isinstance(text, str):\n            raise ValueError("the question must be text")\n', ""),
 ("A11", "removing through the pair counts only what the vector index held", "hybrid.py", "held = {id for id in ids if self.vector.status(id) or self.lexical.status(id)}", "held = [id for id in ids if self.vector.status(id)]"),
 ("A12", "an index can be used in a with block", "_common.py", "    def close(self):\n        self.db.close()\n", "    def close(self):\n        self.db.close()\n\n    def __enter__(self):\n        return self\n\n    def __exit__(self, *exc):\n        self.close()\n"),
]


def run(change=None, extra=None):
    with tempfile.TemporaryDirectory() as d:
        shutil.copytree(PKG, os.path.join(d, "engram_retrieval"), ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        if change:
            name, edits = change
            path = os.path.join(d, "engram_retrieval", name)
            code = open(path).read()
            for old, new in edits:
                assert code.count(old) == 1, (name, old, code.count(old))
                code = code.replace(old, new)
            open(path, "w").write(code)
        if extra:
            open(os.path.join(d, "engine_stub.py"), "w").write(extra)
        # The result is read from pytest's printed lines, so the printing must be plain wherever this runs: colour is
        # switched off on the command line and in the environment, and any colour codes that still arrive are removed.
        plain = dict(os.environ, NO_COLOR="1", PY_COLORS="0", TERM="dumb")
        plain.pop("FORCE_COLOR", None)
        r = subprocess.run([sys.executable, "-m", "pytest", "engram_retrieval/tests", "-q", "-p", "no:cacheprovider", "-x", "--tb=no", "-rfE",
                            "--color=no"], cwd=d, capture_output=True, text=True, env=plain)
    out = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", r.stdout)
    fails = [l.split("::")[1].split(" ")[0] for l in out.splitlines() if l.startswith(("FAILED", "ERROR")) and "::" in l]
    return r.returncode, fails, (out.strip().splitlines() or ["no output"])[-1]


def main():
    ask = argparse.ArgumentParser(description="Run the deliberate breakages.")
    ask.add_argument("--group", help="one letter: V, U, L, H, M, I or A")
    ask.add_argument("--only", help="named breakages, separated by commas")
    ask.add_argument("--part", type=int, help="which part to run, counted from 1; needs --of")
    ask.add_argument("--of", type=int, help="how many parts to divide the chosen breakages into")
    ask.add_argument("--list", action="store_true", help="show the chosen breakages, part by part, and run nothing")
    args = ask.parse_args()
    chosen = B
    if args.group:
        chosen = [entry for entry in chosen if re.fullmatch(re.escape(args.group) + r"\d+", entry[0])]
    if args.only:
        wanted = args.only.split(",")
        unknown = [w for w in wanted if w not in [entry[0] for entry in B]]
        if unknown:
            sys.exit(f"no such breakage: {', '.join(unknown)}")
        chosen = [entry for entry in chosen if entry[0] in wanted]
    if not chosen:
        sys.exit("nothing was chosen")
    if (args.part is None) != (args.of is None) and not args.list:
        sys.exit("--part and --of go together")
    parts = [chosen]
    if args.of is not None:
        if args.of < 1:
            sys.exit("--of must be 1 or more")
        size = math.ceil(len(chosen) / args.of)
        parts = [chosen[start:start + size] for start in range(0, len(chosen), size)]
    if args.list:
        for number, part in enumerate(parts, start=1):
            print(f"part {number} of {len(parts)}: {' '.join(entry[0] for entry in part)}")
        return
    if args.part is not None:
        if not 1 <= args.part <= len(parts):
            sys.exit(f"--part must be from 1 to {len(parts)}")
        chosen = parts[args.part - 1]
        print(f"part {args.part} of {len(parts)}: {' '.join(entry[0] for entry in chosen)}")
    began = time.time()
    rc, _, last = run()
    print(f"unbroken: {last}  [{time.time() - began:.1f}s]")
    if rc != 0:
        sys.exit("the tests do not pass before any breakage; nothing was run")
    caught = 0
    for bid, what, name, old, new in chosen:
        start = time.time()
        if name is None:
            rc, fails, last = run(extra="import engram_retrieval\n")
        else:
            rc, fails, last = run((name, old if isinstance(old, list) else [(old, new)]))
        ok = rc != 0 and bool(fails)
        caught += ok
        print(f"{bid:4} {'caught' if ok else 'MISSED'}  {what}  <- {fails[0] if fails else last}  [{time.time() - start:.1f}s]")
    print(f"{caught} of {len(chosen)} caught  [{time.time() - began:.1f}s in all]")
    sys.exit(0 if caught == len(chosen) else 1)


if __name__ == "__main__":
    main()
