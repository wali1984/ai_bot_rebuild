# 12C Feature Explainability Closure

## Gap statement
Prior to this update, `claude_worklog/v2_architecture/11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md` was a 31-line skeleton. It listed the six lineage IDs and an English-prose payload outline, but did not define:
- the canonical wire/record shape of `feature_snapshot`, including `feature_sources[]` entries with `source_key`, `source_pattern`, `source_ts_ms`, `read_ts_ms`, `freshness_age_ms`, `freshness_sla_ms`, `freshness_status`;
- the tri-state coherence rules linking `stale_flag`, `missing_flag`, and `unused_flag`;
- a per-symbol/timeframe `feature_set_manifest` against which a snapshot's source coverage is validated;
- a normative "completeness-valid" predicate (§4) that snapshots MUST satisfy before any `prediction_id` may be generated;
- a `critical_features[]` floor that, when violated by stale/missing readings, invalidates the snapshot regardless of overall richness;
- the minimum-cardinality rule for `top_positive_features[]` / `top_negative_features[]` (≥ 3 each) with explicit placeholder semantics rather than silent truncation;
- the source-grounding equality requirement between confidence contributors and the bound snapshot's `feature_sources[]`;
- a dedicated rejection class catalog covering snapshot-side incompleteness (`feature_snapshot.*`) and explainability-side incompleteness (`confidence.*`);
- the joint database+API enforcement story (which fields are NOT NULL on the DB side, which are validated at the API boundary, where the rejection ultimately fires).

The post-monitor finding `06_FEATURE_DATA_FLOW_GAPS.md` enumerates exactly these missing pieces: per-key freshness SLA snapshots, durable `feature_snapshot_id`, deterministic prediction↔source binding, end-to-end event graph, and explicit stale/missing/unused annotations at prediction time. The architecture document did not previously translate any of those into rejectable, source-grounded contracts.

## What was added

1. **Canonical `feature_snapshot` shape (§3).** `feature_snapshot_id` is a deterministic SHA-256 of the normalized payload composed with `(symbol, trigger_timeframe, bucket_start_ts_ms, snapshot_sequence)`. Eleven required top-level fields are listed, including `htf_context`, `feature_sources[]`, `feature_values`, `schema_version`, and `producer`.
2. **Source-grounding tuple per `feature_sources[]` entry (§3.3).** Every entry now carries `source_key`, `source_pattern`, `source_ts_ms`, `read_ts_ms`, `freshness_age_ms`, `freshness_sla_ms`, `freshness_status`, plus the three flags (`stale_flag`, `missing_flag`, `unused_flag`), `value_present`, and `value_normalization`. Missing sources are emitted as explicit placeholders, never silently dropped.
3. **`feature_set_manifest` and coverage validation (§3.4).** A per-`(symbol, trigger_timeframe, schema_version)` manifest enumerates required `feature_name` values; the snapshot is validated against it (no missing names, no unknown names).
4. **Completeness-valid predicate (§4).** Seven explicit conditions: identity, source coverage, freshness envelope, flag coherence, critical-floor freshness, HTF binding integrity, ordering. Plus a `stale_tolerance` class (`{strict, tolerant, advisory}`) per feature so policy can distinguish "kill the snapshot" from "annotate as degraded".
5. **Trainer contract (§5).** No `prediction_id` is generated without a completeness-valid snapshot AND a complete `confidence_explainability` block. The snapshot is persisted *before* the prediction, and the prediction is bound to a specific `feature_snapshot_id` (no "latest snapshot" indirection).
6. **Rejection rules for incomplete snapshots (§6).** Eleven dedicated `feature_snapshot.*` classes — `identity_missing`, `empty_sources`, `source_field_missing`, `flag_incoherent`, `manifest_mismatch`, `critical_floor_violated`, `htf_dangling_ref`, `ordering_violation`, `duplicate`, `unknown_feature`, `freshness_envelope_missing` — each mapped to an HTTP status. Downstream effects on `prediction_events` and `confidence_events` are spelled out, including the database-side CHECK enforcing JSON-array length ≥ 3 on each top contributor list.
7. **Confidence explainability block (§7).** Record-level fields formalized (`model_version`, `checkpoint_id`, `calibration_version`, `confidence_raw`, `confidence_calibrated`, `explainability_method`, `explainability_schema_version`). Contributor-row fields formalized (twelve per row, including the source-grounding tuple and `value_at_inference`).
8. **Minimum cardinality with explicit placeholder semantics (§7.3).** Both `top_positive_features[]` and `top_negative_features[]` MUST have ≥ 3 entries; if the model genuinely has fewer, missing slots are filled with `missing_flag=true` placeholders carrying synthetic names, NOT omitted. Un-signed methods (e.g. attention weights) require a signed surrogate (`linear_attribution`) recorded under `surrogate_method`.
9. **Stale/missing/unused contributor handling (§7.4).** A contributor whose source is stale or missing remains in the top list with the flag set — suppression is forbidden because it would hide the real driver.
10. **Rejection rules for incomplete explainability (§7.5).** Nine dedicated `confidence.*` classes covering missing block, low cardinality, missing contributor fields, source drift relative to the bound snapshot, missing signed-method surrogate, unknown method, missing calibration, placeholder misuse, score out-of-range.
11. **Per-stage propagation table (§8).** What each of trainer-inference / trainer-signal-publication / orchestrator / risk / execution carries with respect to the explainability block, including the rule that orchestrator and risk MUST NOT mutate the explainability block (read-only).
12. **Joint enforcement with §03 and §05 (§9, §10).** The architecture now explicitly aligns with `03_DATABASE_SCHEMA.md` (NOT NULL columns on `feature_snapshots`, `feature_values`, `confidence_events`, plus the JSON cardinality CHECK) and with `05_API_CONTRACTS.md` §9.2–§9.4 (the validators that materialize §6 and §7.5 rejection classes at the API boundary).
13. **GUI surface mapping (§9.3).** Signal Explainability, Confidence Driver Breakdown, Audit Ledger, and Monitor Center each have a defined consumption contract over the §3–§7 fields.
14. **Out-of-scope carve-outs (§11).** No V2 code is shipped, no legacy Redis mutation, no live trading unblock, and the pre-feature connector surface is explicitly NOT given a `feature_snapshot_id`.

