# Operator Alert Runbook (Phase 14)

Last verified: 2026-07-07 03:55 EDT.

Primary monitor:
`python -m v2.backend.app.cli.v2_runtime_drift_monitor --write-status --write-redis`

Current outputs:
- Redis: `v2:monitor:runtime_drift`
- Website artifact: `v2/frontend/public/operator_runtime/v2_runtime_drift/latest/status.json`
- Codex Phase K artifacts: `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_K_RUNTIME_ALERT_MATRIX.json`

## RUNTIME_CODE_DRIFT / F-0008

Check:
`redis-cli GET v2:monitor:runtime_drift | python3 -m json.tool | grep -E "service_running_commit|repo_head_commit|service_restart_required|schema_version_mismatch|last_restart_utc"`

Fires when running V2 services predate the newest backend commit. Required evidence fields are `service_running_commit`, `repo_head_commit`, `service_restart_required`, `schema_version_mismatch`, and `last_restart_utc`.

Action: restart listed V2 services at a safe moment. Restart producers before consumers after schema changes. Never restart legacy services or `paper_online_runtime`.

## Feature Schema Drift

Check:
`redis-cli GET v2:monitor:runtime_drift | python3 -m json.tool | grep -E "feature schema changed|schema_version_mismatch|stale_service_count"`

Fires with runtime drift when imported producer/consumer schemas may differ.

Action: keep trading gated, restart affected V2 services, then rerun the monitor.

## Paper Performance Halt

Checks:
- `redis-cli GET v2:paper:performance_governor_status | python3 -m json.tool`
- `redis-cli GET v2:paper:new_entry_emergency_halt_status | python3 -m json.tool`

Alerts:
- `PF < 1 after 5 trades`
- `expectancy <= 0 after 5 trades`
- `new entries allowed while halted`

`HALTED_PERFORMANCE` with `new_entries_allowed=false` is correct fail-closed behavior. Do not force entries or lower thresholds. Investigate exit reasons, bucket quarantines, fees, slippage, and MFE/MAE. Entries resume only from evidence.

## Trainer Learning

Checks:
- `redis-cli GET v2:trainer:hybrid_cuda:status | python3 -m json.tool`
- `redis-cli GET v2:trainer:hybrid_cuda:metrics | python3 -m json.tool`

Alerts:
- `trainer feedback rows = 0 while closed trades > 0`
- `weights not updating`
- `outcome memory stale after restart`

Action: repair trainer feedback/outcome memory before trusting learning state. Check trusted replay scan rejection reasons and cursor state.

## Prediction And Market Feeds

Checks:
- `redis-cli --scan --pattern "v2:prediction:*" | wc -l`
- `redis-cli GET v2:market:coinapi:ohlcv:heartbeat | python3 -m json.tool`
- `cat v2/frontend/public/operator_runtime/v2_microstructure_trust/latest/ios_trust_semantics_truth_status.json | python3 -m json.tool`

Alerts:
- `prediction grid stale`
- `market data stale`
- `orderbook/trust feed stale`

Action: repair/restart the current V2 publisher or ingestor that owns the stale feed. Do not rely on public orderbook alone for final A+ readiness.

## Forbidden Runtime Writers

Checks:
- `systemctl --user is-active ai-bot-v2-paper-online-runtime.service`
- `redis-cli GET v2:live_canary:status | python3 -m json.tool`
- `redis-cli GET v2:live_order_transport:status | python3 -m json.tool`

Alerts:
- `paper_online_runtime active`
- `live gate changed`
- `exchange mutation detected`

Action: freeze live path. If exchange mutation evidence is true, trigger kill-switch incident response and inspect exchange audit trail. Do not submit, cancel, modify, transfer, or mutate exchange settings from this runbook.

## Website And iOS Truth

Checks:
- `cat goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_I_FRONTEND_ROUTE_TRUTH_STATUS.json | python3 -m json.tool`
- `cat goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_J_IOS_RUNTIME_TRUTH_STATUS.json | python3 -m json.tool`

Alerts:
- `website stale-current mismatch`
- `iOS stale-current mismatch`

Action: patch stale-current UI/API contract mismatch before claiming operator readiness.

## Paid Ingestor / Santiment

Check:
`redis-cli --scan --pattern "v2:altdata:santiment:symbol:*" | wc -l`

Alert: `paid ingestor unused`

Action: repair the Santiment ingestor or remove the paid-provider expectation from symbol selection. Santiment must contribute symbol-selection evidence when paid alternative data is expected.
