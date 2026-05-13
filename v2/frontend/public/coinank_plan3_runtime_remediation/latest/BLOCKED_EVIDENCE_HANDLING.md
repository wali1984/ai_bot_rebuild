# Blocked Evidence Handling

Policy selected: commit BLOCKED evidence.

Reason: the previous V2 CoinAnk Plan-3 bridge package is durable evidence, explicitly marked `LEGACY_COINANK_PLAN3_PATCH_DELTA_SYNC_AND_V2_MARKET_INTELLIGENCE_BRIDGE_BLOCKED` and `LEGACY_COINANK_PLAN3_PATCH_DELTA_SYNC_CODEX_FAIL`. It should remain available to the dashboard and migration backlog while the authorized CoinAnk runtime remediation proceeds.

Scope staged for blocked evidence only:
- `claude_worklog/final_readiness/legacy_coinank_plan3_bridge/latest/`
- `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/`
- `v2/frontend/public/legacy_coinank_plan3_bridge/latest/`
- CoinAnk-related script migration backlog updates
- CoinAnk bridge UI support panels
- `claude_worklog/tools/build_legacy_coinank_plan3_bridge.py`

Explicitly not included:
- unrelated autonomous governor/status dirty files
- unrelated operator truth recovery payload churn
- any legacy live bot files

Live gate remains `blocked_human_only`.
