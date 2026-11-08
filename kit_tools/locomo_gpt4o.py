"""Phase B: the LoCoMo final test with GPT-4o in place of Gemma 3 4B.

Same questions, design and prompts as the Gemma final test (frozen_design.json, conversations 5 to 9,
networks trained on conversations 0 to 4 only); only the model changes. GPT-4o writes the noted facts at
chat close (engram_facts.PROMPT, 700 reply tokens) and the answers (vps_kit.ANSWER, 60 reply tokens),
temperature 0, seed 7, as before.

Three ways answer every question, paired:
  with_facts  tested search (open_memory, saved networks) + GPT-4o noted facts   <- frozen design
  no_facts    the same memory with facts switched off
  current     the older search (open_memory design="light"), no facts

Judging: GPT-4o with vps_kit.JUDGE (the generous LoCoMo standard used before). Strict and generous blind
Claude labels are added afterwards from the answers file, as in the Gemma test.

  python kit_tools/locomo_gpt4o.py --save results_dir            # all test questions
  python kit_tools/locomo_gpt4o.py --save results_dir --sample 40 # quick check
  python kit_tools/locomo_gpt4o.py --save results_dir --fake      # dry run, no key, no API calls

Work resumes where it stopped: facts are cached per chat and answers are appended per question.
Needs OPENAI_API_KEY and the LoCoMo data in ./locomo (git clone https://github.com/snap-research/locomo).
"""
import argparse, json, os, random, sys, tempfile, time

MODEL = "gpt-4o-2024-08-06"
URL = "https://api.openai.com/v1"
TEST = [5, 6, 7, 8, 9]
SYSTEMS = ("with_facts", "no_facts", "current")


def fake_llm(prompt, max_tokens=60, temperature=0.0):
    """Stand-in model for a dry run: no facts, 'not mentioned' answers, judge says WRONG."""
    if "Write the facts worth remembering" in prompt: return "", {}, 0.0
    if "CORRECT" in prompt and "WRONG" in prompt: return "WRONG", {}, 0.0
    return "not mentioned", {}, 0.0


