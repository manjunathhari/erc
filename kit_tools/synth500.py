"""Synthetic 500-question lab benchmark for the Engram -> adapter -> ERC unit (ADAPTER_REQUIREMENTS.md, acceptance test 3).

150 preference, 150 multi-hop (2-4 hops), 200 single-hop/temporal, all with dated updates and distractors, ingested
through a real ChatMemory and filed through the base-2 structure layer by a deterministic writer (the generator knows
each sentence's subject and object, so this measures the memory unit, not a writer model). No answer model: a question
passes when the gold answer is in the context the unit hands the model and no stale answer is.

Three contexts are compared on the same memory:
  base1    ChatMemory.context_for (search only)
  base2    structure-layer walk (every version) + excerpts, no gate   (what arm B did)
  adapter  engram_erc_adapter.Adapter.context_for                     (ERC verdicts govern the context)

    python kit_tools/synth500.py --save results/synth500 [--design light|tested] [--seed 7]
"""
import argparse, json, os, random, re, sys, tempfile, time
sys.path.insert(0, os.getcwd())

MONTHS = "January February March April May June July August September October November December".split()
PEOPLE = ["Asha", "Ravi", "Meera", "Karan", "Divya", "Arjun", "Nisha", "Rohan", "Priya", "Vikram", "Sneha", "Aditya", "Kavya", "Rahul", "Ananya",
          "Siddharth", "Pooja", "Manish", "Lakshmi", "Varun", "Isha", "Nikhil", "Tara", "Dev", "Rhea", "Kabir", "Zara", "Aman", "Leela", "Farhan",
          "Gauri", "Harish", "Ira", "Jay", "Kiran", "Maya", "Neel", "Omar", "Pallavi", "Rishi", "Sara", "Tanvi", "Uday", "Vani", "Yash"]
CITIES = ["Pune", "Delhi", "Goa", "Mumbai", "Chennai", "Kochi", "Jaipur", "Lucknow", "Indore", "Surat", "Nagpur", "Bhopal", "Mysuru", "Hubli",
          "Madurai", "Vizag", "Patna", "Ranchi", "Raipur", "Shimla", "Dehradun", "Udaipur", "Agra", "Kanpur", "Thrissur"]
STATES = {"Pune": "Maharashtra", "Mumbai": "Maharashtra", "Nagpur": "Maharashtra", "Delhi": "Delhi NCR", "Goa": "Goa", "Chennai": "Tamil Nadu",
          "Madurai": "Tamil Nadu", "Kochi": "Kerala", "Thrissur": "Kerala", "Jaipur": "Rajasthan", "Udaipur": "Rajasthan", "Lucknow": "Uttar Pradesh",
          "Agra": "Uttar Pradesh", "Kanpur": "Uttar Pradesh", "Indore": "Madhya Pradesh", "Bhopal": "Madhya Pradesh", "Surat": "Gujarat",
          "Mysuru": "Karnataka", "Hubli": "Karnataka", "Vizag": "Andhra Pradesh", "Patna": "Bihar", "Ranchi": "Jharkhand", "Raipur": "Chhattisgarh",
          "Shimla": "Himachal Pradesh", "Dehradun": "Uttarakhand"}
COMPANIES = ["Infosys", "Wipro", "Zoho", "Freshworks", "Razorpay", "Swiggy", "Zomato", "Ola", "Byju", "Paytm", "PhonePe", "Flipkart", "Meesho",
             "Cred", "Groww", "Zerodha", "Nykaa", "Dream11", "Udaan", "Delhivery", "Tata Motors", "Mahindra", "Biocon", "Narayana", "Apollo"]
RELATIVES = ["sister", "brother", "boss", "manager", "doctor", "partner"]
PREF = {"drink": ["filter coffee", "masala chai", "green tea", "cold brew", "buttermilk", "lassi", "lemonade", "hot chocolate"],
        "food": ["masala dosa", "biryani", "pav bhaji", "idli", "rajma chawal", "pani puri", "momos", "thali"],
        "music": ["Carnatic music", "jazz", "lo-fi beats", "Bollywood classics", "indie rock", "ghazals", "techno", "folk"],
        "seat": ["window seats", "aisle seats", "front-row seats", "exit-row seats", "corner tables", "bar stools", "balcony seats", "lounge chairs"],
        "weather": ["cool weather", "rainy days", "winter mornings", "warm evenings", "misty hills", "sea breezes", "monsoon afternoons", "crisp autumn air"],
        "sport": ["cricket", "badminton", "tennis", "football", "chess", "cycling", "swimming", "running"]}
