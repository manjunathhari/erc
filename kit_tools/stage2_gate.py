"""Stage 2 gate runner: Stage 2's writing path and knowledge_section on one LoCoMo conversation (0 to 4 only).

Specification: Stage 2 runner step, Draft 6, frozen 24 Nov 2026 (SHA-256
1681dcb80bf97a7ec7fea8070902de6865e0ccc085af62375797ba1cdd21bc17), with the decisions RQ-R1 to RQ-R8 and TF-1 to TF-5.

Stages, for one conversation:
  0   checks, in order: the repository's commit, the data file's hash, the two writer prompts, the conversation number
  1a  the conversation replayed into ordinary memory as the frozen pilot did (whole turns, no note, no facts)
  1b  part W: each chat read in blocks, one reading per speaker; one block_prompt call per reading with a line it may cite;
      every proposal filed with its reading, its name line (as a sentence id) and its subject_kind when given
  2   ERC told about each speaker as of the day after the last chat, no rule set (as the pilot)
  2b  part K: knowledge_section on the record memory, speaker=None; three states recorded apart
  3   two answer arms from one sentence search: A, the pilot's excerpts; B, the knowledge section first, then excerpts in
      what remains of A's own retrieval count; both judged (an adversarial question is not judged)

  python kit_tools/stage2_gate.py --data <file> --data-sha <sha256> --conversation 0 --questions <file> --out <folder>
                                  --commit <full hash> [--repo <clone>] [--fake] [--design tested|light]

The LoCoMo data stays outside the repository; its path is an argument and its hash is checked. vps_kit is never imported
(importing it reads the LoCoMo file through bench): the answer and judge prompts are read from vps_kit.py's source text,
and the conversation is read here in the same way as vps_kit.load_conv. A real (not --fake) run is refused until the
gate's models and settings are decided (gate specification, RQ-G3).
"""
import argparse, ast, collections, datetime as dt, hashlib, json, os, re, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONVERSATIONS = (0, 1, 2, 3, 4)                    # conversations 5 to 9 are never read
PROMPT_SHA = dict(writer="0a7a0718248d69d2e17f728473d5e4effc5abaf669fd400b90c07424fb6fe878",   # as the tests pin them
                  block="34360fa97f5b092562cff458d1ec7f39204efe73e84cf0d255689785270c2fc7")
WRITER_TOKENS, ANSWER_TOKENS, JUDGE_TOKENS = 1500, 60, 10     # as the pilot
CALL_LIMIT, TRIES = 70, 3                                      # as the pilot (E-10); the gate's own limit is its decision


class Stop(Exception):
    """The run must stop: a check failed, a call failed every try, or the call limit was reached."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- stage 0: the checks
def check_conversation(n):
    if n not in CONVERSATIONS: raise Stop(f"conversation {n} is not one of 0 to 4; conversations 5 to 9 are never read")
    return n


def check_commit(repo, want):
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if head != want: raise Stop(f"the repository is at {head or 'no commit'}, not the commit named, {want}")
    changed = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True).stdout.strip()
    if changed: raise Stop(f"the repository at {want} has changed tracked files: {changed.splitlines()[:5]}")   # IR-5
    return head


def check_data(path, want):
    with open(path, "rb") as f: got = _sha(f.read())
    if got != want: raise Stop(f"the data file's hash is {got}, not {want}")
    return got


def check_prompts(S):
    got = dict(writer=_sha(S.WRITER_PROMPT.encode("utf-8")), block=_sha(S.BLOCK_PROMPT.encode("utf-8")))
    for name, want in PROMPT_SHA.items():
        if got[name] != want: raise Stop(f"the {name} prompt is not the approved text: {got[name]}")
    return got


# ---------------------------------------------------------------- reading the data and the prompts (TF-2, TF-4)
def read_conversation(sample):
    """One LoCoMo record, read as vps_kit.load_conv reads it: sessions in number order, each turn's dia_id, speaker, text
    and image caption, the session's date as written."""
    c = sample["conversation"]
    chats = []
    for i in sorted(int(k.split("_")[1]) for k in c if re.fullmatch(r"session_\d+", k)):
        turns = [dict(id=t["dia_id"], speaker=t["speaker"], text=t["text"], caption=t.get("blip_caption", "")) for t in c[f"session_{i}"]]
        chats.append(dict(session=i, date=c[f"session_{i}_date_time"], turns=turns))
    return dict(sample_id=sample.get("sample_id"), speakers=(c["speaker_a"], c["speaker_b"]), chats=chats)


