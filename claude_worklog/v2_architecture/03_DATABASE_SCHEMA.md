# 03 Database Schema

## Schema objective
Provide a normalized system-of-record supporting full lineage, governance, approvals, replay/paper, monitoring, and audit. Every workflow row from feature snapshot to execution intent must be traceable end-to-end through enforceable foreign keys, NOT NULL constraints, and audit indexes. Any row missing upstream attribution must be rejectable at the database boundary, not relied upon to be filtered in application code.

## Lineage chain (canonical, enforceable)
The full attribution chain is:

`feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id`

Every link in this chain is:
- a NOT NULL foreign key on the downstream table
- ON DELETE RESTRICT (no silent cascade that would erase audit history)
- ON UPDATE RESTRICT (PKs are immutable surrogate keys; updates are forbidden)
- enforced by a database CHECK or NOT NULL constraint, not by application code
- backed by a B-tree index on the FK column for join/explainability speed
- backed by a covering index on `(parent_id, created_ts_ms)` for replay ordering

A row that cannot satisfy its parent FK MUST be rejected at INSERT time. The database is the final gate for missing-attribution rejection. Application code may pre-validate, but pre-validation is not authoritative.

## Tables and key fields

### `exchanges`
- `exchange_id` (PK), `name`, `market_scope`, `status`, `created_ts_ms`, `updated_ts_ms`

### `exchange_connectors`
- `connector_id` (PK), `exchange_id` (FK), `version`, `capabilities_json`, `health_status`, `enabled`, `created_ts_ms`, `updated_ts_ms`

### `exchange_symbols`
- `exchange_symbol_id` (PK), `exchange_id` (FK), `symbol`, `market_type`, `base_asset`, `quote_asset`, `contract_meta_json`, `status`, `updated_ts_ms`

### `universe_versions`
- `universe_version_id` (PK), `version`, `state` (`proposed|validated|approved|applied|verified`), `change_set_json`, `requested_by`, `approved_by`, `created_ts_ms`, `applied_ts_ms`

### `universe_members`
- `universe_member_id` (PK), `universe_version_id` (FK), `layer` (`available|observed|training|trading`), `exchange_symbol_id` (FK), `train_enabled`, `trade_enabled`, `paper_only`, `live_allowed`, `manual_override_state`, `override_reason`, `updated_ts_ms`

### `symbol_scores`
- `symbol_score_id` (PK), `universe_version_id` (FK), `exchange_symbol_id` (FK), `data_completeness_score`, `liquidity_score`, `spread_score`, `volatility_score`, `funding_score`, `open_interest_score`, `orderbook_depth_score`, `liquidation_activity_score`, `technical_regime_score`, `feature_freshness_score`, `paper_performance_score`, `ranking_score`, `score_components_json`, `created_ts_ms`

### `symbol_overrides`
- `symbol_override_id` (PK), `exchange_symbol_id` (FK), `override_type`, `before_value_json`, `after_value_json`, `risk_level`, `reason`, `rollback_value_json`, `changed_by`, `approval_state`, `created_ts_ms`

### `feature_snapshots`
- `feature_snapshot_id` (PK, immutable surrogate key, NOT NULL)
- `symbol` (NOT NULL)
- `timeframe` (NOT NULL)
- `source_refs_json` (NOT NULL — must enumerate raw source pointers)
- `freshness_json` (NOT NULL — per-feature freshness manifest)
- `model_checkpoint` (nullable — populated when snapshot is bound to a checkpoint)
- `created_ts_ms` (NOT NULL)
- Constraints:
  - PK is the only entry point for downstream lineage. Snapshot rows cannot be deleted while any `prediction_events` row references them.
- Indexes:
  - `idx_feature_snapshots_symbol_ts (symbol, created_ts_ms)` for explainability lookup
  - `idx_feature_snapshots_checkpoint (model_checkpoint)` for checkpoint-scoped audit

