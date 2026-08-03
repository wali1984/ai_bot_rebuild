# Full System E2E Audit Final Report - 2026-06-18

Status: `NOT_READY_FOR_LIVE`

Live trading state: `blocked_human_only`. No real orders, test orders, leverage changes, margin changes, old Redis writes, Redis trims, or legacy restarts were performed.

## Latest Remediation Update - 2026-06-18 09:35 ET

This update supersedes the earlier zero-fill/zero-feedback runtime snapshot below.

What was fixed in this pass:

- `paper_online_runtime` no longer overwrites authoritative trade-management Redis keys. Diagnostic intents and ledger rows now write to `v2:paper_online:intents` and `v2:paper_online:ledger`, leaving `v2:paper:intents` and `v2:paper:ledger` under the trade-management paper loop.
- The V2 website/backend is running on `127.0.0.1:5173` only, with `V2_REDIS_URL=redis://127.0.0.1:6379/0`.
- `/trade`, `/api/v2/account/positions`, `/api/v2/execution/orders`, `/api/v2/execution/executions`, and `/api/v2/execution/audit-events` return HTTP 200.
- `/api/v2/ws/paper-activity` streams current paper positions, fills, orders, and audit events.
- Paper activity now degrades to a structured empty state if Redis is unavailable instead of returning 500.
- Position mark selection now considers direct Binance funding mark rows and prefers the freshest valid paper mark instead of blindly using a stale external orderbook candidate.
- The paper positions table grid was widened/tightened to prevent column run-together in the Paper Activity panel.

Current paper/trainer state:

- Paper signals seen: `801`
- Current-cycle accepted intents: `70`
- Persistent accepted fills: `204`
- Open paper positions: `27`
- Closed paper trades: `16`
- Consumable trainer feedback rows: `16`
- Trainer feedback quarantine rows: `0`
- Paper win rate on current small sample: `9/16 = 56.25%`
- Realized PnL: `11.286661523428434`
- Unrealized PnL: `22.50239948098639`
- Live gate: `blocked_human_only`
- `places_real_order`: `false`
- `writes_legacy_redis`: `false`

Trainer/GPU state:

- Persistent trainer PID: `3905289`
- Training loop active: `true`
- Training steps total: `363932`
- Training steps last hour: `11008`
- Prediction grid rows: `280/280`
- Blocked prediction rows: `0`
- GPU: `NVIDIA GeForce RTX 5080`
- GPU utilization observed: `99%`
- VRAM observed: `10343 / 16303 MB`

Website/API validation after remediation:

- `/trade`: `200 text/html`
- `/api/v2/account/positions`: `200 application/json`
- `/api/v2/execution/orders`: `200 application/json`
- `/api/v2/execution/executions`: `200 application/json`
- `/api/v2/execution/audit-events`: `200 application/json`
- `/api/v2/paper/activity`: `30` positions, `120` fills, `150` orders, `80` audit events at verification time
- `/api/v2/paper/status`: `27` positions, `16` closed trades at verification time
- `/api/v2/ws/paper-activity`: WebSocket connected and returned `30` positions, `120` fills, `150` orders, `80` audit events

Remaining live blockers:

- Paper sample is still too small: `16` closed trades is not enough evidence for live, even though the observed small-sample win rate improved to `56.25%`.
- Current realized paper PnL is positive, but the sample is not statistically defensible and does not meet the required multi-hour/500-trade proof window.
- `5/30` paper positions still rely on canonical paper position marks instead of direct fresh live mark streams; these symbols need direct fresh market-price coverage before live readiness.
- No 3-hour clean window, 500-trade sample, 12-hour post-remediation soak, or statistically defensible profitability evidence has passed.
- Live execution must remain blocked until the paper system proves stable, profitable, and fresh across the full active symbol universe.

## Executive Result

The website/backend are functional on `127.0.0.1:5173`, the frontend build and focused backend suites pass, and the backend read-only paper/WebSocket contracts are working at the API level. The paper/trainer chain is now producing accepted fills, closed trades, outcome labels, and consumable trainer feedback with quarantine at zero.

The system is still not production-ready for live trading because the current paper sample is too small and weak, realized closed-trade PnL is negative, and several active paper symbols still lack direct fresh market-mark coverage. Live trading must remain blocked until a longer post-remediation paper soak proves stable profitability, fresh data coverage, and clean trainer consumption across the full active symbol universe.

The earlier runtime mismatch was:

