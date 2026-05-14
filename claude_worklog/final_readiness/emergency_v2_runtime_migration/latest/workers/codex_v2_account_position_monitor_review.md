# Codex Review: V2 Account Position Monitor

result: `V2_ACCOUNT_POSITION_MONITOR_CODEX_PASS`
live_gate: `blocked_human_only`

## Review Scope

- `v2/backend/app/services/account_position_monitor/service.py`
- `v2/backend/app/cli/v2_account_position_monitor.py`
- `v2/backend/tests/integration/cli/test_v2_account_position_monitor.py`
- `v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_account_position_monitor_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_account_position_monitor_legacy_behavior_mapping.json`

## Remediated Prior Blockers

- `READONLY_ENDPOINT_CONFIG_CONTRACT_TEST_INCOMPLETE`: fixed. The tests now reject a fake client exposing an endpoint outside the read-only allowlist.
- `LEGACY_MARGIN_RATIO_BEHAVIOR_UNPORTED_UNTESTED`: fixed. The service derives `maintenance_margin_ratio_pct` from `totalMaintMargin / totalMarginBalance`, and the payload emits `account_margin_ratio_status`.
- `LEGACY_EQUIVALENT_TEST_COVERAGE_INCOMPLETE`: fixed. Tests now assert balance fields, available balance, total unrealized PnL, total maintenance margin, derived margin ratio, active-position filtering, entry price, mark price, liquidation price, notional, leverage, margin type, and PnL.

## Gate Results

- Standalone runnable CLI exists: `python3 -m v2.backend.app.cli.v2_account_position_monitor --once --readonly-only`.
- Tests exist and pass: `12 passed`.
- Read-only endpoint contract exists and is enforced before account reads.
- Allowed endpoint paths are limited to `/fapi/v3/account` and `/fapi/v2/positionRisk`.
- Missing credentials path emits `MISSING_CREDENTIALS`, writes a payload, and fails closed without fabricating account state.
- Paper runtime positions are explicitly ignored for real account evidence.
- `freshness_seconds` is present.
- Margin and leverage gaps emit `MISSING_EVIDENCE`.
- Public payload exists at `v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json`.
- Legacy baseline analysis and mapping exist and cite legacy account/position monitor behavior.
- Symbol Universe contract is present and distinguishes `legacy_active_symbols`, `discovered_symbols`, `observed_symbols`, `training_symbols`, `paper_symbols`, `live_symbols`, and `live_blocked_symbols`.
- The current 25-symbol legacy active subset is preserved as a subset, not the full universe.
- The worker does not train or trade all discovered symbols.
- CoinAnk-only symbols are not treated as directly tradable without Binance USD-M confirmation.

## Safety Checks

- Old Redis writes: none.
- Legacy mutation: none.
- Exchange actions: none.
- Leverage changes: none.
- Margin mode changes: none.
- Live gate remains `blocked_human_only`.
- Final live approval token: absent.
- Redis trim approval token: absent.
- Exact forbidden mutation-token scan over new files: clean.

## Validation

- `.venv/bin/python3 -m py_compile v2/backend/app/services/account_position_monitor/service.py v2/backend/app/cli/v2_account_position_monitor.py v2/backend/tests/integration/cli/test_v2_account_position_monitor.py`
- `.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_account_position_monitor.py -q`
- JSON validation for public/worklog payload and legacy mapping.
- Required public payload field validation.
- `git diff --check` over the account-position monitor file set.

## Residual Runtime Evidence Gap

Current runtime account evidence is still blocked by missing read-only credentials. That is correct and must not be converted into live readiness. Canary remains blocked by `MISSING_CREDENTIALS`, missing isolated-margin evidence, and missing leverage evidence.