## Why this closes the gap

- **Snapshot incompleteness is now rejectable, not advisory.** The eleven `feature_snapshot.*` classes and the §4 completeness-valid predicate together ensure that any snapshot lacking a single source-grounding field, freshness envelope field, manifest-required `feature_name`, or fresh-critical floor entry is rejected at the API and at the database boundary. There is no path by which a partial snapshot becomes the parent of a `prediction_events` row.
- **Source grounding is end-to-end.** The contributor entries in `confidence_explainability` (§7.2) MUST source-equal the bound snapshot's `feature_sources[]`. A drift triggers `confidence.contributor_source_drift`. This makes the chain `signal → prediction → snapshot → source_key` programmatically walkable and verifiable, satisfying post-monitor finding 3 ("deterministic binding of prediction/confidence outputs to exact source feature keys and values").
- **The flag tri-state is coherent.** The §4 step 4 rules eliminate ambiguous combinations (e.g. `value_present=true` with `missing_flag=true`). This means stale/missing/unused readings produce well-defined, comparable records across snapshots.
- **Minimum cardinality is meaningful.** `top_positive_features[]` and `top_negative_features[]` cannot be silently empty or under-populated. Either real contributors are listed, or explicit placeholders make the deficit visible. This satisfies the `04_CONFIDENCE_EXPLAINABILITY_SCHEMA.md` minimum and removes the prior ambiguity about what "minimum 3" means in practice.
- **Critical-floor enforcement preserves safety.** A snapshot that is "mostly complete" but missing a `critical_features[]` reading cannot produce a prediction. This is the on-the-shelf mechanism the post-monitor finding called for and is consistent with the `CLAUDE.md` survival/auditability priorities.
- **Default-deny live trading is preserved.** Explainability completeness does NOT unblock live trading. The GO gate for live remains separate; explainability completeness is a *necessary* condition for V2 readiness, not *sufficient* for live execution.
- **The architecture text is now fully testable.** Every rule maps to a rejection class with an HTTP status, a database constraint, or a tri-state flag check. A future V2 build task that fails any class cannot claim the gap is closed.

## Verification pointers

