# Codex 5.5 Review - V2 Full Dynamic Rebuild

GO/NO-GO: `V2_FULL_DYNAMIC_REBUILD_IMPLEMENTATION_CODEX_FAIL`

Generated UTC: `2026-05-26T04:50:22Z`
Generated local: `2026-05-26 00:50:22 EDT`

## Decision

Codex 5.5 FAILS the `V2_FULL_DYNAMIC_REBUILD_IMPLEMENTATION_READY`
claim. The packet is useful as a status/backlog bundle, but it is not a
completed full dynamic rebuild.

Live remains blocked:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- no live/canary approval
- no real orders
- no leverage/margin mutation
- no Redis trim or legacy deletion
- no legacy restart

## Safe Fixes Applied

1. Downgraded the packet GO/NO-GO from
   `V2_FULL_DYNAMIC_REBUILD_IMPLEMENTATION_READY` to
   `V2_FULL_DYNAMIC_REBUILD_IMPLEMENTATION_BLOCKED`.
2. Fixed the copied-component adapter status so copied files with detected
   old Redis writes are `safe_to_start_copy_as_is=false`; only their V2
   wrappers can be considered startable.
3. Re-ran the packet generator after the safe fix. Current status now reports
   `implementation_ready=false`, `running_component_count=26`,
   `not_started_count=19`, and `backtest_has_run=false`.
4. Registered `v2_full_dynamic_rebuild_implementation` in Report Center as a
   blocking live/shutdown/production-equivalence lane.

## Findings

| Severity | Finding | Classification | Mapping |
| --- | --- | --- | --- |
| FAIL | The original packet counted a partial runtime as `IMPLEMENTATION_READY`: 26/45 components running, 19 not started. | Safe scoped fix applied | GO/NO-GO downgraded to BLOCKED. Missing components remain mapped in backlog/operator gates. |
| FAIL | Backtesting was not executed. `v2_strategy_performance_matrix.json` says `scaffold_pending_first_engine_run`. | Automation remediation | Run the backtest engine in paper/replay mode only; do not count scaffold as implementation. |
| FAIL | Copied legacy files with old Redis writes were marked `safe_to_start_copy_as_is=true` when a V2 wrapper existed. | Safe scoped fix applied | Raw copy safety now false; wrappers explicitly separate. |
| FAIL | Broader old Redis namespaces are present: `prediction:* = 1`, `signals:trading:* = 2`, `price:* = 31`, `ohlcv:list:* = 25`, `ta:* = 150`, `features:coinank:* = 1564`, `kc:* = 150`. | Operator/preservation required | Do not delete. Add write observer evidence proving V2 is not writing old keys before any shutdown/trim decision. |
| FAIL | Dynamic symbol discovery is not proven: `discovered_symbol_count=0`, and all 25 canonical symbols are listed as missing from discovery. | Automation remediation | Wire fresh symbol-universe discovery; 25 legacy symbols remain minimum baseline; 3-symbol smoke mode cannot be default. |
| FAIL | Feature/TA coverage is partial: 14 full-coverage symbols and 11 partial symbols. | Automation remediation | Finish feature/TA parity and keep missing fields explicit. |
| FAIL | Risk remains fail-closed with missing runtime evidence/operator caps. | Operator required | Operator must set numeric caps; risk gateway must continue fail-closed until then. |
| FAIL | The live/canary ladder is blocked. | Operator required after evidence | Requires paper edge, risk caps, canary proof, and explicit operator approvals. |

## Checklist

| Rule | Result |
| --- | --- |
| All ingestors run or exact blocker | FAIL: 19 components not running; most have blockers/backlog, but implementation is not complete. |
| Copied components used before empty scaffolds | PARTIAL: copied sources are inventoried; raw copy safety bug fixed. |
| Dynamic symbols enforced | FAIL: 25-symbol baseline exists, but discovery count is 0. |
| 3-symbol default rejected | PASS as policy; runtime still has 3-symbol lanes, so must remain smoke-only. |
| V2 writes only `v2:*` | FAIL until old-key write observer proves no current old writes; old keys are present. |
| No old Redis writes | FAIL: old key presence exists; current writers not proven absent. |
| Credentials not exposed | PASS: only presence-by-name observed. |
| Trainer mode honest | PASS: current mode is baseline/bridge, not live-ready. |
| Copied trainer not called V2-native | PASS: copied legacy trainer is not certified V2-native. |
| Feature/TA coverage honest | PASS: partial coverage is reported; not full parity. |
| Strategy/backtests valid | FAIL: first backtest run is pending. |
| Risk gates fail closed | PASS. |
| Orchestrator cannot bypass risk | PASS by contract; keep runtime proof required. |
| Trader cannot place real orders without approval | PASS: gate/freeze remains blocked. |
| Website controls safe | PARTIAL: control contract exists; full control center behavior not proven. |
| Report Center clear | PASS after this lane was registered as blocking. |
| No fake edge | PASS: no paper edge claim. |
| No fake readiness | FIXED: readiness claim downgraded to BLOCKED. |

## Runtime Evidence

- Legacy bot processes: `0`
- V2 services: `29` active, `0` failed, `1` activating oneshot worker-pool maintainer
- V2 Redis keys: `257`
- Old order namespaces: `orchestrator:* = 0`, `live_orders:* = 0`, `exchange:order:* = 0`
- Current public payload: `V2_FULL_DYNAMIC_REBUILD_IMPLEMENTATION_BLOCKED`

## Required Next Work

1. Start or explicitly operator-block the 19 not-running components without using raw old-Redis-writing legacy files.
2. Run replay/backtest engine and publish real metrics; do not count scaffolds as implementation.
3. Add an old-Redis write observer proving no active V2 process writes old namespaces.
4. Restore dynamic symbol discovery and keep 25 legacy symbols as the minimum migration baseline.
5. Complete feature/TA parity for all 25 baseline symbols.
6. Keep live/canary disabled until paper edge, risk caps, canary proof, and operator gates pass.

Final Codex status: `V2_FULL_DYNAMIC_REBUILD_IMPLEMENTATION_CODEX_FAIL`.
