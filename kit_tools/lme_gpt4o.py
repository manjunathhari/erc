"""Engram on LongMemEval-S with GPT-4o answering and the official LongMemEval GPT-4o judge.

Same answering model and judge as the published Supermemory, Zep and full-context figures, so the score can sit beside theirs.
Search is the tested design from main (open_memory, saved networks trained on LoCoMo only); nothing is tuned on this data.

  python kit_tools/lme_gpt4o.py --data longmemeval_s_cleaned.json --save results_dir --n 100

--n 100 is the fast run (first 100 test questions in hash order, about 20 minutes); --n 0 runs every question.
--start 100 --n 0 runs the rest after the first 100 (staged runs). Output files carry the question range in their names.
Work resumes where it stopped. Needs OPENAI_API_KEY.

--base2 adds a paired arm per prompt ("<prompt>+b2", Engram base 2): the same search, plus the structure layer's linked
facts (engram_structure.py) shown first as their original sentences; the excerpts fill the rest of the same total budget.
When the walk reaches no fact, the base 2 context is the base 1 context, unchanged. Writer proposals are cached per chat.
"""
import argparse, concurrent.futures, datetime, hashlib, json, math, os, random, re, sys, tempfile, time

ANSWER_MODEL = "gpt-4o-2024-08-06"  # default; --answer-model gpt-5 for the Supermemory comparison
REASONING_BUDGET = 8000  # max_completion_tokens for reasoning models; hidden reasoning counts against it


def is_reasoning(model):
    """GPT-5 and o-series models take max_completion_tokens and reject temperature, top_p and seed."""
    return model.startswith(("gpt-5", "o1", "o3", "o4")) and "chat" not in model
JUDGE_MODEL = "gpt-4o-2024-08-06"  # the official evaluate_qa.py maps "gpt-4o" to this snapshot
DEV_QUESTIONS = 30  # the same 30 development questions as the Gemma test; never counted
LONGEST_SENTENCE = 600

# ---------- data adapter, identical to kit_tools/lme_test.py at d25a8cd ----------

def split_sentences(text):
    out = []
    for piece in re.split(r"(?<=[.!?])\s+|\s*\n+\s*", text or ""):
        piece = piece.strip()
        while len(piece) > LONGEST_SENTENCE:
            cut = piece.rfind(" ", 0, LONGEST_SENTENCE)
            cut = cut if cut > 0 else LONGEST_SENTENCE
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if piece: out.append(piece)
    return out


def session_date(text):
    d = datetime.datetime.strptime(re.sub(r"\s*\(\w+\)\s*", " ", text.strip()), "%Y/%m/%d %H:%M")
    return f"{d.hour % 12 or 12}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'} on {d.day} {d.strftime('%B')}, {d.year}"


def iso_date(text):
    d = datetime.datetime.strptime(re.sub(r"\s*\(\w+\)\s*", " ", text.strip()), "%Y/%m/%d %H:%M")
    return d.strftime("%Y-%m-%d")


def hash_order(question_id):
    return hashlib.sha256(question_id.encode()).hexdigest()


def split_questions(data, dev=DEV_QUESTIONS):
    ordered = sorted(data, key=lambda q: hash_order(q["question_id"]))
    return ordered[:dev], ordered[dev:]


def session_key(session_id, session):
    return session_id + ":" + hashlib.md5(json.dumps(session, sort_keys=True).encode()).hexdigest()[:8]


def session_numbers(data):
    keys = sorted({session_key(i, s) for q in data for i, s in zip(q["haystack_session_ids"], q["haystack_sessions"])})
    return {k: n for n, k in enumerate(keys)}


def session_lines(session, number):
    lines, n = [], 0
    for t, turn in enumerate(session):
        for sentence in split_sentences(turn["content"]):
            n += 1
            lines.append((f"D{number}:{n}", turn["role"].capitalize(), sentence, t, bool(turn.get("has_answer"))))
    return lines

# ---------- official LongMemEval judge prompts, verbatim from src/evaluation/evaluate_qa.py ----------