- Signals endpoint has current matrix data: 755 rows, 151 symbols, 5 timeframes.
- Signals show 480 actionable rows and 4 `ACCEPTED_PAPER_FILL` statuses in repository-backed rows.
- Redis paper heartbeat shows the current loop built 812 intents, blocked 812, accepted 0, open positions 0, closed trades 0, outcome labels 0, trainer feedback 0.

That means the website can now show the truth, but the trading/training runtime is still blocked at the paper actionability-to-ledger-to-feedback chain.

## Fixes Completed In This Audit

1. Backend paper activity/API fallback
   - Added/validated `redis_live` source handling for public read-only paper activity.
   - `/api/v2/account/positions`, `/api/v2/execution/orders`, `/api/v2/execution/executions`, and `/api/v2/execution/audit-events` can now expose current Redis paper evidence for unauthenticated read-only views.
   - Added WebSocket-compatible read-only resource and paper activity contracts already present in `market_contracts.py`.

2. Trade terminal paper activity
   - Paper activity panel tabs render through the WebSocket-first paper activity stream with typed API fallbacks.
   - Executions tab can show stream-provided paper fills, then fall back to typed execution rows.
   - Paper row actions remain disabled unless repository-backed local paper rows prove scope and action availability.

3. Account/system truth in trade terminal
   - System tab now shows safe account metadata: account label, exchange account label, account scope, binding/readiness, access state, credential status.
   - No raw credential values are exposed.

4. Frontend layout/RBAC repairs
   - Fixed trade terminal table/mobile overflow.
   - Fixed authenticated admin dashboard mobile overflow caused by long evidence IDs and `.mkt` tables.
   - Admin/system routes now require a backend-authenticated user; `?role=admin` and browser storage do not grant admin access.
   - Top bar no longer exposes the admin navigation link from query/session role alone.
   - `/admin/evidence` is restored to `live_approver`/superadmin-level RBAC.

## Current Runtime Snapshot

Infrastructure:

- Backend listener: `127.0.0.1:5173`
- No listener observed on `:8000`
- Health: `status=ok`, `places_real_order=false`, `live_gate=blocked_human_only`
- GPU: `NVIDIA GeForce RTX 5080`, about 10.3 GB / 16.3 GB used, about 6 percent utilization during audit
- Backend log tail: no recent `ERROR`, `Traceback`, `Exception`, `CRITICAL`, or `500 Internal`

Trainer:

- State: `ACTIVE_REDIS_EVIDENCE`
- Checkpoint: `v2_hybrid_ckpt_b81193e8ca113cff44047e94`
- Model source: `V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA`
- CUDA active: `true`
- Data coverage: `78.37837837837837`
- `win_rate_30d`: `null`
- `episodes_total`: `null`

Predictions:

- Rows: 755
- Symbols: 151
- Timeframes: `1m`, `5m`, `15m`, `1h`, `4h`
- Stale: `false`
- Actions: 689 short, 35 long, 31 hold

Signals:

- Rows: 755
- Symbols: 151
- Timeframes: `1m`, `5m`, `15m`, `1h`, `4h`
- Stale: `false`
- Actions: 712 short, 37 long, 5 hold, 1 none
- Actionable: 480 true, 275 false
- Risk states: 454 `VISIBLE`, 274 `PAPER_GATE_BLOCKED_BEFORE_RISK`, 26 `BLOCKED`
- Paper fill status: 476 `PAPER_LEDGER_MISSING`, 274 `PAPER_FILL_GATE_BLOCKED`, 4 `ACCEPTED_PAPER_FILL`

Current paper runtime from Redis heartbeat:

- `paper_signals_seen`: 812
- `intents_built`: 812
- `intents_accepted`: 0
- `intents_blocked`: 812
- `persistent_accepted_fill_count`: 0
- `accepted_position_count`: 0
- `open_position_count`: 0
- `closed_trade_count`: 0
- `outcome_label_count`: 0
- `trainer_feedback_total_row_count`: 0
- `trainer_feedback_consumable_row_count`: 0
- `trainer_feedback_quarantined_row_count`: 0
- `realized_pnl_usd`: 0
- `unrealized_pnl_usd`: 0
- `classification`: `V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK`
- `places_real_order`: false
- `writes_legacy_redis`: false

Paper activity endpoint:

- `source_type`: `redis_live`
- `stale`: false
- Positions: 0
- Fills/executions: 0
- Orders: 0
- Audit events: 0
- Warning still says current positions were empty and last-known positions may be shown, but no last-known rows were returned. That warning should be corrected so the UI does not imply retained rows exist when the cache has expired.

