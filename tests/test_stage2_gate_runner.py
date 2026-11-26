"""Stage 2 runner step: tests for kit_tools/stage2_gate.py (frozen runner specification Draft 6, SHA-256
1681dcb80bf97a7ec7fea8070902de6865e0ccc085af62375797ba1cdd21bc17; tests RT1 to RT13, RQ-R7).

Every conversation here is made up. No LoCoMo text, no dataset file, no model, no network. The tool is imported inside each
test, so that before the build every test fails on its own, for the intended reason (the tool does not exist yet)."""
import copy, hashlib, importlib, json, os, socket, subprocess, sys

import pytest

import engram_structure as S
from engram_chat import count_tokens
from engram_knowledge import knowledge_text as KT

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SAMPLE = {"sample_id": "made-up-1", "qa": [], "conversation": {
    "speaker_a": "Asha", "speaker_b": "Ravi",
    "session_1_date_time": "10:00 am on 3 March, 2023",
    "session_1": [
        {"speaker": "Asha", "dia_id": "D1:1", "text": "Hi Ravi! I work at Northwind Clinic. I joined a pottery class."},
        {"speaker": "Ravi", "dia_id": "D1:2", "text": "That is lovely news. I adopted a puppy."},
        {"speaker": "Asha", "dia_id": "D1:3", "text": "Thanks!"}],
    "session_2_date_time": "9:00 am on 4 April, 2023",
    "session_2": [
        {"speaker": "Ravi", "dia_id": "D2:1", "text": "Ok."},
        {"speaker": "Asha", "dia_id": "D2:2", "text": "Sure."}]}}


def larger():
    """SAMPLE with a third chat of thirty made-up sentences, so the search finds enough for the knowledge section to fit."""
    s = copy.deepcopy(SAMPLE)
    s["conversation"]["session_3_date_time"] = "8:00 am on 5 May, 2023"
    s["conversation"]["session_3"] = [{"speaker": "Ravi" if i % 2 else "Asha", "dia_id": f"D3:{i + 1}",
                                      "text": f"Asha told me work at the clinic was busy on day {i + 1} of the month."} for i in range(30)]
    return s


def gate():
    return importlib.import_module("kit_tools.stage2_gate")


def written(sample=SAMPLE, send=None):
    G = gate()
    calls = G.Calls(fake=send is None, send=send)
    rm, sentences, rows = G.write_conversation(G.read_conversation(sample), calls, "writer")
    return G, calls, rm, sentences, rows


# ---------------------------------------------------------------- RT1: the stops
@pytest.mark.parametrize("n", [0, 1, 2, 3, 4])
def test_rt1_conversations_0_to_4_are_accepted(n):
    assert gate().check_conversation(n) == n


@pytest.mark.parametrize("n", [5, 6, 7, 8, 9, -1, 10])
def test_rt1_conversations_5_to_9_and_others_are_refused(n):
    G = gate()
    with pytest.raises(G.Stop):
        G.check_conversation(n)


def test_rt1_the_approved_prompts_pass():
    G = gate()
    got = G.check_prompts(S)
    assert got == dict(writer=hashlib.sha256(S.WRITER_PROMPT.encode()).hexdigest(), block=hashlib.sha256(S.BLOCK_PROMPT.encode()).hexdigest())
    assert got["block"] == "34360fa97f5b092562cff458d1ec7f39204efe73e84cf0d255689785270c2fc7"
    assert got["writer"] == "0a7a0718248d69d2e17f728473d5e4effc5abaf669fd400b90c07424fb6fe878"     # IR-17: pinned here too


@pytest.mark.parametrize("name", ["WRITER_PROMPT", "BLOCK_PROMPT"])
def test_rt1_a_changed_prompt_stops(monkeypatch, name):
    G = gate()
    monkeypatch.setattr(S, name, getattr(S, name) + " ")
    with pytest.raises(G.Stop):
        G.check_prompts(S)


def test_rt1_a_wrong_commit_stops_and_the_right_one_passes(tmp_path):
    G = gate()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "f").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "c"], check=True, env=env)
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert G.check_commit(str(tmp_path), head) == head
    with pytest.raises(G.Stop):
        G.check_commit(str(tmp_path), "0" * 40)


def test_rt1_a_wrong_data_hash_stops_and_the_right_one_passes(tmp_path):
    G = gate()
    p = tmp_path / "data.json"
    p.write_text(json.dumps([SAMPLE]))
    want = hashlib.sha256(p.read_bytes()).hexdigest()
    assert G.check_data(str(p), want) == want
    with pytest.raises(G.Stop):
        G.check_data(str(p), "0" * 64)


# ---------------------------------------------------------------- RT2: block writing only
def test_rt2_writing_uses_readings_and_block_prompt_never_writer_prompt(monkeypatch):
    seen = []
    real = S.block_prompt
    monkeypatch.setattr(S, "writer_prompt", lambda *a, **k: pytest.fail("writer_prompt was called"))
    monkeypatch.setattr(S, "block_prompt", lambda block: seen.append(list(block)) or real(block))
    G, calls, rm, sentences, rows = written()
    assert len(seen) == calls.by_role["writer"] == 2
    assert {b.speaker for blk in seen for b in blk if b.citable} == {"Asha", "Ravi"}


# ---------------------------------------------------------------- RT3: one call per reading with a citable line
def test_rt3_one_call_per_reading_with_a_citable_line_and_none_for_the_chat_of_short_replies():
    G, calls, rm, sentences, rows = written()
    assert calls.by_role["writer"] == 2          # chat 1: Asha's reading and Ravi's; chat 2 ("Ok.", "Sure."): none
    assert [l["what"] for l in calls.log] == ["chat 1 Asha", "chat 1 Ravi"]


