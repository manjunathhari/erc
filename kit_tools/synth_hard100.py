"""Hard 100: a hostile 100-question set for the Engram -> adapter -> ERC unit, with an answer model in the loop.

Designed to break things: same-day conflicts, updates inside one month then a question about that month, retraction then
re-statement, double negation, count updates inside a multi-valued relation, chains updated at two hops, questions that name
no entity, questions about a value "before" another with no date, facts never stated (gold: not mentioned), a second speaker
with opposite tastes, look-alike names, and 600 lines of small talk. 30 preference / 30 multi-hop / 40 single-hop+temporal.

    python kit_tools/synth_hard100.py --out results/hard100   # writes items.jsonl (context per question) + batches for the model
"""
import argparse, json, os, random, sys, tempfile
sys.path.insert(0, os.getcwd())

MONTHS = "January February March April May June July August September October November December".split()
def D(d, mo, y=2024): return f"9:00 am on {d} {MONTHS[mo-1]}, {y}"

SMALL = ["Nice weather today.", "Can you help me with something?", "Thanks, that was useful.", "Let me think about it.", "I had a long day.",
         "Remind me later.", "That sounds good.", "Hello again!", "Could you summarise that?", "Not sure yet.", "Okay, noted.", "Traffic was terrible.",
         "I need to finish a report.", "The meeting ran late.", "Let's pick this up tomorrow.", "What a week.", "Anyway, moving on.", "Back to work."]