def read_prompts(path=None):
    """ANSWER_REASON and JUDGE, read from vps_kit.py's source text without importing it (TF-2)."""
    path = path or os.path.join(HERE, "vps_kit.py")
    with open(path, encoding="utf-8") as f: tree = ast.parse(f.read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("ANSWER_REASON", "JUDGE"):
            found[node.targets[0].id] = ast.literal_eval(node.value)
    missing = {"ANSWER_REASON", "JUDGE"} - set(found)
    if missing: raise Stop(f"vps_kit.py does not define {sorted(missing)}")
    return found["ANSWER_REASON"], found["JUDGE"]


# ---------------------------------------------------------------- the model calls
_FAKE_FACT = re.compile(r"\bI (?:just |recently )?(work at|joined|adopted|own) ((?:(?:a|an|the|my) )*[A-Z][A-Za-z' ]{1,40}?|[a-z][a-z ]{2,30}?)(?=[.,!?;]|$)")
_FAKE_WORD = {"work at": "works_at", "joined": "joined", "adopted": "adopted", "own": "owns"}


def fake_reply(prompt):
    """Stand-in model for the dry run: no key, no network. The writer copies a few 'I <verb> <thing>' phrases from lines it
    may cite (never from a read-only line); answers are 'not mentioned'; the judge says WRONG."""
    if '"facts"' in prompt and "Lines:" in prompt:
        facts = []
        for line in prompt.split("Lines:")[-1].splitlines():
            m = re.match(r"(D\d+:\d+\.\d+) (\(read only\) )?([^:]+): (.*)", line.strip())
            if not m or m[2]: continue
            facts += [dict(line=m[1], subject="I", word=_FAKE_WORD[verb], object=obj.strip()) for verb, obj in _FAKE_FACT.findall(m[4])]
        return json.dumps(dict(facts=facts))
    if "CORRECT" in prompt and "WRONG" in prompt: return "WRONG"
    return "not mentioned"


class Calls:
    """Every model call goes through here: counted against a hard limit, at most `tries` tries a call, each try logged.
    fake=True uses fake_reply; otherwise send(model, prompt, max_tokens) -> text is called."""

    def __init__(self, limit=CALL_LIMIT, tries=TRIES, fake=False, send=None):
        if not fake and send is None: raise Stop("no way to call a model: give send, or fake=True")
        self.limit, self.tries, self.fake, self.send = limit, tries, fake, send
        self.n, self.by_role, self.log = 0, collections.Counter(), []

    def __call__(self, role, model, prompt, max_tokens, what=""):
        for attempt in range(1, self.tries + 1):
            if self.n >= self.limit: raise Stop(f"call limit of {self.limit} reached before {role} {what}")
            self.n += 1
            self.by_role[role] += 1
            row = dict(n=self.n, role=role, model=model, what=what, attempt=attempt, max_tokens=max_tokens)
            try:
                text = fake_reply(prompt) if self.fake else self.send(model, prompt, max_tokens)
            except Stop:
                raise
            except Exception as e:
                self.log.append(dict(row, ok=False, error=f"{type(e).__name__}: {str(e)[:200]}"))
                continue
            self.log.append(dict(row, ok=True))
            return text
        raise Stop(f"{role} {what}: failed {self.tries} times")


# ---------------------------------------------------------------- stage 1a: ordinary memory, as the pilot
def replay_search(conv, design="tested", path=None):
    """Whole turns into ordinary memory, chat by chat, with no note; sleep after the last chat only; no noted facts."""
    from engram_memory import open_memory
    m = open_memory(path or os.path.join(tempfile.mkdtemp(), "search.db"), design=design, durable=False)
    for n, ch in enumerate(conv["chats"], 1):
        m.open_chat(ch["date"])
        for t in ch["turns"]:
            m.add(t["speaker"], t["text"], date=ch["date"], ref=t["id"], caption=t["caption"], commit=False)
        m.db.commit()
        m.close_chat(write_note=False, sleep=n == len(conv["chats"]))
    if m.use_facts: raise Stop("noted facts are on; arm A must be the pilot's sentences only")
    return m


# ---------------------------------------------------------------- stage 1b: part W (RQ-R2)
def _not_an_id(named):
    """IR-2: a name line that is not a line of this chat is passed on as given, except that a bare number is marked, so the
    layer can never read it as a sentence id (it is then held: "the name's line is not in this chat")."""
    text = str(named).strip()
    return f"line {text}" if text.isdigit() else named


def write_conversation(conv, calls, model, path=None):
    """Returns (record memory, sentences by line id, one row per proposal with its outcome)."""
    import engram_chat as E
    import engram_structure as S
    from kit_tools.lme_gpt4o import split_sentences
    rm = E.ChatMemory(path or os.path.join(tempfile.mkdtemp(), "records.db"), durable=False)
    sentences, chats = {}, []
    for ch in conv["chats"]:
        rm.open_chat(ch["date"])
        lines = []
        for t in ch["turns"]:
            for k, sentence in enumerate(split_sentences(t["text"]), 1):
                line = f"{t['id']}.{k}"
                sid = rm.add(t["speaker"], sentence, date=ch["date"], ref=line, commit=False)
                sentences[line] = dict(turn=t["id"], session=ch["session"], speaker=t["speaker"], text=sentence, sid=sid, passed=False)
                lines.append((line, t["speaker"], sentence))
        rm.db.commit()
        rm.close_chat(write_note=False, sleep=False)
        chats.append((ch, lines))
    layer = S.StructureLayer(rm.db)
    rows = []
    for ch, lines in chats:
        sid_of = {line: sentences[line]["sid"] for line, _, _ in lines}
        for who, block in S.readings(lines, ch["date"], conv["speakers"]):
            kind_of = {b.line_id: b.kind for b in block if b.citable}
            for line in kind_of: sentences[line]["passed"] = True
            if not kind_of: continue                                   # no line it may cite: no call
            reply = calls("writer", model, S.block_prompt(block), WRITER_TOKENS, f"chat {ch['session']} {who}")
            for p in S.parse_proposals(reply, set(kind_of), block_lines={b.line_id for b in block}):
                named = p.get("subject_from")
                given = None if named is None else sid_of.get(named, _not_an_id(named))   # a line of this chat as its sentence id
                extra = {"subject_kind": p["subject_kind"]} if "subject_kind" in p else {}
                row = dict(p, reading=who, chat=ch["session"])
                try:
                    o = layer.file(sid_of[p["line"]], p["subject"], p["object"], kind_of.get(p["line"], ""), word=p["word"],
                                   subject_from=given, reading=who, **extra)
                    row.update(verdict=o.verdict, reasons=list(o.reasons), fact_id=o.fact_id, review_id=o.review_id)
                except Exception as e:                                 # a fault in the repository's code is a finding
                    row.update(verdict="error", reasons=[f"{type(e).__name__}: {str(e)[:200]}"], fact_id=None, review_id=None)
                rows.append(row)
    return rm, sentences, rows


# ---------------------------------------------------------------- stage 2b and 3: part K and the two arms
def knowledge(rm, question, total):
    """Part K (RQ-R3): the record memory, the question unchanged, no speaker. Exactly one of text and reason is non-empty."""
    from engram_knowledge.knowledge_text import knowledge_section
    text, tokens, reason = knowledge_section(rm, question, total, speaker=None)
    return dict(text=text, tokens=tokens, reason=reason)


def arm_b(m, sids, total, ks, context_a, find_tokens):
    """Arm B (RQ-R5): the knowledge section first; excerpts, in the search's order, fill what remains of the total, never below
    zero. With no section (a reason), arm B is arm A exactly."""
    if not ks["text"]:
        return dict(context=context_a, ks_tokens=0, excerpt_tokens=find_tokens, total=total)
    keep, used, room = [], 0, total - ks["tokens"]
    for sid in sids:
        t = m._tokens(sid) + 8                     # counted as the search counts: stored tokens plus 8 for the date stamp
        if used + t > room: break                 # IR-12: stop at the first excerpt that does not fit (the reading chosen)
        keep.append(sid)
        used += t
    excerpts = m.text_of(sorted(keep) if m.search is not None else keep) if keep else ""
    return dict(context=ks["text"] + ("\n\n" + excerpts if excerpts else ""), ks_tokens=ks["tokens"], excerpt_tokens=used, total=total)


def contexts(m, rm, question):
    """Both arms from one search (RT13). Arm A is the pilot's context_for; arm B's total is arm A's own count (RQ-R8)."""
    from engram_chat import count_tokens
    context_a, info = m.context_for(question)
    sids, total = list(info["sids"]), info["tokens"]
    ks = knowledge(rm, question, total)
    a = dict(context=context_a, find_tokens=total, text_tokens=count_tokens(context_a), search_empty=not sids)
    b = arm_b(m, sids, total, ks, context_a, total)
    b["text_tokens"] = count_tokens(b["context"])
    return dict(A=a, B=b, ks=ks, sids=sids)


# ---------------------------------------------------------------- stage 2: ERC, as the pilot
def erc_stage(rm, conv):
    import engram_structure as S
    from engram_records import KnowledgeBase
    from erc_overlay import Reasoner
    kb = KnowledgeBase(rm.db)
    as_of = dt.datetime.fromisoformat(S.iso_day(conv["chats"][-1]["date"])).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1)
    out = dict(as_of=as_of.isoformat(), ruleset=None, speakers={})
    for name in conv["speakers"]:
        if not kb.resolve(name):
            out["speakers"][name] = dict(known=False, sent=[], left_out=[])
            continue
        r = Reasoner(kb).reason(name, as_of=as_of)
        sent = [p.id[5:] if p.id.startswith("fact:") else p.id for p in r.adapted.request.propositions]
        left = [dict(fact_id=x.fact_id, reason=x.reason) for x in r.adapted.left_out]
        out["speakers"][name] = dict(known=True, sent=sent, left_out=left)
    return out


