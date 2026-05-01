# 11 Feature Attribution and Signal Explainability Architecture

## 1. Purpose
Close the post-monitor feature-attribution and explainability gap (`claude_worklog/post_monitor/06_FEATURE_DATA_FLOW_GAPS.md`) at the architecture-text level. Every prediction, signal, decision, risk decision, and execution intent in V2 must be resolvable to (a) the exact `feature_snapshot` that produced it and (b) the exact source-grounded contributor set that explains its confidence. Snapshots that do not satisfy the completeness rules in this document MUST be rejected at ingest, and any downstream record bound to such a snapshot MUST be rejected by the same rules. The default-deny `LIVE TRADING: BLOCKED` posture in `CLAUDE.md` is preserved: failing explainability never silently downgrades to a "best-effort" record.

## 2. Lineage IDs (mandatory, immutable)
- `feature_snapshot_id`
- `prediction_id`
- `signal_id`
- `decision_id`
- `risk_decision_id`
- `execution_intent_id`

The chain is enforced by the database (`03_DATABASE_SCHEMA.md`) and the API (`05_API_CONTRACTS.md` §1.3 / §9). This document specifies the *content* requirements that ride on top of those structural constraints.

## 3. `feature_snapshot` canonical shape

### 3.1 Identity
`feature_snapshot_id` is a deterministic, immutable surrogate key composed from:
- `symbol`
- `trigger_timeframe`
- `bucket_start_ts_ms`
- `snapshot_sequence`
- a SHA-256 hash of the normalized key/value payload (`feature_values` after canonical ordering and numeric normalization)

The same five inputs MUST yield the same `feature_snapshot_id`. Re-emission with identical inputs is idempotent (same PK, same content); re-emission with any input change yields a new `feature_snapshot_id` (the prior snapshot is immutable).

### 3.2 Required top-level fields
Every `feature_snapshot` record MUST carry:
- `feature_snapshot_id` (NOT NULL, immutable)
- `snapshot_ts_ms` (NOT NULL, monotonic per `(symbol, trigger_timeframe)`)
- `symbol` (NOT NULL)
- `trigger_timeframe` (NOT NULL, enum `{1m, 5m, 15m, 1h, 4h, 1d}`)
- `bucket_start_ts_ms` (NOT NULL, aligned to `trigger_timeframe`)
- `snapshot_sequence` (NOT NULL, monotonic per `(symbol, trigger_timeframe, bucket_start_ts_ms)`)
- `htf_context` (NOT NULL — bias payload references for higher-timeframe context, e.g. `{1h_bias_ref, 4h_bias_ref}`)
- `feature_sources[]` (NOT NULL, non-empty, see §3.3)
- `feature_values` (NOT NULL — normalized numeric/categorical payload bound to `feature_sources[]`)
- `schema_version` (NOT NULL, semver)
- `producer` (NOT NULL — emitting trainer component name)
- `model_checkpoint` (nullable — populated when the snapshot is bound to a checkpoint at inference time)

### 3.3 `feature_sources[]` entry
Every entry in `feature_sources[]` MUST carry the full source-grounding tuple:
- `source_key` — the exact Redis/storage key the value was read from (e.g. `features:BTCUSDT:1m:rsi_14`)
- `source_pattern` — the canonical Redis/storage pattern this key matches (e.g. `features:{symbol}:{timeframe}:{feature_name}`); used by the Monitor Center for SLA grouping
- `source_ts_ms` — the producer timestamp of the value at the source (NOT the snapshot read time)
- `read_ts_ms` — the snapshotter's read time
- `freshness_age_ms` — `read_ts_ms - source_ts_ms` (NOT NULL, MUST be ≥ 0)
- `freshness_sla_ms` — the SLA budget for this `source_pattern` (NOT NULL)
- `freshness_status` — enum `{fresh, warning, stale, missing}`, derived from `freshness_age_ms` vs. `freshness_sla_ms`
- `stale_flag` — boolean (`freshness_status` ∈ `{stale, missing}`)
- `missing_flag` — boolean (true when the key was absent or the value could not be parsed at read time)
- `unused_flag` — boolean (true when the value was read but not consumed by the model — e.g. masked by a feature gate or filtered by the active feature set)
- `value_present` — boolean (false ⇒ `missing_flag` MUST be true)
- `value_normalization` — enum identifying the normalization applied (`{none, zscore, minmax, log1p, categorical_index}`)

