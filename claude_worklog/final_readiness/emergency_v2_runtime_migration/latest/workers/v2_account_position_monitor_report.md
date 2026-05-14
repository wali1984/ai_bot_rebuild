# V2 Account Position Monitor Report

result: `V2_ACCOUNT_POSITION_MONITOR_IMPLEMENTED_FAIL_CLOSED`
live_gate: `blocked_human_only`

Implemented files:

- `v2/backend/app/services/account_position_monitor/service.py`
- `v2/backend/app/cli/v2_account_position_monitor.py`
- `v2/backend/tests/integration/cli/test_v2_account_position_monitor.py`
- `v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_account_position_monitor_status.json`

Evidence:

- Standalone CLI: `python3 -m v2.backend.app.cli.v2_account_position_monitor --once --readonly-only`
- Missing credentials path emits `MISSING_CREDENTIALS` and does not fabricate account state.
- Only read-only Binance USD-M endpoint paths are allowed: `/fapi/v3/account` and `/fapi/v2/positionRisk`.
- Client contract rejects mutating exchange attributes before reads.
- Paper runtime positions are explicitly ignored for real account evidence.
- Margin and leverage gaps are labeled `MISSING_EVIDENCE`.
- Maintenance-margin ratio is derived from account `totalMaintMargin / totalMarginBalance`.
- Active position evidence preserves entry price, mark price, liquidation price, notional, leverage, margin type, and PnL; zero-size positions are filtered out.
- Symbol Universe contract is emitted with separate legacy, discovered, observed, training, paper, and live-blocked scopes.

Current status:

- `runtime_evidence_status`: `MISSING_CREDENTIALS`
- `canary_ready`: `false`
- `live_symbols`: `[]`
- `exchange_action_taken`: `false`
- `exchange_mutation_performed`: `false`
- `legacy_mutation`: `none`
- `old_redis_writes`: `none`

Tests:

- `.venv/bin/python3 -m py_compile v2/backend/app/services/account_position_monitor/service.py v2/backend/app/cli/v2_account_position_monitor.py v2/backend/tests/integration/cli/test_v2_account_position_monitor.py`
- `.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_account_position_monitor.py -q` -> 12 passed
