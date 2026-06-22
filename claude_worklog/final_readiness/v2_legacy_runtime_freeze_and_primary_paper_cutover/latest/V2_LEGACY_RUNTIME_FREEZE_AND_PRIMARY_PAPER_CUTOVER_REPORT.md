# V2 Legacy Runtime Freeze + Primary Paper Cutover

Executed: 2026-05-25T21:25:00Z (initial SIGTERMs) — 2026-05-26T01:52:29Z (Codex follow-up verification)
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_legacy_runtime_freeze_and_primary_paper_cutover`
GO/NO-GO: `V2_LEGACY_RUNTIME_FREEZE_AND_PRIMARY_PAPER_CUTOVER_READY`

This packet executed the controlled legacy runtime freeze. Legacy runtime
processes that consume APIs / memory / GPU / trade loops have been stopped.
All legacy data, Redis, logs, and reference artifacts are preserved. V2 is
now the only active paper/shadow runtime. **Live trading remains blocked.**

## Plain English

- **LEGACY_RUNTIME_ACTIVE = false**
- **LEGACY_DATA_PRESERVED = true**
- **V2_PRIMARY_PAPER_RUNTIME_ACTIVE = true**
- **LIVE_TRADING_ENABLED = false**
- **REAL_ORDERS_ENABLED = false**
- **LEGACY_REDIS_TRIMMED = false**
- **LEGACY_SHUTDOWN_MODE = RUNTIME_FROZEN_DATA_PRESERVED**

`live_gate=blocked_human_only`. `live_symbols=[]`.

### Why live remains blocked

Paper-edge is not proven (after-cost expectancy -8.98 bps). Risk caps,
capital recovery, checkpoint promotion, and read-only permission probe
approval all remain operator-required gates. The freeze did NOT progress
any of these gates.

### Next automatic V2 fix

Closed-loop Spark continues replay-miner cycles, report-center indexer,
comparator refresh, dry-run canary service, and full-observation internal
burndown. Codex review found the residual trainer tree still active and sent a
follow-up SIGTERM; the trainer root and 126 children exited without SIGKILL.

### Next operator-only decision

(a) sign paper-edge thresholds; (b) sign 14 risk/capital cap fields; (c)
decide checkpoint promotion path; (d) sign read-only permission probe
approval.

## Phase 1 — Pre-Freeze Snapshot

12 top-level legacy processes identified (9 API-consuming ingestors:
binance, binance_liquidations, coinank, kucoin, technical_analysis,
realtime_price_provider, coinapi_v1, coinapi_wsds; plus
opportunity_tracker, feature_pipeline, oom_monitor, hybrid_trainer).
127 multiprocessing children parented by hybrid_trainer. All started
manually from VSCode terminals (no systemd, no cron, no supervisor).

V2 processes inventoried and protected: paper trade management loop, 6
closed-loop workers (claude/codex), worker porting orchestrator daemon,
codex non-live watchdog, plus 22 V2 systemd user timers.

Pre-freeze: memory 49.4 GB used, GPU0 2260 MiB, load avg 8.91, Redis
12658 keys (264 v2:*).

## Phase 2 — Preservation Status

No file deletion. No log truncation. No Redis trim. No Redis flush. No
legacy Redis key removal. No legacy filesystem modification. The legacy
bot root remains read-only reference under `/home/wali/Desktop/AI BOT`
(this lane did not touch it).

## Phase 3 — Stop Status

SIGTERM sent to all 12 top-level legacy PIDs (trader first, ingestors
next, trainer last) at ~21:25Z. After 30 seconds:

- 11 of 12 exited gracefully during the initial freeze window
- Codex review found the residual hybrid_trainer tree still active with
  external sockets and completed the freeze with a follow-up SIGTERM
- 12 of 12 top-level legacy processes are now stopped
- 0 residual hybrid_trainer multiprocessing children remain

Importantly, **zero API-consuming legacy processes remain**, and no legacy
trader/orchestrator/trainer process remains active.

## Phase 4 — Auto-Restart Disable

Audit found zero legacy auto-restart mechanisms: zero legacy systemd user
units, zero cron entries, zero non-V2 tmux sessions, zero supervisor
scripts. Legacy processes were manually started from VSCode terminals.
Nothing to disable. Operator should not re-run the original VSCode
terminal commands until the freeze is explicitly lifted.

## Phase 5 — V2 Primary Paper Runtime Cutover

10 V2 systemd timers verified active. 16 V2 runtime services confirmed:
market data ingestors (V2 native path), feature snapshot builder,
technical analysis pipeline, symbol universe publisher, trainer
prediction publisher (V2 native baseline evaluator), risk decision loop,
orchestrator arbitration loop, paper trade management loop (PID 31327),
paper ledger writer, position history tracker, replay outcome miner,
report center indexer, Spark worker pool (6 workers), event watchers,
production-equivalence comparator, executive command center.

V2 namespace 258 keys; payloads refreshed within last 2 minutes. No real
order attempted, no real order submitted, `places_real_order=false`,
`writes_exchange_orders=false`, `live_enabled=false`.

## Phase 6 — Redis / Write-Boundary Proof

- Total Redis keys: 12658 -> 11795 (-863, **all from natural TTL expiry**)
- V2 namespace: 264 -> 258 (-6, V2 housekeeping)
- Legacy Redis writers remaining: 0
- V2 writes only to `v2:*` prefix
- Old Redis writes after freeze observed: 0
- Redis DEL/TRIM/FLUSH executed by this lane: 0 each
- Legacy Redis keys preserved as static reference

## Phase 7 — API/Rate-Limit Relief

- Legacy API-consuming processes: 8 -> 0
- Duplicate websocket families removed: 5 (binance, binance_liquidations,
  coinank, kucoin, coinapi_wsds)
- Duplicate REST polling reduced: 3 families
- Memory used: 49400 MiB -> 36341 MiB (-13059 MiB after residual trainer exit)
- GPU0 memory: 2260 MiB -> 836 MiB (-1424 MiB after residual trainer exit)
- Load avg: 2.15 / 3.15 / 5.00 after follow-up verification

## Phase 8 — Report Center / Executive Dashboard

`operator_dashboard_payload.json` consolidates all 7 phase summaries with
plain-English explanation. All 7 boolean executive fields surfaced
(LEGACY_RUNTIME_ACTIVE, LEGACY_DATA_PRESERVED, V2_PRIMARY_PAPER_RUNTIME_ACTIVE,
LIVE_TRADING_ENABLED, REAL_ORDERS_ENABLED, LEGACY_REDIS_TRIMMED,
LEGACY_SHUTDOWN_MODE).

## Phase 9 — Validation

- Process checks: passed (verified 12/12 top-level legacy processes exited;
  residual trainer tree absent after Codex follow-up SIGTERM)
- Systemd timer checks: all 22 V2 timers active
- Redis key checks: 11795 total, 258 v2:* — both within healthy bands
- V2 runtime: all 9 V2 protected processes intact
- No old-Redis writes detected
- No exchange mutation calls
- No approval tokens created
- No raw secret material in any payload

## Required Outputs

- [GO_NO_GO.md](GO_NO_GO.md)
- [legacy_runtime_freeze_precheck.json](legacy_runtime_freeze_precheck.json)
- [legacy_reference_preservation_status.json](legacy_reference_preservation_status.json)
- [legacy_runtime_freeze_stop_status.json](legacy_runtime_freeze_stop_status.json)
- [legacy_autorestart_disable_status.json](legacy_autorestart_disable_status.json)
- [v2_primary_paper_runtime_cutover_status.json](v2_primary_paper_runtime_cutover_status.json)
- [post_cutover_redis_write_boundary_status.json](post_cutover_redis_write_boundary_status.json)
- [api_rate_limit_relief_status.json](api_rate_limit_relief_status.json)
- [operator_dashboard_payload.json](operator_dashboard_payload.json)

## Operator Notes

- The residual trainer tree was stopped during Codex review with SIGTERM only;
  no SIGKILL was needed.
- TokenMetrics remains deferred. No TokenMetrics autoseed occurred during this freeze.
