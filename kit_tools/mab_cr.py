"""ERC value test on MemoryAgentBench Conflict Resolution (FactConsolidation): protocol claude/erc-test-protocol-mab.md.

Four paired arms answer every question from one Engram search and one set of writer records:
  A  Engram base 1: Engram's excerpts only (4,000 tokens, prompt v2 + the paper's conflict rule)
  B  writer records for the question's entities, every version, oldest first, then excerpts (same total)
  C  ERC's current facts only (contradiction finder over version keys; multi-hop walk on ERC's graph), then excerpts
  D  ERC's current facts only, no excerpts
  E  as C, but excerpt lines whose fact ERC marked replaced are left out (addendum, protocol section 9)
Scoring is the paper's SubEM (normalised gold answer contained in the answer), on the line after "Answer:".

  python kit_tools/mab_cr.py --parquet Conflict_Resolution.parquet --list              # rows, sizes, sample lines; no API
  python kit_tools/mab_cr.py --parquet Conflict_Resolution.parquet --save out --fake --sources factconsolidation_sh_6k --n 5
  python kit_tools/mab_cr.py --parquet Conflict_Resolution.parquet --save out --sources factconsolidation_sh_32k
  python kit_tools/mab_cr.py --parquet Conflict_Resolution.parquet --save out --sources factconsolidation_mh_32k --arms B,C,E

Each source is one memory ("inject once, ask many"). Work resumes where it stopped; writer records are cached per fact.
Needs OPENAI_API_KEY except with --list or --fake.
"""
import argparse, concurrent.futures, datetime, json, os, random, re, string, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
from lme_gpt4o import make_chat, bootstrap  # noqa: E402

ANSWER_MODEL = "gpt-4o-2024-08-06"
ALL_ARMS = ("A", "B", "C", "D", "E")
FACT_LINE = re.compile(r"^\s*(?:fact\s*)?\[?(\d+)\]?\s*[.:)\]]\s*(.+?)\s*$", re.I)