def world(seed=5):
    R = random.Random(seed); ev = []; Q = []
    def say(date, text, subj=None, obj=None, kind="", speaker="User"): ev.append((date, speaker, text, subj, obj, kind))
    def q(cat, kind, text, gold, stale=(), note=""): Q.append(dict(cat=cat, kind=kind, q=text, gold=list(gold), stale=list(stale), note=note))

    # ---------- single-hop / temporal (40) ----------
    # 1-4 same-day conflict: two statements the same day, newest recorded wins
    for i, (p, a, b) in enumerate([("Asha", "Pune", "Delhi"), ("Ravi", "Goa", "Kochi"), ("Meera", "Surat", "Indore"), ("Karan", "Agra", "Jaipur")]):
        say(D(5, 3), f"{p} lives in {a}.", p, a); say(D(5, 3), f"{p} lives in {b}.", p, b)
        q("single", "same-day", f"Where does {p} live?", [b], [f"{p} lives in {a}."])
    # 5-8 update inside one month, then ask about that month (gold: the LATER value, in force at month end)
    for p, a, b in [("Divya", "Mysuru", "Hubli"), ("Arjun", "Patna", "Ranchi"), ("Nisha", "Shimla", "Dehradun"), ("Rohan", "Udaipur", "Agra")]:
        say(D(3, 5), f"{p} lives in {a}.", p, a); say(D(20, 5), f"{p} lives in {b}.", p, b)
        q("single", "temporal-same-month", f"Where did {p} live in May 2024?", [b], [], "value in force at the end of May")
    # 9-12 three versions, ask about the middle period
    for p, a, b, c in [("Priya", "Kanpur", "Lucknow", "Agra"), ("Vikram", "Vizag", "Chennai", "Madurai"), ("Sneha", "Kochi", "Thrissur", "Goa"), ("Aditya", "Raipur", "Bhopal", "Indore")]:
        say(D(1, 1), f"{p} lives in {a}.", p, a); say(D(1, 4), f"{p} lives in {b}.", p, b); say(D(1, 8), f"{p} lives in {c}.", p, c)
        q("single", "temporal-middle", f"Where did {p} live in June 2024?", [b], [f"{p} lives in {a}.", f"{p} lives in {c}."])
    # 13-16 "before X" with no date: expects the previous value (the adapter has no as_of for this -> likely miss)
    for p, a, b in [("Kavya", "Nagpur", "Pune"), ("Rahul", "Delhi", "Mumbai"), ("Ananya", "Jaipur", "Udaipur"), ("Siddharth", "Hubli", "Mysuru")]:
        say(D(2, 2), f"{p} lives in {a}.", p, a); say(D(2, 7), f"{p} lives in {b}.", p, b)
        q("single", "before-no-date", f"Where did {p} live before moving to {b}?", [a], [], "history asked without a date")
    # 17-20 count updates inside a multi-valued relation
    for p, n1, n2, thing in [("Pooja", 2, 3, "cats"), ("Manish", 1, 2, "cars"), ("Lakshmi", 3, 5, "bikes"), ("Varun", 4, 2, "guitars")]:
        say(D(10, 2), f"{p} has {n1} {thing}.", p, f"{n1} {thing}"); say(D(10, 9), f"{p} has {n2} {thing}.", p, f"{n2} {thing}")
        q("single", "count-update", f"How many {thing} does {p} have?", [str(n2)], [f"{p} has {n1} {thing}."])
    # 21-24 never stated -> not mentioned
    for p in ["Isha", "Nikhil", "Tara", "Dev"]:
        say(D(3, 3), f"{p} lives in Chennai.", p, "Chennai")
        q("single", "not-mentioned", f"Who is {p} married to?", ["not mentioned"], [], "fact never stated")
    # 25-28 look-alike names: base 2's resolver should NOT merge them
    for p, p2, a, b in [("Rhea", "Rhea Kapoor", "Goa", "Pune"), ("Kabir", "Kabir Das", "Delhi", "Kochi"), ("Zara", "Zara Ali", "Surat", "Agra"), ("Aman", "Aman Gill", "Indore", "Bhopal")]:
        say(D(4, 4), f"{p} lives in {a}.", p, a); say(D(4, 6), f"{p2} lives in {b}.", p2, b)
        q("single", "look-alike", f"Where does {p} live?", [a], [f"{p2} lives in {b}."], "the look-alike must not overwrite")
    # 29-32 spouse stable + forget-proof restatement (Pune -> Delhi -> Pune)
    for p, a, b in [("Leela", "Pune", "Delhi"), ("Farhan", "Goa", "Kochi"), ("Gauri", "Jaipur", "Agra"), ("Harish", "Mysuru", "Hubli")]:
        say(D(1, 2), f"{p} lives in {a}.", p, a); say(D(1, 5), f"{p} lives in {b}.", p, b); say(D(1, 9), f"{p} lives in {a}.", p, a)
        q("single", "restated", f"Where does {p} live?", [a], [f"{p} lives in {b}."])
    # 33-36 works_at updated twice, ask current
    for p, c1, c2, c3 in [("Ira", "Zoho", "Infosys", "Wipro"), ("Jay", "Swiggy", "Zomato", "Ola"), ("Kiran", "Paytm", "PhonePe", "Cred"), ("Maya", "Nykaa", "Meesho", "Udaan")]:
        say(D(1, 1), f"{p} works at {c1}.", p, c1); say(D(1, 5), f"{p} works at {c2}.", p, c2); say(D(1, 10), f"{p} works at {c3}.", p, c3)
        q("single", "current-3", f"Which company does {p} work at?", [c3], [f"{p} works at {c1}.", f"{p} works at {c2}."])
    # 37-40 question phrased unlike the statement
    for p, c in [("Neel", "Razorpay"), ("Omar", "Groww"), ("Pallavi", "Zerodha"), ("Rishi", "Dream11")]:
        say(D(7, 7), f"{p} works at {c}.", p, c)
        q("single", "paraphrase", f"Who is {p}'s employer?", [c], [])

    # ---------- multi-hop (30) ----------
    COMP = {"Infosys": "Bengaluru", "Wipro": "Bengaluru", "Zoho": "Chennai", "Freshworks": "Chennai", "Razorpay": "Bengaluru", "Swiggy": "Bengaluru", "Zomato": "Gurugram",
            "Ola": "Bengaluru", "Paytm": "Noida", "PhonePe": "Bengaluru", "Flipkart": "Bengaluru", "Meesho": "Bengaluru", "Cred": "Bengaluru", "Groww": "Bengaluru",
            "Zerodha": "Bengaluru", "Nykaa": "Mumbai", "Dream11": "Mumbai", "Udaan": "Bengaluru", "Delhivery": "Gurugram", "Biocon": "Bengaluru", "Apollo": "Chennai",
            "Tata Motors": "Mumbai", "Mahindra": "Mumbai", "Narayana": "Bengaluru", "Byju": "Bengaluru"}
    STATE = {"Bengaluru": "Karnataka", "Chennai": "Tamil Nadu", "Gurugram": "Haryana", "Noida": "Uttar Pradesh", "Mumbai": "Maharashtra"}
    for c, city in COMP.items(): say(D(2, 1), f"{c} is headquartered in {city}.", c, city)
    for city, st in STATE.items(): say(D(3, 1), f"{city} is in {st}.", city, st)
    names = ["Tulika", "Miresh", "Volora", "Nemika", "Suresh", "Palanth", "Lokika", "Devanth", "Kavora", "Ritesh", "Bhuvi", "Jagath", "Surind", "Tulesh", "Mirora",
             "Lokanth", "Devora", "Palika", "Bhuesh", "Jagora", "Kavind", "Ritora", "Volesh", "Nemanth", "Surika", "Tulanth", "Mirind", "Lokesh", "Devush", "Palaan"]
    comps = list(COMP); R.shuffle(comps)
    for i, p in enumerate(names):
        anchor = ["Asha", "Ravi", "Meera", "Karan", "Divya", "Arjun"][i % 6]; role = ["manager", "mentor", "neighbour", "landlord", "trainer"][i % 5]
        c1, c2 = comps[i % len(comps)], comps[(i + 7) % len(comps)]
        say(D(5, 1), f"{anchor}'s {role} is {p}.", anchor, p)
        kind = i % 6
        if kind == 0:   # plain 3-hop
            say(D(6, 1), f"{p} works at {c1}.", p, c1)
            q("multi", "hop3", f"In which city is the company where {anchor}'s {role} works headquartered?", [COMP[c1]])
        elif kind == 1:  # hop-2 updated
            say(D(6, 1), f"{p} works at {c1}.", p, c1); say(D(6, 6), f"{p} works at {c2}.", p, c2)
            q("multi", "hop3-upd", f"In which city is the company where {anchor}'s {role} works headquartered?", [COMP[c2]], [f"{p} works at {c1}."])
        elif kind == 2:  # hop-1 AND hop-2 updated: anchor changes role-person, new person changes company
            p2 = names[(i + 11) % len(names)] + "x"
            say(D(6, 1), f"{p} works at {c1}.", p, c1); say(D(6, 7), f"{anchor}'s {role} is {p2}.", anchor, p2); say(D(6, 7), f"{p2} works at {c2}.", p2, c2)
            q("multi", "hop3-two-updates", f"In which city is the company where {anchor}'s {role} works headquartered?", [COMP[c2]], [f"{p} works at {c1}.", f"{anchor}'s {role} is {p}."])
        elif kind == 3:  # 4-hop to state, with update
            say(D(6, 1), f"{p} works at {c1}.", p, c1); say(D(6, 8), f"{p} works at {c2}.", p, c2)
            q("multi", "hop4-upd", f"Which state is the headquarters of the company where {anchor}'s {role} works in?", [STATE[COMP[c2]]], [f"{p} works at {c1}."])
        elif kind == 4:  # question names no entity: via the user's own relative
            rel = ["sister", "brother", "boss"][i % 3]
            say(D(6, 2), f"My {rel} is {p}.", f"my {rel}", p); say(D(6, 3), f"{p} works at {c1}.", p, c1)
            q("multi", "hub-rel", f"Where is my {rel}'s employer headquartered?", [COMP[c1]], [], "no entity named; hub relation seed")
        else:            # chain broken: hop-2 never stated
            q("multi", "chain-gap", f"In which city is the company where {anchor}'s {role} works headquartered?", ["not mentioned"], [], "employer never stated")

    # ---------- preference (30) ----------
    PREF = [("drink", "strong filter coffee", "iced masala chai"), ("food", "spicy biryani", "plain idli"), ("music", "Carnatic music", "lo-fi beats"),
            ("seat", "window seats", "aisle seats"), ("weather", "rainy days", "winter mornings"), ("sport", "badminton", "chess"),
            ("dessert", "rasmalai", "gulab jamun"), ("fruit", "mangoes", "jackfruit"), ("snack", "murukku", "banana chips"), ("tea", "ginger tea", "lemon tea")]
    for i, (cat, a, b) in enumerate(PREF):
        kind = i % 5
        if kind == 0:   # retract then re-like
            say(D(1, 2), f"I like {a}.", "I", a, "preference"); say(D(1, 4), f"I no longer like {a}.", "I", a, "preference"); say(D(1, 6), f"I like {a}.", "I", a, "preference")
            q("pref", "retract-relike", f"Pick a {cat} for the user.", [a], [], "re-liked after retraction")
        elif kind == 1: # retract, like other; second speaker likes the retracted one
            say(D(1, 2), f"I like {a}.", "I", a, "preference"); say(D(1, 4), f"I no longer like {a}.", "I", a, "preference"); say(D(1, 5), f"I like {b}.", "I", b, "preference")
            say(D(1, 5), f"I like {a}.", "I", a, "preference", speaker="Ravi")
            q("pref", "retract-other-speaker", f"Suggest a {cat} the user would enjoy.", [b], [f"User: I like {a}."], "Ravi's taste must not leak as the user's")
        elif kind == 2: # double negation / not a retraction
            say(D(1, 2), f"I like {a}.", "I", a, "preference"); say(D(1, 4), f"I don't think I will ever stop liking {a}.", "I", a, "preference")
            q("pref", "double-negation", f"What {cat} does the user like?", [a], [], "'don't ... stop liking' is not a retraction")
        elif kind == 3: # stated 3 times vs other stated once; ask for the favourite
            for m_ in (1, 3, 5): say(D(1, m_), f"I like {a}.", "I", a, "preference")
            say(D(1, 2), f"I like {b}.", "I", b, "preference")
            q("pref", "repeated-vs-once", f"Which {cat} does the user mention most?", [a], [])
        else:           # like, then dislike a different one; ask what to avoid
            say(D(1, 2), f"I like {a}.", "I", a, "preference"); say(D(1, 3), f"I dislike {b}.", "I", b, "preference")
            q("pref", "avoid", f"Which {cat} should be avoided for the user?", [b], [])
    # 11-30: twenty more, mixed phrasing and categories, unique values
    extra = [("coffee", "cold brew"), ("pizza", "thin crust"), ("holiday", "hill stations"), ("book", "detective novels"), ("exercise", "morning runs"),
             ("car", "small hatchbacks"), ("phone", "compact phones"), ("colour", "deep green"), ("film", "slow cinema"), ("hobby", "woodworking"),
             ("cuisine", "Chettinad food"), ("transport", "trains over flights"), ("breakfast", "upma"), ("workspace", "quiet cafes"), ("pet", "indie dogs"),
             ("season", "late monsoon"), ("game", "carrom"), ("newspaper", "The Hindu"), ("shoes", "leather sandals"), ("writing", "fountain pens")]
    for i, (cat, v) in enumerate(extra):
        if i % 4 == 3:
            say(D(2, 3), f"I like {v}.", "I", v, "preference"); say(D(2, 8), f"I no longer like {v}.", "I", v, "preference")
            q("pref", "retracted-only", f"Does the user like {v}?", ["no"], [f"User: I like {v}."], "only a retraction stands; expected answer: no / not any more")
        else:
            say(D(2, 3 + i % 5), f"I like {v}.", "I", v, "preference")
            q("pref", "indirect", f"Recommend a {cat} for the user.", [v], [])

    # small talk, 600 lines
    for k in range(600): say(D(1 + k % 27, 1 + k % 12), R.choice(SMALL))
    ev.sort(key=lambda e: (MONTHS.index(e[0].split(" ")[4].rstrip(",")) + 1, int(e[0].split(" ")[3])))
    return ev, Q