### `feature_values`
- `feature_value_id` (PK)
- `feature_snapshot_id` (FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT)
- `feature_name`, `feature_value`, `source_key`, `freshness_age_ms`, `stale_flag`, `missing_flag`, `unused_flag`
- Indexes:
  - `idx_feature_values_snapshot (feature_snapshot_id)` for snapshot expansion
  - `idx_feature_values_snapshot_name (feature_snapshot_id, feature_name)` for feature-by-name lookup

### `prediction_events`
- `prediction_id` (PK, immutable, NOT NULL)
- `feature_snapshot_id` (FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT — REQUIRED upstream link)
- `symbol` (NOT NULL), `timeframe` (NOT NULL)
- `model_version` (NOT NULL), `checkpoint` (NOT NULL)
- `raw_output_json` (NOT NULL)
- `created_ts_ms` (NOT NULL)
- Constraints:
  - INSERT MUST fail if `feature_snapshot_id` is NULL or does not resolve to an existing `feature_snapshots.feature_snapshot_id`. This is the missing-attribution rejection point for predictions.
  - CHECK: `model_version` and `checkpoint` non-empty.
- Indexes:
  - `idx_predictions_snapshot (feature_snapshot_id)` for snapshot -> prediction joins
  - `idx_predictions_symbol_ts (symbol, created_ts_ms)` for time-series explainability
  - `idx_predictions_checkpoint (checkpoint)` for checkpoint-scoped audit

### `confidence_events`
- `confidence_event_id` (PK)
- `prediction_id` (FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT)
- `confidence_before`, `confidence_after`, `top_positive_json`, `top_negative_json`, `created_ts_ms`
- Indexes:
  - `idx_confidence_prediction (prediction_id)`

### `signal_events`
- `signal_id` (PK, immutable, NOT NULL)
- `prediction_id` (FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT — REQUIRED upstream link)
- `symbol` (NOT NULL), `action` (NOT NULL), `confidence` (NOT NULL)
- `reason_json` (NOT NULL — explainability payload)
- `created_ts_ms` (NOT NULL)
- Constraints:
  - INSERT MUST fail if `prediction_id` is NULL or unresolved. No floating signals.
  - CHECK: `action IN ('long','short','flat','close')`.
  - CHECK: `confidence BETWEEN 0 AND 1`.
- Indexes:
  - `idx_signals_prediction (prediction_id)` for prediction -> signal joins
  - `idx_signals_symbol_ts (symbol, created_ts_ms)` for explainability timeline
  - `idx_signals_action_ts (action, created_ts_ms)` for action-scoped audit

### `orchestrator_decisions`
- `decision_id` (PK, immutable, NOT NULL)
- `signal_id` (FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT — REQUIRED upstream link)
- `decision_action` (NOT NULL), `decision_reason` (NOT NULL)
- `policy_trace_json` (NOT NULL — orchestrator policy step trace)
- `created_ts_ms` (NOT NULL)
- Constraints:
  - INSERT MUST fail if `signal_id` is NULL or unresolved. Orchestrator cannot decide without a signal.
  - CHECK: `decision_action IN ('forward','reject','defer','split')`.
- Indexes:
  - `idx_decisions_signal (signal_id)` for signal -> decision joins
  - `idx_decisions_action_ts (decision_action, created_ts_ms)` for policy audit

### `risk_decisions`
- `risk_decision_id` (PK, immutable, NOT NULL)
- `decision_id` (FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT — REQUIRED upstream link)
- `allow_block` (NOT NULL — `allow|block`)
- `block_reason` (nullable iff `allow_block = 'allow'`; NOT NULL when `block`)
- `policy_checks_json` (NOT NULL — full check trace)
- `created_ts_ms` (NOT NULL)
- Constraints:
  - INSERT MUST fail if `decision_id` is NULL or unresolved. Risk gate has no input without an orchestrator decision.
  - CHECK: `allow_block IN ('allow','block')`.
  - CHECK: `(allow_block = 'allow' AND block_reason IS NULL) OR (allow_block = 'block' AND block_reason IS NOT NULL)`.
- Indexes:
  - `idx_risk_decision (decision_id)` for decision -> risk joins
  - `idx_risk_allow_block_ts (allow_block, created_ts_ms)` for risk-event audit