def get_anscheck_prompt(task, question, answer, response, abstention=False):
    if not abstention:
        if task in ['single-session-user', 'single-session-assistant', 'multi-session']:
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'temporal-reasoning':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response is equivalent to the correct answer or contains all the intermediate steps to get the correct answer, you should also answer yes. If the response only contains a subset of the information required by the answer, answer no. In addition, do not penalize off-by-one errors for the number of days. If the question asks for the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'knowledge-update':
            template = "I will give you a question, a correct answer, and a response from a model. Please answer yes if the response contains the correct answer. Otherwise, answer no. If the response contains some previous information along with an updated answer, the response should be considered as correct as long as the updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        elif task == 'single-session-preference':
            template = "I will give you a question, a rubric for desired personalized response, and a response from a model. Please answer yes if the response satisfies the desired response. Otherwise, answer no. The model does not need to reflect all the points in the rubric. The response is correct as long as it recalls and utilizes the user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\nModel Response: {}\n\nIs the model response correct? Answer yes or no only."
            prompt = template.format(question, answer, response)
        else:
            raise NotImplementedError
    else:
        template = "I will give you an unanswerable question, an explanation, and a response from a model. Please answer yes if the model correctly identifies the question as unanswerable. The model could say that the information is incomplete, or some other information is given but the asked information is not.\n\nQuestion: {}\n\nExplanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the question as unanswerable? Answer yes or no only."
        prompt = template.format(question, answer, response)
    return prompt

# ---------- OpenAI calls ----------

def make_chat(fake=False):
    if fake:  # dry run without a key: answers "not mentioned", judge says no, the writer notes one preference per chat
        def fake_chat(model, prompt, max_tokens, json_mode=False):
            if json_mode and '"facts"' in prompt:  # base 2 writer: the last word of the first line, copied
                first = re.search(r"^(D\d+:\d+) (.*?)[.!?]?$", prompt, re.M)
                words = first.group(2).split() if first else []
                return json.dumps({"facts": [dict(line=first.group(1), subject="I", object=words[-1])] if words else []})
            if json_mode:
                first = re.search(r"^(D\d+:\d+) (.*)$", prompt, re.M)
                rows = [dict(type="preference", about="fake", text="Likes " + first.group(2)[:60], category="other", date=None, lines=[first.group(1)])] if first else []
                return json.dumps({"records": rows})
            return "not mentioned" if max_tokens > 10 else "no"
        return fake_chat
    from openai import OpenAI
    client = OpenAI()

    def chat(model, prompt, max_tokens, json_mode=False):
        for attempt in range(12):  # rate limits (429) can last a minute or more; back off up to 60 s each time
            try:
                if is_reasoning(model):  # default reasoning effort; the answer prompt keeps the visible answer short
                    r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], n=1, max_completion_tokens=REASONING_BUDGET)
                else:
                    extra = {"response_format": {"type": "json_object"}} if json_mode else {}
                    r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": prompt}], n=1, temperature=0, max_tokens=max_tokens, seed=7, **extra)
                text = (r.choices[0].message.content or "").strip()
                if not text and is_reasoning(model):  # budget spent on reasoning: record it, count it as answered wrong
                    return f"[no answer: {r.choices[0].finish_reason}]"
                return text
            except Exception as e:
                err = e
                time.sleep(min(60, 2 ** attempt) + random.random())
        raise RuntimeError(f"OpenAI call failed after 12 tries: {err}")
    return chat


