# ERC-4.0 General Core Host Integration Notes

## 1. Integration principle

ERC-4.0 General Core is a stateless orchestration pass over an immutable request snapshot. It does not own the host's record system, canonical knowledge entities, source documents, P6 experience ledger, or audit database. The host remains the source of truth.

The host also chooses a domain profile (`profile_id`, `profile_version` on the request). The profile only supplies the words shown to users; it does not change any decision. A host that shows words to people should render core values through `profile.label(...)`.

## 2. Input mapping

| ERC request field | Host source | Mapping rule |
|---|---|---|
| `reasoning_request` | Existing reasoning/extraction output | Preserve proposition/evidence/source refs; do not re-extract variables already stored |
| `case_context` | The case record and its context in the host's record system | Use stable case/context/activity/site refs and timestamped source-backed facts |
| `governed_knowledge` + `lifecycle` | Existing governed knowledge projection | Include only lifecycle-reviewed records; preserve exact candidate/evidence refs |
| `situation_rules` + `observations` | Recorded observations and configured thresholds | Explicit units, subject/case refs, timestamps and source refs are mandatory |
| `knowledge_graph` + queries | Existing entity/relation/evidence stores | Build an in-memory graph projection; do not persist duplicate graph nodes in ERC |
| `current_trajectory` + historical episodes | The record system's event timeline | Use ordered, source-linked event codes and adjudicated historical outcomes |
| `experience_details` | Practitioner action records and adjudicated follow-up | Join on exact episode and adjudication references; do not infer missing action records |
| `feedback_ledger` | ERC adjudication projection | Supply immutable feedback records already approved for strategy adaptation |
| `external_strategy_scores` | Thin adapter over existing P6.3 | Pass through score, sample size, exact context key, uncertainty note and source ref; do not recompute P6 logic |
| `decision_options` | Reviewer-authored candidate options (`exclusion_refs` marks an option the reviewer may only take by explicit override) | Include only options explicitly in scope; ERC structures but does not select them |

## 3. Recommended call boundary

1. Host reads its record system, knowledge store, evidence store and P6 state using its existing read transactions.
2. Host constructs one immutable `CaseIntelligenceRequest` with a common `generated_at` snapshot boundary and its `profile_id`/`profile_version`.
3. Host calls `execute_case_intelligence` with approved policies and bounded limits.
4. Host renders the report and provenance to the reviewer, in the profile's words.
5. If a reviewer adjudicates or makes a decision, the host writes that event through its existing record-system/P6 transaction boundaries. ERC does not write it.

Do not hold database transactions open while ERC evaluates rules, traverses graph paths or compares historical episodes. Materialize a bounded snapshot, close the read transaction, execute, then persist any approved reviewer event separately.

## 4. Adaptive selection and P6

The `StrategyExperienceScore` adapter must be read-only and return exact `strategy_ref` and context keys. The default minimum adjudicated support is five observations. If no candidate reaches the configured threshold, ERC records `INSUFFICIENT_EXPERIENCE` and retains eligible catalog priority. A score must never bypass `StrategyCatalog.eligible(...)`; the execution layer ranks only eligible strategies and sends the selected ref back through the canonical eligibility check.

P6 remains the owner of its adaptive scorer and persistence. Do not add another Beta scorer or duplicate experience table in ERC.

## 5. Safety gates and policy configuration

- Default blocking severity: `critical`.
- Host may configure additional severities to block, but must do so explicitly and version the policy.
- High/other active signals are surfaced for review by default; they do not silently become blockers.
- A blocked safety gate skips contextual reasoning and all downstream case-comparison/decision stages.
- `require_situation_assessment`, `require_temporal_comparison` and `require_decision_structuring` express workflow completeness requirements, not domain thresholds.
- The host must continue to run its own emergency escalation/alert workflow. ERC does not deliver alerts.

## 6. Audit and replay fields to persist at the host boundary

Persist or reference (according to host policy): request ID, generated-at timestamp, profile id and version, replay fingerprint, policy versions, ruleset version/fingerprint, catalog version, context/case refs, input snapshot refs, graph fingerprint, selected strategy ref, adaptation report and score source refs, stage statuses, result/trace refs, limitations, reviewer disposition and adjudication ref. Do not duplicate raw source text in the ERC report.

## 7. Rollout

**M1 — offline replay:** run against a frozen, privacy-minimised snapshot of the record system; verify deterministic stage order, graph path provenance, strategy eligibility and replay fingerprints.

**M2 — shadow mode:** compute reports alongside existing workflow without exposing automated actions; compare safety-gate behavior and missing-data handling with reviewer adjudication.

**M3 — reviewer-facing review:** expose stage-by-stage outputs, uncertainty, source refs and cross-domain transfer warnings. Require explicit acknowledgement for locally configured high-risk signals.

**M4 — governed feedback:** only after audit approval, route reviewer decisions/outcomes to the existing record-system and P6 transactions. ERC remains read-only.

## 8. Not claimed

This package has not been merged into the private Engram repository, connected to a live record system, or verified against production P6 records. The local tests validate the ERC package contracts and composition, not a live deployment or a safety certification for any field.

## 9. Term map for the surgical registry

For a surgical deployment (profile `surgical`, see `engram_erc/profiles/surgical.py`):

| General term (General Core) | Surgical registry term |
|---|---|
| the host's record system | the surgical registry |
| case / `case_context` | patient case / `surgical_context` (0.4.0) |
| activity / `activity_ref` | procedure / `procedure_ref` (0.4.0) |
| practitioner / `practitioner_ref` | surgeon / `surgeon_ref` (0.4.0) |
| reviewer / `reviewer_ref` | clinician / `clinician_ref` (0.4.0) |
| excluded / `exclusion_refs` | contraindicated / `contraindication_refs` (0.4.0) |
| adverse event | complication |
| `PRACTITIONER_EXPERIENCE` | surgical experience (local; never independent external evidence) |
| `RECORDS_ANALYSIS` | registry analysis |
| node `ENTITY` / `ACTIVITY` + `subtype` | anatomy / procedure nodes |

Build registry-adapter requests with the General Core names directly. For stored 0.4.0 data, `from_legacy(...)` and `profiles.surgical.legacy_kwargs(...)` translate old field names and values (see `README_ERC_4_0.md`).
