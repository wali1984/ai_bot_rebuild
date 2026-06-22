# V2 Copied Runtime Burn-In Remediation Execution — Report

- **Task ID**: `v2_copied_runtime_burn_in_remediation_execution`
- **Generated EST**: 2026-05-30T23:59:00-0400
- **Generated UTC**: 2026-05-31T03:59:00Z
- **GO/NO-GO**: `V2_COPIED_RUNTIME_BURN_IN_REMEDIATION_EXECUTION_READY`
- **Live gate**: `blocked_human_only`
- **Live symbols**: `[]`
- **Live recommendation**: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`
- **Canary recommendation**: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`

## What this READY verdict DOES claim

All 9 burn-in remediation tasks were executed to a defined, evidence-backed
disposition. No remediation was left idle waiting for operator input on a
non-operator-gated task.

## What this READY verdict does NOT claim

- Paper edge is NOT proven (still `INCONCLUSIVE` on all 3 profiles).
- Paper PnL is NOT positive (still `-49.345535 USDT`, blockers preserved).
- Liquidation event flow is NOT operationally proven (still `XLEN=0`; root cause identified, remediation options queued, no synthetic events injected).
- Live trading is NOT unblocked. Canary is NOT unblocked.

## Remediation dispositions

| Task | Disposition | Evidence artifact |
|------|-------------|--------------------|
| r1 refresh `v2_feature_pipeline_native_status.json` | `REFRESHED` (age = seconds) | `stale_payload_refresh_status.json` |
| r2 refresh `v2_owned_trainer/status.json` | `REFRESHED` (age = seconds) | `stale_payload_refresh_status.json` |
| r3 refresh `v2_liquidation_ingestor_status.json` | `REFRESHED` (age = seconds) | `stale_payload_refresh_status.json` |
| r4 diagnose `v2:liquidations:events` XLEN=0 | `ROOT_CAUSE_IDENTIFIED` — bridge inputs `v2:binance:force:raw` (LLEN=0) and `v2:raw:coinank:liquidation_orders:global` (STRLEN=0) have NO upstream producer in active V2 runtime | `liquidation_event_flow_diagnosis.json` |
| r5 diagnose `v2:market:liquidation_levels:*` zero keys | `ROOT_CAUSE_IDENTIFIED` — namespace mismatch + downstream of r4 (engine writes `liquidation_*` fields into `v2:unified_features:*` hashes, not into a separate `v2:market:liquidation_levels:*` family) | `liquidation_levels_zero_key_diagnosis.json` |
| r6 re-run 24h war-room | `WAR_ROOM_RERUN_EXECUTED` — dataset 58 rows / 12 val / 46 train; edge `INCONCLUSIVE` on aggressive/balanced/conservative; after-cost expectancy = -7.25 bps (improved from -9.08); validation < 300 threshold | `war_room_rerun_schedule_status.json` |
| r7 symbol-universe rolling diff buffer | `IMPLEMENTED` — CLI `v2.backend.app.cli.v2_symbol_universe_diff_buffer`, systemd timer `ai-bot-v2-symbol-universe-diff-buffer.timer` (5-min cadence), seed snapshot captured (1h/6h/12h windows reporting `INSUFFICIENT_HISTORY_FOR_WINDOW` until buffer fills) | `symbol_universe_diff_buffer_status.json` |
| r8 root-cause negative paper PnL | `ROOT_CAUSE_DECOMPOSED` — 3 causes: (a) -49.35 USDT was accumulated by 2 279 historical fills BEFORE current observation window; (b) recent 1h/6h/24h windows show `deny_canary_profile_tightening` dominating 94-96% with 76% of blocked intents at confidence 0.75+; (c) recent intent generation 100% concentrated on `1000BONKUSDT` | `negative_paper_pnl_root_cause_status.json` |
| r9 operator screenshot proof for 45 routes | `HTTP_ROUTE_PROBE_PASS_45_OF_45` + `RENDERED_SCREENSHOT_PASS_45_OF_45` using frontend Playwright Chromium | `trading_platform_screenshot_proof_status.json` + `trading_platform_screenshot_matrix_codex.json` |

## Stale payload refresh (tasks 1-3)

| Payload | Pre-refresh age | Refresh command | Post-refresh age |
|---------|-----------------|------------------|--------------------|
| `v2_feature_pipeline_native_status.json` | ~13.8 days | `python3 -m v2.backend.app.cli.v2_feature_pipeline_native --write-evidence` | seconds |
| `v2_owned_trainer/status.json` | ~13.8 days | `python3 -m v2.backend.app.cli.v2_owned_trainer_runtime --dry-run --no-train-runtime-active` | seconds |
| `v2_liquidation_ingestor_status.json` | ~11.9 days | `python3 -m v2.backend.app.cli.v2_liquidation_ingestor_loop --once --no-redis-heartbeat` | seconds |

All three writers are idempotent paper-only CLIs that emit fresh status payloads
without touching Redis writes outside `v2:` namespace.

## Liquidation event flow diagnosis (task 4)