A `feature_sources[]` entry with `missing_flag=true` MUST still be emitted as a placeholder so that audit can distinguish "we tried and the source was absent" from "we never asked". Such placeholders carry `value_present=false` and the actual `feature_values` slot is omitted (not zero-filled).

### 3.4 Per-symbol/timeframe completeness manifest
Each `feature_snapshot` MUST be validated against a published `feature_set_manifest` keyed by `(symbol, trigger_timeframe, schema_version)`. The manifest enumerates the `feature_name` values the snapshotter is required to attempt. Validation is:
- every manifest `feature_name` MUST appear as a `feature_sources[]` entry (present, missing, or unused);
- no `feature_sources[]` entry may carry a `feature_name` not in the manifest (`unknown_feature` rejection — see §6);
- the manifest version is recorded in the snapshot's `schema_version`.

## 4. Snapshot completeness validation

A snapshot is *completeness-valid* iff ALL of the following hold:

1. **Identity present.** Every field listed in §3.2 is non-null and well-formed.
2. **Source coverage.** `len(feature_sources) ≥ feature_set_manifest.required_count` AND every required `feature_name` from the manifest is represented (present, missing, or unused).
3. **Freshness envelope present.** Every `feature_sources[]` entry has all freshness fields (`source_ts_ms`, `read_ts_ms`, `freshness_age_ms`, `freshness_sla_ms`, `freshness_status`).
4. **Flag tri-state coherent.** Exactly the right combination of `stale_flag`/`missing_flag`/`unused_flag` is set:
   - `freshness_status="missing"` ⇒ `missing_flag=true`, `value_present=false`.
   - `freshness_status ∈ {stale}` ⇒ `stale_flag=true`, `value_present` MAY be true (the read succeeded but is past SLA).
   - `unused_flag=true` is independent of freshness; it MAY combine with any `freshness_status`.
   - `freshness_status="fresh"` ⇒ `stale_flag=false` AND `missing_flag=false`.
   - Mutually exclusive: `value_present=true` AND `missing_flag=true` is forbidden.
5. **Non-stale critical floor.** A configurable critical floor (`critical_features[]` declared by the manifest) MUST satisfy `freshness_status="fresh"`. If any critical feature is `stale` or `missing`, the snapshot is *NOT completeness-valid* (regardless of how rich the rest is).
6. **HTF binding.** `htf_context` references resolve to existing higher-timeframe snapshots/bias rows; dangling refs invalidate the snapshot.
7. **Ordering.** `snapshot_ts_ms ≥ max(source_ts_ms over feature_sources)` and `snapshot_sequence` is strictly monotonic per `(symbol, trigger_timeframe, bucket_start_ts_ms)`.

### 4.1 Stale-tolerance class
Each `feature_name` in the manifest carries a `stale_tolerance` class: `{strict, tolerant, advisory}`.
- `strict` features MUST be `fresh`. Stale ⇒ snapshot invalid.
- `tolerant` features MAY be `stale` once but produce a `degraded_snapshot` flag.
- `advisory` features MAY be `stale` or `missing` without invalidating the snapshot but still appear in the audit trail with their flags set.

`degraded_snapshot=true` is a record-level annotation (NOT a relaxation of validation rules); downstream consumers MAY refuse degraded snapshots based on policy.

## 5. Trainer contract

No `prediction_id` may be generated without (a) a *completeness-valid* `feature_snapshot_id` and (b) a `confidence_explainability` block satisfying §7.