def test_rt3_a_conversation_of_short_replies_makes_no_call():
    s = copy.deepcopy(SAMPLE)
    s["conversation"]["session_1"] = [{"speaker": "Asha", "dia_id": "D1:1", "text": "Ok."}, {"speaker": "Ravi", "dia_id": "D1:2", "text": "Sure."}]
    G, calls, rm, sentences, rows = written(s)
    assert calls.n == 0 and rows == []


# ---------------------------------------------------------------- RT4: block_lines, reading and subject_from reach the layer
def _reply(*facts):
    return lambda model, prompt, max_tokens: json.dumps({"facts": list(facts)})


def test_rt4_block_lines_reach_parsing_so_a_read_only_line_is_held_not_dropped():
    # Asha's reading: Ravi's line D1:2.2 is read-only. Without block_lines, parse_proposals would drop this proposal.
    G, calls, rm, sentences, rows = written(send=_reply(dict(line="D1:2.2", subject="I", word="adopted", object="a puppy")))
    asha = [r for r in rows if r["reading"] == "Asha"]
    assert asha and asha[0]["verdict"] == "uncertain" and asha[0]["reasons"] == [S.READ_ONLY]


def test_rt4_reading_and_subject_from_reach_file_as_a_sentence_id(monkeypatch):
    got = []
    real = S.StructureLayer.file
    monkeypatch.setattr(S.StructureLayer, "file", lambda self, *a, **k: got.append(k) or real(self, *a, **k))
    G, calls, rm, sentences, rows = written(send=_reply(dict(line="D1:1.3", subject="I", word="joined", object="a pottery class", subject_from="D1:1.2"),
                                                        dict(line="D1:1.3", subject="I", word="joined", object="a pottery class", subject_from="D9:9.9")))
    asha = [k for k in got if k.get("reading") == "Asha"]
    assert [k["subject_from"] for k in asha] == [sentences["D1:1.2"]["sid"], "D9:9.9"]
    assert {k.get("reading") for k in got} == {"Asha", "Ravi"}


def test_rt4_subject_kind_is_passed_only_when_the_reply_gives_it(monkeypatch):
    got = []
    real = S.StructureLayer.file
    monkeypatch.setattr(S.StructureLayer, "file", lambda self, *a, **k: got.append(k) or real(self, *a, **k))
    written(send=_reply(dict(line="D1:1.2", subject="I", word="works_at", object="Northwind Clinic", subject_kind="person"),
                        dict(line="D1:1.3", subject="I", word="joined", object="a pottery class")))
    asha = [k for k in got if k.get("reading") == "Asha"]
    assert asha[0]["subject_kind"] == "person" and "subject_kind" not in asha[1]


# ---------------------------------------------------------------- RT5: the call counter
def test_rt5_the_counter_stops_at_its_limit():
    G = gate()
    calls = G.Calls(limit=2, fake=True)
    calls("answer", "m", "q", 10); calls("answer", "m", "q", 10)
    with pytest.raises(G.Stop):
        calls("answer", "m", "q", 10)
    assert calls.n == 2


