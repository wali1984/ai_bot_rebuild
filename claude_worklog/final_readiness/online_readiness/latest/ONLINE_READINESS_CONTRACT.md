# V2 Online Readiness Contract

- rollup_version: `v1`
- generated_at: `2026-05-11T07:15:00+00:00`
- live_gate_status: `blocked_human_only`
- aggregate marker: `CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_READY`
- all_required_matched: `True`

## Required Lanes

- `final_non_live_rebuild` (READY): `claude_worklog/final_readiness/04_GO_NO_GO.md`
- `automation_liveness` (READY): `claude_worklog/final_readiness/automation_liveness/latest/GO_NO_GO.md`
- `trainer_lineage_and_readiness` (READY): `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md`
- `readonly_market_exchange_data_plane` (READY): `claude_worklog/final_readiness/readonly_market_exchange_data_plane/latest/GO_NO_GO.md`
- `decision_explainability_lineage` (READY): `claude_worklog/final_readiness/decision_explainability_lineage/latest/069D2_GO_NO_GO.md`

## Forbidden Operations

This aggregator never performs any of the following:

- `place_exchange_order`
- `cancel_exchange_order`
- `modify_exchange_order`
- `change_leverage`
- `change_margin_mode`
- `change_position_mode`
- `activate_live_keys`
- `enable_live_trading`
- `restart_live_trader`
- `restart_live_trainer`
- `restart_orchestrator`
- `restart_redis`
- `write_redis_key`
- `delete_redis_key`
- `trim_redis_key`
- `mutate_legacy_bot`

## Safety

This module (`v2/backend/app/proof/online_readiness_aggregator.py`) is a pure
file-system reader of marker files under
`claude_worklog/final_readiness/**/latest/`. It opens no source-state file in
a write/append/truncate mode, invokes no subprocess, imports no Redis or
exchange client, and never mutates the legacy bot.

The only files this module ever writes are the three rollup artifacts below,
and only inside the caller-supplied `output_dir`:

- `ONLINE_READINESS_ROLLUP.json`
- `ONLINE_READINESS_CONTRACT.md`
- `GO_NO_GO.md`

Live trading remains BLOCKED and human-only regardless of the aggregate
marker. Promotion to live requires an explicit
`FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED` step outside this module.