- File updated: `claude_worklog/v2_architecture/11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md` — see §3 (canonical shape), §3.3 (source-grounding tuple), §3.4 (manifest), §4 (completeness-valid predicate, including critical-floor and stale-tolerance), §5 (trainer contract), §6 (snapshot rejection classes), §7 (confidence block, cardinality, contributor handling, rejection classes), §8 (per-stage propagation), §9 (storage/API/GUI surfaces), §10 (joint invariants).
- File created: `claude_worklog/v2_architecture_remediation/12C_FEATURE_EXPLAINABILITY_CLOSURE.md` (this file).
- Inputs incorporated:
  - `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md` — `feature_snapshot_id` composition, required fields, `feature_sources[]` shape, freshness policy fields, trainer contract.
  - `claude_worklog/v2_requirements/04_CONFIDENCE_EXPLAINABILITY_SCHEMA.md` — explainability block fields, contributor fields, minimum cardinality, compliance rule.
  - `claude_worklog/v2_requirements/01_OBSERVABILITY_AND_ATTRIBUTION_SPEC.md` — canonical IDs, mandatory record envelope.
  - `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` — stage-by-stage propagation.
  - `claude_worklog/post_monitor/06_FEATURE_DATA_FLOW_GAPS.md` — gaps closed (per-key SLA snapshots, durable `feature_snapshot_id`, deterministic source binding, end-to-end event graph, explicit stale/missing/unused).
- Paired structural enforcement (already closed):
  - `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md` (database FK / CHECK / index plan for the chain).
  - `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` (API lineage block, error classes, per-endpoint enforcement).
- Task spec: `claude_worklog/agent_supervisor/tasks/012c_feature_explainability_completeness.json`.
- Required outputs declared by task spec are both produced:
  - `claude_worklog/v2_architecture/11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md`
  - `claude_worklog/v2_architecture_remediation/12C_FEATURE_EXPLAINABILITY_CLOSURE.md`

## Out of scope
- No V2 code is shipped. Validators, rejection classes, manifest stores, and CHECK constraints are architecture-text deliverables. A later build task materializes them.
- No Redis writes, no service restarts, no live trader changes, no legacy bot mutation. `LIVE TRADING: BLOCKED` remains the default per `CLAUDE.md`.
- The pre-feature connector ingest path (raw market data, raw orderbook frames) is explicitly NOT given a `feature_snapshot_id`. Snapshots are constructed at the V2 feature-assembly stage, downstream of connectors.
- This document does not redefine `model_version` or `checkpoint_id` semantics; those remain owned by the trainer atlas.

## Status
Feature snapshot and explainability completeness architecture gap: CLOSED at the architecture-text level. A future V2 build task must materialize:
- the `feature_snapshot` schema (Pydantic/JSON-Schema model) per §3;
- the §4 completeness validator as middleware/service;
- the `feature_set_manifest` store and lookup;
- the eleven `feature_snapshot.*` and nine `confidence.*` rejection classes as exception types mapping to the documented HTTP statuses;
- the database CHECK on `top_positive_json` / `top_negative_json` JSON-array length;
- the §7.4 stale/missing/unused contributor surfacing on the Signal Explainability and Confidence Driver Breakdown pages.

Any deviation from §3, §4, §6, §7.3, or §7.5 reopens this gap.
Both files emitted as `BEGIN_FILE:` blocks under the task's allowed prefixes (`claude_worklog/v2_architecture/`, `claude_worklog/v2_architecture_remediation/`). The supervisor's `materialize_emit_files()` (`claude_worklog/tools/agent_supervisor.py:184`) will write them. Closure covers: §3 canonical snapshot shape with full source-grounding tuple (`source_key`, `source_pattern`, `source_ts_ms`/`read_ts_ms`, `freshness_age_ms`/`freshness_sla_ms`/`freshness_status`), §3.4 manifest-driven coverage, §4 seven-condition completeness-valid predicate plus stale-tolerance classes, §6 eleven `feature_snapshot.*` rejection classes, §7.3 ≥3 cardinality on both top lists with explicit placeholder semantics, §7.4 stale/missing/unused contributor handling, and §7.5 nine `confidence.*` rejection classes. No V2 code shipped, no Redis writes, no service restarts, `LIVE TRADING: BLOCKED` preserved.