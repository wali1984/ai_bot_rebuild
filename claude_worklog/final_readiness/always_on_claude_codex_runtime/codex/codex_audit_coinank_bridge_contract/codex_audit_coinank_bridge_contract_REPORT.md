# Codex Audit: CoinAnk Bridge Contract

Audit id: `codex_audit_coinank_bridge_contract`  
Working root: `/home/wali/Desktop/AI BOT REBUILD`  
Audit timestamp: `2026-06-27T22:03:07-04:00` (`2026-06-28T02:03:07Z`)  
Mode: non-live, read-only evidence collection except this report directory

## Decision

`FAIL_FOR_CURRENT_RUNTIME_TRUTH`

The code-level V2 CoinAnk bridge contract still passes: baseline SHA checks pass, contract tests pass, live gate remains `blocked_human_only`, and the reviewed bridge service has no Redis client or exchange-mutation calls.

Current runtime truth does not match that bridge contract. The active runtime is `DIRECT_LEGACY_OWNED_COINANK_INGESTORS_NO_V2_BRIDGE_WRAPPER`, the standalone `v2_coinank_and_liquidation_bridge` status is stale, and active `v2/legacy_owned_runtime` CoinAnk processes are writing legacy CoinAnk Redis namespaces. This is primary-objective drift from a V2 bridge/no-old-Redis-write posture.

This audit does not approve live trading, order placement, cancellation, leverage changes, margin changes, Redis trims/deletes, or old bot mutation.

## Current Runtime Truth

- Supervisor task state: `codex_audit_coinank_bridge_contract` is `running` with start `2026-06-28T02:01:03.909878+00:00`.
- Active CoinAnk-related processes found:
  - `.venv/bin/python3 -m v2.backend.app.cli.v2_coinank_direct_runtime_status_publisher --loop --interval-seconds 60`
  - `.venv/bin/python3 v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py`
  - `.venv/bin/python3 v2/legacy_owned_runtime/ingest/live_coinank.py`
- No active standalone `v2_coinank_and_liquidation_bridge` runtime process was found outside this audit.
- Stale standalone bridge status:
  - `v2/runtime/v2_coinank_and_liquidation_bridge/latest/v2_coinank_and_liquidation_bridge_status.json`
  - mtime `2026-06-09 18:32:01 -0400`
  - `last_run_ts=2026-06-09T22:32:01Z`
  - `live_gate=blocked_human_only`, `live_symbols=[]`
  - `liquidations_persisted_total=0`
  - missing blockers include `v2_liquidation_event_source_empty` and `binance_force_order_ws_owner_unbound`
- Fresh operator-facing CoinAnk status is produced by the direct publisher:
  - `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`
  - mtime `2026-06-27 22:02:21 -0400`
  - `classification=DIRECT_COINANK_RUNTIME_OK_WITH_HISTORICAL_ERRORS`
  - `runtime_mode=DIRECT_LEGACY_OWNED_COINANK_INGESTORS_NO_V2_BRIDGE_WRAPPER`
  - `ingestor_bridge_active=false`
  - `legacy_key_contract_is_current_source=true`
  - `direct_legacy_key_write_enabled=true`
  - `v2_redis_global_write_enabled=false`
  - missing blockers: `COINANK_DIRECT_API_HISTORICAL_ENDPOINT_ERRORS`, `COINANK_DIRECT_HISTORICAL_NON_200_SEE_CALL_LOG`

## Contract Evidence

- `python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --verify-baseline-shas` returned `ok: true` with no mismatches.
- `./.venv/bin/python -m pytest v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py` passed: `11 passed in 0.09s`.
- Reviewed V2 bridge files keep `LIVE_GATE_STATUS = "blocked_human_only"` and emit `live_symbols: []`.
- Targeted grep of the V2 bridge CLI/service did not find Redis mutation calls or exchange mutation calls.
- The bridge service writes only `v2:coinank:*` and `v2:liquidations:*` data-plane keys.

## Safety Findings

- Exchange safety: PASS for reviewed CoinAnk bridge/direct-status paths. No order, cancel, leverage, or margin mutation call was found.
- Live trading gate: PASS. The bridge status and reviewed code remain `blocked_human_only`.
- Old bot boundary: PASS for this audit. No command accessed or modified `/home/wali/Desktop/AI BOT`.
- Redis side-effect boundary for this audit: PASS. This audit did not write Redis.
- Current runtime Redis posture: FAIL relative to a no-old-Redis-writes bridge objective. Active `v2/legacy_owned_runtime/ingest/live_coinank.py` and `live_coinank_global_aggregator.py` write legacy CoinAnk Redis namespaces.

## Primary Objective Drift

The historical V2 bridge contract is preserved in code and tests, but current operational truth has drifted to direct legacy-owned ingestors plus a status publisher. The operator-facing current payload explicitly says the V2 bridge wrapper is inactive.

This is not an immediate order-safety failure because live trading remains blocked and no exchange mutation path was found. It is a data-plane and readiness-governance failure.

## Remediation Task Recommendations

1. Create `remediate_coinank_runtime_single_source_bridge_activation`.
2. Create `prove_or_remove_coinank_legacy_redis_writers`.
3. Create `refresh_v2_coinank_bridge_runtime_status`.
4. Create `close_coinank_direct_api_endpoint_blockers`.
5. Create `bind_or_explicitly_defer_binance_force_order_ws_owner`.
6. Create `coinank_symbol_universe_runtime_contract_proof`.

## Files Changed

- Created `claude_worklog/final_readiness/always_on_claude_codex_runtime/codex/codex_audit_coinank_bridge_contract/codex_audit_coinank_bridge_contract_REPORT.md`
- Created `claude_worklog/final_readiness/always_on_claude_codex_runtime/codex/codex_audit_coinank_bridge_contract/codex_audit_coinank_bridge_contract_GO_NO_GO.md`

## Commands Run

```text
pwd
git status --short
rg --files | rg -i 'coinank|bridge|always_on|runtime|redis|order|execution|leverage|margin|live|config'
python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --verify-baseline-shas
ps -eo pid,ppid,etimes,cmd | rg -i 'v2_coinank_and_liquidation_bridge|coinank_market_intelligence|live_coinank|liquidation_bridge|forceOrder|coinank' | rg -v 'rg -i'
./.venv/bin/python -m pytest v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py
mkdir -p claude_worklog/final_readiness/always_on_claude_codex_runtime/codex/codex_audit_coinank_bridge_contract
git status --short
```

## Non-Live Boundary Confirmation

- Did not access `/home/wali/Desktop/AI BOT`.
- Did not write old Redis.
- Did not place or cancel orders.
- Did not change leverage or margin.
- Did not enable live trading.
- Did not modify strategy, PPO, MASA, risk, or execution logic.
