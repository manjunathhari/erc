# ERC 0.5.0 — Temporal Contract Foundation (increment B1)

**Package version:** 0.5.0  
**Status:** Implemented and locally tested. Types and validation only; **no reasoning behaviour changes**.
**Baseline:** `f175f03` (tag `erc-adapter-step1a`). Specification and decisions: `claude/erc-b1-spec-validation.md`.

## What 0.5.0 adds

ERC could hold a state with two exact, known ends and nothing else. It could not tell apart a time that is unknown, a state that is still going, a date known only to a month or year, or the moment an event happened. 0.5.0 lets a caller *say* each of these. Nothing in ERC *reads* the additions yet: comparison, contradiction detection, rules and evaluation behave exactly as in 0.4.1. Later increments (B3 to B6) use them.

| Addition | Where | What it says |
|---|---|---|
| `TimeInterval` keyword-only fields `start_latest`, `end_earliest`, `start_unbounded`, `end_unbounded`, `start_is_lower_bound`, `end_is_upper_bound` | `contracts.py` | Each boundary can be exact, within a window, bounded on one side only, unknown, or explicitly unbounded |
| `TimeInterval.start_status`, `.end_status` and `BoundaryStatus` | `contracts.py` | The status of a boundary, derived from the fields and never stored, so contradictory combinations cannot be built |
| `Occurrence(earliest, latest)` | `contracts.py` | When an event happened: one instant, exact when the two are equal |
| `Proposition.occurred` (keyword-only) | `contracts.py` | An event carries `occurred`; a state carries `valid_time`; never both |

One spelling for each case:

| Case | Spelling |
|---|---|
| No temporal statement (every caller before 0.5.0) | `valid_time=None` and `occurred=None` |
| A time that is unknown | `TimeInterval()` |
| Still going | `TimeInterval(start, end_unbounded=True)` |
| Ended at a moment not known | `TimeInterval(start)` — unchanged from 0.4.1 |
| Began some time in 2021 | `TimeInterval(1 Jan 2021, start_latest=1 Jan 2022)` |
| Had begun by 5 March 2024, start not known | `TimeInterval(start_latest=5 Mar 2024)` |
| Happened at an exact moment | `Occurrence(t, t)` |

ERC holds only bounding instants. It holds no original date text and no precision label, and it parses no dates: the system that owns the facts computes the bounds.

## Compatibility

- `TimeInterval(start, end)`, `.start`, `.end`, equality and hashing of existing values are unchanged. The new fields are keyword-only, so no positional call changes meaning.
- A non-datetime passed as a boundary is now refused with a clear `ValueError` (it used to fail with an internal `AttributeError`).
- `engram_erc/generalization.py`: the snapshot fingerprint includes a new field only when it is set. Every fingerprint computed before 0.5.0 is unchanged; two intervals that differ only in a new field no longer share one.
- **`contracts.py` is no longer byte-identical to 0.4.0.** The 0.4.0 hash table is kept unedited as a historical record (its own digest is pinned). A separate release-pin table lists each file changed since 0.4.0 with the release and the reason; `contracts.py` is its only entry. The other 13 ERC 1.x files are still held to their 0.4.0 bytes.
- The deprecated 0.4.0 names (`compat.py`) are **kept** in 0.5.0. The 0.4.1 notes planned their removal "in the next release"; that removal is not part of this increment.

## Known limitations carried forward

- Every result still reports `engine_version` `0.1.8` (hard-coded in `orchestration.py`, which this increment does not touch). To be corrected in the first increment that changes that file.
- Nothing reads the new fields yet. In particular the rule engine still ignores time, a derived conclusion still has no time, and `as_of` is still not enforced (increments B3 to B6).
- The Engram adapter (`erc_overlay/`) is unchanged: it does not yet send any of the new fields.

## Tests

`engram_erc/tests/test_temporal_contracts.py` (83 tests). `engram_erc/tests/test_domain_profiles.py`: the byte-pin guard split into historical record and release pins; version assertion 0.5.0. Deliberate breakages: `python kit_tools/check_base2_breakage.py --suite erc`.

---

# ERC-4.0 General Core — General-Domain Case Intelligence

*Naming: this release was built as "ERC-4.1" to the spec `claude/erc-4-1-general-domain-spec.md` and relabelled ERC-4.0 General Core. "0.4.0" below means the earlier surgical release that carried the 4.0 label.*

**Package version:** 0.4.1  
**Status:** Implemented and locally tested. 461 tests (367 ported from 0.4.0, 94 new).

## What changed

