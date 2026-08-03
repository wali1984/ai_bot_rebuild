# Codex 5.5 Review - V2 Full Dynamic Rebuild Blocker Execution

**Result: `V2_FULL_DYNAMIC_REBUILD_BLOCKER_EXECUTION_CODEX_FAIL`**

Claude claimed `V2_FULL_DYNAMIC_REBUILD_BLOCKER_EXECUTION_READY`. Codex cannot
clear this as ready because the current blocker execution and current public
runtime payloads still show BTC/ETH/SOL or BTC-only defaults in core
market/feature/liquidation lanes. That violates the operating line: dynamic
universe with the 25 legacy symbols as the minimum migration baseline, and no
3-symbol default outside explicit smoke tests.

## Findings

1. **FAIL - 3-symbol/default-symbol mode is still active in evidence.**
   - `v2/backend/app/cli/v2_binance_public_metadata_ingestor.py:45` defines
     `DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")`.
   - `v2/backend/app/cli/v2_binance_public_metadata_ingestor.py:241` uses that
     value as the CLI default.
   - `v2/backend/app/cli/v2_liquidation_observation_aggregator_status.py:32`
     defaults to `BTCUSDT,ETHUSDT,SOLUSDT`, and line 39 falls back to the same.
   - `v2/backend/app/cli/v2_coinank_and_liquidation_bridge.py:103` starts its
     default list with BTC/ETH/SOL, and the current public payload reports only
     `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`.
   - `v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py:545` defaults to
     `BTCUSDT`; the current public payload reports `symbols=["BTCUSDT"]`.
   - `cmd_logs/binance_public_metadata.log` shows the actual blocker run used
     `["BTCUSDT", "ETHUSDT", "SOLUSDT"]`.

2. **PARTIAL - 13 components were exercised, but not proven as persistent
   dynamic V2 runtime.**
   - `v2_missing_component_start_execution_status.json` records 13/13 as
     `started_via_one_shot=true`.
   - The main report explicitly says persistent systemd wiring is future work.
   - Some logs are empty (`coinank_and_liquidation_bridge.log`,
     `feature_pipeline_and_ta_worker.log`, `risk_gateway_runtime_worker.log`),
     so those entries are not strong runtime evidence.

3. **PARTIAL - old-Redis observer is useful but not complete proof.**
   - `v2_old_redis_write_observer_status.json` reports 0 proven old writers and
     `orchestrator:*`, `live_orders:*`, `exchange:order:*` all at 0.
   - It is a static-source scan, and several active services report no CLI
     module hint in `ExecStart`. That cannot fully prove current writer state.
   - Separate Redis count comparison did not show added old writes.

## Verification Matrix

| # | Check | Codex result |
| --- | --- | --- |
| 1 | Not-running components started or blocked | PARTIAL - one-shot only; 7 credential-blocked and 4 raw-old-Redis blocked |
| 2 | Backtest first run happened | PASS WITH CAVEAT - 12 fixture artifacts, not edge proof |
| 3 | Dynamic symbol discovery active | PASS - fresh symbol-universe payload with 27 discovered symbols |
| 4 | 25 baseline symbols enforced | PASS - `baseline_missing=[]` |
| 5 | 3-symbol mode not default | FAIL |
| 6 | Feature/TA parity improved or exact blockers exist | PASS WITH BLOCKERS - 14 full, 11 partial with blockers |
| 7 | Old-Redis observer proves writer state | PARTIAL |
| 8 | No old Redis writes added | PASS - old counts match prior Codex baseline |
| 9 | No exchange mutation | PASS |
| 10 | No live/canary/shutdown approval | PASS |
| 11 | `live_gate=blocked_human_only` | PASS |
| 12 | `live_symbols=[]` | PASS |

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `orchestrator:*`: `0`
- `live_orders:*`: `0`
- `exchange:order:*`: `0`
- `order:*`: `0`
- `*leverage*`: `0`
- `*margin*`: `0`
- No Redis trim/delete observed.
- No legacy restart performed by Codex.
- No trade, canary, live, or shutdown approval granted by Codex.

## Required Remediation

1. Replace static BTC/ETH/SOL or BTC-only defaults with the dynamic symbol
   universe source and the 25-symbol legacy baseline minimum.
2. Re-run blocker execution for market metadata, liquidation/CoinAnk, and
   feature/TA against the baseline/dynamic universe.
3. Add a guard test that fails any active runtime lane using a 3-symbol default
   unless it has an explicit smoke-test-only flag.
4. Upgrade the old-Redis observer so every active V2 unit maps to source or an
   explicit blocked reason before it claims writer-state proof.

Until then: **`V2_FULL_DYNAMIC_REBUILD_BLOCKER_EXECUTION_CODEX_FAIL`**.