SMALLTALK = ["Nice weather today.", "Can you help me with something?", "Thanks, that was useful.", "Let me think about it.", "What time is it there?",
             "I had a long day.", "Remind me later.", "That sounds good.", "Hello again!", "Could you summarise that?", "Not sure yet.", "Okay, noted.",
             "Traffic was terrible this morning.", "I need to finish a report.", "The meeting ran late.", "Let's pick this up tomorrow."]


def date_str(y, mo, d): return f"9:00 am on {d} {MONTHS[mo - 1]}, {y}"
def iso(y, mo, d): return f"{y:04d}-{mo:02d}-{d:02d}"


def build_world(seed):
    R = random.Random(seed); build_world.used = set()
    events = []   # (date tuple, speaker, text, subject, object, kind) ; subject None = not filed
    questions = []
    months = [(2024, m) for m in range(1, 13)] + [(2025, m) for m in range(1, 7)]
    def when(i): y, m = months[i]; return (y, m, R.randint(1, 27))
    hq = {}
    for c in COMPANIES: hq[c] = R.choice(CITIES); events.append((when(R.randint(0, 2)), "User", f"{c} is headquartered in {hq[c]}.", c, hq[c], ""))
    for city, state in STATES.items(): events.append((when(R.randint(0, 2)), "User", f"{city} is in {state}.", city, state, ""))
    people = list(PEOPLE); R.shuffle(people)

    # ---- single-hop / temporal: 200 ----
    sh = people[:40]
    for k, p in enumerate(sh):
        n_updates = [0, 1, 2, 3][k % 4]
        vals = R.sample(CITIES, n_updates + 1); times = sorted(R.sample(range(0, 16), n_updates + 1))
        for v, t in zip(vals, times): events.append((when(t), "User", f"{p} lives in {v}.", p, v, ""))
        questions.append(dict(cat="single", kind="current", q=f"Where does {p} live?", gold=[vals[-1]], stale=[f"{p} lives in {v}." for v in vals[:-1]]))
        if n_updates:  # temporal: ask about the period of an earlier version
            i = R.randrange(n_updates); y, m = months[times[i]]
            # a month strictly inside version i's period (after its start month, before the next start month)
            ny, nm = months[times[i + 1]]
            cand = [j for j in range(times[i], times[i + 1]) if j > times[i]] or [times[i]]
            qy, qm = months[cand[-1]]
            questions.append(dict(cat="single", kind="temporal", q=f"Where did {p} live in {MONTHS[qm - 1]} {qy}?", gold=[vals[i]], stale=[f"{p} lives in {v}." for v in vals if v != vals[i]]))
        spouse = R.choice([x for x in PEOPLE if x != p]); events.append((when(R.randint(0, 16)), "User", f"{p} is married to {spouse}.", p, spouse, ""))
        cos = R.sample(COMPANIES, 2); tw = sorted(R.sample(range(0, 17), 2))
        for c_, t_ in zip(cos, tw): events.append((when(t_), "User", f"{p} works at {c_}.", p, c_, ""))
        questions.append(dict(cat="single", kind="current", q=f"Which company does {p} work at?", gold=[cos[-1]], stale=[f"{p} works at {cos[0]}."]))
        qy, qm = months[tw[0]] if tw[1] > tw[0] + 1 else months[tw[0]]
        if tw[1] > tw[0]: questions.append(dict(cat="single", kind="temporal", q=f"Where did {p} work in {MONTHS[qm - 1]} {qy}?", gold=[cos[0]], stale=[f"{p} works at {cos[1]}."]))
        questions.append(dict(cat="single", kind="stable", q=f"Who is {p} married to?", gold=[spouse], stale=[]))
        if len(questions) >= 200: break
    questions = questions[:200]

    # ---- multi-hop: 150 ----  chains start from a named anchor person: anchor's <role> is P; P works at C; C hq City; City in State
    anchors = list(PEOPLE); ci = 0
    ROLES = ["manager", "mentor", "neighbour", "landlord", "trainer", "accountant", "cousin", "roommate"]
    while len(questions) < 350:
        anchor = anchors[ci % len(anchors)]; role = ROLES[(ci // len(anchors)) % len(ROLES)]; ci += 1
        S1 = ["Kav", "Rit", "Vol", "Nem", "Sur", "Tul", "Mir", "Lok", "Dev", "Pal", "Bhu", "Jag"]; S2 = ["anth", "esh", "ika", "ora", "ind", "ush", "ael", "oni", "ami", "uru", "eet", "aan"]
        p = S1[ci % 12] + S2[(ci // 12) % 12] + ("", "a", "i")[(ci // 144) % 3]   # 432 distinct invented names, none sharing a token with PEOPLE
        t0 = R.randint(0, 6)
        events.append((when(t0), "User", f"{anchor}'s {role} is {p}.", anchor, p, ""))
        c_old, c_new = R.sample(COMPANIES, 2)
        updated = ci % 2 == 0
        events.append((when(t0 + 1), "User", f"{p} works at {c_old}.", p, c_old, ""))
        if updated: events.append((when(t0 + 5), "User", f"{p} works at {c_new}.", p, c_new, ""))
        cur = c_new if updated else c_old
        depth = [2, 3, 4][ci % 3]; upd = "-upd" if updated else ""
        stale_sent = [f"{p} works at {c_old}."] if updated else []
        if depth == 2:
            questions.append(dict(cat="multi", kind="hop2" + upd, q=f"Which company does {anchor}'s {role} work at?", gold=[cur], stale=stale_sent))
        elif depth == 3:
            questions.append(dict(cat="multi", kind="hop3" + upd, q=f"In which city is the company where {anchor}'s {role} works headquartered?", gold=[hq[cur]], stale=stale_sent))
        else:
            questions.append(dict(cat="multi", kind="hop4" + upd, q=f"Which state is the headquarters of the company where {anchor}'s {role} works in?", gold=[STATES[hq[cur]]], stale=stale_sent))

    # ---- preference: 150 ----
    pk = 0
    cats = list(PREF)
    while len(questions) < 500:
        cat = cats[pk % len(cats)]; kind = ["stable", "retracted", "repeated"][pk % 3]
        ADJ = ["strong", "mild", "iced", "spicy", "classic", "homemade", "late-night", "weekend", "morning", "festival", "street-style", "regional"]
        used_vals = R.__dict__.setdefault("_used_vals", set()) if False else build_world.__dict__.setdefault("used", set()); opts = []
        for a_ in ADJ:
            for b_ in PREF[cat]:
                v_ = f"{a_} {b_}"
                if v_ not in used_vals and len(opts) < 2: used_vals.add(v_); opts.append(v_)
        pk += 1
        t0 = R.randint(0, 12)
        if kind == "stable":
            events.append((when(t0), "User", f"I like {opts[0]}.", "I", opts[0], "preference"))
            questions.append(dict(cat="pref", kind="stable", q=f"Recommend a {cat} option for the user.", gold=[opts[0]], stale=[]))
        elif kind == "retracted":
            events.append((when(t0), "User", f"I like {opts[0]}.", "I", opts[0], "preference"))
            events.append((when(t0 + 3), "User", f"I no longer like {opts[0]}.", "I", opts[0], "preference"))
            events.append((when(t0 + 4), "User", f"I like {opts[1]}.", "I", opts[1], "preference"))
            questions.append(dict(cat="pref", kind="retracted", q=f"Suggest a {cat} the user would enjoy.", gold=[opts[1]], stale=[f"I like {opts[0]}."]))
        else:
            for t in sorted(R.sample(range(0, 17), 3)): events.append((when(t), "User", f"I like {opts[0]}.", "I", opts[0], "preference"))
            questions.append(dict(cat="pref", kind="repeated", q=f"What {cat} does the user go for?", gold=[opts[0]], stale=[]))

    # distractors: small talk, roughly one per two facts
    for _ in range(len(events) // 2): events.append((when(R.randint(0, 17)), "User", R.choice(SMALLTALK), None, None, ""))
    events.sort(key=lambda e: e[0])
    return events, questions


def ingest(events, design):
    import engram_chat as E
    from engram_memory import open_memory
    from engram_structure import StructureLayer
    m = open_memory(f"{tempfile.mkdtemp()}/synth.db", design=design, durable=False, settings=E.Settings(retrieved_tokens=4000))
    L = StructureLayer(m.db)
    stats = dict(sentences=0, filed=0, accepted=0, uncertain=0, rejected=0)
    cur_day, open_ = None, False
    for (y, mo, d), speaker, text, subj, obj, kind in events:
        day = (y, mo, d)
        if day != cur_day:
            if open_: m.close_chat(write_note=False, sleep=False)
            m.open_chat(date_str(*day)); cur_day, open_ = day, True
        sid = m.add(speaker, text, date=date_str(*day)); stats["sentences"] += 1
        if subj:
            o = L.file(sid, subj, obj, kind); stats["filed"] += 1; stats[o.verdict] += 1
    if open_: m.close_chat(write_note=False, sleep=True)
    return m, L, stats


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--save", default="results/synth500"); ap.add_argument("--design", default="tested"); ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(); os.makedirs(a.save, exist_ok=True)
    events, questions = build_world(a.seed)
    t0 = time.time(); m, L, stats = ingest(events, a.design); print(f"ingested {stats} in {time.time()-t0:.0f}s", flush=True)
    import engram_structure as S
    from engram_erc_adapter import Adapter, norm
    A = Adapter(m)
    g = S.graph if False else L.graph()

    def base2_context(q):
        sids, info = m.find(q)
        reached = S.walk(g, q, seed_sids=list(sids)[:10], hubs=("User",))
        text, used = S.facts_section(m, g, reached, 2000)
        keep, u = [], 0
        for sid in sids:
            t = m._tokens(sid) + 8
            if used + u + t > 4000: break
            keep.append(sid); u += t
        return "\n\n".join(x for x in (text, m.text_of(sorted(keep)) if keep else "") if x) or "(nothing found)"

    def has(ctx, val, positive_only=False):
        if positive_only: ctx = "\n".join(l for l in ctx.splitlines() if "no longer" not in l.lower())
        return f" {norm(val)} " in f" {norm(ctx)} "
    rows, t0 = [], time.time()
    for i, qq in enumerate(questions):
        ctxs = {"base1": m.context_for(qq["q"])[0], "base2": base2_context(qq["q"])}
        adp, info = A.context_for(qq["q"]); ctxs["adapter"] = adp
        row = dict(i=i, **qq, withheld=len(info["withheld"]))
        for arm, ctx in ctxs.items():
            row[arm] = dict(gold=any(has(ctx, v) for v in qq["gold"]), stale=any(v.lower() in ctx.lower() for v in qq["stale"]), tokens=len(ctx) // 4)
        rows.append(row)
        if (i + 1) % 100 == 0: print(f"  {i+1}/500 ({time.time()-t0:.0f}s)", flush=True)
    json.dump(rows, open(f"{a.save}/rows.json", "w"), indent=0)

    def summarize(sel, name):
        out = {}
        for arm in ("base1", "base2", "adapter"):
            n = len(sel); g_ = sum(r[arm]["gold"] for r in sel); with_stale = [r for r in sel if r["stale"]]
            s_ = sum(r[arm]["stale"] for r in with_stale); pass_ = sum(r[arm]["gold"] and not r[arm]["stale"] for r in sel)
            out[arm] = dict(n=n, gold_in_context=g_, stale_in_context=f"{s_}/{len(with_stale)}", passed=pass_, pass_pct=round(100 * pass_ / max(1, n), 1), mean_tokens=sum(r[arm]["tokens"] for r in sel) // max(1, n))
        return out
    summary = dict(design=a.design, seed=a.seed, ingest=stats, total=summarize(rows, "all"))
    for cat in ("pref", "multi", "single"): summary[cat] = summarize([r for r in rows if r["cat"] == cat], cat)
    for kind in sorted({r["kind"] for r in rows}): summary["by_kind_" + kind] = {arm: summarize([r for r in rows if r["kind"] == kind], kind)[arm]["pass_pct"] for arm in ("base1", "base2", "adapter")}
    json.dump(summary, open(f"{a.save}/summary.json", "w"), indent=1); print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