def test_rt5_a_failing_call_is_tried_three_times_then_stops():
    G = gate()
    calls = G.Calls(limit=70, send=lambda *a: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(G.Stop):
        calls("writer", "m", "p", 10)
    assert calls.n == 3 and [l["ok"] for l in calls.log] == [False, False, False]


def test_rt5_a_call_that_fails_once_succeeds_on_the_second_try():
    G = gate()
    state = {"n": 0}

    def flaky(*a):
        state["n"] += 1
        if state["n"] == 1: raise RuntimeError("once")
        return "fine"
    calls = G.Calls(limit=70, send=flaky)
    assert calls("writer", "m", "p", 10) == "fine" and calls.n == 2


# ---------------------------------------------------------------- RT6: the knowledge section call
def test_rt6_the_record_memory_is_read_with_the_question_unchanged_and_no_ordinary_search():
    G, calls, rm, sentences, rows = written()
    rm.find = lambda *a, **k: pytest.fail("ordinary-memory search was performed")
    want = KT.knowledge_section(rm, "Where does Asha work?", 800, speaker=None)
    got = G.knowledge(rm, "Where does Asha work?", 800)
    assert (got["text"], got["tokens"], got["reason"]) == want
    assert "Northwind Clinic" in got["text"]


def test_rt6_no_speaker_is_passed_so_a_first_person_question_gives_its_reason():
    G, calls, rm, sentences, rows = written()
    assert KT.knowledge_section(rm, "Where do I work?", 800, speaker="Asha")[0]    # a speaker would give text
    got = G.knowledge(rm, "Where do I work?", 800)
    assert got == dict(text="", tokens=0, reason=KT.R5)


# ---------------------------------------------------------------- RT7: the three states, recorded apart
def _run(sample, questions, **kw):
    G = gate()
    calls = G.Calls(fake=True)
    return G, calls, G.run(sample, questions, calls, design="light", **kw)


def test_rt7_text_returned():
    G, calls, rec = _run(larger(), [dict(question="Where does Asha work?", gold="Northwind Clinic")])
    q = rec["questions"][0]
    assert q["ks_text"] and q["ks_tokens"] == count_tokens(q["ks_text"]) and q["ks_reason"] == "" and q["search_empty"] is False


def test_rt7_a_reason_returned_while_the_search_found_sentences():
    G, calls, rec = _run(SAMPLE, [dict(question="Who adopted a puppy?", gold="Ravi")])
    q = rec["questions"][0]
    assert (q["ks_text"], q["ks_tokens"], q["ks_reason"]) == ("", 0, KT.R1) and q["search_empty"] is False


def test_rt7_the_search_found_nothing_is_its_own_field():
    G, calls, rec = _run(SAMPLE, [dict(question="Tell me a story.", gold="none")])
    q = rec["questions"][0]
    assert q["search_empty"] is True and q["ks_reason"] == KT.R1 and q["ks_text"] == ""


# ---------------------------------------------------------------- RT8: on a reason, the ordinary context unchanged
def test_rt8_on_a_reason_arm_b_is_exactly_arm_a():
    G = gate()
    conv = G.read_conversation(SAMPLE)
    m = G.replay_search(conv, design="light")
    rm, _, _ = G.write_conversation(conv, G.Calls(fake=True), "writer")
    c = G.contexts(m, rm, "Who adopted a puppy?")
    assert c["ks"]["reason"] and c["B"]["context"] == c["A"]["context"] and c["B"]["ks_tokens"] == 0


# ---------------------------------------------------------------- RT9: the budget
def test_rt9_knowledge_and_excerpts_never_pass_arm_a_own_count():
    G = gate()
    conv = G.read_conversation(larger())
    m = G.replay_search(conv, design="light")
    rm, _, _ = G.write_conversation(conv, G.Calls(fake=True), "writer")
    c = G.contexts(m, rm, "Where does Asha work?")
    b = c["B"]
    assert b["total"] == c["A"]["find_tokens"] > 0
    assert b["ks_tokens"] > 0 and b["excerpt_tokens"] > 0 and b["ks_tokens"] + b["excerpt_tokens"] <= b["total"]      # IR-15: > 0
    # IR-15: arm B's excerpts are the first of arm A's search, in its order, up to the room the section leaves
    prefix, used = [], 0
    for sid in c["sids"]:
        t = m._tokens(sid) + 8
        if used + t > b["total"] - b["ks_tokens"]: break
        prefix.append(sid); used += t
    assert 0 < len(prefix) < len(c["sids"]) and used == b["excerpt_tokens"]
    assert b["context"] == c["ks"]["text"] + "\n\n" + m.text_of(sorted(prefix) if m.search is not None else prefix)


def test_rt9_knowledge_that_cannot_fit_gives_its_reason_and_arm_a_unchanged():
    G = gate()
    conv = G.read_conversation(SAMPLE)
    m = G.replay_search(conv, design="light")
    rm, _, _ = G.write_conversation(conv, G.Calls(fake=True), "writer")
    c = G.contexts(m, rm, "Where does Asha work?")      # the search finds little, so the total is smaller than the section
    assert c["ks"]["reason"] == KT.R9 and c["B"]["context"] == c["A"]["context"]


def test_rt9_knowledge_filling_the_total_leaves_no_excerpts():
    G = gate()
    conv = G.read_conversation(larger())
    m = G.replay_search(conv, design="light")
    ctx, info = m.context_for("Where does Asha work?")
    ks = dict(text="K" * 4 * info["tokens"], tokens=info["tokens"], reason="")
    b = G.arm_b(m, list(info["sids"]), info["tokens"], ks, ctx, info["tokens"])
    assert b["context"] == ks["text"] and b["excerpt_tokens"] == 0 and b["ks_tokens"] == b["total"]


def test_rt9_knowledge_only_with_nothing_found_by_the_search():
    # IR-11 (25 Nov 09:59): a unit test of arm_b alone. A full run cannot reach this state: when the search finds nothing,
    # arm A's count is 0, so (T-a) the section is given 0 tokens and never appears. The full-run case is the next test.
    G = gate()
    conv = G.read_conversation(SAMPLE)
    m = G.replay_search(conv, design="light")
    ks = dict(text="K" * 40, tokens=10, reason="")
    b = G.arm_b(m, [], 10, ks, "(no excerpts)", 0)
    assert b["context"] == ks["text"] and b["excerpt_tokens"] == 0


# ---------------------------------------------------------------- RT10: several questions on one conversation
def _store(rm):
    return sorted(map(tuple, rm.db.execute("SELECT fact_id, status, object_value, metadata FROM knowledge_records")))


def test_rt10_reading_changes_no_record_and_no_question_carries_over():
    G = gate()
    conv = G.read_conversation(larger())
    m = G.replay_search(conv, design="light")
    rm, _, _ = G.write_conversation(conv, G.Calls(fake=True), "writer")
    before = _store(rm)
    qs = ["Where does Asha work?", "Who adopted a puppy?", "Tell me a story."]
    first = [G.contexts(m, rm, q) for q in qs]
    again = [G.contexts(m, rm, q) for q in reversed(qs)][::-1]
    assert _store(rm) == before
    assert [(c["A"]["context"], c["B"]["context"], c["ks"]) for c in first] == [(c["A"]["context"], c["B"]["context"], c["ks"]) for c in again]


# ---------------------------------------------------------------- RT11: the record holds the gate's measures
def test_rt11_the_record_holds_every_measure():
    G, calls, rec = _run(larger(), [dict(question="Where does Asha work?", gold="Northwind Clinic", evidence=["D1:1"]),
                                    dict(question="Who adopted a puppy?", adversarial=True, evidence=["D1:2"])])
    t = rec["totals"]
    assert {"sentences", "passed_filter", "writer_calls", "proposals", "by_verdict", "held_by_reason",
            "stored", "stored_in_vocabulary", "stored_outside_vocabulary", "by_subject_kind", "rejected_by_reason", "errors"} <= set(t)
    assert t["writer_calls"] == calls.by_role["writer"] and t["stored"] == t["stored_in_vocabulary"] + t["stored_outside_vocabulary"]
    assert set(rec["erc"]["speakers"]) == {"Asha", "Ravi"} and {"sent", "left_out", "known"} <= set(rec["erc"]["speakers"]["Asha"])
    q = rec["questions"][0]
    assert {"arm_a", "arm_b", "ks_text", "ks_tokens", "ks_reason", "search_empty", "record_check", "answers"} <= set(q)
    works = [c for c in q["record_check"] if c["sentence"] == "D1:1.2"][0]
    assert works["passed"] and works["stored"] and works["sent_to_erc"] == works["stored"] and works["in_knowledge_section"]
    assert set(q["answers"]) == {"A", "B"}
    assert rec["questions"][1]["answers"]["A"]["judge"] is None          # an adversarial question is not judged


def test_rt11_calls_by_role_two_answer_arms_and_judge_only_when_not_adversarial():
    G, calls, rec = _run(SAMPLE, [dict(question="Where does Asha work?", gold="x"), dict(question="Who adopted a puppy?", adversarial=True)])
    assert dict(calls.by_role) == dict(writer=2, answer=4, judge=2)


# ---------------------------------------------------------------- RT12: the dry run needs no key, no network, no dataset
def test_rt12_a_dry_run_needs_no_key_no_network_and_no_dataset(tmp_path):
    """IR-18 (25 Nov 07:12): inside the dry run's own process, every environment variable read and every file opened is recorded.
    No key, token or secret is read; no LoCoMo or other dataset file is opened; only the repository, Python's own files and the
    test's folder are opened; no network connection; no model library or Kaggle secret module is loaded."""
    script = tmp_path / "dry.py"
    script.write_text(f"""
import builtins, io, os, socket, sys, json, tempfile
sys.path.insert(0, {HERE!r}); os.chdir({str(tmp_path)!r})
os.environ.pop("ANTHROPIC_API_KEY", None); os.environ.pop("OPENAI_API_KEY", None)
READ, OPENED = [], []
real_get = os._Environ.__getitem__
def getitem(self, key):
    READ.append(key)
    return real_get(self, key)
os._Environ.__getitem__ = getitem
real_open = builtins.open
def opened(file, *a, **k):
    if isinstance(file, (str, bytes, os.PathLike)): OPENED.append(os.path.abspath(os.fsdecode(file)))
    return real_open(file, *a, **k)
builtins.open = io.open = opened
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network used"))
import kit_tools.stage2_gate as G
sample = json.loads({json.dumps(json.dumps(SAMPLE))})
calls = G.Calls(fake=True)
rec = G.run(sample, [dict(question="Where does Asha work?", gold="x")], calls, design="light")
print(json.dumps(dict(n=calls.n, read=sorted(set(READ)), opened=sorted(set(OPENED)), tmp=tempfile.gettempdir(),
                      roots=sorted({{sys.prefix, sys.base_prefix, sys.exec_prefix}}),
                      mods=sorted(m for m in ("vps_kit", "bench", "anthropic", "openai", "kaggle_secrets") if m in sys.modules))))
""")
    r = subprocess.run([sys.executable, "-B", str(script)], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["n"] == 6 and out["mods"] == []          # writer 2, answer 2 (arms A and B), judge 2
    secret = [k for k in out["read"] if any(w in k.upper() for w in ("KEY", "TOKEN", "SECRET", "PASSWORD", "ANTHROPIC", "OPENAI", "KAGGLE"))]
    assert secret == [], secret
    allowed = [HERE, str(tmp_path), out["tmp"]] + out["roots"]
    stray = [p for p in out["opened"] if "locomo" in p.lower() or not any(p.startswith(os.path.abspath(a) + os.sep) for a in allowed)]
    assert stray == [], stray


# ---------------------------------------------------------------- RT13: two answer arms from one search
def test_rt13_both_arms_come_from_one_search_and_arm_a_is_the_pilot_context():
    G = gate()
    conv = G.read_conversation(larger())
    m = G.replay_search(conv, design="light")
    rm, _, _ = G.write_conversation(conv, G.Calls(fake=True), "writer")
    want = m.context_for("Where does Asha work?")[0]
    n = {"find": 0}
    real = m.find
    m.find = lambda q: n.__setitem__("find", n["find"] + 1) or real(q)
    c = G.contexts(m, rm, "Where does Asha work?")
    assert n["find"] == 1 and c["A"]["context"] == want
    assert c["B"]["context"].startswith(c["ks"]["text"]) and c["B"]["ks_tokens"] + c["B"]["excerpt_tokens"] <= c["B"]["total"]


# ---------------------------------------------------------------- TF-4 (20:01): the tool reads LoCoMo's format as vps_kit.load_conv
def _load_conv():
    """vps_kit.load_conv, taken from vps_kit.py's source without importing vps_kit (which would import bench and read the
    LoCoMo file). Only the function is run; `evidence` is not reached because the made-up sample has no questions."""
    import ast, re, types
    src = open(os.path.join(HERE, "vps_kit.py"), encoding="utf-8").read()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "load_conv")
    space = dict(re=re, types=types, evidence=lambda q, ids: pytest.fail("evidence reached"))
    exec(compile(ast.Module([fn], []), "vps_kit.py", "exec"), space)
    return space["load_conv"]


def test_tf4_the_tool_reads_turns_dates_speakers_and_captions_as_load_conv():
    s = copy.deepcopy(SAMPLE)
    s["conversation"]["session_10_date_time"] = "7:00 pm on 6 June, 2023"   # session 10 after 2: number order, not text order
    s["conversation"]["session_10"] = [{"speaker": "Ravi", "dia_id": "D10:1", "text": "Here is the bowl I made.", "blip_caption": "glazed blue bowl beside teacups"}]
    want = [(t["id"], t["session"], t["date"], t["speaker"], t["text"], t["cap"]) for t in _load_conv()(s).turns]
    conv = gate().read_conversation(s)
    got = [(t["id"], ch["session"], ch["date"], t["speaker"], t["text"], t["caption"]) for ch in conv["chats"] for t in ch["turns"]]
    assert got == want and want[-1][-1] == "glazed blue bowl beside teacups" and [w[1] for w in want] == [1, 1, 1, 2, 2, 10]
    assert conv["speakers"] == ("Asha", "Ravi") and conv["sample_id"] == "made-up-1"


# ---------------------------------------------------------------- TF-5 (20:02): the command line
def _git_repo(path):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "f").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "c"], check=True, env=env)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _cli(tmp_path, conversation=0, commit=None, data_sha=None, fake=True, questions_text=None):
    repo = tmp_path / "repo"; repo.mkdir()
    head = _git_repo(repo)
    data = tmp_path / "data.json"
    data.write_text(json.dumps([SAMPLE] * 5 + [SAMPLE]))
    questions = tmp_path / "questions.json"
    questions.write_text(questions_text if questions_text is not None else json.dumps({"questions": [{"question": "Where does Asha work?", "gold_answer": "Northwind Clinic", "kind": "single-hop", "evidence": ["D1:1"]},
                                                   {"question": "Who adopted a puppy?", "gold_answer": None, "kind": "adversarial", "evidence": ["D1:2"]}]}))
    out = tmp_path / "out"
    cmd = [sys.executable, "-B", os.path.join(HERE, "kit_tools", "stage2_gate.py"), "--data", str(data),
           "--data-sha", data_sha or hashlib.sha256(data.read_bytes()).hexdigest(), "--conversation", str(conversation),
           "--questions", str(questions), "--out", str(out), "--commit", commit or head, "--repo", str(repo)] + (["--fake"] if fake else []) + ["--design", "light"]
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(tmp_path), env=env)
    assert (out / "run.json").exists(), "no run.json written: " + r.stderr[-1000:]
    return r, json.loads((out / "run.json").read_text()), out