The trainer MUST:
1. Persist the `feature_snapshot` (and `feature_values`) BEFORE emitting `prediction_id`.
2. Bind the prediction to the exact `feature_snapshot_id` it consumed (not a "latest snapshot" reference).
3. Record the `model_version` and `checkpoint_id` active at inference time on the prediction.
4. Reject its own inference output if the bound snapshot is not completeness-valid; emit a `trainer.snapshot_invalid` audit event instead of a prediction.

## 6. Rejection rules for incomplete snapshots

The following rejection classes apply at the snapshot-ingest API boundary (`POST /v1/feature_snapshots/ingest`) AND at the database INSERT boundary (`feature_snapshots`, `feature_values`):

| Class | Trigger | API status | Behavior |
|---|---|---|---|
| `feature_snapshot.identity_missing` | Any field in §3.2 null/malformed | 422 | Reject; no row written |
| `feature_snapshot.empty_sources` | `feature_sources[] = []` | 422 | Reject; no row written |
| `feature_snapshot.source_field_missing` | Entry missing `source_key`, `source_pattern`, `source_ts_ms`, `freshness_age_ms`, or `freshness_sla_ms` | 422 | Reject; no row written |
| `feature_snapshot.flag_incoherent` | Combination violates §4 step 4 | 422 | Reject |
| `feature_snapshot.manifest_mismatch` | Required `feature_name` missing OR unknown `feature_name` present | 422 | Reject |
| `feature_snapshot.critical_floor_violated` | A `critical_features[]` entry is `stale` or `missing` | 422 | Reject |
| `feature_snapshot.htf_dangling_ref` | `htf_context` references a non-existent snapshot/bias row | 422 | Reject |
| `feature_snapshot.ordering_violation` | `snapshot_ts_ms < max(source_ts_ms)` or non-monotonic sequence | 422 | Reject |
| `feature_snapshot.duplicate` | Same `feature_snapshot_id` ingested twice with different content | 409 | Reject second; first wins |
| `feature_snapshot.unknown_feature` | `feature_name` not in manifest | 422 | Reject |
| `feature_snapshot.freshness_envelope_missing` | Any `freshness_*` field absent | 422 | Reject |

Downstream effects:
- A `prediction_events` INSERT bound to a `feature_snapshot_id` that does not exist is rejected by the FK in `03_DATABASE_SCHEMA.md` (`lineage.parent_not_found`).
- A `prediction_events` INSERT bound to a snapshot that exists but was marked `degraded_snapshot=true` is allowed by the FK but flagged in the audit trail; consumer policy decides.
- A `confidence_events` row whose `top_positive_json`/`top_negative_json` violates §7 cardinality is rejected by application validation AND by a database CHECK that enforces JSON-array length ≥ 3 on each side.

## 7. Confidence explainability block

Every `prediction_events` and downstream `signal_events` record MUST carry a `confidence_explainability` block (persisted in `confidence_events.top_positive_json` / `top_negative_json` and mirrored on the API as `PredictionExplain` / `SignalExplain`).

### 7.1 Record-level fields
- `model_version` (NOT NULL)
- `checkpoint_id` (NOT NULL)
- `calibration_version` (NOT NULL)
- `confidence_raw` (NOT NULL, in `[0, 1]`)
- `confidence_calibrated` (NOT NULL, in `[0, 1]`)
- `explainability_method` (NOT NULL, enum `{shap, integrated_gradients, feature_perturbation, attention_weights, linear_attribution}`)
- `explainability_schema_version` (NOT NULL, semver)

### 7.2 Contributor lists
- `top_positive_features[]` — ordered descending by `contribution_score` over positive contributions.
- `top_negative_features[]` — ordered ascending by `contribution_score` over negative contributions (most negative first).

Each item MUST include:
- `feature_name`
- `contribution_score` (signed float)
- `source_redis_key`
- `source_redis_pattern`
- `source_ts_ms`
- `read_ts_ms`
- `freshness_age_ms`
- `freshness_sla_ms`
- `freshness_status`
- `stale_flag`
- `missing_flag`
- `unused_flag`
- `value_at_inference` (the normalized value the model actually saw)
- `value_normalization`