def answer_line_summary(rows):
    """How often the line holding the answer was shown, not just its session; and where it ranked."""
    marked = [r for r in rows if r.get("answer_turns")]
    if not marked: return None
    all_shown = [r for r in marked if r["answer_turns_shown"] == r["answer_turns"]]
    at = sorted(r["first_answer_at"] for r in marked if r.get("first_answer_at") is not None)
    fits = lambda b: round(100 * sum(x <= b for x in at) / len(marked), 1)
    return dict(questions_with_marked_lines=len(marked),
                all_answer_lines_shown=round(100 * len(all_shown) / len(marked), 1),
                right_when_all_shown=round(100 * sum(r["label"] for r in all_shown) / max(1, len(all_shown)), 1),
                right_when_some_missing=round(100 * sum(r["label"] for r in marked if r not in all_shown) / max(1, len(marked) - len(all_shown)), 1),
                first_answer_line_within={"800": fits(800), "2000": fits(2000), "4000": fits(4000)},
                first_answer_line_median_tokens=at[len(at) // 2] if at else None,
                note="first_answer_at counts memory tokens in search rank order; budgets below the run's own are an estimate")


def bootstrap(values, reps=10000, seed=7):
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return round(100 * means[int(.025 * reps)], 1), round(100 * means[int(.975 * reps) - 1], 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--save", required=True)
    ap.add_argument("--n", type=int, default=100, help="test questions to run; 0 = all")
    ap.add_argument("--start", type=int, default=0, help="skip this many test questions first (hash order), for staged runs")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--context-tokens", type=int, default=800, help="memory text shown to the model (Settings.retrieved_tokens); 800 is the tested design")
    ap.add_argument("--answer-model", default=ANSWER_MODEL, help="model that writes the answers; the judge stays GPT-4o")
    ap.add_argument("--prompt", default="reason", help="answer prompt: reason (default), v2 or frozen; a comma list (reason,v2) answers every question with each prompt from one search, paired")
    ap.add_argument("--erc", action="store_true", help="add a paired ERC arm for each prompt: the bridge's preference profile first, then Engram excerpts, within the same total budget")
    ap.add_argument("--writer-model", default="gpt-4o-mini", help="model that writes the typed memory records for the ERC arm (cached per chat)")
    ap.add_argument("--profile-tokens", type=int, default=600, help="most tokens the ERC profile may take out of --context-tokens")
    ap.add_argument("--base2", action="store_true", help="add a paired base 2 arm for each prompt: linked facts from the structure layer first, then Engram excerpts, within the same total budget")
    ap.add_argument("--b2-writer-model", default=ANSWER_MODEL, help="model that proposes subject and object for base 2 (cached per chat)")
    ap.add_argument("--facts-tokens", type=int, default=1000, help="most tokens base 2's linked facts may take out of --context-tokens")
    ap.add_argument("--hops", type=int, default=4, help="links the base 2 walk follows")
    ap.add_argument("--seed-facts", type=int, default=10, help="facts on Engram's top N results also seed the base 2 walk")
    ap.add_argument("--types", default="", help="only these question types, comma-separated (e.g. single-session-preference); default all")
    ap.add_argument("--fake", action="store_true", help="dry run without OpenAI")
    ap.add_argument("--design", default="tested", help="Engram search design; 'light' only for offline tests (benchmarks use 'tested')")
    a = ap.parse_args()
    global ARGS
    ARGS = a
    os.makedirs(a.save, exist_ok=True)

    sys.path.insert(0, os.getcwd())
    import vps_kit as K
    import engram_chat as E
    from engram_memory import open_memory

    data = json.load(open(a.data))
    numbers = session_numbers(data)
    _, test = split_questions(data)
    questions = test[a.start:a.start + a.n] if a.n else test[a.start:]
    prompts = [p.strip() for p in a.prompt.split(",") if p.strip()]
    bad = [p for p in prompts if p not in K.PROMPTS]
    if bad: raise SystemExit(f"unknown prompt {bad}; choose from {sorted(K.PROMPTS)}")
    types = [t.strip() for t in a.types.split(",") if t.strip()]
    if types: questions = [q for q in questions if q["question_type"] in types]
    short = {"single-session-preference": "ssp", "single-session-user": "ssu", "single-session-assistant": "ssa", "temporal-reasoning": "tr", "multi-session": "ms", "knowledge-update": "ku"}
    rng = f"_q{a.start + 1}-{a.start + (a.n or len(test) - a.start)}"
    extra = ("" if a.answer_model == ANSWER_MODEL else "_" + a.answer_model) + ("" if a.context_tokens == 800 else f"_ctx{a.context_tokens}")
    extra += ("_only-" + "+".join(short.get(t, t) for t in types)) if types else ""
    arms = prompts + ([p + "+erc" for p in prompts] if a.erc else []) + ([p + "+b2" for p in prompts] if a.base2 else [])
    tags = {p: f"{rng}_{p.replace('+erc', 'erc').replace('+b2', 'b2')}{extra}" for p in arms}
    chat = make_chat(a.fake)
    tmp = tempfile.mkdtemp()
    out_paths = {p: f"{a.save}/lme_gpt4o_answers{tags[p]}.jsonl" for p in arms}
    done = {p: ({r["question_id"] for r in map(json.loads, open(out_paths[p]))} if os.path.exists(out_paths[p]) else set()) for p in arms}
    todo = [q for q in questions if any(q["question_id"] not in done[p] for p in arms)]
    print(f"{len(questions)} questions, {len(todo)} still to run; arms {arms}; answer model {a.answer_model}, context budget {a.context_tokens} tokens, judge {JUDGE_MODEL}", flush=True)
    if a.erc:
        import threading
        import engram_erc_bridge as B
        scorer = B._overlap_scores if a.fake else B.make_scorer()
        cache_path = f"{a.save}/erc_records_{a.writer_model}.json"
        cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
        cache_lock = threading.Lock()
        writer_pool = concurrent.futures.ThreadPoolExecutor(16)
        print(f"ERC arm: writer {a.writer_model}, {len(cache)} chats already written, profile up to {a.profile_tokens} tokens", flush=True)

        def write_chat(key, lines, d):
            reply = chat(a.writer_model, B.writer_prompt(lines, f"{session_date(d)} ({iso_date(d)})"), 900, json_mode=True)
            rows = B.parse_records(reply, iso_date(d), {i for i, _ in lines})
            with cache_lock: cache[key] = rows

        def records_for(q):
            jobs = []
            for i, s, d in zip(q["haystack_session_ids"], q["haystack_sessions"], q["haystack_dates"]):
                key = session_key(i, s)
                if key in cache: continue
                lines = [(lid, sent) for lid, speaker, sent, _, _ in session_lines(s, numbers[key]) if speaker == "User"]
                if not lines: cache[key] = []; continue
                jobs.append(writer_pool.submit(write_chat, key, lines, d))
            for j in jobs: j.result()
            if jobs:
                with cache_lock: json.dump(cache, open(cache_path, "w"))
            return {session_key(i, s): cache[session_key(i, s)] for i, s in zip(q["haystack_session_ids"], q["haystack_sessions"])}

    if a.base2:
        import threading
        import engram_structure as S
        b2_path = f"{a.save}/base2_proposals_{a.b2_writer_model}.json"
        b2_cache = json.load(open(b2_path)) if os.path.exists(b2_path) else {}
        b2_lock = threading.Lock()
        b2_pool = concurrent.futures.ThreadPoolExecutor(16)
        print(f"base 2 arm: writer {a.b2_writer_model}, {len(b2_cache)} chats already written, facts up to {a.facts_tokens} tokens, hops {a.hops}, seeds {a.seed_facts}", flush=True)

        def b2_write(key, picked):
            reply = chat(a.b2_writer_model, S.writer_prompt([(lid, t) for lid, t, _ in picked]), 1500, json_mode=True)
            kinds = {lid: k for lid, _, k in picked}
            rows = [dict(p, kind=kinds[p["line"]]) for p in S.parse_proposals(reply, set(kinds))]
            with b2_lock: b2_cache[key] = rows

        def proposals_for(q):
            """Per chat: the P2 gate picks the user's sentences, the writer proposes for those only. Written once per chat."""
            jobs = []
            for i, s, d in zip(q["haystack_session_ids"], q["haystack_sessions"], q["haystack_dates"]):
                key = session_key(i, s)
                if key in b2_cache: continue
                date = session_date(d)
                picked = []
                for lid, speaker, sentence, _, _ in session_lines(s, numbers[key]):
                    if speaker != "User": continue
                    ok, kind = S.gate(speaker, sentence, date)
                    if ok: picked.append((lid, sentence, kind))
                if not picked:
                    with b2_lock: b2_cache[key] = []
                    continue
                jobs.append(b2_pool.submit(b2_write, key, picked))
            for j in jobs: j.result()
            if jobs:
                with b2_lock: json.dump(b2_cache, open(b2_path, "w"))
            return {session_key(i, s): b2_cache[session_key(i, s)] for i, s in zip(q["haystack_session_ids"], q["haystack_sessions"])}

    def retrieve(q):
        """Replays the question's history into a fresh memory, closing each session as a chat, then searches."""
        path = f"{tmp}/{hash_order(q['question_id'])[:12]}.db"
        m = open_memory(path, design=a.design, durable=False, settings=E.Settings(retrieved_tokens=a.context_tokens))
        where, total, sid_of = {}, len(q["haystack_sessions"]), {}
        for n, (i, s, d) in enumerate(zip(q["haystack_session_ids"], q["haystack_sessions"], q["haystack_dates"]), 1):
            date = session_date(d)
            m.open_chat(date)
            for line_id, speaker, sentence, turn, answer in session_lines(s, numbers[session_key(i, s)]):
                where[line_id] = (i, turn, answer)
                sid_of[line_id] = m.add(speaker, sentence, date=date, ref=line_id, commit=False)
            m.db.commit()
            m.close_chat(write_note=False, sleep=n == total)
        ctx, info = m.context_for(q["question"])
        refs = {r[0] for sid in info["sids"] for r in m.db.execute("SELECT ref FROM sentences WHERE sid=?", (sid,))}
        hit = {where[r][0] for r in refs if r in where}
        wanted = set(q["answer_session_ids"])
        reached = len(wanted & hit) / len(wanted) if wanted else None
        # Answer lines: the turns LongMemEval marks has_answer. Shown = at least one sentence of the turn is in the context.
        # first_answer_at = memory tokens used, in search rank order, when the first answer sentence comes up (None if never).
        answer_turns = {(v[0], v[1]) for v in where.values() if v[2]}
        shown_turns, used, first_at = set(), 0, None
        for sid in info["sids"]:
            r = m.db.execute("SELECT ref, tokens FROM sentences WHERE sid=?", (sid,)).fetchone()
            if not r: continue
            used += r[1] or 0
            w = where.get(r[0])
            if w and w[2]:
                shown_turns.add((w[0], w[1]))
                if first_at is None: first_at = used
        lines = dict(answer_turns=len(answer_turns), answer_turns_shown=len(shown_turns), first_answer_at=first_at)
        ctxs = {"raw": (ctx, info["tokens"])}
        if a.erc:
            state = B.build_memory_state(records_for(q))
            prof = B.profile_section(state, q["question"], a.profile_tokens, scorer)
            budget, keep, used2 = a.context_tokens - (B.count_tokens(prof) if prof else 0), [], 0
            for sid in info["sids"]:  # same search ranking, cut to the space the profile leaves
                t = m._tokens(sid) + 8
                if used2 + t > budget: break
                keep.append(sid); used2 += t
            raw2 = m.text_of(sorted(keep)) if keep else "(no excerpts)"
            ctxs["erc"] = ((prof + "\n\n" + raw2) if prof else raw2, used2 + (B.count_tokens(prof) if prof else 0))
            lines = dict(lines, erc_records=len(state.records), erc_superseded=len(state.superseded),
                         erc_profile_tokens=B.count_tokens(prof) if prof else 0)
        if a.base2:  # filed after base 1's search, so the base 1 context cannot change
            props, layer, seen = proposals_for(q), S.StructureLayer(m.db), {"accepted": 0, "uncertain": 0, "rejected": 0}
            for i, s in zip(q["haystack_session_ids"], q["haystack_sessions"]):  # chats in their order, so versions are in order
                for p in props[session_key(i, s)]:
                    if p["line"] in sid_of: seen[layer.file(sid_of[p["line"]], p["subject"], p["object"], p.get("kind", "")).verdict] += 1
            g = layer.graph()
            fids = S.walk(g, q["question"], info["sids"][: a.seed_facts], a.hops, hubs=("User", "Assistant"))
            sec, used_f = S.facts_section(m, g, fids, a.facts_tokens)
            if sec:
                budget, keep, used3 = a.context_tokens - used_f, [], 0
                for sid in info["sids"]:  # same search ranking, cut to the space the facts leave
                    t = m._tokens(sid) + 8
                    if used3 + t > budget: break
                    keep.append(sid); used3 += t
                ctxs["b2"] = (sec + ("\n\n" + m.text_of(sorted(keep)) if keep else ""), used_f + used3)
            else:
                ctxs["b2"] = ctxs["raw"]  # nothing reached: base 2 shows exactly what base 1 shows
            lines = dict(lines, b2_proposals=sum(seen.values()), b2_accepted=seen["accepted"], b2_uncertain=seen["uncertain"],
                         b2_rejected=seen["rejected"], b2_facts=len(g.facts), b2_walked=len(fids), b2_facts_tokens=used_f)
        m.db.close()
        for tail in ("", "-wal", "-shm"):
            if os.path.exists(path + tail): os.remove(path + tail)
        return ctxs, reached, lines

    def answer_and_judge(arm, q, ctxs, reached, lines, secs):
        p = arm.replace("+erc", "").replace("+b2", "")
        ctx, tokens = ctxs["erc" if arm.endswith("+erc") else "b2" if arm.endswith("+b2") else "raw"]
        asked = f"{q['question']} (Today is {session_date(q['question_date'])}.)"
        reply = chat(a.answer_model, K.PROMPTS[p].format(ctx=ctx, q=asked), K.REPLY_TOKENS.get(p, 60))
        hyp = K.final_answer(reply) if p == "v2" else reply
        prompt = get_anscheck_prompt(q["question_type"], q["question"], q["answer"], hyp, abstention="_abs" in q["question_id"])
        verdict = chat(JUDGE_MODEL, prompt, 10)
        return dict(question_id=q["question_id"], question_type=q["question_type"], abstention="_abs" in q["question_id"], question=q["question"], answer=str(q["answer"]),
                    hypothesis=hyp, **({"reply": reply} if reply != hyp else {}), judge_reply=verdict, label="yes" in verdict.lower(), context_tokens=tokens, answer_sessions_reached=reached, **lines, retrieval_secs=round(secs, 2))

    t0 = time.time()
    outs = {p: open(out_paths[p], "a") for p in arms}
    with concurrent.futures.ThreadPoolExecutor(a.threads) as pool:
        futures = []
        def flush(wait=False):
            for f, p in [x for x in futures if wait or x[0].done()]:
                outs[p].write(json.dumps(f.result()) + "\n"); outs[p].flush(); futures.remove((f, p))
        for n, q in enumerate(todo, 1):
            s0 = time.time()
            ctxs, reached, lines = retrieve(q)  # one search per question; every arm answers from the same search
            for p in arms:
                if q["question_id"] not in done[p]:
                    futures.append((pool.submit(answer_and_judge, p, q, ctxs, reached, lines, time.time() - s0), p))
            if n % 10 == 0: print(f"searched {n}/{len(todo)}, {(time.time() - t0) / n:.1f} s each", flush=True)
            flush()
        flush(wait=True)
    for f in outs.values(): f.close()

    wanted_ids = {q["question_id"] for q in questions}
    results = {p: summarise(p, [r for r in map(json.loads, open(out_paths[p])) if r["question_id"] in wanted_ids], tags[p]) for p in arms}
    if len(arms) > 1: compare_prompts(arms, out_paths, wanted_ids, f"{a.save}/lme_gpt4o_compare{rng}_{'-vs-'.join(t.replace('+erc', 'erc').replace('+b2', 'b2') for t in arms)}{extra}.json")
    if a.erc: writer_pool.shutdown()
    if a.base2: b2_pool.shutdown()
    print("Done", flush=True)


def summarise(p, rows, tag):
    labels = [int(r["label"]) for r in rows]
    by_type = {}
    for r in rows: by_type.setdefault(r["question_type"], []).append(int(r["label"]))
    reached = [r["answer_sessions_reached"] for r in rows if r["answer_sessions_reached"] is not None]
    summary = dict(
        questions=len(rows), answer_prompt=p, context_tokens_budget=ARGS.context_tokens, answer_model=ARGS.answer_model, no_answer=sum(r["hypothesis"].startswith("[no answer") for r in rows), judge=JUDGE_MODEL, search="Engram tested design (open_memory, main)",
        accuracy=round(100 * sum(labels) / max(1, len(labels)), 1), interval_95=bootstrap(labels) if labels else None,
        by_type={k: dict(n=len(v), accuracy=round(100 * sum(v) / len(v), 1)) for k, v in sorted(by_type.items())},
        not_answerable=dict(n=sum(r["abstention"] for r in rows), right=sum(r["label"] for r in rows if r["abstention"])),
        all_answer_sessions_reached=round(100 * sum(x == 1 for x in reached) / max(1, len(reached)), 1),
        answer_lines=answer_line_summary(rows),
        mean_context_tokens=round(sum(r["context_tokens"] for r in rows) / max(1, len(rows))),
        published_for_comparison="Supermemory report, LongMemEval-S, GPT-4o judge: Zep 71.2, full context 60.2; Supermemory 84.6 (GPT-5 answers), 85.2 (Gemini 3 Pro). Their 97 (GPT-4o row) equals their Recall@20.",
        caveats="Fast run is a sample of the 470 test questions, so its interval is wide; the published figures use all 500. Errors are not dropped: every question is in the score.")
    json.dump(summary, open(f"{ARGS.save}/lme_gpt4o_summary{tag}.json", "w"), indent=1)
    print(json.dumps(summary, indent=1))
    return summary


def compare_prompts(prompts, out_paths, wanted_ids, path):
    """Paired comparison of each later prompt against the first, on the questions every prompt answered."""
    rows = {p: {r["question_id"]: r for r in map(json.loads, open(out_paths[p])) if r["question_id"] in wanted_ids} for p in prompts}
    base = prompts[0]
    out = {}
    for p in prompts[1:]:
        ids = sorted(set(rows[base]) & set(rows[p]))
        pairs = [(int(rows[p][i]["label"]), int(rows[base][i]["label"])) for i in ids]
        rng = random.Random(7); n = len(pairs)
        d = sorted(sum(x - y for x, y in (pairs[rng.randrange(n)] for _ in range(n))) / n for _ in range(10000)) if n else [0]
        types = sorted({rows[base][i]["question_type"] for i in ids})
        out[f"{p}_vs_{base}"] = dict(
            questions=n, points=round(100 * sum(x - y for x, y in pairs) / max(1, n), 1),
            interval_95=[round(100 * d[250], 1), round(100 * d[9749], 1)] if n else None,
            won=sum(x > y for x, y in pairs), lost=sum(x < y for x, y in pairs),
            by_type={t: dict(n=sum(rows[base][i]["question_type"] == t for i in ids),
                             **{q: sum(rows[q][i]["label"] for i in ids if rows[base][i]["question_type"] == t) for q in (base, p)}) for t in types},
            not_mentioned_on_answerable={q: sum("not mentioned" in rows[q][i]["hypothesis"].lower() for i in ids if not rows[q][i]["abstention"]) for q in (base, p)},
            unanswerable_right={q: sum(rows[q][i]["label"] for i in ids if rows[q][i]["abstention"]) for q in (base, p)})
    json.dump(out, open(path, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