def test_tf5_the_command_line_writes_its_files_after_the_checks_in_order(tmp_path):
    r, run, out = _cli(tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    assert list(run["checked"]) == ["commit", "data", "prompts", "conversation"] and run["stopped"] is None
    assert run["calls_by_role"] == dict(writer=2, answer=4, judge=2)
    rec = json.loads((out / "record.json").read_text())
    assert rec["sample_id"] == "made-up-1" and len(rec["questions"]) == 2


def test_tf5_conversation_5_is_refused_before_any_call(tmp_path):
    r, run, out = _cli(tmp_path, conversation=5)
    assert r.returncode != 0 and "conversation" in run["stopped"] and run["calls_made"] == 0
    assert not (out / "record.json").exists()


def test_tf5_a_wrong_data_hash_stops_before_any_call(tmp_path):
    r, run, out = _cli(tmp_path, data_sha="0" * 64)
    assert r.returncode != 0 and "data" in run["stopped"] and run["calls_made"] == 0 and list(run["checked"]) == ["commit"]
    assert not (out / "record.json").exists()


def test_tf5_a_wrong_commit_is_checked_first(tmp_path):
    r, run, out = _cli(tmp_path, commit="1" * 40, data_sha="0" * 64, conversation=7)   # different digits: the two stops are told apart
    assert r.returncode != 0 and run["checked"] == {} and "1" * 40 in run["stopped"] and "0" * 64 not in run["stopped"] and run["calls_made"] == 0


def test_b1_a_run_without_fake_stops_after_the_four_checks_and_makes_no_call(tmp_path):
    """B-1 (accepted 24 Nov 20:22): a real run is refused until the gate decides its models and settings (gate RQ-G3)."""
    r, run, out = _cli(tmp_path, fake=False)
    assert r.returncode != 0 and list(run["checked"]) == ["commit", "data", "prompts", "conversation"]
    assert "RQ-G3" in run["stopped"] and run["calls_made"] == 0 and not (out / "record.json").exists()


# ---------------------------------------------------------------- IR-1 (21:27): an unexpected error is recorded as a stop
def test_ir1_an_unexpected_error_is_recorded_as_a_stop_with_no_record(tmp_path):
    r, run, out = _cli(tmp_path, questions_text=json.dumps({"qs": []}))       # no "questions" key
    assert r.returncode == 1 and run["stopped"].startswith("unexpected error: KeyError")
    assert not (out / "record.json").exists()


# ---------------------------------------------------------------- IR-2 (21:30): a bare number is never read as a sentence id
@pytest.mark.parametrize("named", ["1", 1, " 2 "])
def test_ir2_a_bare_number_as_the_name_line_is_held_as_not_in_this_chat(named):
    G, calls, rm, sentences, rows = written(send=_reply(dict(line="D1:1.3", subject="I", word="joined", object="a pottery class", subject_from=named)))
    asha = [r for r in rows if r["reading"] == "Asha"]
    assert asha and asha[0]["verdict"] == "uncertain" and asha[0]["reasons"] == [S.NAME_NOT_HERE]


# ---------------------------------------------------------------- IR-8 (21:33): the pilot's E-6 rule for adversarial questions
@pytest.mark.parametrize("reply,right", [("not mentioned", True), ("Not mentioned.", True), ("  NOT  mentioned!", True),
                                         ("It is not mentioned anywhere.", False), ("Ravi", False), ("", False)])
def test_ir8_an_adversarial_answer_is_right_only_if_it_is_not_mentioned(reply, right):
    assert gate().not_mentioned(reply) is right


def test_ir8_adversarial_questions_get_the_rule_not_the_judge_and_others_the_judge_not_the_rule():
    G, calls, rec = _run(SAMPLE, [dict(question="Where does Asha work?", gold="x"), dict(question="Who adopted a puppy?", adversarial=True)])
    plain, adv = rec["questions"]
    for arm in ("A", "B"):
        assert plain["answers"][arm]["rule_correct"] is None and plain["answers"][arm]["judge"] == "WRONG"
        assert adv["answers"][arm]["judge"] is None and adv["answers"][arm]["rule_correct"] is True    # the stand-in answers "not mentioned"


# ---------------------------------------------------------------- IR-4 (21:39): the questions file is recorded and its evidence checked
def test_ir4_the_questions_file_hash_is_recorded(tmp_path):
    r, run, out = _cli(tmp_path)
    assert r.returncode == 0 and run["questions_sha"] == hashlib.sha256((tmp_path / "questions.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("evidence", [["D9:1"], ["D:1:1"], ["D1:01"], ["D1:1; D1:2"]])
def test_ir4_evidence_matching_no_turn_stops_before_any_call(tmp_path, evidence):
    text = json.dumps({"questions": [{"question": "Where does Asha work?", "gold_answer": "x", "kind": "single-hop", "evidence": evidence}]})
    r, run, out = _cli(tmp_path, questions_text=text)
    assert r.returncode == 1 and run["stopped"].startswith("evidence that matches no turn of conversation 0")
    assert run["calls_made"] == 0 and not (out / "record.json").exists()


# ---------------------------------------------------------------- IR-5 (21:59): changed tracked files stop; what ran is recorded
def test_ir5_changed_tracked_files_stop_the_commit_check(tmp_path):
    G = gate()
    head = _git_repo(tmp_path)
    (tmp_path / "f").write_text("changed")
    with pytest.raises(G.Stop):
        G.check_commit(str(tmp_path), head)


def test_ir5_run_json_records_the_tool_folder_and_the_answer_and_judge_prompt_hashes(tmp_path):
    import ast
    src = open(os.path.join(HERE, "vps_kit.py"), encoding="utf-8").read()
    want = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(src).body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and getattr(n.targets[0], "id", None) in ("ANSWER_REASON", "JUDGE")}
    r, run, out = _cli(tmp_path)
    assert r.returncode == 0 and run["tool_folder"] == HERE
    assert run["prompt_sha"] == dict(answer=hashlib.sha256(want["ANSWER_REASON"].encode()).hexdigest(),
                                     judge=hashlib.sha256(want["JUDGE"].encode()).hexdigest())


# ---------------------------------------------------------------- IR-7 (22:02): calls counted first; a stop part-way keeps what was finished
QS2 = [dict(question="Where does Asha work?", gold="x"), dict(question="Who adopted a puppy?", adversarial=True)]


def test_ir7_planned_calls_are_counted_before_any_call():
    G = gate()
    assert G.planned_calls(G.read_conversation(SAMPLE), QS2) == dict(writer=2, answer=4, judge=2)


def test_ir7_a_run_needing_more_calls_than_the_limit_is_refused_before_any_call():
    G = gate()
    calls, record = G.Calls(limit=7, fake=True), {}
    with pytest.raises(G.Stop):
        G.run(SAMPLE, QS2, calls, design="light", record=record)
    assert calls.n == 0 and record["planned_calls"] == dict(writer=2, answer=4, judge=2) and record["complete"] is False and "totals" not in record


def test_ir7_a_stop_during_the_questions_keeps_the_writing_and_erc_and_is_marked_incomplete():
    G = gate()

    def send(model, prompt, max_tokens):
        if '"facts"' in prompt: return G.fake_reply(prompt)
        raise RuntimeError("answer service down")
    calls, record = G.Calls(limit=70, send=send), {}
    with pytest.raises(G.Stop):
        G.run(SAMPLE, QS2, calls, design="light", record=record)
    assert record["complete"] is False and record["totals"]["writer_calls"] == 2 and set(record["erc"]["speakers"]) == {"Asha", "Ravi"}
    assert record["questions"] == [] and calls.by_role["answer"] == 3


def test_ir7_the_command_line_writes_an_incomplete_record_on_a_stop_part_way(tmp_path, monkeypatch):
    G = gate()
    real = G.fake_reply
    monkeypatch.setattr(G, "fake_reply", lambda p: real(p) if '"facts"' in p else (_ for _ in ()).throw(RuntimeError("down")))
    repo = tmp_path / "repo"; repo.mkdir()
    head = _git_repo(repo)
    data = tmp_path / "data.json"; data.write_text(json.dumps([SAMPLE]))
    qf = tmp_path / "q.json"; qf.write_text(json.dumps({"questions": [{"question": "Where does Asha work?", "gold_answer": "x", "kind": "single-hop", "evidence": ["D1:1"]}]}))
    out = tmp_path / "out"
    code = G.main(["--data", str(data), "--data-sha", hashlib.sha256(data.read_bytes()).hexdigest(), "--conversation", "0", "--questions", str(qf),
                   "--out", str(out), "--commit", head, "--repo", str(repo), "--fake", "--design", "light"])
    run, rec = json.loads((out / "run.json").read_text()), json.loads((out / "record.json").read_text())
    assert code == 1 and run["complete"] is False and run["stopped"].startswith("answer")
    assert rec["complete"] is False and rec["stopped"] == run["stopped"] and rec["totals"]["writer_calls"] == 2 and rec["questions"] == []


def test_ir7_a_finished_run_is_marked_complete(tmp_path):
    r, run, out = _cli(tmp_path)
    rec = json.loads((out / "record.json").read_text())
    assert r.returncode == 0 and run["complete"] is True and rec["complete"] is True and run["planned_calls"] == dict(writer=2, answer=4, judge=2)


# ---------------------------------------------------------------- IR-6 (22:05): the call log is saved in run.json
def test_ir6_run_json_holds_every_try_without_prompts_or_replies(tmp_path):
    r, run, out = _cli(tmp_path)
    assert r.returncode == 0 and len(run["calls"]) == run["calls_made"] == 8
    assert [c["n"] for c in run["calls"]] == list(range(1, 9)) and all(c["ok"] for c in run["calls"])
    assert all(set(c) == {"n", "role", "model", "what", "attempt", "max_tokens", "ok"} for c in run["calls"])


def test_ir6_failed_tries_and_their_errors_are_kept(tmp_path, monkeypatch):
    G = gate()
    real = G.fake_reply
    monkeypatch.setattr(G, "fake_reply", lambda p: real(p) if '"facts"' in p else (_ for _ in ()).throw(RuntimeError("down")))
    repo = tmp_path / "repo"; repo.mkdir()
    head = _git_repo(repo)
    data = tmp_path / "data.json"; data.write_text(json.dumps([SAMPLE]))
    qf = tmp_path / "q.json"; qf.write_text(json.dumps({"questions": [{"question": "Where does Asha work?", "gold_answer": "x", "kind": "single-hop", "evidence": ["D1:1"]}]}))
    out = tmp_path / "out"
    G.main(["--data", str(data), "--data-sha", hashlib.sha256(data.read_bytes()).hexdigest(), "--conversation", "0", "--questions", str(qf),
            "--out", str(out), "--commit", head, "--repo", str(repo), "--fake", "--design", "light"])
    failed = [c for c in json.loads((out / "run.json").read_text())["calls"] if not c["ok"]]
    assert [(c["role"], c["attempt"], c["error"]) for c in failed] == [("answer", k, "RuntimeError: down") for k in (1, 2, 3)]


# ---------------------------------------------------------------- IR-9 (22:06): the reading per sentence; a whole-line section match
SECTION = "\n".join(["[Records from the knowledge store: each fact with the original sentences behind it]",
                     "[1] Asha (person) — Works at: Northwind Clinic (start not stated; first said 2023-03-03; still held)",
                     "  said 10:00 am on 3 March, 2023, Asha: I work at Northwind Clinic. (also supports [2])",
                     "  name line, 10:00 am on 3 March, 2023, Ravi: Ok so Asha is here.",
                     "  said 10:00 am on 3 March, 2023, Ravi: Ok. See you soon.",        # BK41: "Ok." inside a longer sentence
                     "[2] Asha (person) — Joined: Ok",
                     "  said: see [1]"])


@pytest.mark.parametrize("speaker,text,shown", [
    ("Asha", "I work at Northwind Clinic.", True),            # with an "(also ...)" marker after it
    ("Ravi", "Ok so Asha is here.", True),                    # a name line
    ("Asha", "Ok.", False), ("Ravi", "Ok.", False),           # a short sentence is not found inside other lines
    ("Asha", "Northwind Clinic.", False),                     # part of a sentence is not the sentence
    ("Ravi", "I work at Northwind Clinic.", False)])          # the speaker must match
def test_ir9_a_sentence_is_in_the_section_only_as_a_whole_line(speaker, text, shown):
    assert gate().in_section(SECTION, speaker, text) is shown


def test_ir9_the_record_shows_each_evidence_sentence_reading():
    G, calls, rec = _run(larger(), [dict(question="Where does Asha work?", gold="x", evidence=["D1:1", "D1:2"])])
    by = {c["sentence"]: c for c in rec["questions"][0]["record_check"]}
    assert by["D1:1.2"]["reading"] == "Asha" and by["D1:2.2"]["reading"] == "Ravi"
    assert by["D1:1.1"]["passed"] is False and by["D1:1.1"]["reading"] is None          # "Hi Ravi!": dropped by the first filter
    assert by["D1:1.2"]["in_knowledge_section"] is True and by["D1:1.3"]["in_knowledge_section"] is False


# ---------------------------------------------------------------- IR-14 (22:09): no second search of the ordinary memory
def test_ir14_building_the_section_never_searches_the_ordinary_memory_again():
    G = gate()
    conv = G.read_conversation(larger())
    m = G.replay_search(conv, design="light")
    rm, _, _ = G.write_conversation(conv, G.Calls(fake=True), "writer")
    n = {"find": 0, "context_for": 0}
    real_find, real_context = m.find, m.context_for

    def find(q):
        n["find"] += 1
        if n["find"] > 1: pytest.fail("the ordinary memory was searched again")
        return real_find(q)

    def context_for(q):
        n["context_for"] += 1
        return real_context(q)
    m.find, m.context_for = find, context_for
    rm.find = lambda *a, **k: pytest.fail("the record memory was searched")
    c = G.contexts(m, rm, "Where does Asha work?")
    assert n == {"find": 1, "context_for": 1} and c["ks"]["text"]


# ---------------------------------------------------------------- IR-16 (25 Nov 07:09): the other reachable reasons, through a full run
@pytest.mark.parametrize("question,reason", [
    ("Where do Asha and Ravi work?", KT.R3),                     # two known entities named
    ("Does Ravi know where I work?", KT.R10),                    # first person, with another known entity, no speaker
    ("What is Asha doing now?", KT.R6)])                         # a kind of question the router has no slot for
def test_ir16_full_run_records_the_exact_reason(question, reason):
    G, calls, rec = _run(larger(), [dict(question=question, gold="x")])
    q = rec["questions"][0]
    assert (q["ks_text"], q["ks_tokens"], q["ks_reason"]) == ("", 0, reason)


def test_ir16_full_run_records_a_name_shared_by_two_entities():
    G = gate()
    s = copy.deepcopy(SAMPLE)
    s["conversation"]["session_1"] = [{"speaker": "Asha", "dia_id": "D1:1", "text": "My sister Priya works at Lakeside School."},
                                      {"speaker": "Ravi", "dia_id": "D1:2", "text": "My sister Priya works at Hill Bank."}]

    def send(model, prompt, max_tokens):
        if '"facts"' not in prompt: return G.fake_reply(prompt)
        facts = []
        if "D1:1.1 Asha:" in prompt: facts.append(dict(line="D1:1.1", subject="my sister Priya", word="works_at", object="Lakeside School"))
        if "D1:2.1 Ravi:" in prompt: facts.append(dict(line="D1:2.1", subject="my sister Priya", word="works_at", object="Hill Bank"))
        return json.dumps({"facts": facts})
    rec = G.run(s, [dict(question="Where does Priya work?", gold="x")], G.Calls(send=send), design="light")
    assert rec["totals"]["stored"] == 2 and rec["questions"][0]["ks_reason"] == KT.R2


# ---------------------------------------------------------------- IR-19 (25 Nov 07:13): names that say what they count; errors fail the run
def test_ir19_rejections_are_counted_by_reason_and_kinds_by_subject():
    G = gate()
    send = _reply(dict(line="D1:1.2", subject="I", word="works_at", object="Southgate Clinic"))     # not in the sentence: rejected
    rec = G.run(SAMPLE, [], G.Calls(send=send), design="light")
    t = rec["totals"]
    assert t["by_verdict"].get("rejected") and sum(t["rejected_by_reason"].values()) >= t["by_verdict"]["rejected"]
    assert "by_kind" not in t and t["errors"] == 0


def test_ir19_an_error_in_the_repository_code_fails_the_run_and_keeps_the_complete_record(tmp_path, monkeypatch):
    G = gate()
    real = S.StructureLayer.file

    def file(self, sid, subject, obj, *a, **k):
        if obj == "a pottery class": raise ValueError("planted")
        return real(self, sid, subject, obj, *a, **k)
    monkeypatch.setattr(S.StructureLayer, "file", file)
    repo = tmp_path / "repo"; repo.mkdir()
    head = _git_repo(repo)
    data = tmp_path / "data.json"; data.write_text(json.dumps([SAMPLE]))
    qf = tmp_path / "q.json"; qf.write_text(json.dumps({"questions": [{"question": "Where does Asha work?", "gold_answer": "x", "kind": "single-hop", "evidence": ["D1:1"]}]}))
    out = tmp_path / "out"
    code = G.main(["--data", str(data), "--data-sha", hashlib.sha256(data.read_bytes()).hexdigest(), "--conversation", "0", "--questions", str(qf),
                   "--out", str(out), "--commit", head, "--repo", str(repo), "--fake", "--design", "light"])
    run, rec = json.loads((out / "run.json").read_text()), json.loads((out / "record.json").read_text())
    assert code == 1 and run["stopped"] is None and run["errors"] == 1 and run["complete"] is True
    assert rec["complete"] is True and rec["totals"]["errors"] == 1 and len(rec["questions"]) == 1
    assert [r["reasons"] for r in rec["proposals"] if r["verdict"] == "error"] == [["ValueError: planted"]]


# ---------------------------------------------------------------- IR-11 (25 Nov 09:59): a search that finds nothing, through a full run
def test_ir11_when_the_search_finds_nothing_the_section_gives_a_reason_and_arm_b_is_arm_a():
    G = gate()
    conv = G.read_conversation(SAMPLE)
    m = G.replay_search(conv, design="light")
    rm, _, _ = G.write_conversation(conv, G.Calls(fake=True), "writer")
    c = G.contexts(m, rm, "Tell me a story.")
    assert c["sids"] == [] and c["A"]["find_tokens"] == 0 and c["B"]["total"] == 0
    assert c["ks"]["text"] == "" and c["ks"]["reason"] and c["B"]["context"] == c["A"]["context"] and c["B"]["ks_tokens"] == 0
    G2, calls, rec = _run(SAMPLE, [dict(question="Tell me a story.", gold="x")])
    q = rec["questions"][0]
    assert q["search_empty"] is True and q["ks_reason"] and q["arm_b"]["total"] == 0 and q["arm_b"]["text_tokens"] == q["arm_a"]["text_tokens"]