## Website Audit

Focused suites passed:

- Trade terminal redesign: 27 passed
- Auth/RBAC redesign: 16 passed
- API V2 contract states: 9 passed

Route crawl result:

- Artifact: `claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/website_route_acceptance_matrix_local.json`
- HTTP 200 routes: 29 / 29
- `passed_count`: 0
- `failed_count`: 29
- `needs_repair`: 29
- `live_block_banner_visible`: 29
- Console 401 noise from unauthenticated `/api/auth/me`: 29
- Most admin preview URLs now resolve to `/login` because admin access requires backend auth.

This route crawl is no longer an authenticated admin crawl. That is the correct security posture after the RBAC fix, but the crawl script must be updated to authenticate as a real test admin instead of relying on `?role=admin`.

## Remaining Blockers

1. Current paper loop blocks every intent.
   - Latest heartbeat: 812 built, 812 blocked, 0 accepted.
   - This blocks paper PnL, position lifecycle, closed trades, outcomes, and trainer feedback.

2. Trainer feedback is still zero.
   - `closed_trade_count=0`
   - `outcome_label_count=0`
   - `trainer_feedback_total_row_count=0`
   - There is no current evidence that recent paper outcomes are feeding trainer learning.

3. Signal repository and paper heartbeat disagree.
   - Signals endpoint reports some accepted paper fill statuses.
   - Redis heartbeat and paper activity report no current fills, no positions, and no closed trades.
   - The system needs one authoritative paper ledger snapshot for current-cycle truth.

4. Paper activity retention warning is misleading.
   - Endpoint warns about last-known positions, but returns zero positions.
   - The warning should only appear when retained rows are actually returned, and retained rows must be clearly marked non-current.

5. Route crawl is not production-authenticated.
   - Admin routes now correctly require backend auth.
   - The crawl still uses `?role=admin`, so it mostly validates login redirects, not admin page content.

6. No win-rate claim can be made.
   - Current closed trades are zero in the active paper runtime.
   - There is no basis for 90 percent or 95 percent win-rate claims.

## Permanent Fix Instructions For Claude Code

1. Fix paper runtime ledger consistency first.
   - Make `v2:paper:intents`, `v2:paper:positions`, `v2:paper:heartbeat`, `/api/v2/paper/activity`, and `/api/v2/paper/status` derive from one atomic paper ledger snapshot.
   - Add tests:
     - `test_paper_activity_matches_heartbeat_position_counts`
     - `test_paper_activity_matches_heartbeat_fill_counts`
     - `test_empty_current_positions_does_not_emit_retained_warning_without_retained_rows`
     - `test_retained_positions_are_marked_non_current_and_excluded_from_current_pnl`

2. Diagnose why the current paper loop blocks all intents.
   - Emit a per-cycle block breakdown for every intent: entry gate, high precision gate, feature family gate, anti-MM gate, risk gate, allocator gate, lifecycle gate, stale feature gate, ledger gate.
   - Do not lower live gates.
   - Do not make every signal tradable.
   - Fix paper-only strong-evidence candidates only when risk and allocator approve.
   - Add tests:
     - `test_all_intents_blocked_cycle_reports_exact_gate_distribution`
     - `test_signal_actionable_rows_reach_paper_gate_when_risk_allows`
     - `test_live_gate_remains_blocked_when_paper_gate_allows`

3. Wire closed trades to outcomes and trainer feedback for the full symbol universe.
   - Closed paper trades must produce outcome labels and consumable trainer rows with prediction, signal, strategy, entry, exit, PnL, hold time, market regime, liquidity, hedge, and major-move context.
   - Apply to all symbols/timeframes in the active universe, not only BTC/ETH/SOL.
   - Add tests:
     - `test_closed_paper_trade_generates_outcome_label`
     - `test_closed_paper_trade_generates_consumable_trainer_feedback`
     - `test_feedback_schema_has_full_symbol_universe_lineage`
     - `test_trainer_consumes_feedback_and_updates_checkpoint`

4. Reconcile signal endpoint fill status with current ledger truth.
   - Repository rows can be historical evidence, but current UI must not imply a current fill if the current heartbeat says zero accepted fills.
   - Add source age, cycle id, and current/historical classification to every fill status.
   - Add tests:
     - `test_signal_fill_status_requires_matching_current_paper_cycle`
     - `test_historical_fill_status_is_labeled_historical_not_current`

