"""Deliberate breakages for the engram_interface build (build revision 2, against the frozen r10 tests).

Each breakage changes one rule (one or more text replacements) in a temporary copy of engram_interface/
and runs the copy's whole test folder, without -x, listing every test that fails.
A breakage the suite does not catch prints MISSED; a pattern not found exactly once prints !!.
A control run with no change must pass. The real files are never changed.
The repository root is put on PYTHONPATH only so that T59 can read engram_chat (read-only).
Run from anywhere: python engram_interface/tests/break_interface.py
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
REPO = PKG.parent

S, A, R, P, RD, C = "stub.py", "adapters.py", "render.py", "profiles.py", "readiness.py", "contract.py"
# Build revision 1 (25 Nov 2026): every pattern below is anchored to the built modules. Each keeps its breakage's
# id and meaning (the same rule broken). X127 to X130 are retired with the legacy helper source_is_real_run_ready
# (D-A41): they changed only that helper, and their one catching test (T130) is retired with it. Their ids are not
# reused. X131 is kept: the rule it breaks (a date written as its own token) is part of the source rule of 4.17.
# Build revision 2 adds X169 to X180 (his review of build r1). They are caught by the frozen tests and by the
# build-stage supplementary file test_build_r2_supplementary.py, which this script runs with the rest of the folder.
BREAKS = [
    # ---- revision 1 (X01-X15) ----
    ("X01 assistant words allowed as a fact source", [(S, 'if self._excerpts[s].role != "user":', "if False:")]),
    ("X02 uncertain facts given as validated", [(S, "validated = f.status == VALIDATED", "validated = True")]),
    ("X03 budget ignored", [(S, "return count_tokens(render_context(trial, notice=True)) <= budget", "return True")]),
    ("X04 empty result without a reason", [
        (S, "ctx = ModelContext(tid, question, (), (), (), prof, 0, budget, reason)",
            'ctx = ModelContext(tid, question, (), (), (), prof, 0, budget, "")'),
        (S, "ctx = ModelContext(tid, question, (), (), (), prof, 0, budget, E_BUDGET, tuple(excluded), tuple(omitted))",
            'ctx = ModelContext(tid, question, (), (), (), prof, 0, budget, "", tuple(excluded), tuple(omitted))')]),
    ("X05 source excerpts not attached to facts", [(S,
        "srcs = [self._excerpts[s] for s in dict.fromkeys(f.sources) if s not in given_ids]", "srcs = []")]),
    ("X06 dropped facts left out of the trace", [(S,
        '                entries.append(TraceEntry("fact", fid, WHY_FACT + WHY_FACT_LEFT_OUT, tuple(sorted(m)), False,\n'
        "                                          OVER_BUDGET))\n", "                pass\n")]),
    ("X07 profile fabricated", [(S, "return ProfileResult(False, (), (), NOT_UNTIL_B8)",
                                 'return ProfileResult(True, ("likes tea",), (), "")')]),
    ("X08 feedback raises instead of answering", [(S, "return FeedbackResult(False, NOT_UNTIL_B9)", "raise NotImplementedError")]),
    ("X09 reserved forget deletes", [(S, 'return Unavailable("forget")',
                                      'self._facts.pop(memory_id, None); return Unavailable("forget")')]),
    ("X10 Claude adapter puts memory in messages", [(A,
        'return {"system": system, "messages": [{"role": "user", "content": question}]}',
        'return {"messages": [{"role": "user", "content": system + "\\n\\n" + question}]}')]),
    ("X11 OpenAI answer() puts memory in the input, not instructions (r5: Responses API)", [(A,
        'return {"instructions": system, "input": question}', 'return {"input": system + "\\n\\n" + question}')]),
    ("X12 SDK imported at module load", [(A, "import importlib\n", "import importlib\nimport anthropic\n")]),
    ("X13 dates dropped from the rendered fact lines", [(R,
        'line = f"- [{f.fact_id}] ({_date(f.date)}) {f.subject}: {f.statement}',
        'line = f"- [{f.fact_id}] {f.subject}: {f.statement}')]),
    ("X14 model default hard-coded", [(A, "        self.model = model                     # IF-8: never defaulted in code\n",
                                       '        self.model = model or "some-default-model"\n')]),
    ("X15 adapter writes the question into memory", [(A, "        client = self.client(self.profile)\n",
        '        self.memory.ingest(__import__("engram_interface").Turn("user", "user", question))\n'
        "        client = self.client(self.profile)\n")]),
    # ---- revision 2 (X16-X30) ----
    ("X16 trace lists a source excerpt twice", [(S,
        "entries.append(self._source_entry(s, owners[s], asked, s in given_ids))",
        "entries.append(self._source_entry(s, owners[s], asked, s in given_ids)); "
        "entries.append(self._source_entry(s, owners[s], asked, s in given_ids))")]),
    ("X17 an excerpt given without a trace entry", [(S,
        '                entries.append(TraceEntry("excerpt", eid, WHY_EXCERPT, tuple(sorted(m)), True))\n', "")]),
    ("X18 reopen renumbers excerpts", [(S, 'self._excerpts[e["excerpt_id"]] = Excerpt(**e)',
        'e = {**e, "excerpt_id": "e" + str(len(self._excerpts) + 1000)}; self._excerpts[e["excerpt_id"]] = Excerpt(**e)')]),
    ("X19 trace counter restarts after reopen", [(S,
        'self._counters = {k: int(v) for k, v in state["counters"].items()}',
        'self._counters = {**{k: int(v) for k, v in state["counters"].items()}, "trace": 0}')]),
    ("X20 a fact id may be overwritten", [(S, "if fact.fact_id in self._facts:", "if False:")]),
    # X21 and X22 (cut sources not marked; block hides cut sources) are retired in r3: the fallback they
    # guarded was removed by the decision of 25 Nov 2026. Their ids are not reused.
    ("X23 forget deletes and ids come from the count (reuse)", [
        (S, 'return Unavailable("forget")',
            'self._excerpts.pop(memory_id, None); self._facts.pop(memory_id, None); return Unavailable("forget")'),
        (S, "        self._counters[kind] += 1\n",
            '        self._counters[kind] = len(self._excerpts) + 1 if kind == "excerpt" else self._counters[kind] + 1\n')]),
    ("X24 speaker ignored for first-person questions", [(S, "only = speaker if first_person else None", "only = None")]),
    ("X25 first-person question answered with no speaker", [(S, "if first_person and speaker is None:", "if False:")]),
    ("X26 speaker applied to every question", [(S, "only = speaker if first_person else None", "only = speaker")]),
    ("X27 per-model run settings ignored", [(A, "self.params = self._checked_params(params)", "self.params = {}")]),
    ("X28 tokens not recorded with the answer", [(A, "text, n_in, n_out, _ = self._parse(response)",
                                                  "text, n_in, n_out = self._parse(response)[0], None, None")]),
    ("X29 default budget differs from the engine's", [(C, "DEFAULT_BUDGET = 800", "DEFAULT_BUDGET = 1000")]),
    ("X30 traces not kept on disk", [(S, '"traces": [dataclasses.asdict(t) for t in self._traces.values()]}',
                                      '"traces": []}')]),
    # ---- revision 3 (X31-X33): never a fact without its supporting sentence (decision of 25 Nov 2026) ----
    ("X31 old fallback restored: fact given without its sentence", [(S,
        "            else:\n                excluded.append(fid)\n",
        "            elif fits(trial_f, trial_u, given_e):\n"
        "                given_f, given_u = trial_f, trial_u\n"
        '                entries.append(TraceEntry("fact", fid, WHY_FACT, tuple(sorted(m)), True))\n'
        "            else:\n                excluded.append(fid)\n")]),
    ("X32 left-out facts not recorded in the context", [(S, "                excluded.append(fid)\n", "                pass\n")]),
    ("X33 a given fact also listed as left out", [(S, "                given_f, given_u = trial_f, trial_u\n",
        "                given_f, given_u = trial_f, trial_u\n                excluded.append(fid)\n")]),
    # ---- revision 4 (X34-X43), patterns rewritten in r5; X40 and X42 retired in r5 (Chat Completions fields) ----
    ("X34 adapter sends a different temperature than requested", [(A,
        'req["temperature"] = self._temperature(profile, temperature, thinking_on)',
        'req["temperature"] = self._temperature(profile, temperature, thinking_on) + 0.5')]),
    ("X35 Claude adapter sends a different token limit than requested", [(A,
        'req["max_tokens"] = self._limit(max_tokens, 1, profile.max_tokens_limit)',
        'req["max_tokens"] = self._limit(max_tokens, 1, profile.max_tokens_limit) + 1')]),
    ("X36 Claude adapter drops manual thinking", [(A,
        'req["thinking"] = {"type": "enabled", "budget_tokens": n}', "pass")]),
    ("X37 OpenAI adapter sends a different reasoning effort", [(A,
        'req["reasoning"] = {"effort": reasoning["effort"]}', 'req["reasoning"] = {"effort": "high"}')]),
    ("X38 effective copied from the requested settings, not the outbound call", [(A,
        '"effective": self.effective(req, fn.profile),',
        '"effective": dict(model=fn.model, max_tokens=max_tokens, temperature=temperature, reasoning=reasoning),')]),
    ("X39 OpenAI adapter sends a different model than named", [(A,
        '        req["max_output_tokens"] = self._limit(max_tokens, profile.min_output_tokens, profile.max_tokens_limit)\n',
        '        req["model"] = req["model"] + "-latest"\n'
        '        req["max_output_tokens"] = self._limit(max_tokens, profile.min_output_tokens, profile.max_tokens_limit)\n')]),
    ("X41 an effort the model does not accept is sent anyway", [(A,
        "            if effort != DEFAULT_EFFORT and effort not in profile.efforts:\n", "            if False:\n")]),
    ("X43 served model reported as the model sent", [(A, '"served_model": served,', '"served_model": req["model"],')]),
    # ---- revision 5 (X44-X65) ----
    ("X44 OpenAI adapter sends a different token limit than requested", [(A,
        "self._limit(max_tokens, profile.min_output_tokens, profile.max_tokens_limit)",
        "self._limit(max_tokens, profile.min_output_tokens, profile.max_tokens_limit) + 1")]),
    ("X45 Claude adapter drops adaptive thinking", [(A, 'req["thinking"] = {"type": "adaptive"}', "pass")]),
    ("X46 Claude effort put inside thinking, not output_config", [(A,
        'req["output_config"] = {"effort": effort}      # never inside thinking', 'req["thinking"]["effort"] = effort')]),
    ("X47 Claude mode check skipped (adaptive sent to a legacy-only model)", [(A,
        "        if mode not in profile.modes:\n", "        if False:\n")]),
    ("X48 Claude manual budget not checked (below 1024 or not below max_tokens)", [(A,
        "if not _whole(n) or n < profile.min_budget or n >= max_tokens:", "if False:")]),
    ("X49 Claude none sent by leaving thinking out on an adaptive-default model", [(A,
        "if profile.none_sends in NONE_SENT_AS:", "if False:")]),
    ("X50 Claude effective ignores what the profile says an absent thinking field means", [(A,
        "kind = profile.omitted_means if thinking is None else", 'kind = "none" if thinking is None else')]),
    ("X51 temperature sent to a model that takes none", [
        (A, "        if profile.temperature is None:\n", "        if False:\n"),
        (A, "        low, high = profile.temperature\n", "        low, high = profile.temperature or (0, 2)\n")]),
    ("X52 temperature sent while thinking is on, where the model forbids it", [(A,
        "if thinking_on and not self._temperature_with_thinking(profile):", "if False:")]),
    ("X53 deprecated-mode warning dropped", [(A,
        'warnings.append(f"reasoning mode {mode!r} is deprecated for {profile.model}; sent because it is allowed "\n'
        '                            f"by the freeze")', "pass")]),
    ("X54 OpenAI effort allowlist ignored", [(A, 'if reasoning["effort"] not in profile.efforts:', "if False:")]),
    ("X55 OpenAI reasoning sent Chat Completions style (reasoning_effort)", [(A,
        'req["reasoning"] = {"effort": reasoning["effort"]}', 'req["reasoning_effort"] = reasoning["effort"]')]),
    ("X56 OpenAI output-limit minimum not enforced", [(A,
        "self._limit(max_tokens, profile.min_output_tokens, profile.max_tokens_limit)",
        "self._limit(max_tokens, 1, profile.max_tokens_limit)")]),
    ("X57 OpenAI effort left unsent where the model needs it named", [(A,
        "            if not profile.default_allowed:\n", "            if False:\n")]),
    ("X58 params may set or remove controlled fields", [(A, "        if bad:\n            raise ValueError(f\"per-model params",
                                                          "        if False:\n            raise ValueError(f\"per-model params")]),
    ("X59 a profile for another model accepted", [(A, "        if profile.model != model:\n", "        if False:\n")]),
    ("X60 no profile required", [(A, "        if not isinstance(profile, self.profile_type):\n", "        if False:\n")]),
    ("X61 a params temperature not checked against the profile", [(A,
        'req["temperature"] = self._temperature(profile, v, thinking_on)', 'req["temperature"] = v')]),
    ("X62 budget-exclusion notice not shown", [(R, "    if with_notice:\n        lines.append(NOTICE)\n",
                                                 "    if False:\n        lines.append(NOTICE)\n")]),
    ("X63 notice space not reserved before choosing", [(S, "render_context(trial, notice=True)", "render_context(trial, notice=False)")]),
    ("X64 notice names the facts left out", [(R, "        lines.append(NOTICE)\n",
        '        lines.append(NOTICE + " Omitted: " + ", ".join(ctx.excluded_facts))\n')]),
    ("X65 notice shown when nothing was left out", [(R,
        "with_notice = bool(ctx.excluded_facts or ctx.omitted_excerpts) if notice is None else bool(notice)",
        "with_notice = True if notice is None else bool(notice)")]),
    # ---- revision 6 (X66-X85) ----
    ("X66 Claude request does not carry the frozen API version", [(A,
        'req["extra_headers"] = {"anthropic-version": profile.api_version}', "pass")]),
    ("X67 Claude client left on the SDK's default version", [(A,
        'return module.Anthropic(default_headers={"anthropic-version": profile.api_version})', "return module.Anthropic()")]),
    ("X68 a profile for 2026-10-21 may allow temperature", [(P,
        "            if self.temperature is not None:\n", "            if False:\n")]),
    ("X69 reported API version taken from elsewhere, not the request", [(A,
        'return (req.get("extra_headers") or {}).get("anthropic-version")', 'return "2026-10-21"')]),
    ("X70 one SDK client shared across API versions", [(A,
        "return profile.api_version             # one client per API version (D-A16)", "return None")]),
    ("X71 a deprecated mode sent without the freeze allowing it", [(A,
        "            if mode not in allow_deprecated:\n", "            if False:\n")]),
    ("X72 answer() ignores the freeze's deprecated allowance", [
        (A, "self.temperature, self.reasoning, self.allow_deprecated)", "self.temperature, self.reasoning, ())"),
        (A, "self.reasoning,\n                                self.allow_deprecated)", "self.reasoning,\n                                ())")]),
    ("X73 answer() default temperature 0.0 again", [(A,
        "temperature=DEFAULT_TEMPERATURE, params=None", "temperature=0.0, params=None")]),
    ("X74 answer() does not need a profile (profile check removed from answer and its request)", [
        (A, "        self.kit_request(self.model, self.profile, self._memory_fields(\"\", question)",
            "        self.kit_request(self._any_profile().model, self._any_profile(), self._memory_fields(\"\", question)"),
        (A, "        return self.kit_request(self.model, self.profile, fields,",
            "        return self.kit_request(self._any_profile().model, self._any_profile(), fields,"),
        (A, "        client = self.client(self.profile)\n", "        client = self.client(self._any_profile())\n"),
        (A, "self.sdk_version, profile_hash(self.profile))", "self.sdk_version, profile_hash(self._any_profile()))"),
        (A, "    def api_version_sent(self, req):\n        return None\n",
            "    def api_version_sent(self, req):\n        return None\n\n"
            "    def _any_profile(self):\n"
            "        if isinstance(self.profile, self.profile_type) and self.profile.model == self.model:\n"
            "            return self.profile\n"
            "        name = self.model or 'any-model'\n"
            "        if self.provider == 'anthropic':\n"
            "            return ClaudeProfile(name, modes=('none', 'manual', 'adaptive'), none_sends='omit',\n"
            "                                 efforts=('low', 'medium', 'high', 'xhigh', 'max'), temperature=(0, 1),\n"
            "                                 api_version='2023-06-01')\n"
            "        return OpenAIProfile(name, efforts=('low', 'medium', 'high'), temperature=(0, 2))\n")]),
    ("X75 answer() request adds a temperature outside the preflight", [(A,
        "        req, warnings = self._answer_request(found.context, question)\n",
        "        req, warnings = self._answer_request(found.context, question)\n        req[\"temperature\"] = 0.0\n")]),
    ("X76 standalone excerpts left out are not recorded", [(S,
        "omitted.append(eid)               # D-A18: a standalone match left out for budget", "pass")]),
    ("X77 the notice ignores omitted excerpts", [(R,
        "with_notice = bool(ctx.excluded_facts or ctx.omitted_excerpts) if notice is None else bool(notice)",
        "with_notice = bool(ctx.excluded_facts) if notice is None else bool(notice)")]),
    ("X78 an empty budget result is not counted", [(S,
        "ctx = dataclasses.replace(ctx, tokens=used, over_budget=used > budget)",
        "ctx = dataclasses.replace(ctx, tokens=0, over_budget=False)")]),
    ("X79 an empty budget result that cannot fit is not marked (fail open)", [(S,
        "over_budget=used > budget)", "over_budget=False)")]),
    ("X80 answer() sends a result marked over budget", [(A, "        if found.context.over_budget:\n", "        if False:\n")]),
    ("X81 no-match and no-memory empty results get the notice", [(R,
        "with_notice = bool(ctx.excluded_facts or ctx.omitted_excerpts) if notice is None else bool(notice)",
        "with_notice = bool(ctx.excluded_facts or ctx.omitted_excerpts or ctx.is_empty) if notice is None else bool(notice)")]),
    ("X82 extras allowlist ignored", [(A,
        "            if k not in listed:\n                raise ValueError(f\"{k!r} is not in {profile.model}'s extras allowlist\")\n",
        "            if k not in listed:\n                req[k] = v\n                continue\n")]),
    ("X83 extras constraint ignored", [(A, "            elif extra_allows(listed[k], v):\n", "            elif True:\n")]),
    ("X84 manual budget with effort accepted", [
        (A, '            if "effort" in reasoning:\n                raise ValueError("a manual thinking budget',
            '            if False:\n                raise ValueError("a manual thinking budget'),
        (A, '            if keys != {"mode", "budget_tokens"}:\n', '            if not keys <= {"mode", "budget_tokens", "effort"}:\n')]),
    ("X85 params may use the SDK's extra_* options", [(A,
        'SDK_OVERRIDE_OPTIONS = ("extra_headers", "extra_body", "extra_query")', "SDK_OVERRIDE_OPTIONS = ()")]),
    # ---- revision 7 (X86-X117) ----
    ("X86 none_sends not checked against the supported values", [(P,
        "        if self.none_sends is not None and (not isinstance(self.none_sends, str) or self.none_sends not in NONE_SENDS):\n",
        "        if False:\n")]),
    ("X87 deprecated modes need not be supported modes", [(P,
        "        if not set(self.deprecated) <= set(self.modes):\n", "        if False:\n")]),
    ("X88 api_version format not checked", [(P,
        "    if not isinstance(v, str) or not API_VERSION_SHAPE.fullmatch(v):\n", "    if not isinstance(v, str):\n")]),
    ("X89 api_version need not be a real date", [(P,
        "        datetime.date(int(v[:4]), int(v[5:7]), int(v[8:]))\n", "        pass\n")]),
    ("X90 non-finite numbers accepted as bounds", [(P,
        "    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)\n",
        "    return isinstance(x, (int, float)) and not isinstance(x, bool)\n")]),
    ("X91 negative temperature bounds accepted", [(P, "    if low < 0 or high < 0:\n", "    if False:\n")]),
    ("X92 temperature low above high accepted", [(P, "    if low > high:\n", "    if False:\n")]),
    ("X93 token limit of zero or below accepted", [(P,
        "    if not _whole(least) or least <= 0:\n", "    if not _whole(least):\n")]),
    ("X94 non-integer token limit accepted", [(P,
        "    if not _whole(least) or least <= 0:\n", "    if isinstance(least, (int, float)) and least <= 0:\n")]),
    ("X95 least token limit above the ceiling accepted", [(P, "    if least > most:\n", "    if False:\n")]),
    ("X96 int extra bounds not type-checked", [(P,
        '            bound = _whole if kind == "int" else _finite\n', '            bound = (lambda x: True) if kind == "int" else _finite\n')]),
    ("X97 number extra bounds not type-checked", [(P,
        '            bound = _whole if kind == "int" else _finite\n', '            bound = _whole if kind == "int" else (lambda x: True)\n')]),
    ("X98 int and number extras take any argument count", [
        (P, "            if len(args) != 2:\n", "            if False:\n"),
        (P, "            if not (bound(args[0]) and bound(args[1])):\n",
            "            if len(args) >= 2 and not (bound(args[0]) and bound(args[1])):\n"),
        (P, "            if args[0] > args[1]:\n", "            if len(args) >= 2 and args[0] > args[1]:\n")]),
    ("X99 int and number extras may have low above high", [(P, "            if args[0] > args[1]:\n", "            if False:\n")]),
    ("X100 choice extra arguments not checked", [
        (P, "            if len(args) != 1 or not isinstance(args[0], tuple) or not args[0]:\n", "            if False:\n"),
        (P, "            if not all(_plain_choice(v) for v in args[0]):\n", "            if False:\n")]),
    ("X101 dict and str extras accept arguments", [(P, "        elif args:\n", "        elif False:\n")]),
    ("X102 duplicate extra names accepted", [(P, "        if name in names:\n", "        if False:\n")]),
    ("X103 empty extra names accepted", [(P,
        "        if not isinstance(name, str) or not name.strip():\n", "        if not isinstance(name, str):\n")]),
    ("X104 unknown extra kinds accepted", [(P,
        "        if not isinstance(kind, str) or kind not in EXTRA_KINDS:\n", "        if False:\n")]),
    ("X105 canonical JSON keys not sorted", [(P, "sort_keys=True, separators=", "sort_keys=False, separators=")]),
    ("X106 canonical JSON separators not fixed", [(P, 'separators=(",", ":"), ensure_ascii', "ensure_ascii")]),
    ("X107 canonical JSON escapes non-ASCII", [(P, "ensure_ascii=False, allow_nan=False", "ensure_ascii=True, allow_nan=False")]),
    ("X108 canonical JSON accepts non-finite numbers", [(P, "allow_nan=False)", "allow_nan=True)"), (P,
        '    if isinstance(x, float) and not math.isfinite(x):\n        raise ValueError("a non-finite number cannot be put in canonical JSON")\n', "")]),
    ("X109 schema version left out of the hash", [(P,
        '    return {"schema": schema, "kind": type(profile).__name__, "fields": values}',
        '    return {"kind": type(profile).__name__, "fields": values}')]),
    ("X110 profile kind left out of the hash", [(P,
        '    return {"schema": schema, "kind": type(profile).__name__, "fields": values}',
        '    return {"schema": schema, "fields": values}')]),
    ("X111 source left out of the hash", [(P,
        "    values = {f.name: _canon_value(getattr(profile, f.name)) for f in dataclasses.fields(profile)}\n",
        '    values = {f.name: _canon_value(getattr(profile, f.name)) for f in dataclasses.fields(profile) if f.name != "source"}\n')]),
    ("X112 hash over UTF-16 rather than UTF-8", [(P, '.encode("utf-8")).hexdigest()', '.encode("utf-16")).hexdigest()')]),
    ("X113 SDK major not compared with the pin (both providers from r8)", [(A, "        if major != self.sdk_major:\n", "        if False:\n")]),
    ("X114 exact SDK version not recorded", [(A, "            self.sdk_version = version\n", "")]),
    ("X115 profile token-limit ceiling not enforced", [(A,
        "        if most is not None and max_tokens > most:\n", "        if False:\n")]),
    ("X116 profile hash not reported with each call", [(A, '"profile_hash": fn.profile_hash}', '"profile_hash": None}')]),
    ("X117 SDK not pinned is accepted", [(A,
        "        if self.sdk_major is None:\n"
        "            raise ValueError(f\"the {self.provider} SDK major version must be pinned in the freeze (sdk_major)\")\n",
        "        if self.sdk_major is None:\n"
        "            self.sdk_major = read_major(getattr(module, \"__version__\", None))\n")]),
    # ---- revision 8 (X118-X131) ----
    ("X118 OpenAI SDK not pinned: only Anthropic is checked", [(A,
        '        """The installed version if its major matches the pin; ValueError otherwise. Constructs nothing."""\n',
        '        """The installed version if its major matches the pin; ValueError otherwise. Constructs nothing."""\n'
        '        if self.provider == "openai":\n            return getattr(module, "__version__", None)\n')]),
    ("X119 an unreadable SDK version is accepted", [(A,
        '        if major is None:\n            raise ValueError(f"the installed {self.provider} SDK version {version!r} cannot be read")\n',
        "        if major is None:\n            major = self.sdk_major\n")]),
    ("X120 an injected client treated as a loaded SDK by the real-run check", [(RD,
        '    if adapter._client is not None:\n        checks.fault("RR-10")\n', '    if False:\n        checks.fault("RR-10")\n')]),
    ("X121 the real-run check does not refuse an unknown sdk_version", [(RD,
        '    if adapter._client is not None:\n        checks.fault("RR-10")\n',
        '    if adapter._client is not None:\n        checks.unmade.add("RR-10")\n')]),
    ("X122 the real-run check does not check the SDK pin", [(RD,
        "    version = _sdk_checks(checks, adapter)\n",
        '    version = getattr(adapter.import_sdk() if adapter._client is None else None, "__version__", None)\n')]),
    ("X123 the real-run check constructs a client", [(RD,
        '    record = {"provider": adapter.provider,',
        '    if adapter._client is None:\n        adapter.client(profile)\n    record = {"provider": adapter.provider,')]),
    ("X124 the real-run check calls the provider", [(RD,
        '    record = {"provider": adapter.provider,',
        "    adapter._send(adapter.client(profile), adapter.kit_request(model, profile, adapter._prompt_fields('ping'), 16,\n"
        "        'default', {'mode': 'none'} if adapter.provider == 'anthropic' else {'mode': 'default'})[0])\n"
        '    record = {"provider": adapter.provider,')]),
    ("X125 a real-run profile without max_tokens_limit accepted", [(RD,
        '    if not checks.blocked("RR-04", ("RR-01",)) and profile.max_tokens_limit is None:\n',
        '    if not checks.blocked("RR-04", ("RR-01",)) and False:\n')]),
    ("X126 a real-run profile's source not checked", [(RD,
        "        _source_checks(checks, profile.source, adapter.provider)\n", "        pass\n")]),
    # X127 to X130 are retired at the build with the legacy helper source_is_real_run_ready (D-A41).
    ("X131 the source date may be joined to other characters", [(RD,
        'DATE = re.compile(r"(?<![A-Za-z0-9_-])(\\d{4})-(\\d{2})-(\\d{2})(?![A-Za-z0-9_-])")',
        'DATE = re.compile(r"(\\d{4})-(\\d{2})-(\\d{2})")')]),
    # ---- revision 9 (X132-X153) ----
    ("X132 host matched as a substring", [(RD, "        if host.lower() not in DOC_HOSTS[provider]:\n",
        "        if not any(h in host.lower() for h in DOC_HOSTS[provider]):\n")]),
    ("X133 host matched by suffix", [(RD, "        if host.lower() not in DOC_HOSTS[provider]:\n",
        "        if not any(host.lower().endswith(h) for h in DOC_HOSTS[provider]):\n")]),
    ("X134 host found anywhere in the URL", [(RD, "        if host.lower() not in DOC_HOSTS[provider]:\n",
        "        if not any(h in urls[0] for h in DOC_HOSTS[provider]):\n")]),
    ("X135 any provider's host accepted", [(RD, "        if host.lower() not in DOC_HOSTS[provider]:\n",
        "        if host.lower() not in sum(DOC_HOSTS.values(), ()):\n")]),
    ("X136 allowlists swapped", [(RD,
        'DOC_HOSTS = types.MappingProxyType({"anthropic": ("platform.claude.com",), "openai": ("developers.openai.com",)})',
        'DOC_HOSTS = types.MappingProxyType({"anthropic": ("developers.openai.com",), "openai": ("platform.claude.com",)})')]),
    ("X137 http accepted", [(RD, '    if parts.scheme.lower() != "https":\n', '    if parts.scheme.lower() not in ("https", "http"):\n')]),
    ("X138 user-info accepted", [(RD, '    if at:\n        return "user-info", ""\n', '    if False:\n        return "user-info", ""\n')]),
    ("X139 explicit port accepted (any port)", [(RD, "    elif port != ALLOWED_PORT:\n", "    elif False:\n")]),
    ("X140 trailing dot accepted", [(RD, '    if host.endswith("."):\n', "    if False:\n")]),
    ("X141 punycode labels accepted", [(RD,
        '    if any(label.lower().startswith("xn--") for label in host.split(".")):\n', "    if False:\n")]),
    ("X142 non-ASCII hostnames accepted", [(RD, "    if not host.isascii():\n", "    if False:\n"),
        (RD, "    if not HOST_CHARS.fullmatch(host):\n", "    if False:\n")]),
    ("X143 percent-encoded hostname accepted", [(RD, '    if "%" in host:\n', "    if False:\n"),
        (RD, "    if not HOST_CHARS.fullmatch(host):\n", "    if False:\n")]),
    ("X144 host compared case-sensitively", [(RD, "        if host.lower() not in DOC_HOSTS[provider]:\n",
        "        if host not in DOC_HOSTS[provider]:\n")]),
    ("X145 more than one address accepted (first used)", [(RD, "    if len(urls) + len(bare) != 1:\n",
        "    if len(urls) + len(bare) == 0:\n")]),
    ("X146 more than one date accepted (first used)", [(RD, "    if len(dates) != 1:\n", "    if len(dates) == 0:\n")]),
    ("X147 a date inside an address counted", [(RD,
        "    dates = DATE.findall(rest)                     # outside every address, explicit or bare\n",
        "    dates = DATE.findall(source)\n")]),
    ("X148 an invalid date accepted", [(RD, "            datetime.date(int(y), int(m), int(d))\n", "            pass\n")]),
    ("X149 stop at the first fault restored", [(RD,
        "    found = sorted(checks.found, key=lambda f: FAULT_ORDER.index(f.id))\n",
        "    found = sorted(checks.found, key=lambda f: FAULT_ORDER.index(f.id))\n"
        "    first = next((f for f in found if f.status == 'fault'), None)\n    found = [first] if first else found\n")]),
    ("X150 findings not in the fixed order", [(RD,
        "    found = sorted(checks.found, key=lambda f: FAULT_ORDER.index(f.id))\n",
        "    found = sorted(checks.found, key=lambda f: -FAULT_ORDER.index(f.id))\n")]),
    ("X151 a dependent check invented as a fault", [(RD,
        '    if not checks.blocked("RR-14", ("RR-10", "RR-11", "RR-12", "RR-13")) and read_major(version) != adapter.sdk_major:\n',
        '    if any(n in checks.unmade for n in ("RR-10", "RR-11", "RR-12", "RR-13")) or read_major(version) != adapter.sdk_major:\n')]),
    ("X152 skipped findings dropped", [(RD, "        raise RealRunRefused(found)\n",
        '        raise RealRunRefused([f for f in found if f.status == "fault"])\n')]),
    ("X153 one concatenated message, no structured list", [(RD,
        "        self.findings = tuple(findings)\n"
        '        self.faults = tuple(f for f in self.findings if f.status == "fault")\n'
        '        lines = "; ".join(f"{f.id} {f.status}: {f.message}" for f in self.findings)\n',
        '        lines = "; ".join(f"{f.id} {f.status}: {f.message}" for f in findings)\n'
        "        self.findings = self.faults = ()\n")]),
    # ---- revision 10 (X154-X168) ----
    ("X154 the :443 check accepts any number", [(RD, "    elif port != ALLOWED_PORT:\n", "    elif not port.isdigit():\n")]),
    ("X155 the port judged by integer value (0443, +443 accepted)", [(RD, "    elif port != ALLOWED_PORT:\n",
        '    elif not (port.lstrip("+").isdigit() and int(port) == 443):\n')]),
    ("X156 port judged from text anywhere in the URL", [(RD, "    if not colon:\n        host = hostport\n",
        '    if re.search(r":(?!443\\b)\\d+", url.split("://", 1)[1]):\n        return "port text", ""\n'
        "    if not colon:\n        host = hostport\n")]),
    ("X157 the authority taken from a raw split on '/' (r9 behaviour)", [(RD, "    authority = parts.netloc\n",
        '    authority = url.split("://", 1)[1].split("/", 1)[0]\n')]),
    ("X158 the ASCII check applied to the whole URL", [(RD, "    if not host.isascii():\n", "    if not url.isascii():\n")]),
    ("X159 the punycode check applied to the whole URL", [(RD,
        '    if any(label.lower().startswith("xn--") for label in host.split(".")):\n', '    if "xn--" in url.lower():\n')]),
    ("X160 the percent check applied to the whole URL", [(RD, '    if "%" in host:\n', '    if "%" in url:\n')]),
    ("X161 bare domains and www addresses ignored", [(RD, "        if cleaned and _is_bare_address(cleaned):\n", "        if False:\n")]),
    ("X162 www addresses not counted", [(RD, '    if token.lower().startswith("www."):\n        return True\n', "")]),
    ("X163 the bare-domain rule counts any dotted token", [(RD,
        "    return (len(labels) >= 2 and all(LABEL.fullmatch(l) for l in labels) and labels[-1].lower() in BARE_TLDS)\n",
        "    return len(labels) >= 2\n")]),
    ("X164 a lone bare domain treated as an https URL", [(RD,
        '        if bare:\n            checks.fault("RR-06", f"{bare[0]!r} is a bare or www address")\n            host = ""\n'
        "        else:\n            problem, host = _url_problem(urls[0])\n",
        "        if True:\n            problem, host = _url_problem(urls[0] if urls else \"https://\" + bare[0])\n")]),
    ("X165 backslash refused only in the hostname", [(RD, '    if "\\\\" in url:\n',
        '    if "\\\\" in url.split("://", 1)[-1].split("/", 1)[0]:\n')]),
    ("X166 hostname character check removed", [(RD, "    if not HOST_CHARS.fullmatch(host):\n", "    if False:\n")]),
    ("X167 user-info detected only with a password", [(RD, "    if at:\n", '    if at and ":" in userinfo:\n')]),
    ("X168 RR-05 and RR-06 descriptions not updated", [(RD,
        '    "RR-05": "the source does not hold exactly one address (an explicit URL, a bare domain or a www address)",',
        '    "RR-05": "the source does not hold exactly one URL",')]),
    # ---- build revision 2 (X169-X180): his review of build r1 (25 Nov 2026, 20:29), points A to C ----
    ("X169 the missing-address refusal bypassed (a source with no address accepted)", [
        (RD, "    if len(urls) + len(bare) != 1:\n", "    if len(urls) + len(bare) > 1:\n"),
        (RD, '    if not checks.blocked("RR-06", ("RR-05",)):\n', '    if (urls or bare) and not checks.blocked("RR-06", ("RR-05",)):\n'),
        (RD, '    if not checks.blocked("RR-07", ("RR-05", "RR-06")):\n',
             '    if (urls or bare) and not checks.blocked("RR-07", ("RR-05", "RR-06")):\n')]),
    ("X170 the missing-date refusal bypassed (a source with no date accepted)", [
        (RD, "    if len(dates) != 1:\n", "    if len(dates) > 1:\n"),
        (RD, '    if not checks.blocked("RR-09", ("RR-08",)):\n', '    if dates and not checks.blocked("RR-09", ("RR-08",)):\n')]),
    ("X171 FAULTS made a mutable dict", [(RD, "FAULTS = types.MappingProxyType({\n", "FAULTS = dict({\n")]),
    ("X172 DOC_HOSTS made a mutable dict", [(RD,
        'DOC_HOSTS = types.MappingProxyType({"anthropic": ("platform.claude.com",), "openai": ("developers.openai.com",)})',
        'DOC_HOSTS = dict({"anthropic": ("platform.claude.com",), "openai": ("developers.openai.com",)})')]),
    ("X173 DOC_HOSTS host entries made mutable lists", [(RD,
        'DOC_HOSTS = types.MappingProxyType({"anthropic": ("platform.claude.com",), "openai": ("developers.openai.com",)})',
        'DOC_HOSTS = types.MappingProxyType({"anthropic": ["platform.claude.com"], "openai": ["developers.openai.com"]})')]),
    ("X174 findings ordered by iterating FAULTS, not by FAULT_ORDER", [(RD,
        "    found = sorted(checks.found, key=lambda f: FAULT_ORDER.index(f.id))\n",
        "    found = sorted(checks.found, key=lambda f: list(FAULTS).index(f.id))\n")]),
    ("X175 FAULT_ORDER made a mutable list", [(RD,
        'FAULT_ORDER = ("RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06", "RR-07", "RR-08", "RR-09", "RR-10", "RR-11",\n'
        '               "RR-12", "RR-13", "RR-14")\n',
        'FAULT_ORDER = ["RR-01", "RR-02", "RR-03", "RR-04", "RR-05", "RR-06", "RR-07", "RR-08", "RR-09", "RR-10", "RR-11",\n'
        '               "RR-12", "RR-13", "RR-14"]\n'), (RD, "if tuple(FAULTS) != FAULT_ORDER:\n", "if list(FAULTS) != FAULT_ORDER:\n")]),
    ("X176 a permitted profile list stored un-normalised (the caller's list kept)", [(P,
        "    object.__setattr__(profile, name, tuple(value))\n", "")]),
    ("X177 permitted profile lists refused (tuple only)", [(P,
        "    if not isinstance(value, (tuple, list)) or not all(isinstance(v, str) for v in value):\n",
        "    if not isinstance(value, tuple) or not all(isinstance(v, str) for v in value):\n")]),
    ("X178 a temperature list accepted, where the specification states a tuple", [(P,
        "    if not isinstance(t, tuple) or len(t) != 2:\n", "    if not isinstance(t, (tuple, list)) or len(t) != 2:\n")]),
    ("X179 reviewed data may be rebound through the package or module", [(RD,
        "        if name in PROTECTED and name in self.__dict__:\n", "        if False:\n"),
        (RD, "        if name in PROTECTED:\n            raise AttributeError(f\"{name} is reviewed data and cannot be deleted\")\n",
             "        if False:\n            raise AttributeError(f\"{name} is reviewed data and cannot be deleted\")\n")]),
    ("X180 an extras list accepted, where the specification states a tuple", [(P,
        "    if not isinstance(extras, tuple):\n", "    if not isinstance(extras, (tuple, list)):\n")]),
]


def run(name, edits):
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "engram_interface"
        shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__", "break_interface.py"))
        for fname, old, new in edits:
            f = dst / fname
            src = f.read_text()
            if src.count(old) != 1:
                return f"!! {name}: pattern found {src.count(old)} times in {fname}", []
            f.write_text(src.replace(old, new))
        env = dict(os.environ, PYTHONPATH=str(REPO))
        p = subprocess.run([sys.executable, "-m", "pytest", "engram_interface/tests", "-q", "-p", "no:cacheprovider", "-rfE"],
                           cwd=tmp, capture_output=True, text=True, env=env)
        lines = p.stdout.splitlines()
        tail = next((l.strip("= ") for l in reversed(lines) if re.search(r"\d+ (passed|failed|error)", l)), "(no totals)")
        failing = sorted({l.split(" ")[1].split(" - ")[0] for l in lines if l.startswith(("FAILED ", "ERROR "))})
        if p.returncode == 0:
            return f"MISSED {name}: {tail}", []
        return f"caught {name}: {len(failing)} failing ({tail})", failing


def main():
    ctrl, _ = run("X00 control (no change)", [])
    print(ctrl.replace("MISSED", "control passes").replace("caught", "!! control FAILS"))
    caught = 0
    for name, edits in BREAKS:
        head, failing = run(name, edits)
        print(head)
        for t in failing:
            print(f"    {t.replace('engram_interface/tests/', '')}")
        caught += head.startswith("caught")
    print(f"{caught} of {len(BREAKS)} breakages caught")
    return 0 if caught == len(BREAKS) and ctrl.startswith("MISSED") else 1


if __name__ == "__main__":
    sys.exit(main())