_ALSO = re.compile(r"(?: \(also (?:supports|the name line for) [^)]*\))+$")


def in_section(section, speaker, text):
    """IR-9: a sentence is in the knowledge section only when a whole line shows it, "said <date>, <speaker>: <text>" or
    "name line, <date>, <speaker>: <text>", with nothing after it but "(also ...)" markers."""
    for line in (section or "").splitlines():
        line = _ALSO.sub("", line.strip())
        if line.startswith(("said ", "name line, ")) and line.endswith(f", {speaker}: {text}"): return True
    return False


def not_mentioned(reply):
    """E-6, as the pilot (runner Amendment 1): an adversarial question is answered right only if the reply is "not mentioned",
    ignoring capitals and punctuation. It is not sent to the judge."""
    return re.sub(r"[^a-z ]+", "", (reply or "").lower()).split() == ["not", "mentioned"]


# ---------------------------------------------------------------- one conversation, start to end
def planned_calls(conv, questions):
    """IR-7: the calls a run needs, counted before any call (retries not included): one writer call per reading with a line
    it may cite; two answers per question (arms A and B); two judge calls per question that is not adversarial."""
    import engram_structure as S
    from kit_tools.lme_gpt4o import split_sentences
    writer = 0
    for ch in conv["chats"]:
        lines = [(f"{t['id']}.{k}", t["speaker"], x) for t in ch["turns"] for k, x in enumerate(split_sentences(t["text"]), 1)]
        writer += sum(any(b.citable for b in block) for _, block in S.readings(lines, ch["date"], conv["speakers"]))
    return dict(writer=writer, answer=2 * len(questions), judge=2 * sum(not q.get("adversarial") for q in questions))