### `execution_intents`
- `execution_intent_id` (PK, immutable, NOT NULL)
- `risk_decision_id` (FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT — REQUIRED upstream link)
- `trader_id` (FK NOT NULL)
- `intent_action` (NOT NULL), `mode` (NOT NULL — `paper|live`)
- `status` (NOT NULL)
- `created_ts_ms` (NOT NULL), `executed_ts_ms` (nullable until executed)
- Constraints:
  - INSERT MUST fail if `risk_decision_id` is NULL or unresolved.
  - CHECK: a row with `risk_decisions.allow_block = 'block'` MUST NOT produce an `execution_intents` row. Enforced via trigger or a partial-unique constraint that asserts the parent risk decision is `allow`.
  - CHECK: `mode IN ('paper','live')`.
  - CHECK: live execution requires a separate live-readiness gate (see `approvals`); the schema rejects `mode = 'live'` when global `LIVE_TRADING_BLOCKED` flag table is set.
- Indexes:
  - `idx_intents_risk (risk_decision_id)` for risk -> intent joins
  - `idx_intents_trader_ts (trader_id, created_ts_ms)` for trader audit
  - `idx_intents_mode_status_ts (mode, status, created_ts_ms)` for execution dashboards

### `trader_instances`
- `trader_id` (PK), `account_id`, `exchange_id`, `strategy_profile`, `symbol_scope_json`, `risk_profile_json`, `paper_live_mode`, `heartbeat_ts_ms`, `pnl_json`, `attribution_completeness`, `status`

### `trader_assignments`
- `assignment_id` (PK), `trader_id` (FK), `exchange_symbol_id` (FK), `assignment_state`, `created_ts_ms`, `updated_ts_ms`

### `audit_events`
- `audit_event_id` (PK), `actor_type`, `actor_id`, `action`, `resource_type`, `resource_id`, `before_json`, `after_json`, `reason`, `evidence_pointers_json`, `approval_state`, `created_ts_ms`

### `ai_action_changes`
- `change_id` (PK), `actor` (`claude|codex|ollama|human|system`), `risk_level`, `reason`, `evidence_pointers_json`, `before_value_json`, `after_value_json`, `validation_result`, `rollback_plan`, `gui_explanation`, `approval_state`, `created_ts_ms`

### `config_versions`
- `config_version_id` (PK), `scope`, `version`, `diff_json`, `state`, `created_by`, `approved_by`, `created_ts_ms`, `applied_ts_ms`

### `monitor_snapshots`
- `monitor_snapshot_id` (PK), `source`, `snapshot_json`, `liveness_status`, `created_ts_ms`

### `evidence_packets`
- `evidence_packet_id` (PK), `packet_type` (`hourly|daily|alert|claude|codex|ollama`), `packet_json`, `related_snapshot_id`, `created_ts_ms`

### `redis_key_observations`
- `redis_observation_id` (PK), `key_name`, `namespace`, `key_type`, `size_estimate`, `ttl`, `observed_ts_ms`

### `heartbeat_events`
- `heartbeat_event_id` (PK), `component`, `component_instance`, `status`, `latency_ms`, `payload_json`, `created_ts_ms`

### `replay_runs`
- `replay_run_id` (PK), `scenario_name`, `config_version_id` (FK), `status`, `result_json`, `created_ts_ms`, `completed_ts_ms`

### `paper_trades`
- `paper_trade_id` (PK), `execution_intent_id` (FK NOT NULL, ON DELETE RESTRICT), `symbol`, `side`, `qty`, `price`, `pnl`, `created_ts_ms`

### `users`
- `user_id` (PK), `username`, `email`, `status`, `mfa_state`, `created_ts_ms`

### `roles`
- `role_id` (PK), `role_name`, `permissions_json`, `created_ts_ms`

### `approvals`
- `approval_id` (PK), `subject_type`, `subject_id`, `required_level`, `approver_user_id`, `decision`, `decision_reason`, `created_ts_ms`

## Lineage enforcement

### Required NOT NULL foreign keys (the chain)
The chain is closed by these six enforced links. Each link is `NOT NULL`, `ON DELETE RESTRICT`, `ON UPDATE RESTRICT`:

