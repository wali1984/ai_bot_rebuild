# 03 Database Schema

## Schema objective
Provide a normalized system-of-record supporting full lineage, governance, approvals, replay/paper, monitoring, and audit.

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
- `feature_snapshot_id` (PK), `symbol`, `timeframe`, `source_refs_json`, `freshness_json`, `model_checkpoint`, `created_ts_ms`

### `feature_values`
- `feature_value_id` (PK), `feature_snapshot_id` (FK), `feature_name`, `feature_value`, `source_key`, `freshness_age_ms`, `stale_flag`, `missing_flag`, `unused_flag`

### `prediction_events`
- `prediction_id` (PK), `feature_snapshot_id` (FK), `symbol`, `timeframe`, `model_version`, `checkpoint`, `raw_output_json`, `created_ts_ms`

### `confidence_events`
- `confidence_event_id` (PK), `prediction_id` (FK), `confidence_before`, `confidence_after`, `top_positive_json`, `top_negative_json`, `created_ts_ms`

### `signal_events`
- `signal_id` (PK), `prediction_id` (FK), `symbol`, `action`, `confidence`, `reason_json`, `created_ts_ms`

### `orchestrator_decisions`
- `decision_id` (PK), `signal_id` (FK), `decision_action`, `decision_reason`, `policy_trace_json`, `created_ts_ms`

### `risk_decisions`
- `risk_decision_id` (PK), `decision_id` (FK), `allow_block`, `block_reason`, `policy_checks_json`, `created_ts_ms`

### `execution_intents`
- `execution_intent_id` (PK), `risk_decision_id` (FK), `trader_id`, `intent_action`, `mode` (`paper|live`), `status`, `created_ts_ms`, `executed_ts_ms`

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
- `paper_trade_id` (PK), `execution_intent_id` (FK), `symbol`, `side`, `qty`, `price`, `pnl`, `created_ts_ms`

### `users`
- `user_id` (PK), `username`, `email`, `status`, `mfa_state`, `created_ts_ms`

### `roles`
- `role_id` (PK), `role_name`, `permissions_json`, `created_ts_ms`

### `approvals`
- `approval_id` (PK), `subject_type`, `subject_id`, `required_level`, `approver_user_id`, `decision`, `decision_reason`, `created_ts_ms`

## Lineage enforcement
All workflow tables must preserve:
`feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id`