ERC-3.0 through the 0.4.0 surgical release were already domain-neutral in their logic; only names, docstrings, examples and a few fixed lists were surgical. The General Core makes the core general and moves the surgical words into a profile.

Rules this release keeps:

1. **ERC 1.x files are byte-identical to 0.4.0** (`contracts.py`, `graph.py`, `inference.py`, `orchestration.py`, `evaluation.py`, `rules.py`, `validation.py`, `feedback.py`, `adaptation.py`, `trace_learning.py`, `primitives/`). A test checks their SHA-256 hashes.
2. **No logic changes.** A differential check (`tools/diff_check/`, re-runnable) ran every 0.4.0 test under 0.4.0 and the ported test under General Core, recording the output of every public core function (23,538 calls in 319 test cases). After mapping old names to new, every status, code, reference, count, ordering and fingerprint was identical. Limitation texts differ in wording only (same count and order).
3. **The core names no field.** No core identifier, enum value, docstring, default, message or limitation text says surgical, surgeon, clinician, clinical, patient, procedure, contraindication, complication, anatomy, operative or drain. A test parses every core module to enforce this. Exempt: `profiles/surgical.py`, `compat.py`, the `surgical_intelligence.py` alias module, examples, tests, and the frozen ERC 1.x files (`trace_learning.py` still says "patient" and "clinical" in two strings; it cannot change under rule 1).
4. **Old names keep working for one release**, with a `DeprecationWarning`. Removal is planned for the next release.

## Rename table

### Classes and functions

| 0.4.0 | General Core | Module |
|---|---|---|
| `SurgicalContext` | `CaseContext` | application |
| `SurgicalReasoningPolicy` / `Report` / `SurgicalTaskStatus` | `CaseReasoningPolicy` / `Report` / `CaseTaskStatus` | task_orchestration |
| `SurgicalTrajectory` | `CaseTrajectory` | temporal_patterns |
| `SurgicalPatternSummary` | `CasePatternSummary` | longitudinal_learning |
| `SurgicalKnowledgeGraph` | `DomainKnowledgeGraph` | knowledge_graph |
| `SurgicalIntelligenceRequest` / `Report` | `CaseIntelligenceRequest` / `Report` | case_intelligence |
| `ClinicianDecision` / `Ledger` / `Disposition` | `ReviewerDecision` / `Ledger` / `Disposition` | decision_support |
| `orchestrate_surgical_reasoning` | `orchestrate_case_reasoning` | |
| `compare_surgical_experience` | `compare_case_experience` | |
| `build_surgical_knowledge_graph` | `build_knowledge_graph` | |
| `execute_surgical_intelligence` | `execute_case_intelligence` | |
| `record_clinician_decision` | `record_reviewer_decision` | |
| module `surgical_intelligence` | module `case_intelligence` | (old module re-exports, warns on import) |

### Fields

`procedure_ref`→`activity_ref`, `distinct_procedures`→`distinct_activities`, `min_distinct_procedures`→`min_distinct_activities`, `require_same_procedure`→`require_same_activity`, `procedure_match`→`activity_match`, `surgeon_ref`→`practitioner_ref`, `distinct_surgeons`→`distinct_practitioners`, `surgeon_action_refs`→`practitioner_action_refs`, `surgeon_perception_tags`→`practitioner_perception_tags`, `clinician_ref`→`reviewer_ref`, `surgical_context`→`case_context`, `contraindication_refs`→`exclusion_refs`, `clinical_outcome`→`case_outcome`, `complication` (outcome counts)→`adverse_event`, `independent_of_local_registry`→`independent_of_local_records`.

### Enum values

| 0.4.0 | General Core |
|---|---|
| `OptionAssessmentStatus.CONTRAINDICATED` / `"contraindicated"` | `EXCLUDED` / `"excluded"` (same blocking: needs an explicit `OVERRIDDEN` disposition) |
| `DecisionSupportStatus.READY_FOR_CLINICIAN_REVIEW` | `READY_FOR_REVIEW` / `"ready_for_review"` |
| `EpisodeOutcome.COMPLICATION` | `ADVERSE_EVENT` / `"adverse_event"` |
| `KnowledgeNodeKind.ANATOMY` / `PROCEDURE` | `ENTITY` / `ACTIVITY`, with the profile word kept as the node's `subtype` |
| `EvidenceClass.SURGICAL_EXPERIENCE` | `PRACTITIONER_EXPERIENCE` (local experience; never independent external evidence) |
| `EvidenceClass.REGISTRY_ANALYSIS` | `RECORDS_ANALYSIS` |
| `OBSERVATIONAL_STUDY`, `RANDOMIZED_TRIAL` | `PUBLISHED_STUDY`, with the profile word kept as `evidence_label` |
| `GUIDELINE` | `STANDARD_OR_GUIDELINE`; `EXPERT_OPINION` is new |