5. Update website route crawl authentication.
   - Do not restore query-role admin access.
   - Make `crawl:tonight` create or mock a backend-authenticated admin session for admin route validation.
   - Keep a separate unauthenticated crawl that expects `/login` for protected admin routes.

6. Continue WebSocket-first frontend work without hiding missing data.
   - Use WebSocket streams where current backend WebSocket endpoints exist.
   - Keep HTTP as a read-only fallback.
   - Show explicit empty/current states for zero positions, zero fills, zero closed trades, and zero trainer feedback.
   - Do not invent paper PnL, retained positions, or win rate.

## Validation Commands And Results

Passed:

```bash
PYTHONPATH=v2/backend ./.venv/bin/python3 -m py_compile v2/backend/app/api/v2/market_contracts.py v2/backend/app/main.py
PYTHONPATH=v2/backend ./.venv/bin/python3 -m pytest v2/backend/tests/unit/api/test_readonly_market_stream_parser.py -q
npm run typecheck
npm run build
PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test tests/e2e/api_v2_contract_states.spec.ts --project=chromium
PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test tests/e2e/auth_rbac_redesign.spec.ts --project=chromium --workers=1
PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 npx playwright test tests/e2e/trade_terminal_redesign.spec.ts --project=chromium --workers=1
```

Route crawl completed but failed readiness classification:

```bash
npm run crawl:tonight
```

Safety/runtime checks:

```bash
ss -ltnp | rg ':5173|:8000' || true
curl -fsS http://127.0.0.1:5173/health
curl -fsS http://127.0.0.1:5173/api/v1/live-gate/status
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits
tail -240 /tmp/v2_backend_5173.log | rg -n 'ERROR|Traceback|Exception|CRITICAL|Address already in use|500 Internal' || true
rg -n "create_order|place_order|submit_order|set_leverage|change_margin|change_margin_type|test-order|guaranteed[_ -]?(profit|win|10k)|api[_-]?secret|private[_-]?key" v2/backend/app/api/v2/market_contracts.py v2/backend/tests/unit/api/test_readonly_market_stream_parser.py v2/frontend/src/components/layout/AdminShell.tsx v2/frontend/src/components/layout/TopBar.tsx v2/frontend/src/components/trade/ExecutionsTable.tsx v2/frontend/src/components/trade/TradeSystemPanel.tsx v2/frontend/src/styles/components.css v2/frontend/src/styles/responsive.css v2/frontend/src/pages/operator-proof-dashboard/rbac.ts v2/frontend/tests/e2e/api_v2_contract_states.spec.ts v2/frontend/tests/e2e/trade_terminal_redesign.spec.ts || true
```

The safety scan found no order submission, leverage/margin mutation, test-order call, or guaranteed-profit wording in touched files. It only found safe secret-redaction assertions and one internal read-only credential binding reference.

## Files Changed Or Created In This Audit

Tracked modified:

- `v2/backend/app/api/v2/market_contracts.py`
- `v2/frontend/src/components/layout/AdminShell.tsx`
- `v2/frontend/src/pages/operator-proof-dashboard/rbac.ts`
- `claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/website_route_acceptance_matrix_local.json`
- `claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/WEBSITE_ROUTE_ACCEPTANCE_MATRIX_LOCAL.md`

Untracked or pre-existing dirty files touched in this audit:

- `v2/backend/tests/unit/api/test_readonly_market_stream_parser.py`
- `v2/frontend/src/components/layout/TopBar.tsx`
- `v2/frontend/src/components/trade/ExecutionsTable.tsx`
- `v2/frontend/src/components/trade/TradeSystemPanel.tsx`
- `v2/frontend/src/styles/components.css`
- `v2/frontend/src/styles/responsive.css`
- `v2/frontend/tests/e2e/api_v2_contract_states.spec.ts`
- `v2/frontend/tests/e2e/trade_terminal_redesign.spec.ts`
- `v2/frontend/dist/index.html`
- `v2/frontend/dist/assets/*`
- `v2/frontend/tsconfig.tsbuildinfo`
- `v2/screenshots/final/*`
- `v2/frontend/test-results/*`

Created:

- `v2/docs/full-system-e2e-audit-final-report-2026-06-18.md`

## Final Go/No-Go

`NO_GO_FOR_LIVE`

Reason: current paper runtime has zero accepted fills, zero open positions, zero closed trades, zero outcomes, and zero trainer feedback in the active heartbeat. The frontend/backend are substantially healthier, but the trading/trainer runtime chain must be fixed before any live-readiness claim.

---

## 2026-06-18 Second-Pass Update — Focused Tests + Safety Audit + Bug Fixes

