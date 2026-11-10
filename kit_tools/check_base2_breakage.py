"""Deliberate-breakage check: breaks each rule in turn, runs the tests, restores the file. Every breakage must make a test fail.
Three suites: "base2" (Engram base 2, the default), "adapter" (the Engram -> ERC adapter, erc_overlay) and "erc" (ERC's own
contracts, engram_erc). Run from the repository root with a clean tree:

  python kit_tools/check_base2_breakage.py            # base 2
  python kit_tools/check_base2_breakage.py --suite adapter
  python kit_tools/check_base2_breakage.py --suite erc

The "erc" suite runs only the behavioural contract tests. The byte-pin test is left out on purpose: it fails on any edit to a
pinned file, so it would "catch" every breakage without showing that a rule is actually tested.
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
 ("state record dropped", "erc_overlay/knowledge.py", "if rule.state_record or interval is None:", "if False:"),
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
 # step 1A: eligibility inside the walk; one point in time
 ("walk expands through an excluded fact", "erc_overlay/knowledge.py", "                    eligible.append((x, rule, interval))\n                    obj = f.object_entity_id or self._resolved(f)\n                    if obj: nxt.append(obj)", "                    eligible.append((x, rule, interval))\n                    obj = f.object_entity_id or self._resolved(f)\n                    if obj: nxt.append(obj)\n                for x in self.kb.about_entity(ent, statuses=FETCHED, source_types=None):\n                    obj = x.fact.object_entity_id or self._resolved(x.fact)\n                    if obj: nxt.append(obj)"),
 ("history leaks past as_of", "erc_overlay/knowledge.py", "if interval and interval.end and interval.end <= as_of:", "if False:"),
 ("future fact enters a present question", "erc_overlay/knowledge.py", "if interval and interval.start and interval.start > as_of:", "if False:"),
 ("undated fact marked as known time", "erc_overlay/knowledge.py", '"time_kind": self._time_kind(f), "valid_time": "known" if interval else "unknown"', '"time_kind": self._time_kind(f), "valid_time": "known"'),
 ("included fact's state missing from explain", "erc_overlay/reasoner.py", 'if leaf.startswith("fact:"): lines.append(f"    {self._state_line(props[leaf], request)}")', "pass"),
 # 1A follow-up: unknown time is qualifying evidence; excluded facts cannot alter eligible periods
 ("undated premise sent without a state record", "erc_overlay/knowledge.py", "if rule.state_record or interval is None:", "if rule.state_record:"),
 ("undated premise's reason missing from its record", "erc_overlay/knowledge.py", 'if interval is None: qualified_for.append("valid time unknown")', "pass"),
 ("periods built with disputed facts", "erc_overlay/knowledge.py", 'self.engine.get_history(entity_id, slot, **PLAYED)["periods"]', 'self.engine.get_history(entity_id, slot)["periods"]'),
 ("state engine ignores the statuses it was given", "engram_knowledge/state_engine.py", "if f.status in statuses and", "if f.status in COUNTED and"),
 # 1A follow-up 2: only accepted observations set period boundaries
 ("pending or needs_review observations set period boundaries", "erc_overlay/knowledge.py", 'PLAYED = dict(statuses=("active",), validations=("accepted",))', 'PLAYED = dict(statuses=("active", "needs_review"), validations=None)'),
 ("state engine ignores the validations it was given", "engram_knowledge/state_engine.py", 'valid = f.validation_status != "rejected" if validations is None else f.validation_status in validations', 'valid = f.validation_status != "rejected"'),
 # 1A follow-up 3: an event keeps its own date; only the state takes the period's span
 ("events dated like states", "erc_overlay/knowledge.py", "if fact.predicate in EVENTS:  # an event happened on a day", "if False:  # an event happened on a day"),
 ("event given a synthetic end at as_of", "erc_overlay/knowledge.py", "return TimeInterval(begin, None) if begin else None", "return TimeInterval(begin, as_of + ONE_DAY) if begin else None"),
 ("event dated by the period's start, not its own sentence", "erc_overlay/knowledge.py", "if x.fact.valid_from: return x.fact.valid_from\n        days = []", "if x.fact.valid_from: return x.fact.valid_from\n        return None\n        days = []"),
 ("state predicates counted as events", "erc_overlay/knowledge.py", "EVENTS = frozenset(p for p, s in {**OPENS, **CLOSES}.items() if p != s)", "EVENTS = frozenset({**OPENS, **CLOSES})"),
 ("diagnostic fields dropped from explain", "erc_overlay/reasoner.py", 'lines.append(f"left out: fact {l.fact_id} ({l.reason}; status {s[\'status\']}, validation {s[\'validation_status\']}, "\n                         f"source {s[\'source_type\']}; needs {l.needs})")', 'lines.append(f"left out: fact {l.fact_id} ({l.reason})")'),
 # B2a: adapter enrichment (claude/erc-b2a-spec.md, section 8). Additive only: each breakage either drops or falsifies an addition,
 # or lets a later increment's change (B2b) arrive early.
 ("B2a: observation date not sent with sentence evidence", "erc_overlay/knowledge.py", "**self._observed(e)", ""),
 ("B2a: observation date put on the adapter's own state record", "erc_overlay/knowledge.py", "evidence_kind=EvidenceKind.OTHER,", "evidence_kind=EvidenceKind.OTHER, observed_at=as_of,"),
 ("B2a: a date invented for a sentence with no readable date", "erc_overlay/knowledge.py", "if not day: return {}", 'if not day: day = "1970"'),
 ("B2a: latest start is the next period's first instant, not this period's last", "erc_overlay/knowledge.py", "return _day(span(stated)[1]) + LAST_INSTANT if _coarse(stated) else None", "return _day(span(stated)[1]) + ONE_DAY if _coarse(stated) else None"),
 ("B2a: bound added to a first-said start", "erc_overlay/knowledge.py", '_start_latest(start) if start_basis == "stated" else None', "_start_latest(start)"),
 ("B2a: bound added to an event's interval", "erc_overlay/knowledge.py", "return TimeInterval(begin, None) if begin else None, labels", "return TimeInterval(begin, None, start_latest=_start_latest(self._event_date(x))) if begin else None, labels"),
 ("B2a: bound added to a closed or replaced end", "erc_overlay/knowledge.py", '_end_earliest(end) if end_basis == "stated" else None', "_end_earliest(end)"),
 ("B2a: start_basis always stated", "erc_overlay/knowledge.py", '"stated" if p.start else "first_said", p.end_kind)', '"stated", p.end_kind)'),
 ("B2a: end_basis not taken from Engram's end_kind", "erc_overlay/knowledge.py", '"stated" if p.start else "first_said", p.end_kind)', '"stated" if p.start else "first_said", "open" if p.end is None else "stated")'),
 ("B2a: a day made into an instant outside the one function", "erc_overlay/knowledge.py", '"observed_at": _day(first)', '"observed_at": dt.datetime(first.year, first.month, first.day, tzinfo=dt.timezone.utc)'),
 ("B2a: B2b arriving early - a first-said start sent with no start", "erc_overlay/knowledge.py", "begin = _start(start)\n        if begin is None and end is None: return None, {}", 'begin = _start(start) if start_basis == "stated" else None\n        if begin is None and end is None: return None, {}'),
 ("B2a: an existing qualifier renamed", "erc_overlay/knowledge.py", '"fact_type": f.fact_type,', '"type": f.fact_type,'),
 # review of bd6d977: a known end with no start
 ("B2a: a start label attached where there is no start", "erc_overlay/knowledge.py", 'if begin is None: del labels["start_basis"]', "pass"),
 ("B2a: explain assumes every interval has a start", "erc_overlay/reasoner.py", 'if t.start is None: start = "start not known"', 'if False: start = "start not known"'),
]
# ERC temporal contract foundation, increment B1 (ERC 0.5.0)
ERC = [
 ("unbounded start accepted with a date", "engram_erc/contracts.py", "if self.start_unbounded and (self.start or self.start_latest or self.start_is_lower_bound):", "if False:"),
 ("unbounded end accepted with a date", "engram_erc/contracts.py", "if self.end_unbounded and (self.end or self.end_earliest or self.end_is_upper_bound):", "if False:"),
 ("start window order unchecked", "engram_erc/contracts.py", "if self.start and self.start_latest and self.start_latest <= self.start:", "if False:"),
 ("end window order unchecked", "engram_erc/contracts.py", "if self.end and self.end_earliest and self.end_earliest >= self.end:", "if False:"),
 ("zero-width start window accepted (a second spelling of exact)", "engram_erc/contracts.py", "self.start_latest <= self.start:", "self.start_latest < self.start:"),
 ("zero-width end window accepted (a second spelling of exact)", "engram_erc/contracts.py", "self.end_earliest >= self.end:", "self.end_earliest > self.end:"),
 ("lower-bound start accepted with no start", "engram_erc/contracts.py", "if self.start_is_lower_bound and (self.start is None or self.start_latest is not None):", "if False:"),
 ("upper-bound end accepted with no end", "engram_erc/contracts.py", "if self.end_is_upper_bound and (self.end is None or self.end_earliest is not None):", "if False:"),
 ("start-before-end check off", "engram_erc/contracts.py", "if self.start and self.end and self.start >= self.end:", "if False:"),
 ("new interval fields not validated (naive or non-datetime accepted)", "engram_erc/contracts.py", 'for name in ("start", "end", "start_latest", "end_earliest"):', 'for name in ("start", "end"):'),
 ("non-boolean flag accepted", "engram_erc/contracts.py", "if not isinstance(getattr(self, name), bool):", "if False:"),
 ("new interval field made positional", "engram_erc/contracts.py", "start_latest: datetime | None = field(default=None, kw_only=True)", "start_latest: datetime | None = None"),
 ("occurred made positional", "engram_erc/contracts.py", "occurred: Occurrence | None = field(default=None, kw_only=True)", "occurred: Occurrence | None = None"),
 ("unknown end reported as unbounded", "engram_erc/contracts.py", "return BoundaryStatus.UNKNOWN if self.end_earliest is None else BoundaryStatus.NO_EARLIER_THAN", "return BoundaryStatus.UNBOUNDED if self.end_earliest is None else BoundaryStatus.NO_EARLIER_THAN"),
 ("unbounded end reported as unknown", "engram_erc/contracts.py", "        if self.end_unbounded:\n            return BoundaryStatus.UNBOUNDED", "        if self.end_unbounded:\n            return BoundaryStatus.UNKNOWN"),
 ("one-sided start reported as unknown", "engram_erc/contracts.py", "return BoundaryStatus.UNKNOWN if self.start_latest is None else BoundaryStatus.NO_LATER_THAN", "return BoundaryStatus.UNKNOWN"),
 ("lower-bound start reported as exact", "engram_erc/contracts.py", "return BoundaryStatus.NO_EARLIER_THAN if self.start_is_lower_bound else BoundaryStatus.EXACT", "return BoundaryStatus.EXACT"),
 ("upper-bound end reported as exact", "engram_erc/contracts.py", "return BoundaryStatus.NO_LATER_THAN if self.end_is_upper_bound else BoundaryStatus.EXACT", "return BoundaryStatus.EXACT"),
 ("window start reported as exact", "engram_erc/contracts.py", "        if self.start_latest is not None:\n            return BoundaryStatus.WITHIN", "        if self.start_latest is not None:\n            return BoundaryStatus.EXACT"),
 ("an event cannot be an exact moment", "engram_erc/contracts.py", "self.earliest > self.latest:", "self.earliest >= self.latest:"),
 ("occurrence order unchecked", "engram_erc/contracts.py", "if self.earliest and self.latest and self.earliest > self.latest:", "if False:"),
 ("exact occurrence reported as a window", "engram_erc/contracts.py", "return BoundaryStatus.EXACT if self.earliest == self.latest else BoundaryStatus.WITHIN", "return BoundaryStatus.WITHIN"),
 ("a proposition may be both a state and an event", "engram_erc/contracts.py", "if self.valid_time is not None and self.occurred is not None:", "if False:"),
 ("occurred of the wrong type accepted", "engram_erc/contracts.py", "if self.occurred is not None and not isinstance(self.occurred, Occurrence):", "if False:"),
 ("fingerprint blind to the window fields", "engram_erc/generalization.py", 'for name in ("start_latest", "end_earliest"):', "for name in ():"),
 ("fingerprint blind to the unbounded and one-sided flags", "engram_erc/generalization.py", 'for name in ("start_unbounded", "end_unbounded", "start_is_lower_bound", "end_is_upper_bound"):', "for name in ():"),
 ("fingerprint blind to an occurrence", "engram_erc/generalization.py", "        if p.occurred is not None:", "        if False:"),
 ("fingerprint of existing intervals changed (new keys always written)", "engram_erc/generalization.py", "                if getattr(p.valid_time, name):\n                    interval[name] = True", "                interval[name] = bool(getattr(p.valid_time, name))"),
 ("fingerprint blind to enriched evidence validity", "engram_erc/generalization.py", "        if added:\n            item[\"valid_time\"]", "        if False:\n            item[\"valid_time\"]"),
 ("fingerprint blind to the window fields on evidence", "engram_erc/generalization.py", 'added = {name: getattr(v, name).isoformat() for name in ("start_latest", "end_earliest")', 'added = {name: getattr(v, name).isoformat() for name in ()'),
 ("fingerprint blind to the flags on evidence", "engram_erc/generalization.py", 'for name in ("start_unbounded", "end_unbounded", "start_is_lower_bound",\n                                              "end_is_upper_bound") if getattr(v, name)})', 'for name in () if getattr(v, name)})'),
 ("enriched evidence fingerprint omits the plain end", "engram_erc/generalization.py", '"end": v.end.isoformat() if v.end else None, **added}', '**added}'),
 ("enriched evidence fingerprint omits the plain start", "engram_erc/generalization.py", '            item["valid_time"] = {"start": v.start.isoformat() if v.start else None,\n', '            item["valid_time"] = {\n'),
 ("fingerprint of existing evidence changed (plain validity now written)", "engram_erc/generalization.py", "        if added:\n            item[\"valid_time\"]", "        if True:\n            item[\"valid_time\"]"),
 ("new contract names not exported", "engram_erc/__init__.py", '    "BoundaryStatus", "Occurrence",\n', ""),
 # ERC temporal comparison, increment B3 (ERC 0.6.0)
 ('B3: start window ignored (the start read as exact)', 'engram_erc/primitives/comparison.py', '    if interval.start_latest is not None:\n', '    if interval.start_latest is not None and interval.start is None:\n'),
 ('B3: end window ignored (the end read as exact)', 'engram_erc/primitives/comparison.py', '    if interval.end_earliest is not None:\n', '    if interval.end_earliest is not None and interval.end is None:\n'),
 ('B3: still going read as an end not known', 'engram_erc/primitives/comparison.py', '    if interval.end_unbounded:\n        return _NEVER', '    if interval.end_unbounded:\n        return None'),
 ('B3: an end not known read as still going', 'engram_erc/primitives/comparison.py', '    return None  # an end not known, or an upper bound only', '    return _NEVER'),
 ('B3: lower-bound start read as exact', 'engram_erc/primitives/comparison.py', '    if interval.start is not None and not interval.start_is_lower_bound:', '    if interval.start is not None:'),
 ('B3: upper-bound end read as exact', 'engram_erc/primitives/comparison.py', '    if interval.end is not None and not interval.end_is_upper_bound:', '    if interval.end is not None:'),
 ("B3: a start known only as 'no later than' ignored", 'engram_erc/primitives/comparison.py', '    if interval.start_latest is not None:\n', '    if interval.start_latest is not None and interval.start is not None:\n'),
 ("B3: an end known only as 'no earlier than' ignored", 'engram_erc/primitives/comparison.py', '    if interval.end_earliest is not None:\n', '    if interval.end_earliest is not None and interval.end is not None:\n'),
 ("B3: the disjoint test moved onto the windows' inner bounds", 'engram_erc/primitives/comparison.py', '    if left.start is not None and right.end is not None and left.start >= right.end:', '    if left.start is not None and right.end is not None and (left.start_latest or left.start) >= (right.end_earliest or right.end):'),
 ('B3: certain parts that only touch read as overlapping', 'engram_erc/primitives/comparison.py', 'max(begins) < min(ends):', 'max(begins) <= min(ends):'),
 ('B3: a shared start with ends not known read as a certain overlap', 'engram_erc/primitives/comparison.py', '    if None in begins or None in ends:\n', '    if left.start is not None and left.start == right.start and left.end is None and right.end is None and not left.end_unbounded and not right.end_unbounded:\n        return TemporalRelation.OVERLAP\n    if None in begins or None in ends:\n'),
 ('B3: a tolerance arriving unapproved (a start window that passes the end read as an exact start)', 'engram_erc/primitives/comparison.py', '    if interval.start_latest is not None:\n', '    if interval.start_latest is not None and not (interval.start is not None and interval.end is not None and interval.end_earliest is None and interval.start_latest >= interval.end):\n'),
 ('B3: two events not sent to the occurrence comparison', 'engram_erc/primitives/comparison.py', '    if left.occurred is not None and right.occurred is not None:', '    if False:'),
 ('B3: an event against a state answered as a certain overlap', 'engram_erc/primitives/comparison.py', '    elif left.occurred is not None or right.occurred is not None:\n        temporal_relation = TemporalRelation.UNKNOWN', '    elif left.occurred is not None or right.occurred is not None:\n        temporal_relation = TemporalRelation.OVERLAP'),
 ('B3: occurrence windows that share an instant read as unable to meet', 'engram_erc/primitives/comparison.py', 'left.latest < right.earliest:', 'left.latest <= right.earliest:'),
 ('B3: occurrence windows that may meet read as one instant', 'engram_erc/primitives/comparison.py', '    if _is_exact(left) and _is_exact(right):', '    if True:'),
 ('B3: the comparison reads start_basis', 'engram_erc/primitives/comparison.py', '        temporal_relation = _temporal_relation(left.valid_time, right.valid_time)', '        temporal_relation = TemporalRelation.UNKNOWN if "first_said" in (left.qualifiers.get("start_basis"), right.qualifiers.get("start_basis")) else _temporal_relation(left.valid_time, right.valid_time)'),
 ('B3: the comparison reads end_basis', 'engram_erc/primitives/comparison.py', '        temporal_relation = _temporal_relation(left.valid_time, right.valid_time)', '        temporal_relation = TemporalRelation.OVERLAP if left.qualifiers.get("end_basis") == right.qualifiers.get("end_basis") == "open" else _temporal_relation(left.valid_time, right.valid_time)'),
 ('B3: a new public name exported', 'engram_erc/primitives/__init__.py', '    "compare_propositions", "Contradiction", "ContradictionCertainty",\n', '    "compare_propositions", "Contradiction", "ContradictionCertainty", "_temporal_relation",\n'),
]
SUITES = {"base2": (BASE2, "tests/test_base2_structure.py tests/test_entity_validation.py tests/test_p2_pipeline.py tests/test_knowledge_store.py"),
          "adapter": (ADAPTER, "tests/test_erc_overlay.py tests/test_state_engine.py"),
          # The byte-pin test is left out on purpose: every mutation of a pinned file changes its bytes, so the pin would
          # "catch" all of them and prove nothing about behaviour.
          "erc": (ERC, "engram_erc/tests/test_temporal_contracts.py engram_erc/tests/test_temporal_comparison.py "
                       "--deselect engram_erc/tests/test_temporal_comparison.py::test_v1_version_and_release_pin")}
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