The source-grounding tuple in each contributor entry MUST equal the corresponding `feature_sources[]` entry on the bound snapshot. Drift is `confidence.contributor_source_drift` (422).

### 7.3 Minimum cardinality (normative)
- `top_positive_features[]` MUST contain ≥ 3 entries.
- `top_negative_features[]` MUST contain ≥ 3 entries.
- If the underlying model genuinely has fewer than 3 positive (or negative) contributors, the missing slots MUST be filled with explicit placeholders carrying `missing_flag=true`, `contribution_score=0.0`, and a synthetic `feature_name="__placeholder_{n}__"`. Placeholders are NOT silently omitted.
- If `explainability_method` does not natively produce signed contributions (e.g. attention weights), the producer MUST run a signed surrogate (`linear_attribution` over the active feature set) and record both methods, with `explainability_method` reflecting the primary and `surrogate_method` recording the source of the signed list.

### 7.4 Stale/missing/unused contributor handling
A contributor row whose source is `stale` or `missing` is NOT excluded from the top lists (suppressing it would hide the actual driver). It is included with the appropriate flag set. A signal whose top driver is stale/missing is a strong audit signal and is highlighted on the Signal Explainability page.

`unused_flag=true` contributors MAY appear only if the explainability method natively assigns them a contribution (e.g. SHAP baseline contribution); otherwise they are excluded. The Confidence Driver Breakdown page shows unused contributors in a separate sub-panel.

### 7.5 Rejection rules for incomplete explainability
| Class | Trigger | API status |
|---|---|---|
| `confidence.explainability_missing` | Block absent on a prediction/signal record | 422 |
| `confidence.cardinality_low` | `top_positive_features[]` or `top_negative_features[]` shorter than 3 (no placeholders) | 422 |
| `confidence.contributor_field_missing` | Any field in §7.2 list absent on any entry | 422 |
| `confidence.contributor_source_drift` | Contributor source-grounding tuple disagrees with the bound snapshot | 422 |
| `confidence.method_signed_required` | `explainability_method` un-signed and no `surrogate_method` provided | 422 |
| `confidence.method_unknown` | `explainability_method` not in §7.1 enum | 422 |
| `confidence.calibration_missing` | `calibration_version` or `confidence_calibrated` absent | 422 |
| `confidence.placeholder_misuse` | Placeholder used while real contributors exist | 422 |
| `confidence.score_out_of_range` | `confidence_raw` or `confidence_calibrated` outside `[0, 1]` | 422 |

## 8. Per-stage propagation

### 8.1 Trainer inference
Emits `prediction_events` carrying `feature_snapshot_id`, `prediction_id`, full `confidence_explainability` (§7), `model_version`, `checkpoint_id`. No prediction without a completeness-valid snapshot (§4) AND a complete explainability block (§7).

### 8.2 Trainer signal publication
Emits `signal_events` carrying full upstream lineage and a `reason_json` that includes:
- a copy/reference of the bound `confidence_explainability` block,
- the `action` and `action_type`,
- the `signal_thresholds` active at decision time (e.g. confidence cutoff, calibration band).

### 8.3 Orchestrator
Emits `orchestrator_decisions` carrying upstream lineage and `policy_trace_json` (orchestrator policy steps). The orchestrator MAY consult the explainability block but MUST NOT mutate it.

### 8.4 Risk gateway
Emits `risk_decisions` carrying upstream lineage and `policy_checks_json`. A risk gateway block MUST include a reason-code list; explainability is read-only.

### 8.5 Execution intent
Emits `execution_intents` carrying full upstream lineage. No new explainability is added; the surface is the explainability already attached to the upstream prediction/signal.

## 9. Storage and retrieval surfaces