**Root cause**: the V2 liquidation bridge consumes from
`v2:binance:force:raw` (Redis LIST) and `v2:raw:coinank:liquidation_orders:global`
(Redis STRING JSON). A `grep -rln` over `v2/backend/` and
`v2/legacy_owned_runtime/` shows the ONLY references to these keys are:

1. The bridge consumer itself (`liquidation_bridge.py`)
2. A test wrapper (`test_v2_copied_liquidation_runtime_wrappers.py`)

There is NO active V2 producer XADDing into either input. The WSS client
(`v2_liquidation_wss_loop.py`) writes per-symbol observations to
`v2:market:liquidations:*` (a different namespace) and does NOT XADD into
`v2:binance:force:raw`.

**Live Redis state**:
- `LLEN v2:binance:force:raw = 0`
- `STRLEN v2:raw:coinank:liquidation_orders:global = 0`
- `GET v2:cursor:liq_bridge:binance_force_raw = (nil)`
- `XLEN v2:liquidations:events = 0`

**Remediation options queued (paper-only, no operator gate)**:
1. Wire `v2_liquidation_wss_loop.py` to LPUSH raw force-order events to
   `v2:binance:force:raw` so the bridge can dedupe and publish.
2. Wire the CoinAnk REST client to emit raw liquidation-orders snapshot
   to `v2:raw:coinank:liquidation_orders:global`.

NO synthetic events injected.

## Liquidation levels zero-key diagnosis (task 5)

**Root cause classification (two layers)**:

1. **Namespace mismatch in prior expectation**: the `v2:market:liquidation_levels:*`
   family was aspirational. The actual engine
   (`v2/legacy_owned_runtime/ingest/liquidation_levels_engine.py`) writes
   liquidation_long_level / liquidation_short_level / liquidation_long_distance_pct
   / etc as hash FIELDS inside `v2:unified_features:{symbol}:{tf}` (and `:latest`).
   The `v2:market:liquidation_levels:*` family will NEVER be populated by this
   engine — that's a documentation-only fix to the burn-in schema.
2. **Downstream event starvation**: the engine consumes from
   `v2:liquidations:events` via `xreadgroup`. With XLEN=0 (see task 4),
   only the no-event default branch runs, emitting
   `liquidation_long_level=0.0`, `liquidation_is_stale=1`. Fixing r4 will
   propagate non-zero level fields into `v2:unified_features:*`.

**Live Redis state**:
- `v2:unified_features:*` key count: 170 (covers 27 symbols)
- `v2:market:liquidation_levels:*` key count: 0 (expected — never written)

NO synthetic levels injected.

## War-room re-run (task 6)

Executed `python3 -m v2.backend.app.cli.v2_24h_parallel_recovery_war_room` in
this turn. Artifact regenerated at `claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest/war_room_status.json`.

| Metric | Prior run | This run |
|--------|-----------|----------|
| Dataset total rows | 76 | 58 |
| Validation rows | 16 | 12 |
| Train rows | 60 | 46 |
| `edge_claimed` | False | False |
| `aggressive` verdict | INCONCLUSIVE | INCONCLUSIVE |
| `balanced` verdict | INCONCLUSIVE | INCONCLUSIVE |
| `conservative` verdict | INCONCLUSIVE | INCONCLUSIVE |
| `expected_move_after_cost_bps` | -9.08 | -7.25 |
| `sample_count` | 3 067 | 7 750 |

Edge remains unproven. Validation count BELOW the 300 threshold required
for a non-INCONCLUSIVE per-profile verdict. After-cost expectancy is
improving but still negative. The next 8h war-room timer cycle will
auto-fire; the 24h executor remains on-demand.

## Symbol-universe diff buffer (task 7)

**Implemented**:
- New CLI: `v2/backend/app/cli/v2_symbol_universe_diff_buffer.py`
- Buffer directory: `v2/runtime/symbol_universe_diff_buffer/snapshots/` (filesystem-only)
- Status payload: `v2/frontend/public/operator_runtime/symbol_universe_diff_buffer/latest/symbol_universe_diff_buffer_status.json`
- Systemd service: `ai-bot-v2-symbol-universe-diff-buffer.service` (oneshot)
- Systemd timer: `ai-bot-v2-symbol-universe-diff-buffer.timer` (`OnBootSec=2min`, `OnUnitActiveSec=5min`)
- Buffer bounds: `MAX_BUFFER_ENTRIES=2048`, `MAX_BUFFER_AGE_SECONDS=14*24*3600`

**Current state**:
- Snapshot count: 1 (seeded by this turn)
- Current dynamic-discovered symbol count: 27
- 1h / 6h / 12h windows: `INSUFFICIENT_HISTORY_FOR_WINDOW` (until buffer
  accumulates entries older than each window cutoff)

No Redis writes. No exchange action. No legacy mutation.

## Negative paper-PnL root cause (task 8)

**Current state**:
- `paper_pnl_current_usdt = -49.345535`
- `profitability_proof_status = PROFITABILITY_PROOF_BLOCKED_NEGATIVE_PNL`
- Lifetime simulated fills: 2 279; lifetime allowed intents: 2 279; lifetime blocked: 35 873