| Downstream table | FK column | Parent table.column |
|---|---|---|
| `feature_values` | `feature_snapshot_id` | `feature_snapshots.feature_snapshot_id` |
| `prediction_events` | `feature_snapshot_id` | `feature_snapshots.feature_snapshot_id` |
| `confidence_events` | `prediction_id` | `prediction_events.prediction_id` |
| `signal_events` | `prediction_id` | `prediction_events.prediction_id` |
| `orchestrator_decisions` | `signal_id` | `signal_events.signal_id` |
| `risk_decisions` | `decision_id` | `orchestrator_decisions.decision_id` |
| `execution_intents` | `risk_decision_id` | `risk_decisions.risk_decision_id` |
| `paper_trades` | `execution_intent_id` | `execution_intents.execution_intent_id` |

### Missing-attribution rejection
- Every chain FK is `NOT NULL`. INSERT of a child without its parent ID is rejected by the database with an integrity error.
- Every chain FK is a real foreign key with `RESTRICT` semantics. INSERT of a child whose parent does not exist is rejected.
- `risk_decisions` has a CHECK that aligns `allow_block` with `block_reason`. A `block` with no reason is rejected.
- `execution_intents` is gated so that an intent referencing a `risk_decisions` row whose `allow_block = 'block'` cannot exist. This is enforced via:
  - a trigger on `execution_intents` INSERT that resolves the parent `risk_decisions.allow_block` and rejects on `block`, or
  - a generated/materialized column on `risk_decisions` plus a CHECK joining the values.
- The application layer SHOULD pre-validate, but the database is the authoritative rejection boundary. Any orphan row is impossible by construction.

### Indexes for explainability and audit
The chain is heavily joined by Signal Explainability, Audit Ledger, and Replay. Required indexes:

- `idx_feature_snapshots_symbol_ts (symbol, created_ts_ms)`
- `idx_feature_snapshots_checkpoint (model_checkpoint)`
- `idx_feature_values_snapshot (feature_snapshot_id)`
- `idx_predictions_snapshot (feature_snapshot_id)`
- `idx_predictions_symbol_ts (symbol, created_ts_ms)`
- `idx_predictions_checkpoint (checkpoint)`
- `idx_confidence_prediction (prediction_id)`
- `idx_signals_prediction (prediction_id)`
- `idx_signals_symbol_ts (symbol, created_ts_ms)`
- `idx_signals_action_ts (action, created_ts_ms)`
- `idx_decisions_signal (signal_id)`
- `idx_decisions_action_ts (decision_action, created_ts_ms)`
- `idx_risk_decision (decision_id)`
- `idx_risk_allow_block_ts (allow_block, created_ts_ms)`
- `idx_intents_risk (risk_decision_id)`
- `idx_intents_trader_ts (trader_id, created_ts_ms)`
- `idx_intents_mode_status_ts (mode, status, created_ts_ms)`

These indexes guarantee that:
- a Signal Explainability page can resolve `signal_id -> prediction_id -> feature_snapshot_id` and its features in O(index lookup) per hop
- an Audit Ledger query can walk `execution_intent_id -> risk_decision_id -> decision_id -> signal_id -> prediction_id -> feature_snapshot_id` without table scans
- replay can re-derive a full chain by `(symbol, created_ts_ms)` range scans on each level

### Immutability and update policy
- All chain PKs (`feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`) are immutable surrogate keys.
- UPDATE on chain PKs is forbidden by `ON UPDATE RESTRICT`.
- Status fields (`execution_intents.status`, `executed_ts_ms`) are mutable; lineage columns are not.
- DELETE on parent rows in the chain is forbidden by `ON DELETE RESTRICT` to preserve audit history. Soft-archive is the only retirement path.

### Closure of lineage gap
All workflow tables preserve the canonical chain:
`feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id`

Each hop is enforced by a NOT NULL foreign key with RESTRICT semantics, every parent has a covering audit index, and every CHECK constraint that protects business invariants (action enum, confidence range, risk allow/block alignment, paper/live mode) is declared at the schema layer. Missing-attribution rows are rejected at INSERT. The database — not application code — is the lineage authority.