def norm_answer(text):  # MemoryAgentBench utils/eval_other_utils.normalize_answer
    text = text.lower()
    text = "".join(ch for ch in text if ch not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def sub_em(prediction, golds):
    p = norm_answer(prediction or "")
    return any(norm_answer(g) in p for g in golds if norm_answer(g))


def load_rows(path):
    if path.endswith(".json"):
        return json.load(open(path))
    import pandas as pd
    df = pd.read_parquet(path)
    rows = []
    for _, r in df.iterrows():
        meta = r["metadata"] if isinstance(r["metadata"], dict) else {}
        rows.append(dict(context=r["context"], questions=list(r["questions"]),
                         answers=[list(a) if not isinstance(a, str) else [a] for a in r["answers"]], source=meta.get("source", "")))
    return rows


def parse_facts(context):
    """Numbered fact lines -> {serial: sentence}. Lines without a number are skipped (reported in --list)."""
    facts, other = {}, 0
    for line in context.splitlines():
        m = FACT_LINE.match(line)
        if m: facts[int(m.group(1))] = m.group(2)
        elif line.strip(): other += 1
    return facts, other


def fake_chat_factory():
    def fake(model, prompt, max_tokens, json_mode=False):
        if json_mode:  # stand-in writer: object = text after the last " is " / " of "
            rows = []
            for n, sent in re.findall(r"^Fact (\d+): (.*)$", prompt, re.M):
                m = re.search(r"^(.*?)\s+(?:is|are|was|were)\s+(?:a citizen of\s+|affiliated with the religion of\s+)?(.+?)\.?$", sent)
                if m: rows.append(dict(n=int(n), subject=m.group(1).replace("The ", "", 1), object=m.group(2)))
            return json.dumps({"facts": rows})
        return "Notes: (dry run)\nAnswer: not mentioned"
    return fake


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True, help="Conflict_Resolution parquet from ai-hyz/MemoryAgentBench (or a JSON list of rows for tests)")
    ap.add_argument("--save", default="mab_results")
    ap.add_argument("--list", action="store_true", help="show the rows, fact counts and sample lines, then stop (no API)")
    ap.add_argument("--sources", default="", help="comma list of sources, e.g. factconsolidation_sh_32k; default all")
    ap.add_argument("--n", type=int, default=0, help="questions per source; 0 = all")
    ap.add_argument("--fake", action="store_true", help="dry run with stand-in writer and answers; no API calls")
    ap.add_argument("--answer-model", default=ANSWER_MODEL)
    ap.add_argument("--writer-model", default="gpt-4o-mini")
    ap.add_argument("--context-tokens", type=int, default=4000, help="total context per arm (Engram base 1: 4,000)")
    ap.add_argument("--facts-tokens", type=int, default=2000, help="most tokens the records may take in arms B and C")
    ap.add_argument("--chunk-tokens", type=int, default=4096, help="facts per Engram chat, as MemoryAgentBench's chunk_size")
    ap.add_argument("--hops", type=int, default=4, help="links followed from the question's entities (MQuAKE chains have up to 4)")
    ap.add_argument("--seed-facts", type=int, default=10, help="Engram's top N results also seed the walk (0 = question names only)")
    ap.add_argument("--threads", type=int, default=3, help="parallel answer calls; keep low to stay under the account's tokens-per-minute limit")
    ap.add_argument("--design", default="tested", help="Engram search design; 'light' only for offline tests (benchmarks use 'tested')")
    ap.add_argument("--keep-context", action="store_true", help="also save each arm's full context in its answer file (for review)")
    ap.add_argument("--arms", default="A,B,C,D", help="comma list of arms to answer, from A,B,C,D,E (E: protocol section 9)")
    a = ap.parse_args()
    ARMS = tuple(x.strip().upper() for x in a.arms.split(",") if x.strip())
    if not ARMS or any(x not in ALL_ARMS for x in ARMS): raise SystemExit(f"--arms must be from {ALL_ARMS}")

    rows = load_rows(a.parquet)
    if a.list:
        for r in rows:
            facts, other = parse_facts(r["context"])
            print(f"{r['source']}: {len(r['questions'])} questions, {len(facts)} numbered facts, {other} other lines, "
                  f"~{len(r['context']) // 4} tokens")
        r = rows[0]
        print("\nfirst lines of", r["source"], ":")
        for line in r["context"].splitlines()[:4]: print("  ", line[:160])
        print("question:", r["questions"][0][:200], "| answers:", r["answers"][0])
        return

    import engram_chat as E
    import engram_erc_bridge as B
    import vps_kit as K
    from engram_memory import open_memory

    prompt = K.ANSWER_V2.replace(
        "Answer the question from them.",
        "Answer the question from them, and only from them, not from what you know about the real world. Each fact carries "
        "a serial number; a larger number means a newer fact. When facts conflict, use the newest one.")
    chat = fake_chat_factory() if a.fake else make_chat(False)
    os.makedirs(a.save, exist_ok=True)
    wanted = [s.strip() for s in a.sources.split(",") if s.strip()]
    todo_rows = [r for r in rows if not wanted or r["source"] in wanted]
    if wanted and len(todo_rows) != len(wanted):
        raise SystemExit(f"unknown source in {wanted}; available: {[r['source'] for r in rows]}")
    tag = ("_fake" if a.fake else "")

    for r in todo_rows:
        src = r["source"]
        facts, other = parse_facts(r["context"])
        if not facts: raise SystemExit(f"{src}: no numbered facts found; check --list")
        qs = list(enumerate(zip(r["questions"], r["answers"])))[: a.n or None]
        print(f"\n== {src}: {len(facts)} facts, {len(qs)} questions; arms {ARMS}; answer {a.answer_model}, writer {a.writer_model}", flush=True)

        # 1. writer records (cached per fact)
        cache_path = f"{a.save}/mab_facts_{a.writer_model}{tag}_{src.rsplit('_', 1)[-1]}.json"  # sh and mh at one length share facts
        cache = {int(k): v for k, v in json.load(open(cache_path)).items()} if os.path.exists(cache_path) else {}
        missing = sorted(n for n in facts if n not in cache)
        batches = [missing[i:i + 60] for i in range(0, len(missing), 60)]
        t0 = time.time()

        def write(batch):
            got = B.parse_fact_records(chat(a.writer_model, B.fact_writer_prompt((n, facts[n]) for n in batch), 3000, json_mode=True),
                                       {n: facts[n] for n in batch})
            return {n: got.get(n) for n in batch}
        with concurrent.futures.ThreadPoolExecutor(16) as pool:
            for k, res in enumerate(pool.map(write, batches), 1):
                cache.update(res)
                if k % 20 == 0 or k == len(batches):
                    json.dump(cache, open(cache_path, "w"))
                    print(f"  writer {k}/{len(batches)} batches", flush=True)
        records = {n: v for n, v in cache.items() if v}
        state = B.build_fact_state(records)
        print(f"  records {len(records)}/{len(facts)} ({time.time() - t0:.0f} s); version keys with >1 version {state.keys_with_versions}; "
              f"superseded {len(state.superseded)}", flush=True)

        # 2. Engram memory: one chat per chunk of facts, dates one day apart so date order = serial order
        t0 = time.time()
        m = open_memory(f"{tempfile.mkdtemp()}/{src}.db", design=a.design, durable=False, settings=E.Settings(retrieved_tokens=a.context_tokens))
        chunks, cur, used = [], [], 0
        for n in sorted(facts):
            t = len(facts[n]) // 4 + 6
            if cur and used + t > a.chunk_tokens: chunks.append(cur); cur, used = [], 0
            cur.append(n); used += t
        if cur: chunks.append(cur)
        day0 = datetime.datetime(2023, 1, 1, 9, 0)
        for k, chunk in enumerate(chunks, 1):
            d = day0 + datetime.timedelta(days=k - 1)
            date = f"{d.hour % 12 or 12}:{d.minute:02d} am on {d.day} {d.strftime('%B')}, {d.year}"
            m.open_chat(date)
            for n in chunk: m.add("User", f"Fact {n}: {facts[n]}", date=date, ref=f"F{n}", commit=False)
            m.db.commit()
            m.close_chat(write_note=False, sleep=k == len(chunks))
        print(f"  Engram: {len(chunks)} chats in {time.time() - t0:.0f} s", flush=True)

        # 3. questions: one search, four contexts, four answers
        paths = {arm: f"{a.save}/mab_{src}_{arm}{tag}.jsonl" for arm in ARMS}
        done = {arm: ({json.loads(x)["i"] for x in open(paths[arm])} if os.path.exists(paths[arm]) else set()) for arm in ARMS}
        outs = {arm: open(paths[arm], "a") for arm in ARMS}

        def answer(arm, i, q, golds, ctx, info):
            reply = chat(a.answer_model, prompt.format(ctx=ctx, q=q), 400)
            hyp = K.final_answer(reply)
            return arm, dict(i=i, source=src, arm=arm, question=q, answers=golds, hypothesis=hyp, reply=reply,
                             label=sub_em(hyp, golds), answer_in_context=sub_em(ctx, golds), context_tokens=B.count_tokens(ctx),
                             **info, **(dict(context=ctx) if a.keep_context else {}))

        t0 = time.time()
        with concurrent.futures.ThreadPoolExecutor(a.threads) as pool:
            futures = []
            for k, (i, (q, golds)) in enumerate(qs, 1):
                if all(i in done[arm] for arm in ARMS): continue
                raw, info = m.context_for(q)
                seeds = []  # facts in Engram's top results seed the walk too, for questions that don't name a subject exactly
                for sid in info["sids"][: a.seed_facts]:
                    ref = m.db.execute("SELECT ref FROM sentences WHERE sid=?", (sid,)).fetchone()
                    if ref and str(ref[0]).startswith("F") and str(ref[0])[1:].isdigit(): seeds.append(int(str(ref[0])[1:]))
                walk_all = B.fact_walk(state, q, a.hops, current_only=False, seeds=seeds)
                walk_cur = B.fact_walk(state, q, a.hops, current_only=True, seeds=seeds)
                sec_b = B.facts_section(state, walk_all, a.facts_tokens, "[Facts about the entities in the question, every version, oldest first]")
                sec_c = B.facts_section(state, walk_cur, a.facts_tokens, "[Current facts from the memory layer: the newest version of each, linked from the question]")
                sec_d = B.facts_section(state, walk_cur, a.context_tokens, "[Current facts from the memory layer: the newest version of each, linked from the question]")

                refs = {sid: (m.db.execute("SELECT ref FROM sentences WHERE sid=?", (sid,)).fetchone() or [None])[0] for sid in info["sids"]}

                def with_excerpts(sec, clean=False):  # clean=True (arm E): skip lines whose fact ERC marked replaced
                    budget, keep, u = a.context_tokens - (B.count_tokens(sec) if sec else 0), [], 0
                    for sid in info["sids"]:
                        if clean and B.is_superseded_ref(state, refs[sid]): continue
                        t = m._tokens(sid) + 8
                        if u + t > budget: break
                        keep.append(sid); u += t
                    body = m.text_of(sorted(keep)) if keep else ""
                    return "\n\n".join(x for x in (sec, body) if x) or "(nothing found)"
                ctxs = {"A": raw, "B": with_excerpts(sec_b), "C": with_excerpts(sec_c), "D": sec_d or "(nothing found)",
                        "E": with_excerpts(sec_c, clean=True)}
                hidden = sum(B.is_superseded_ref(state, refs[s]) for s in info["sids"])
                extra = dict(walk_all=len(walk_all), walk_current=len(walk_cur), replaced_in_search=hidden)
                for arm in ARMS:
                    if i not in done[arm]: futures.append(pool.submit(answer, arm, i, q, list(golds), ctxs[arm], extra))
                if k % 10 == 0: print(f"  searched {k}/{len(qs)}, {(time.time() - t0) / k:.1f} s each", flush=True)
                for f in [f for f in futures if f.done()]:
                    arm, row = f.result(); outs[arm].write(json.dumps(row) + "\n"); outs[arm].flush(); futures.remove(f)
            for f in futures:
                arm, row = f.result(); outs[arm].write(json.dumps(row) + "\n"); outs[arm].flush()
        for f in outs.values(): f.close()
        m.db.close()

        # 4. summary
        res = {arm: {x["i"]: x for x in map(json.loads, open(paths[arm]))} for arm in ARMS}
        ids = sorted(set.intersection(*[set(v) for v in res.values()]) & {i for i, _ in qs})
        acc = {arm: round(100 * sum(res[arm][i]["label"] for i in ids) / max(1, len(ids)), 1) for arm in ARMS}

        def diff(x, y):
            if x not in res or y not in res: return None
            vals = [int(res[x][i]["label"]) - int(res[y][i]["label"]) for i in ids]
            rng = random.Random(7); n = len(vals)
            d = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(10000)) if n else [0]
            return dict(points=round(100 * sum(vals) / max(1, n), 1), interval_95=[round(100 * d[250], 1), round(100 * d[9749], 1)],
                        won=sum(v > 0 for v in vals), lost=sum(v < 0 for v in vals))
        summary = dict(
            source=src, questions=len(ids), answer_model=a.answer_model, writer_model=a.writer_model, fake=a.fake,
            accuracy_subem=acc, interval_95={arm: bootstrap([int(res[arm][i]["label"]) for i in ids]) if ids else None for arm in ARMS},
            arms=list(ARMS),
            C_minus_B=diff("C", "B"), C_minus_A=diff("C", "A"), C_minus_D=diff("C", "D"),
            E_minus_B=diff("E", "B"), E_minus_C=diff("E", "C"),
            mean_replaced_lines_in_search=round(sum(res[ARMS[0]][i].get("replaced_in_search", 0) for i in ids) / max(1, len(ids)), 1),
            answer_in_context={arm: round(100 * sum(res[arm][i]["answer_in_context"] for i in ids) / max(1, len(ids)), 1) for arm in ARMS},
            facts=len(facts), records=len(records), version_keys_with_more_than_one=state.keys_with_versions, superseded=len(state.superseded),
            mean_walk={"all_versions": round(sum(res[ARMS[0]][i]["walk_all"] for i in ids) / max(1, len(ids)), 1),
                       "current": round(sum(res[ARMS[0]][i]["walk_current"] for i in ids) / max(1, len(ids)), 1)},
            settings=dict(context_tokens=a.context_tokens, facts_tokens=a.facts_tokens, chunk_tokens=a.chunk_tokens, hops=a.hops, seed_facts=a.seed_facts),
            published="MemoryAgentBench GPT-4o long context 60 SH / 5 MH; Mem0 18/2; MemGPT 28/3; deterministic pipeline (arXiv 2606.01435) 93/41 at 262K",
            rule="ERC adds value if C beats B by >=10 points (interval excluding 0) at the largest length; stop if C-B < 5 on SH and MH at every length",
            rule_arm_E="addendum (section 9): E-B >=10 with interval excluding 0 -> confirm at 262K; 5-10 or interval touching 0 -> unclear; < 5 -> ERC stays out of chat memory")
        json.dump(summary, open(f"{a.save}/mab_summary_{src}{tag}.json", "w"), indent=1)
        print(json.dumps(summary, indent=1), flush=True)
    print("Done", flush=True)


if __name__ == "__main__":
    main()