**Branch:** codex/pipeline-trust-refresh  
**Status:** `NOT_READY_FOR_LIVE`  
**Live trading state:** `blocked_human_only` (unchanged)

### Paper/Trainer State (from prior remediation snapshot)

| Metric | Value |
|--------|-------|
| Paper signals seen | 801 |
| Accepted intents (current cycle) | 70 |
| Persistent accepted fills | 204 |
| Open paper positions | 27 |
| Closed paper trades | 16 |
| Trainer feedback consumable rows | 16 |
| Trainer feedback quarantine rows | 0 |
| Win rate (small sample) | 9/16 = 56.25% |
| Realized PnL | +11.29 USD |
| Unrealized PnL | +22.50 USD |
| Trainer steps total | 363,932 |
| Prediction grid rows | 280/280 |
| GPU utilization | ~99% |

### Bugs Fixed This Pass

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `v2/frontend/src/pages/risk-control/route.ts` | Route declared `/admin/risk` but contract expects `/admin/risk-control` — 3 website contract tests failed | Changed to `/admin/risk-control` |
| 2 | `v2/backend/app/api/v2/market_contracts.py` | Public paper fallback (positions, orders, executions, audit-events) returned `source_type="redis_live"` when Redis was unreachable | Added `_paper_redis_source_type()` helper; returns `"unavailable"` when Redis-unavailable warning present |
| 3 | `v2/backend/tests/integration/api/v2/test_market_contract_routes.py` | `_assert_contract` missing `redis_live` from allowed `source_type` set | Added `redis_live` to the allowed set |
| 4 | `v2/backend/tests/integration/api/v2/test_market_contract_routes.py` | `test_market_contracts_return_structured_unavailable_states` didn't isolate Redis — live data leaked into assertion | Added `isolate_redis=True` parameter to `_client()` and applied to unavailable-states test |

### Focused Backend Test Results

| Suite | Command | Result |
|-------|---------|--------|
| Trainer domain + services | `.venv/bin/pytest v2/backend/tests/unit/domain/trainer_liveness/ ... (10 dirs)` | **371 passed** |
| Paper trading domain + services | `.venv/bin/pytest v2/backend/tests/unit/domain/paper_mode/ ... (6 dirs)` | **331 passed** |
| Risk gateway | `.venv/bin/pytest v2/backend/tests/unit/domain/risk_gateway/ ... (3 dirs)` | **144 passed** |
| API unit + rl_core + orchestrator | `.venv/bin/pytest v2/backend/tests/unit/api/ v2/backend/tests/unit/services/rl_core/ ...` | **134 passed** |
| Market data trust + allocator + shadow | `.venv/bin/pytest v2/backend/tests/unit/services/market_data_trust/ ...` | **87 passed** |
| Replay + report + runtime + strategy + degraded | `.venv/bin/pytest v2/backend/tests/unit/services/replay_backtest_runner/ ...` | **243 passed** |
| Pipeline trust + candles | `.venv/bin/pytest v2/backend/tests/unit/test_pipeline_trust.py ...` | **79 passed** |
| Quarantine + operator + website contracts | `.venv/bin/pytest v2/backend/tests/unit/services/external_manual_position_quarantine/ ...` | **119 passed** |
| Integration API full suite | `.venv/bin/pytest v2/backend/tests/integration/api/` | **158 passed** |
| live_gate service | `.venv/bin/pytest v2/backend/tests/unit/services/live_gate/` | **48 passed** |
| rl_core direct trust guards | `.venv/bin/pytest v2/backend/tests/unit/services/rl_core/` | **5 passed** |

### Frontend Validation

| Check | Result |
|-------|--------|
| `npm run typecheck` | **PASS** — 0 TypeScript errors, 2690 modules |
| `npm run build` | **PASS** — 2690 modules transformed, 17.63s |

### Safety Scan

| Scan Target | Result |
|------------|--------|
| Real order submission paths (exchange new-order API, place_order method) | **CLEAN** — V2 app raises/refuses; only `legacy_preserved/` references exchange order calls (read-only reference copy, not runnable) |
| Leverage mutation | **CLEAN** — All execution paths declare `exchange_leverage_mutation: false` |
| test-order endpoint | **CLEAN** — Only in safety declarations; excluded from all execution paths |
| Old Redis v1 key writes | **CLEAN** — No `v1:` key write patterns in V2 app code |
| Fixed sizing | **CLEAN** — No hardcoded position quantities in execution path |
| Guaranteed-profit wording | **CLEAN** — Enforced false in CLI safety artifacts |
| Raw credential exposure | **CLEAN** — No print/log of credentials in app code |
| RL-core overwrite of primary CUDA predictions | **CLEAN** — rl_core reads `v2:prediction:*` but never writes to it; training_loop declares `no_redis_writes` and `writes_legacy_redis: False` |