Other literal codes that changed with the words: the failed-condition code `task_or_procedure_mismatch` is now `task_or_activity_mismatch`, and the synthesis outcome-count key `complication` is now `adverse_event`.

## New in General Core

- **`DomainProfile`** (`engram_erc/profiles/`): immutable and versioned. `case_label`, `activity_label`, `practitioner_label`, `reviewer_label`, `exclusion_label`, `adverse_event_label`; `evidence_classes` (profile word → core `EvidenceClass`); `node_subtypes` (profile word → core `KnowledgeNodeKind`); `label(core_value)` for display. `register_profile` / `get_profile` / `registered_profiles`.
- **`CaseIntelligenceRequest.profile_id` / `profile_version`** (default `"general"` / `"1.0.0"`), carried onto the report.
- **`CaseIntelligenceReport.replay_fingerprint`**: a SHA-256 over the profile and every decision-bearing output (statuses, stage order and results, option statuses, blocking signals, reviews, source refs, limitations). 0.4.0 had no report-level fingerprint; this one is new.
- **`KnowledgeNode.subtype`** (optional): a profile's word for the node kind. It may not be the value of a different core kind, and within one graph a subtype names one kind only, so the fingerprint stays unambiguous. The graph fingerprint uses it when present, so a surgical graph built as `ACTIVITY` + `subtype="procedure"` keeps **exactly its 0.4.0 fingerprint** (tested against a value computed with 0.4.0). Traversal never reads it.
- **`evidence_label`** (optional) on `EvidenceLinkRecord`, `ExternalEvidence` and `EvidenceSynthesisItem`: the profile's own evidence word. Rules read only the core class.
- `__version__` now comes from the `VERSION` file.

## Compatibility layer (`engram_erc/compat.py`, removed in the next release)

- Old class and function names import from the package and from their 0.4.0 module, with a `DeprecationWarning`, and return the same object as the new name.
- Old enum members are true aliases of the new ones, by attribute and by name (`KnowledgeNodeKind["ANATOMY"]`), and are never iterated. Old enum values (`"contraindicated"`, `"complication"`, `"randomized_trial"` …) are accepted by the enum constructors with a `DeprecationWarning`, for stored 0.4.0 data.
- Old field names: use `<Class>.from_legacy(**kwargs)` (on every dataclass with a renamed field) or `profiles.surgical.legacy_kwargs(**kwargs)`. `from_legacy` converts a node kind or evidence class only on classes that have `subtype` / `evidence_label`, so unrelated `kind` fields are left alone. A 0.4.0 evidence class string keeps its word as `evidence_label`; a 0.4.0 node kind `"anatomy"`/`"procedure"` keeps its word as `subtype`, which preserves the 0.4.0 graph fingerprint.

Not supported, by design or by Python:

- Reading an old attribute name on a General Core object (`report.procedure_ref`). Frozen slotted dataclasses can't hold two names for one field.
- `from module import *` does not bring in the old names (star-imports never call module `__getattr__`). Import them by name. (Listing old names in each module's `__all__` would make every star-import, including new code's, emit warnings, so General Core doesn't.)
- Accessing an old enum member by attribute (`OptionAssessmentStatus.CONTRAINDICATED`) does not warn: Python enum aliases can't. Old enum values do warn.
- `hasattr(module, "SurgicalContext")` raises when DeprecationWarnings are turned into errors, because the lookup warns. It returns `True` normally.
- Using the old enum alias directly (`KnowledgeNodeKind.PROCEDURE`) gives `ACTIVITY` with no subtype, so that graph's fingerprint changes. Use `from_legacy` or set `subtype` to keep it.
- Code that compares enum values to 0.4.0 strings (`status.value == "contraindicated"`) must change; compare members instead.

## Housekeeping in this release

- Folder name matches version (`ERC_4_0_General_Core/`; it was built as `ERC_4_1/`), both VERSION files say 0.4.1, and the zip carries no `__pycache__` or `.pytest_cache`. (The VERSION bump went in with the rename commit rather than a separate housekeeping commit.)
- pytest is the stated test runner (see top-level README).
- The ERC-1.9 core gaps (`ReasoningRequest.as_of`/`constraints`/`options`/`context_refs` ignored, no `valid_time` on derived propositions, `engine_version` hard-coded as 0.1.8, result id independent of rules and facts) are **still open**. Fixing them touches ERC 1.x files, so they belong in their own release.