def run(sample, questions, calls, design="tested", writer="writer", answerer="answerer", judge="judge", record=None):
    """questions: dicts with question, gold, adversarial (bool) and evidence (turn ids). Returns the record.
    IR-7: the calls needed are counted first and the run is refused if they pass the limit. If a record dict is given it is
    filled as the run goes, so that a stop part-way leaves what was finished; `complete` is True only at the end."""
    record = {} if record is None else record
    conv = read_conversation(sample)
    answer_prompt, judge_prompt = read_prompts()
    plan = planned_calls(conv, questions)
    record.update(sample_id=conv["sample_id"], speakers=list(conv["speakers"]), planned_calls=plan, complete=False)
    if sum(plan.values()) > calls.limit - calls.n:
        raise Stop(f"the run needs {sum(plan.values())} calls {plan}, more than the {calls.limit - calls.n} the limit leaves")
    m = replay_search(conv, design)
    rm, sentences, rows = write_conversation(conv, calls, writer)
    facts = {fid: (json.loads(meta or "{}"), kind) for fid, meta, kind in rm.db.execute(
        "SELECT r.fact_id, r.metadata, e.entity_type FROM knowledge_records r JOIN entities e ON e.entity_id = r.subject_id")}
    outside = sum(meta.get("vocabulary") == "outside" for meta, _ in facts.values())
    erc = erc_stage(rm, conv)
    sent = {f for v in erc["speakers"].values() for f in v["sent"]}
    totals = dict(sentences=len(sentences), passed_filter=sum(v["passed"] for v in sentences.values()),
                  writer_calls=calls.by_role["writer"], proposals=len(rows),
                  by_verdict=dict(collections.Counter(r["verdict"] for r in rows)),
                  held_by_reason=dict(collections.Counter(x for r in rows if r["verdict"] == "uncertain" for x in r["reasons"])),
                  rejected_by_reason=dict(collections.Counter(x for r in rows if r["verdict"] == "rejected" for x in r["reasons"])),   # IR-19
                  errors=sum(r["verdict"] == "error" for r in rows),                                                        # IR-19
                  stored=len(facts), stored_in_vocabulary=len(facts) - outside, stored_outside_vocabulary=outside,
                  by_subject_kind=dict(collections.Counter(kind for _, kind in facts.values())))   # IR-19: the stored subject's type
    record.update(totals=totals, erc=erc, proposals=rows, questions=[])
    for q in questions:
        c = contexts(m, rm, q["question"])
        row = dict(question=q["question"], gold=q.get("gold"), adversarial=bool(q.get("adversarial")),
                   arm_a=dict(find_tokens=c["A"]["find_tokens"], text_tokens=c["A"]["text_tokens"]),
                   arm_b={k: c["B"][k] for k in ("ks_tokens", "excerpt_tokens", "total", "text_tokens")},
                   ks_text=c["ks"]["text"], ks_tokens=c["ks"]["tokens"], ks_reason=c["ks"]["reason"], search_empty=c["A"]["search_empty"])
        row["record_check"] = [dict(sentence=line, passed=v["passed"], reading=v["speaker"] if v["passed"] else None, proposals=[r for r in rows if r["line"] == line],
                                    stored=[r["fact_id"] for r in rows if r["line"] == line and r.get("fact_id")],
                                    sent_to_erc=[r["fact_id"] for r in rows if r["line"] == line and r.get("fact_id") in sent],
                                    in_knowledge_section=in_section(c["ks"]["text"], v["speaker"], v["text"]))
                               for line, v in sentences.items() if v["turn"] in q.get("evidence", [])]
        row["answers"] = {}
        for arm in ("A", "B"):
            reply = calls("answer", answerer, answer_prompt.format(ctx=c[arm]["context"], q=q["question"]), ANSWER_TOKENS, f"arm {arm}: {q['question']}")
            label = None if row["adversarial"] else calls("judge", judge, judge_prompt.format(q=q["question"], gold=q.get("gold"), pred=reply),
                                                          JUDGE_TOKENS, f"arm {arm}: {q['question']}")
            row["answers"][arm] = dict(answer=reply, judge=label, rule_correct=not_mentioned(reply) if row["adversarial"] else None)
        record["questions"].append(row)
    record["complete"] = True
    return record


