"""What a base 1 vs base 2 LongMemEval run would cost, counted from the data before any API call. No key needed.

Counts, for the same questions the runner would answer (--start/--n, hash order, development questions excluded):
unique chats, the user's sentences the P2 gate picks (only those go to the writer), the writer's input tokens, and
the answer and judge calls for two paired arms (base 1 and base 2). Prices are per million tokens.

  python kit_tools/base2_cost.py --data longmemeval_s_cleaned.json --start 0 --n 0
"""
import argparse, json, os, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--n", type=int, default=0, help="test questions; 0 = all")
    ap.add_argument("--context-tokens", type=int, default=4000)
    ap.add_argument("--price-in", type=float, default=2.50, help="$ per million input tokens (gpt-4o-2024-08-06)")
    ap.add_argument("--price-out", type=float, default=10.00, help="$ per million output tokens")
    a = ap.parse_args()

    import lme_gpt4o as L
    import engram_structure as S
    from engram_chat import count_tokens

    data = json.load(open(a.data))
    numbers = L.session_numbers(data)
    _, test = L.split_questions(data)
    qs = test[a.start:a.start + a.n] if a.n else test[a.start:]
    keys = {}
    for q in qs:
        for i, s, d in zip(q["haystack_session_ids"], q["haystack_sessions"], q["haystack_dates"]):
            keys.setdefault(L.session_key(i, s), (s, d))
    t0, user_lines, picked, prompt_tokens, chats_with_picks = time.time(), 0, 0, 0, 0
    template = count_tokens(S.writer_prompt([]))
    for n, (key, (s, d)) in enumerate(keys.items(), 1):
        date = L.session_date(d)
        mine = []
        for lid, speaker, sentence, _, _ in L.session_lines(s, numbers[key]):
            if speaker != "User": continue
            user_lines += 1
            if S.gate(speaker, sentence, date)[0]: mine.append(f"{lid} {sentence}")
        if mine:
            chats_with_picks += 1
            picked += len(mine)
            prompt_tokens += template + count_tokens("\n".join(mine))
        if n % 2000 == 0: print(f"  {n}/{len(keys)} chats counted, {time.time() - t0:.0f} s", flush=True)

    # Writer output: up to one short proposal per picked line (about 30 tokens each); low = a third of lines get one.
    out_hi, out_lo = picked * 30, picked * 10
    # Answers: two arms per question, each up to the context budget plus about 400 prompt and question tokens,
    # up to 400 reply tokens (prompt v2); the judge reads question, answer and reply (about 400) and writes ~5.
    ans_in = len(qs) * 2 * (a.context_tokens + 400)
    ans_out = len(qs) * 2 * 250
    judge_in, judge_out = len(qs) * 2 * 400, len(qs) * 2 * 5
    cost = lambda i, o: i / 1e6 * a.price_in + o / 1e6 * a.price_out
    writer_lo, writer_hi = cost(prompt_tokens, out_lo), cost(prompt_tokens, out_hi)
    answers = cost(ans_in + judge_in, ans_out + judge_out)
    report = dict(
        questions=len(qs), unique_chats=len(keys), chats_with_gated_lines=chats_with_picks,
        user_sentences=user_lines, gated_sentences=picked, gated_share=round(picked / max(1, user_lines), 3),
        writer_input_tokens=prompt_tokens, writer_calls=chats_with_picks,
        writer_cost_usd=[round(writer_lo, 2), round(writer_hi, 2)],
        answers_and_judge_cost_usd_two_arms=round(answers, 2),
        total_cost_usd=[round(writer_lo + answers, 2), round(writer_hi + answers, 2)],
        prices=dict(input=a.price_in, output=a.price_out, model="gpt-4o-2024-08-06"),
        note="Writer proposals are cached per chat, so a rerun or a later run on overlapping questions pays only for new chats.")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
