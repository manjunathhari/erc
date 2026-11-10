"""Deliberate-breakage check: breaks each rule in turn, runs the tests, restores the file. Every breakage must make a test fail.
Two suites: "base2" (Engram base 2, the default) and "adapter" (the Engram -> ERC adapter, erc_overlay). Run from the repository root
with a clean tree:

  python kit_tools/check_base2_breakage.py            # base 2
  python kit_tools/check_base2_breakage.py --suite adapter
"""
import subprocess, sys
BASE2 = [
 ("copy rule off", "engram_structure.py", "if not copied(obj, src.text): return REJECTED", "if False: return REJECTED"),
 ("whole-word copy off", "engram_structure.py", 'r"(?<![a-z0-9])" + re.escape(o.replace("’", "\'")) + r"(?![a-z0-9])"', 're.escape(o.replace("’", "\'"))'),
 ("date rule off", "engram_structure.py", "if is_partial_date(obj): return REJECTED", "if False: return REJECTED"),
 ("P2 checker skipped", "engram_structure.py", "if d.verdict == REJECTED: return REJECTED, d.reasons, d", "d = d.__class__('accepted', (), d.subject, d.predicate, d.time)"),
 ("checker built in fixed-list mode", "engram_structure.py", "FactValidator(self.kb, open_predicate=True)", "FactValidator(self.kb)"),
 ("who-rule: named not accepted", "engram_structure.py", 'doubts = tuple(r for r in d.reasons if r != "reported by someone else, not the subject")', "doubts = tuple(d.reasons)"),
 ("who-rule: anyone accepted (P2 attribution)", "engram_knowledge/fact_validator.py", 'elif not names_subject: return Decision(REJECTED, ("the speaker of the source is someone else",), who, word)', "elif False: pass"),
 ("uncertain stored as fact", "engram_structure.py", "        if verdict == UNCERTAIN:\n", "        if False:\n"),
 ("old version not superseded", "engram_structure.py", 'self.kb.set_status(old.fact.fact_id, "superseded"', 'None and self.kb.set_status(old.fact.fact_id, "superseded"'),
 ("repeat makes a second fact", "engram_structure.py", "        if same:  # the same fact", "        if False:  # the same fact"),
 ("deleted facts still walked", "engram_structure.py", "WHERE r.status IN ('active','superseded')", "WHERE r.status IS NOT NULL"),
 ("hub expanded wholesale", "engram_structure.py", "len(s) >= 3 and s not in hub and", "len(s) >= 3 and"),
 ("walk ignores links", "engram_structure.py", "if o and o not in seen_subj and o not in hub and o in g.by_subject:", "if False:"),
 ("budget ignored", "engram_structure.py", 'if count_tokens("\\n".join(lines + [text])) > budget: continue', "pass"),
 ("paraphrase instead of sentence", "engram_structure.py", "text = memory.text_of([sid])", "text = g.facts[fid]['subject'] + ' ' + g.facts[fid]['object']"),
 ("gate lets everything through", "engram_structure.py", 'return decision.decision == "candidate" and decision.keep_as == "none"', "return True"),
 ("open-predicate skips negation", "engram_knowledge/fact_validator.py", 'if word != "dislikes" and (NEGATION', 'if not open_predicate and word != "dislikes" and (NEGATION'),
 ("resolver loop back", "engram_knowledge/entity_resolver.py", "if normalize_name(speaker) in FIRST_PERSON:", "if False:"),
 ("resolver little words back", "engram_knowledge/entity_resolver.py", "set(normalize_name(name).split()) - LITTLE", "set(normalize_name(name).split())"),
 ("runner: base 2 leaks into base 1 arm", "kit_tools/lme_gpt4o.py", 'b2_walked=len(fids), b2_facts_tokens=used_f)', 'b2_walked=len(fids), b2_facts_tokens=used_f); ctxs["raw"] = ctxs["b2"]'),
 ("runner: base 1 arm answers from base 2", "kit_tools/lme_gpt4o.py", 'ctxs["erc" if arm.endswith("+erc") else "b2" if arm.endswith("+b2") else "raw"]', 'ctxs["erc" if arm.endswith("+erc") else "b2" if "b2" in ctxs else "raw"]'),
 ("runner: b2 always rebuilt", "kit_tools/lme_gpt4o.py", 'ctxs["b2"] = ctxs["raw"]  # nothing reached', 'ctxs["b2"] = ("(no excerpts)", 0)  # nothing reached'),
]
ADAPTER = [  # ERC adapter step 1: the fact-state gate (claude/erc-adapter-step1-eng-review.md)
 ("state record linked as support", "erc_overlay/knowledge.py", "links.append(EvidenceLink(sid, pid, EvidenceRelation.QUALIFIES))", "links.append(EvidenceLink(sid, pid, EvidenceRelation.SUPPORTS))"),
 ("state record dropped", "erc_overlay/knowledge.py", "if rule.state_record:", "if False:"),
 ("sentence relinked as qualifies", "erc_overlay/knowledge.py", "links.append(EvidenceLink(eid, pid, EvidenceRelation(e.evidence_role)))", "links.append(EvidenceLink(eid, pid, EvidenceRelation.QUALIFIES))"),
 ("pending or inferred sent as assertion", "erc_overlay/knowledge.py", 'STATE_RULES["active", _v, _s] = ASSERT if _checked else HYPOTHESIS', 'STATE_RULES["active", _v, _s] = ASSERT'),
 ("needs_review sent as assertion", "erc_overlay/knowledge.py", 'STATE_RULES["needs_review", _v, _s] = HYPOTHESIS', 'STATE_RULES["needs_review", _v, _s] = ASSERT'),
 ("disputed sent as hypothesis", "erc_overlay/knowledge.py", 'STATE_RULES["disputed", _v, _s] = DISPUTED', 'STATE_RULES["disputed", _v, _s] = HYPOTHESIS'),
 ("superseded sent as current", "erc_overlay/knowledge.py", 'STATE_RULES["superseded", _v, _s] = HISTORY_ASSERT if _checked else HISTORY_HYPOTHESIS', 'STATE_RULES["superseded", _v, _s] = ASSERT if _checked else HYPOTHESIS'),
 ("superseded with no end date sent", "erc_overlay/knowledge.py", 'if rule.action == "history" and not (f.valid_to and interval and interval.end):', "if False:"),
 ("superseded not fetched", "erc_overlay/knowledge.py", "statuses=FETCHED", "statuses=COUNTED"),
 ("rejected validation sent", "erc_overlay/knowledge.py", 'STATE_RULES[_st, "rejected", _s] = REJECTED', 'STATE_RULES[_st, "rejected", _s] = ASSERT'),
 ("unmapped state falls through to assertion", "erc_overlay/knowledge.py", "return STATE_RULES.get((status, validation_status, source_type), UNMAPPED)", "return STATE_RULES.get((status, validation_status, source_type), ASSERT)"),
 ("fingerprint blind to validation", "erc_overlay/knowledge.py", "facts=sorted((x.fact.fact_id, x.fact.status, x.fact.validation_status, x.fact.source_type, x.fact.recorded_at)", "facts=sorted((x.fact.fact_id, x.fact.status, x.fact.recorded_at)"),
 ("diagnostic fields dropped from explain", "erc_overlay/reasoner.py", 'lines.append(f"left out: fact {l.fact_id} ({l.reason}; status {s[\'status\']}, validation {s[\'validation_status\']}, "\n                         f"source {s[\'source_type\']}; needs {l.needs})")', 'lines.append(f"left out: fact {l.fact_id} ({l.reason})")'),
]
SUITES = {"base2": (BASE2, "tests/test_base2_structure.py tests/test_entity_validation.py tests/test_p2_pipeline.py tests/test_knowledge_store.py"),
          "adapter": (ADAPTER, "tests/test_erc_overlay.py")}
B, TESTS = SUITES[sys.argv[sys.argv.index("--suite") + 1] if "--suite" in sys.argv else "base2"]
caught = 0
GUARD = subprocess.run(f"{sys.executable} -m pytest -q -p no:cacheprovider {TESTS}", shell=True, capture_output=True, text=True).returncode
assert GUARD == 0, "tests must pass before breaking anything"
for name, path, old, new in B:
    src = open(path).read()
    if src.count(old) != 1: print(f"!! {name}: pattern found {src.count(old)} times"); continue
    open(path, "w").write(src.replace(old, new))
    try:
        r = subprocess.run(f"{sys.executable} -m pytest -q -x -p no:cacheprovider {TESTS}", shell=True, capture_output=True, text=True, timeout=600)
        ok = r.returncode != 0
    finally:
        open(path, "w").write(src)
    caught += ok
    print(("CAUGHT " if ok else "MISSED ") + name, "|", (r.stdout.strip().splitlines() or [""])[-1][:90])
print(f"{caught} of {len(B)} breakages caught")