# ---------------------------------------------------------------- the command line (TF-5)
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True, help="the LoCoMo file (kept outside the repository)")
    ap.add_argument("--data-sha", required=True, help="its SHA-256")
    ap.add_argument("--conversation", type=int, required=True, help="0 to 4 only")
    ap.add_argument("--questions", required=True, help="a questions file in the pilot's format")
    ap.add_argument("--out", required=True, help="folder for run.json and record.json")
    ap.add_argument("--commit", required=True, help="the full commit the repository must be at")
    ap.add_argument("--repo", default=HERE, help="the repository clone (default: this one)")
    ap.add_argument("--fake", action="store_true", help="dry run: no key, no network")
    ap.add_argument("--design", default="tested", choices=("tested", "light"))
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    info = dict(started_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), fake=a.fake, design=a.design,
                conversation=a.conversation, checked={}, stopped=None)
    calls, record = None, {}
    try:
        import engram_structure as S                  # this repository's own (the commit check is on --repo)
        info["checked"]["commit"] = check_commit(a.repo, a.commit)
        info["checked"]["data"] = check_data(a.data, a.data_sha)
        info["checked"]["prompts"] = check_prompts(S)
        info["checked"]["conversation"] = check_conversation(a.conversation)
        answer_prompt, judge_prompt = read_prompts()                      # IR-5: what the run used, recorded
        info["tool_folder"] = HERE
        info["prompt_sha"] = dict(answer=_sha(answer_prompt.encode("utf-8")), judge=_sha(judge_prompt.encode("utf-8")))
        if not a.fake: raise Stop("a real run is not yet possible: the gate's models and settings are not decided (gate RQ-G3)")
        with open(a.data) as f: sample = json.load(f)[a.conversation]
        with open(a.questions, "rb") as f: raw = f.read()
        info["questions_sha"] = _sha(raw)                                 # IR-4: recorded
        listed = json.loads(raw)["questions"]
        turns = {t["id"] for ch in read_conversation(sample)["chats"] for t in ch["turns"]}
        unknown = sorted({str(e) for q in listed for e in q.get("evidence", [])} - turns)
        if unknown: raise Stop(f"evidence that matches no turn of conversation {a.conversation}: {unknown[:10]}")   # IR-4
        questions = [dict(question=q["question"], gold=q.get("gold_answer"), adversarial=q.get("kind") == "adversarial",
                          evidence=q.get("evidence", [])) for q in listed]
        calls = Calls(fake=True)
        run(sample, questions, calls, design=a.design, record=record)
    except Stop as e:
        info["stopped"] = str(e)
    except Exception as e:                                # IR-1: anything unexpected is recorded as a stop, never hidden
        info["stopped"] = f"unexpected error: {type(e).__name__}: {str(e)[:300]}"
    finally:
        if record.get("totals") is not None:                  # IR-7: written whenever writing was finished, marked complete or not
            record["stopped"] = info["stopped"]
            with open(os.path.join(a.out, "record.json"), "w", encoding="utf-8") as f: json.dump(record, f, indent=1, ensure_ascii=False, default=str)
        info.update(planned_calls=record.get("planned_calls"), complete=bool(record.get("complete")),
                    errors=(record.get("totals") or {}).get("errors", 0))      # IR-19: proposals that hit an error in the repository's code
        info["calls"] = list(calls.log) if calls else []          # IR-6: every try, with its error; never a prompt or a reply
        info.update(calls_made=calls.n if calls else 0, calls_by_role=dict(calls.by_role) if calls else {},
                    finished_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        with open(os.path.join(a.out, "run.json"), "w", encoding="utf-8") as f: json.dump(info, f, indent=1)
    return 1 if info["stopped"] or info["errors"] else 0                      # IR-19: an error fails the run; the record stays complete


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    sys.exit(main())