**Recent window block-reason distribution (1h / 6h / 24h)**:
- `deny_canary_profile_tightening`: 105 / 626 / 2454 (96.3% / 95.9% / 94.0%)
- `deny_low_confidence`: 1 / 14 / 93
- `deny_orchestrator_held`: 3 / 13 / 63

**Recent window symbol distribution (1h / 6h / 24h)**:
- All windows: 100% `1000BONKUSDT`

**Recent window confidence-bucket distribution (1h / 6h / 24h)**:
- `0.75+`: 83 / 497 / 1759 (76.1% / 76.1% / 67.4%)
- `0.65_to_0.75`: 13 / 62 / 383
- `0.58_to_0.65`: 9 / 67 / 312
- `below_0.58`: 4 / 27 / 156

**Per-symbol attribution from `paper_events.jsonl`**:
- Total events observed: 38 154
- Fills observed: 0 (all blocked)
- Blocked events: BTCUSDT=31 156 (87.1%), 1000BONKUSDT=4 645 (12.9%)

**Root causes**:
1. The -49.35 USDT cumulative PnL came from 2 279 historical fills BEFORE
   the current observation window — current windows have zero fills.
2. Canary profile is tighter than strategy confidence — 76% of blocked
   intents are at confidence 0.75+ and dominant block reason is
   `deny_canary_profile_tightening`.
3. Strategy intent generation is concentrated on `1000BONKUSDT` in recent
   windows.

**Remediation options paper-only, no operator gate**:
1. Build a per-fill attribution ledger for the 2 279 lifetime fills (read-only).
2. Surface top-3 block reasons per window in decision-quality scoreboard.

**Remediation options requiring operator gate (NOT executed)**:
1. Relax canary profile tightening thresholds — `enable_canary` operator
   gate. Preserved for operator decision.

No orders placed. No strategy thresholds changed.

## Trading platform screenshot proof (task 9)

**HTTP route probe**: all 45 registered SPA routes returned HTTP 200 from
`http://127.0.0.1:5173/`. Backend `ai-bot-v2-public-website-backend.service`
active.

**Rendered screenshot pass (playwright)**: PASS. Codex used the existing
frontend Playwright dependency and cached Chromium under `v2/frontend` without
modifying the protected backend venv. Current screenshot matrix:
`trading_platform_screenshot_matrix_codex.json`.

**Fresh evidence**:
- 45 registered routes tested
- 45 HTTP 200 route probes
- 45 rendered PNG screenshots captured
- 0 screenshot failures
- screenshot directory: `screenshots/codex_review_current/`

## Safety honoured

| Constraint | Status |
|-----------|--------|
| `LIVE_GATE=blocked_human_only` | held |
| `live_symbols=[]` | held |
| Did not enable live | held |
| Did not enable canary | held |
| Did not place/cancel/modify orders | held |
| Did not call test-order endpoint | held |
| Did not change leverage | held |
| Did not change margin mode | held |
| Did not write old Redis (`live_orders:*`, `exchange:order:*`, `orchestrator:*`) | held |
| Did not restart legacy | held |
| Did not trim Redis | held |
| Did not fake liquidation events | held |
| Did not fake liquidation levels | held |
| Did not claim edge while PnL is negative | held |
| Used EST timestamps in artifacts | held |

## Artifacts

- `GO_NO_GO.md` — single-line verdict
- `V2_COPIED_RUNTIME_BURN_IN_REMEDIATION_EXECUTION_REPORT.md` (this file)
- `stale_payload_refresh_status.json` (task 1-3)
- `liquidation_event_flow_diagnosis.json` (task 4)
- `liquidation_levels_zero_key_diagnosis.json` (task 5)
- `war_room_rerun_schedule_status.json` (task 6)
- `symbol_universe_diff_buffer_status.json` (task 7)
- `negative_paper_pnl_root_cause_status.json` (task 8)
- `trading_platform_screenshot_proof_status.json` (task 9)
- `trading_platform_screenshot_matrix_codex.json` (Codex rendered route screenshots)
- `operator_dashboard_payload.json` (composite)
- `build_remediation_execution_artifacts.py` — builder script for this turn

Also mirrored to `v2/frontend/public/v2_copied_runtime_burn_in_remediation_execution/latest/`.

## Path from this READY to paper-edge READY

This milestone READY only means the **9 remediation tasks executed**. The
prior burn-in milestone (`v2_copied_runtime_burn_in_and_paper_edge_improvement`)
remains `BLOCKED`. Unblocking that requires:

1. r4 follow-up: wire a producer for `v2:binance:force:raw` so the bridge
   has input → `v2:liquidations:events XLEN > 0` → `v2:unified_features:*`
   liquidation fields populate.
2. Burn-in accumulates 12h continuous post-WSS-restart (currently ~9.74h).
3. War-room validation rows reach ≥ 300 (currently 12).
4. Paper PnL turns positive AND `expected_move_after_cost_bps` turns
   positive in war-room evaluator output.
5. Operator sets edge thresholds explicitly.