### 9.1 Tables (per `03_DATABASE_SCHEMA.md`)
- `feature_snapshots` (`source_refs_json`, `freshness_json` are NOT NULL — they hold the §3.3 tuple set)
- `feature_values` (`source_key`, `freshness_age_ms`, `stale_flag`, `missing_flag`, `unused_flag` per row)
- `prediction_events`, `confidence_events` (`top_positive_json`, `top_negative_json` carry the §7 contributor lists)
- `signal_events.reason_json` mirrors the explainability block

### 9.2 API (per `05_API_CONTRACTS.md`)
- `POST /v1/feature_snapshots/ingest` validates §3 and §4; `GET /v1/feature_snapshots/{id}` returns the canonical snapshot.
- `GET /v1/predictions/{id}/explain` returns `PredictionExplain` with the embedded snapshot + `confidence_explainability`.
- `GET /v1/signals/{id}/explain` returns `SignalExplain` with the embedded prediction-explain envelope.
- Lineage filters short-circuit chain walks: `?filter[feature_snapshot_id]=`, `?filter[prediction_id]=`, etc.

### 9.3 GUI surfaces
- **Signal Explainability page**: per-signal view showing the bound `feature_snapshot`, `feature_sources[]` table with freshness and flags, `top_positive_features[]` / `top_negative_features[]` with source links, model version/checkpoint, calibration version.
- **Confidence Driver Breakdown page**: per-prediction deep dive with contribution-score bars, stale/missing/unused badges, value-at-inference column, and links to source key inspectors.
- **Audit Ledger**: cross-links every `execution_intent_id` back through the chain to the originating `feature_snapshot_id`.
- **Monitor Center**: aggregates `freshness_status` per `source_pattern` for SLA monitoring; flags rejected snapshots and predictions.

## 10. Invariants enforced jointly with §03 and §05

- The database (`03_DATABASE_SCHEMA.md`) enforces the chain FKs and the explainability JSON cardinality CHECK. The API (`05_API_CONTRACTS.md` §9.3) embeds the resolved snapshot in `/explain` responses.
- A prediction row cannot exist without a parent snapshot (FK NOT NULL).
- A confidence row cannot pass the database without ≥ 3 entries in each top list (CHECK on JSON array length).
- A snapshot whose `feature_sources[]` violates §3.3 is rejectable at the application API boundary AND the values insert is rejectable at the `feature_values` NOT NULL boundary.
- Live execution remains BLOCKED by default (`CLAUDE.md`, `05_API_CONTRACTS.md` §7); a complete explainability block does NOT unblock live trading by itself.

## 11. Out of scope (explicitly)
- No V2 code is shipped from this document. Validators, error classes, and CHECK constraints are architecture-text deliverables, materialized in a later build task.
- No mutation of legacy Redis namespaces; explainability/freshness for V2 is computed on the V2 ingestion path, not by rewriting legacy keys.
- The connector / pre-feature ingest surface (raw market data, raw orderbook frames) is not given a `feature_snapshot_id`. It is referenced by `source_key` only.
- This document does not redefine `model_version` or `checkpoint_id` semantics; they are inherited from the trainer atlas.

## 12. Verification pointers
- Inputs incorporated:
  - `claude_worklog/v2_requirements/01_OBSERVABILITY_AND_ATTRIBUTION_SPEC.md` (canonical IDs, record envelope)
  - `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md` (ID composition, source fields, freshness policy, trainer contract)
  - `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` (stage-by-stage propagation)
  - `claude_worklog/v2_requirements/04_CONFIDENCE_EXPLAINABILITY_SCHEMA.md` (top contributor schema, minimum cardinality)
  - `claude_worklog/post_monitor/06_FEATURE_DATA_FLOW_GAPS.md` (gaps this architecture closes)
- Paired structural enforcement:
  - `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` §"feature_snapshots", §"feature_values", §"prediction_events", §"confidence_events", §"signal_events"
  - `claude_worklog/v2_architecture/05_API_CONTRACTS.md` §1.3, §3.2/§3.3, §9.2–§9.4
- Closure summary: `claude_worklog/v2_architecture_remediation/12C_FEATURE_EXPLAINABILITY_CLOSURE.md`