def ingest(events, design="light"):
    import engram_chat as E
    from engram_memory import open_memory
    from engram_structure import StructureLayer
    m = open_memory(f"{tempfile.mkdtemp()}/hard.db", design=design, durable=False, settings=E.Settings(retrieved_tokens=4000))
    L = StructureLayer(m.db); stats = dict(sentences=0, filed=0, accepted=0, uncertain=0, rejected=0); cur = None
    for date, speaker, text, subj, obj, kind in events:
        if date != cur:
            if cur: m.close_chat(write_note=False, sleep=False)
            m.open_chat(date); cur = date
        sid = m.add(speaker, text, date=date); stats["sentences"] += 1
        if subj:
            o = L.file(sid, subj, obj, kind); stats["filed"] += 1; stats[o.verdict] += 1
    m.close_chat(write_note=False, sleep=True)
    return m, L, stats


PROMPT = """You answer questions from a person's memory excerpts. Use ONLY the excerpts below; do not use world knowledge.
Where excerpts disagree, the later date wins. If the excerpts do not contain the answer, answer exactly: not mentioned.
Reply with the answer only, as short as possible (a name, a place, a number, a yes/no).

[Excerpts]
{ctx}

[Question]
{q}
"""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="results/hard100"); ap.add_argument("--design", default="light"); ap.add_argument("--batch", type=int, default=10)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    events, Q = world(); assert len(Q) == 100, len(Q)
    m, L, stats = ingest(events, a.design); print("ingested", stats, flush=True)
    from engram_erc_adapter import Adapter
    A = Adapter(m); items = []
    for i, qq in enumerate(Q):
        ctx, info = A.context_for(qq["q"])
        items.append(dict(i=i, **qq, context=ctx, prompt=PROMPT.format(ctx=ctx, q=qq["q"]), sections=info["sections"], reached=info["reached"],
                          withheld=info["withheld"], shown=[(s["entity"], s["relation"], s["value"]) for s in info["shown"]], profile_n=len(info["profile"])))
    with open(f"{a.out}/items.jsonl", "w") as f:
        for it in items: f.write(json.dumps(it) + "\n")
    for b in range(0, 100, a.batch):
        with open(f"{a.out}/batch_{b // a.batch:02d}.json", "w") as f:
            json.dump([dict(i=it["i"], prompt=it["prompt"]) for it in items[b:b + a.batch]], f, indent=0)
    print(f"wrote {a.out}/items.jsonl and {100 // a.batch} batches; mean context tokens {sum(len(it['context']) // 4 for it in items) // 100}")


if __name__ == "__main__":
    main()