def bootstrap_diff(pairs, reps=10000, seed=7):
    rng = random.Random(seed); n = len(pairs)
    d = sorted(sum(a - b for a, b in (pairs[rng.randrange(n)] for _ in range(n))) / n for _ in range(reps))
    return round(100 * d[int(.025 * reps)], 1), round(100 * d[int(.975 * reps) - 1], 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", required=True)
    ap.add_argument("--sample", type=int, default=100000, help="questions to run, in the balanced order; default all")
    ap.add_argument("--fake", action="store_true", help="dry run without OpenAI")
    ap.add_argument("--design", default="tested", help="tested (default) or light; light only for dry runs without wordllama")
    a = ap.parse_args()
    os.makedirs(a.save, exist_ok=True)
    sys.path.insert(0, os.getcwd())
    import vps_kit as K
    from engram_memory import open_memory

    D = json.load(open("frozen_design.json"))
    assert D["sentence_tokens"] == 800 and D["fact_tokens"] == 300, "frozen design changed"
    if a.fake:
        llm = fake_llm
    else:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key: raise SystemExit("Set OPENAI_API_KEY (Kaggle: Add-ons > Secrets).")
        llm = K.LLM(URL, MODEL, key, 120)

    convs = {c: K.load_conv(K.DATA[c]) for c in TEST}
    tmp = tempfile.mkdtemp()
    cache_path = f"{a.save}/locomo_gpt4o_facts.json"
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}

    def replay(c, design, with_helper):
        state = {}

        def helper(prompt, max_tokens=0):
            key = state["key"]
            if key not in cache:
                t0 = time.time()
                cache[key] = dict(raw=llm(prompt, max_tokens=max_tokens)[0], secs=round(time.time() - t0, 1))
                json.dump(cache, open(cache_path, "w"))
            return cache[key]["raw"], {}, cache[key]["secs"]

        kw = dict(helper=helper, helper_name=MODEL) if with_helper else {}
        m = open_memory(f"{tmp}/{c}_{design}_{with_helper}.db", design=design, durable=False, **kw)
        last = None
        for t in convs[c].turns:
            if t["session"] != last:
                if last is not None:
                    state["key"] = f"{c}:{last}"; m.close_chat(write_note=False, sleep=False)
                m.open_chat(t["date"]); last = t["session"]
            m.add(t["speaker"], t["text"], date=t["date"], ref=t["id"], caption=t["cap"], commit=False)
        m.db.commit(); state["key"] = f"{c}:{last}"; m.close_chat(write_note=False)
        return m

    print(f"model {MODEL}{' (FAKE dry run)' if a.fake else ''}; writing facts for conversations 5-9", flush=True)
    MEM = {c: replay(c, a.design, True) for c in TEST}
    CUR = {c: replay(c, "light", False) for c in TEST}
    n_facts = sum(m.db.execute("SELECT count(*) FROM facts").fetchone()[0] for m in MEM.values())
    print(f"facts stored: {n_facts} from {len(cache)} chats", flush=True)

    REF = {c: dict(MEM[c].db.execute("SELECT ref, sid FROM sentences").fetchall()) for c in TEST}
    CREF = {c: dict(CUR[c].db.execute("SELECT ref, sid FROM sentences").fetchall()) for c in TEST}
    plan = [(c, i) for c, i in K.balanced(convs, TEST, a.sample) if convs[c].qs[i]["cat"] != 5]
    plan = [(c, i) for c, i in plan if any(e in REF[c] for e in convs[c].qs[i]["ev"])]
    print(f"{len(plan)} questions, {len(SYSTEMS)} ways each", flush=True)

    path = f"{a.save}/locomo_gpt4o_answers.jsonl"
    done = {(r["conv"], r["i"], r["system"]) for r in map(json.loads, open(path))} if os.path.exists(path) else set()
    t0 = time.time()
    with open(path, "a") as out:
        for n, (c, i) in enumerate(plan, 1):
            q = convs[c].qs[i]
            for name in SYSTEMS:
                if (c, i, name) in done: continue
                m, ref = (CUR[c], CREF[c]) if name == "current" else (MEM[c], REF[c])
                m.use_facts = name == "with_facts"
                ctx, info = m.context_for(q["q"])
                gold_sids = {ref[e] for e in q["ev"] if e in ref}
                pred, usage, secs = llm(K.ANSWER.format(ctx=ctx, q=q["q"]), max_tokens=60)
                verdict = llm(K.JUDGE.format(q=q["q"], gold=q["answer"], pred=pred), max_tokens=10)[0]
                out.write(json.dumps(dict(
                    conv=c, i=i, system=name, cat=K.CATS[q["cat"]], q=q["q"], gold=q["answer"], pred=pred,
                    judge_gpt4o=verdict, correct_gpt4o="CORRECT" in verdict.upper(),
                    recall=len(set(info["sids"]) & gold_sids) / len(gold_sids) if gold_sids else None,
                    tokens=info["tokens"], secs=round(secs, 2))) + "\n")
                out.flush()
            if n % 25 == 0: print(f"question {n}/{len(plan)}, {(time.time() - t0) / n:.1f} s each", flush=True)

    rows = [r for r in map(json.loads, open(path)) if (r["conv"], r["i"]) in set(plan)]
    by = {(r["conv"], r["i"], r["system"]): r for r in rows}
    keys = [(c, i) for c, i in plan if all((c, i, s) in by for s in SYSTEMS)]

    def acc(s): return round(100 * sum(by[(c, i, s)]["correct_gpt4o"] for c, i in keys) / max(1, len(keys)), 1)

    def diff(x, y):
        pairs = [(int(by[(c, i, x)]["correct_gpt4o"]), int(by[(c, i, y)]["correct_gpt4o"])) for c, i in keys]
        return dict(points=round(acc(x) - acc(y), 1), interval_95=bootstrap_diff(pairs) if pairs else None,
                    won=sum(p > q for p, q in pairs), lost=sum(p < q for p, q in pairs))

    cats = sorted({by[(c, i, SYSTEMS[0])]["cat"] for c, i in keys})
    summary = dict(
        questions=len(keys), model=MODEL, judge=f"{MODEL} with vps_kit.JUDGE (generous LoCoMo standard)",
        accuracy={s: acc(s) for s in SYSTEMS},
        facts_vs_no_facts=diff("with_facts", "no_facts"), facts_vs_current=diff("with_facts", "current"),
        no_facts_vs_current=diff("no_facts", "current"),
        by_type={cat: {s: round(100 * sum(by[(c, i, s)]["correct_gpt4o"] for c, i in keys if by[(c, i, s)]["cat"] == cat)
                              / max(1, sum(by[(c, i, s)]["cat"] == cat for c, i in keys)), 1) for s in SYSTEMS} for cat in cats},
        evidence_found={s: round(100 * sum(by[(c, i, s)]["recall"] or 0 for c, i in keys) / max(1, len(keys)), 1) for s in SYSTEMS},
        not_mentioned={s: round(100 * sum("not mentioned" in by[(c, i, s)]["pred"].lower() for c, i in keys) / max(1, len(keys)), 1) for s in SYSTEMS},
        facts_stored=n_facts, fact_chats=len(cache),
        gemma_final_test_for_comparison="Gemma 3 4B, blind Claude labels: with facts strict 62.4 / generous 79.9; no facts 58.6 / 75.4; current 53.9 / 67.5 (776 questions)",
        caveats="GPT-4o judge scores here are the generous standard only and are not the same judge as the Gemma figures; blind strict and generous labels follow.")
    json.dump(summary, open(f"{a.save}/locomo_gpt4o_summary.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))
    print("Done", flush=True)


if __name__ == "__main__":
    main()