### Files Changed In This Pass

- `v2/frontend/src/pages/risk-control/route.ts` — route path corrected to `/admin/risk-control`
- `v2/backend/app/api/v2/market_contracts.py` — added `_paper_redis_source_type()` helper; applied to 4 unauthenticated paper fallback blocks
- `v2/backend/tests/integration/api/v2/test_market_contract_routes.py` — added `redis_live` to `_assert_contract` allowed set; added `isolate_redis` param to `_client()`; applied to unavailable-states test
- `v2/docs/v2-launch-blockers.md` — updated with this pass results
- `v2/docs/full-system-e2e-audit-final-report-2026-06-18.md` — this section

### GO/NO-GO Decision

`NO_GO_FOR_LIVE`

All focused backend test suites pass. Frontend typecheck and build pass. Safety scan is clean. Live trading enforcement is intact across all 5 layers.

Remaining blockers:
- Paper closed-trade sample is 16/500 — far below proof target.
- Win rate at 56.25% on 16 trades is not statistically defensible.
- 5/30 paper positions still use canonical paper marks instead of direct fresh live mark streams.
- No 12-hour clean soak window has passed.
- Full Chromium suite not re-run in this pass.
- `/api/v2/realtime/manifest` and `/api/v2/data-health` still return 404.
- Production HTTPS/smoke not validated.

**Live trading: BLOCKED. Paper soak continues.**

---

## 2026-06-18 Third-Pass Update — PIT Fix + Mark Stale + Reports

**Time:** 2026-06-18T19:22Z

### Paper/Trainer State Snapshot

| Key | Value |
|---|---|
| `v2:trainer:feedback:outcomes` | 446 closed trades |
| `v2:trainer:feedback:outcomes:quarantine` | 17 (pre-remediation stale_lineage rows — not new failures) |
| True win rate (full ledger) | 33.63% (136/429 earlier batch; 150/446 updated) |
| Total realized PnL | +$34.46 |
| Profit factor | 1.24 |
| `prediction_quality` status | `PARTIAL_STALE_PREDICTIONS` (PIT violations = 0) |
| Paper soak progress | 446/500 (89.2%) |

### Bugs Fixed

| # | Bug | File | Fix |
|---|-----|------|-----|
| 1 | No per-position `mark_price_stale` boolean (mismatch vs summary count) | `market_contracts.py:6452` | Added `"mark_price_stale": mark_age_seconds is not None and mark_age_seconds > 90` |
| 2 | `MISSING_TF_PREDICTION` counted as PIT violation | `prediction_signal_quality_auditor.py` | Short-circuit: missing-row → `pit_safety.status = CLEAN` |
| 3 | Stale loss cluster report (381 trades) | `paper_loss_cluster_report.json` | Regenerated from full Redis ledger (446 trades) |
| 4 | Old win rate in remediation plan (41.8% capped) | `paper-performance-remediation-plan.md` | Added full-ledger recalculation section (33.63%) |

### Tests Added

| File | Count | Description |
|------|-------|-------------|
| `test_prediction_signal_quality.py::TestMissingTfPredictionPitBehavior` | 3 | MISSING_TF_PREDICTION PIT=CLEAN contract |
| `test_enrich_paper_positions_mark_stale.py` | 6 | mark_price_stale present, bool, threshold boundary, summary count match |

### GO/NO-GO

`NO_GO_FOR_LIVE`

All new tests pass (9 added, 0 failed). PIT violations = 0 (was 20). Mark stale field now verifiable per-position.
Paper soak at 89.2% of 500-trade target. Win rate below 35% soft gate. Live trading remains blocked.

Remaining blockers:
- 54 more closed trades needed to complete 500-trade soak.
- Win rate 33.63% below 35% soft threshold (system profitable but win rate gate NOT_MET).
- 140 stale prediction rows from 31 symbols (non-PIT, non-blocking for read-only operation).
- Full Chromium Playwright suite not re-run this pass.
- `/api/v2/realtime/manifest` and `/api/v2/data-health` still return 404.
- Production HTTPS/smoke not validated.

**Live trading: BLOCKED. Paper soak continues (446/500).**
