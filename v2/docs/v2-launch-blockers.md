# V2 Launch Blockers

Date: 2026-06-15 (Updated June 15, 2026 — website-redesign-June15 session)
Launch status: BLOCKED
Real live trading status: BLOCKED (5 enforcement layers intact)

---

## Blockers Fixed This Session

| # | Blocker | Fix |
|---|---------|-----|
| 1 | 9 pytest collection errors: RISK_DECISION_REASON_DENY_HALT_MANAGER_ACTIVE + 8 others missing from domain | Added 9 risk reason constants to record.py + __init__.py; test collection now 0 errors |
| 2 | evaluate_risk_evaluator_context missing from service.py | Implemented with risk_context dict support |
| 3 | local_paper_audit_policy_metadata, verify_local_paper_audit_chain, chain_local_paper_audit_event missing from audit_chain.py | All implemented |
| 4 | __init__.py missing from 15 service test subdirs (basename collision) | Added __init__.py to all |
| 5 | RISK_DECISION_REASON_DENY_DEFAULT forbidden in service.py | Moved to service_block_reason_code() in evaluators.py |
| 6 | Phase B data contract layer absent | Created ValidatedDataEnvelope, hooks, FreshnessBadge, SourceBadge, DataQualityBadge, EvidenceDrawer, RealtimeStatusBar |
| 7 | theme-light.css missing | Created with full institutional light token set |
| 8 | responsive.css missing | Created with mobile-first breakpoints and patterns |

## Current Build Gates

| Gate | Status |
|------|--------|
| npm run typecheck | PASS — 0 TypeScript errors, 2590 modules |
| npm run build | PASS — 860ms |
| pytest collection | PASS — 4,066 tests, 0 collection errors (was 9) |
| pytest unit | PARTIAL — 2262 passed, 50 failed (pre-existing), backend-dependent tests need service |
| Backend FastAPI | UP locally — `127.0.0.1:8000` responding after restart |
| Full Playwright | PENDING CURRENT RERUN — backend no longer blocks API-dependent tests |

## Remaining Critical Blockers for Phase 14

| Blocker | Action |
|---------|--------|
| Full Chromium current rerun missing | Run `npx playwright test --project=chromium` after frontend route/data cleanup |
| Realtime manifest/data-health endpoints missing | `/api/v2/realtime/manifest` and `/api/v2/data-health` currently return 404 |
| Launch smoke missing | HTTPS/deployed-origin, no-console-error, asset-404, and production env checks remain pending |

## Blockers for Phase 15 (Paper/Read-Only Launch)

1. Backend must be running and stable
2. Full Playwright Chromium suite must be green
3. Phase B data contract must be consumed by all public/trader pages
4. All public/trader pages must show real data or be explicitly gated
5. Admin pages must be backend-protected
6. HTTPS must be configured
7. Production monitoring must be wired
8. Status page must be public-safe

## Live Trading Gate (Permanent)

Real live trading remains **CONFIRMED BLOCKED** by 5 enforcement layers.
Do not enable without explicit separate authorization through live_gate process.

## Blocking gates

1. Full route inventory exists, but all public/trader pages remain BLOCKED or IN_PROGRESS until source wiring/gating and full tests pass.
2. Full data surface inventory exists at Phase A level, but per-metric source/freshness/quality metadata is not universal.
3. Backend pytest full suite is no longer blocked by collection errors; current full backend result is `4111 passed, 4 skipped, 1 warning`.
4. Full Chromium suite remains pending current rerun; historical failures cannot be used as current acceptance evidence.
5. Full all-route screenshot matrix is not captured.
6. Public/trader pages still have modules with missing or snapshot-backed sources.
7. Admin canonical route migration from `/system/*` to `/admin/*` is not complete.
8. Backend monitoring endpoints `/api/admin/monitoring/*` are not validated.
9. Realtime manifest/data-health/data-coverage endpoints are not validated.
10. Production HTTPS/env/smoke validation is not run.
11. Durable production auth/RBAC/MFA/step-up/audit/live-gate final approval is not complete.
12. Local `localhost:5173` development was previously proxying `/api` back to the frontend server unless `VITE_API_PROXY_TARGET` was set, which made backend-backed panels show unavailable data. The frontend now defaults the proxy to `http://127.0.0.1:8000`, but the backend still must be running.

## Launch decision

- Paper/read-only launch: BLOCKED.
- Real live trading: BLOCKED and not authorized.

---

## 2026-06-15 local 5173 blocker update

Launch remains BLOCKED.

New/confirmed blockers from current Phase A evidence:

1. Root `v2` npm scripts for `typecheck` and `build` are missing; frontend package scripts pass, but root command contract is not aligned with the requested audit command list.
2. Backend pytest collection/import has been recovered; current full backend run passed.
3. Full Chromium against the actual local frontend on `5173` still requires a current rerun after backend recovery and route fixes.
4. Public status is not yet public-safe enough under the test contract.
5. RBAC and role-query/storage mutation behavior are still inconsistent with the security gate.
6. Trader surfaces still have runtime-alpha/trainer proof-panel leakage or visibility-test failures.
7. Account/exchange metadata labels and validation are not yet trader-safe enough.
8. ProChart still has signed-in watchlist and overflow defects.
9. Alert state coverage is incomplete.
10. Trader signal scope filtering is wrong for account-specific rows.
11. Canonical `/admin/*` migration and legacy `/system/*` behavior are still unresolved.
12. Full per-route screenshot matrix and human visual review are not complete.

Real live trading remains BLOCKED and was not enabled.

---

## 2026-06-16 current-truth reconciliation addendum

Authoritative detail: see `docs/v2-current-truth-after-june15.md`.

- Data-contract primitives are EXISTS/PARTIAL, not MISSING: `ValidatedDataEnvelope`, `useRealtimeResource`, `useDataFreshness`, `DataQualityBadge`, `FreshnessBadge`, `SourceBadge`, `EvidenceDrawer`, `RealtimeStatusBar`, `ProTable`, `MetricCard`, and `KPIGrid` exist in `frontend/src`.
- Adoption is PARTIAL. Any public/trader page or visible component still importing `usePayloadFile`, `operatorTruthData`, raw `/operator_runtime/*` paths, raw payload filenames, or legacy cockpit/operator surfaces remains DATA-BLOCKED until rewired to `/api/v2/*` envelopes/realtime streams or gated behind admin incident views.
- Backend collection currently succeeds: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/pytest v2/backend/tests/ --collect-only -q` collected `4093` tests with no collection/import errors.
- Local viewing is restored with Vite on `5173`, Cloudflare serving the Vite shell, and FastAPI on `8000` using the checked-in backend startup script. This is local smoke evidence only, not launch readiness.
- `/` renders the public landing page directly; `/landing` remains a compatibility route; `/market` redirects to `/market/BTCUSDT`; `/dashboard` redirects to `/trade`; unauthenticated protected routes fail closed through backend-confirmed auth.
- Full backend pytest is proven clean in the current pass; full Chromium, route-by-route data coverage, and screenshot matrix are still UNPROVEN.
- Do not mark Phase 14, Phase 15, `/trade`, `/market/:symbol`, realtime data, paper/read-only launch, admin security, or real live trading as PASS from this evidence.
- Real live trading remains BLOCKED.

### 2026-06-16 targeted backend evidence update

- Scoped backend auth/RBAC/status plus market-contract target now passes: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/integration/api/test_auth_rbac_and_status.py v2/backend/tests/integration/api/v2/test_market_contract_routes.py -q` -> `119 passed in 57.67s`.
- Superseded by current full backend evidence: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/ -q --maxfail=25` -> `4111 passed, 4 skipped, 1 warning in 383.06s`. Full Chromium, production smoke, route-by-route data coverage, and screenshot matrix remain UNPROVEN/BLOCKED for launch purposes.

### 2026-06-16 backend service startup and live-gate status update

- Local backend service is running on `127.0.0.1:8000`.
- `/api/v2/status` returns HTTP 200 with `live_trading_enabled=false` and public-safe degraded data status.
- `/api/v2/market/overview` returns HTTP 200 with a read-only API envelope and `stale=false`.
- `/api/v1/live-gate/status` now returns HTTP 200 without authentication and exposes only safe blocked-state fields: `live_gate=blocked_human_only`, `live_symbols=[]`, `trader_execution_enabled=false`, and `places_real_order=false`.
- `/api/v1/live-gate/evaluate` and `/api/v1/live-gate/enable` remain protected; unauthenticated requests return `401 authentication_required`.
- `/api/auth/me` returns `401 authentication_required`; `/api/auth/login` exists as POST and empty POST returns `422` rather than 404.
- `/api/v2/realtime/manifest` and `/api/v2/data-health` still return 404 and remain blockers for realtime/data-health validation.
- Paper/read-only launch remains BLOCKED. Real live trading remains BLOCKED.
- Real live trading remains BLOCKED.

### 2026-06-16 local access correction

- Local Vite `http://127.0.0.1:5173/` and Cloudflare `https://dashboard.wajidali.us/` render the AlphaForge landing page.
- Bare `http://127.0.0.1:5173/market` now redirects to `/market/BTCUSDT` instead of the protected `/markets` listing.
- FastAPI starts with `bash v2/backend/scripts/start_v2_backend_uvicorn.sh`.
- Blocking Binance public market HTTP reads were moved off the FastAPI event loop, so `/api/v2/status` remains responsive while read-only market endpoints load.
- Focused validation passed: frontend typecheck, frontend build, Python compile for `market_contracts.py`, and backend auth/status + market-contract pytest (`119 passed in 60.06s`).
- Full backend pytest is current-pass green after this latest patch; full Chromium remains pending current rerun. Phase 15 and real live trading remain BLOCKED.

### 2026-06-16 full backend pytest after market threadpool patch

- Command: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/ -q`.
- Result: `4111 passed, 4 skipped, 1 warning in 413.81s`.
- Local service smoke in the same pass confirmed Vite on `5173`, FastAPI on `8000`, `/api/v2/status` HTTP 200 with `live_trading_enabled=false`, `/api/auth/me` HTTP 401 unauthenticated, `/api/v1/live-gate/status` HTTP 200 blocked state, and `/api/v2/market/overview` HTTP 200 read-only envelope.
- Full Chromium remains pending current rerun after this latest patch; Phase 15 and real live trading remain BLOCKED.

## 2026-06-16 Current Full Chromium Rerun Blockers

- Command: `cd v2/frontend && npx playwright test --project=chromium --reporter=list`.
- Result: `174 passed`, `98 failed`, `31 did not run`.
- Backend is no longer the primary test blocker: current full backend pytest passed with `4111 passed, 4 skipped, 1 warning`.
- Current frontend blockers: auth/RBAC route drift, mission-control legacy contract drift, public status contract drift, ProChart/mobile overflow, runtime-alpha/trainer proof leakage on trader routes, legacy route canonicalization drift, `/trade` UI/data-state regressions, trader nav cleanliness, signal selector controls, stale-state alerts, and `/markets/symbols` route contract failures.
- `/api/v2/realtime/manifest` and `/api/v2/data-health` still return 404 and block realtime/data-health proof.
- Paper/read-only launch remains BLOCKED.
- Phase 15 remains BLOCKED.
- Real live trading remains BLOCKED.

## 2026-06-16 Auth/RBAC Focused Remediation

- Focused auth/RBAC Chromium coverage now passes: `20 passed` across `auth_rbac_redesign.spec.ts` and `rbac_visibility.spec.ts`.
- The previous auth cluster from the current full Chromium run is considered focused-remediated, pending full-suite rerun.
- Remaining full-suite blockers still include mission-control legacy contract drift, public status contract drift, overflow, runtime-alpha/trainer proof leakage, legacy route redirects, `/trade` UI/data states, trader nav cleanliness, signal selector controls, stale-state alerts, and `/markets/symbols` route contract failures.
- Paper/read-only launch remains BLOCKED.
- Real live trading remains BLOCKED.

### 2026-06-16 current full Chromium after backend/local-access patch

- Command: `cd /home/wali/Desktop/AI\ BOT\ REBUILD/v2/frontend && npx playwright test --project=chromium --reporter=list`.
- Result: `185 passed`, `87 failed`, `31 did not run` in `3.8m`.
- Previous current full Chromium evidence was `174 passed`, `98 failed`, `31 did not run`; current pass improves by 11 fewer failures but remains failing.
- Remaining clusters: auth/RBAC edge states, default-deny admin dangerous controls, legacy mission-control/operator cockpit tests, market detail timeouts/overflow, public status contract drift, runtime-alpha leakage on trader/system routes, stale-state alerts, `/markets/symbols`, trade terminal console/copy, trader-first overflow, trader nav/legacy redirects, trader signal selector panels, and mobile screenshot overflow.
- Full backend pytest is current green, so launch is now blocked primarily by full Chromium/product-contract/data-surface/visual/realtime/production-smoke gates rather than backend collection/startup.
- Paper/read-only launch remains BLOCKED. Phase 15 remains BLOCKED. Real live trading remains BLOCKED.

### 2026-06-16 focused auth/RBAC route-protection fix

- Frontend typecheck passed after route-protection fixes.
- Focused auth/RBAC Chromium passed: `20 passed in 6.8s` across `auth_rbac_redesign.spec.ts` and `rbac_visibility.spec.ts`.
- Fixes: canonical AdminShell RBAC lookup, protected `/admin/mission-control -> /admin/system`, and protected `/admin/risk-control -> /admin/risk`.
- Full Chromium remains pending rerun after this focused fix. Phase 15 remains BLOCKED. Real live trading remains BLOCKED.

---

## 2026-06-18 Focused Backend + Safety Audit Pass

**Date:** 2026-06-18
**Branch:** codex/pipeline-trust-refresh

### Bugs Fixed

| # | Bug | Fix |
|---|-----|-----|
| 1 | `risk-control/route.ts` declared `/admin/risk` but contract expected `/admin/risk-control` — 3 website contract tests failed | Changed route to `/admin/risk-control` in `v2/frontend/src/pages/risk-control/route.ts` |
| 2 | Public paper fallback endpoints (`/api/v2/account/positions`, `/api/v2/execution/audit-events`, orders, executions) returned `source_type="redis_live"` even when Redis was unreachable — `test_market_contracts_return_structured_unavailable_states` failed | Added `_paper_redis_source_type()` helper in `market_contracts.py` that returns `"unavailable"` when the Redis-unavailable warning is present; applied to all 4 unauthenticated paper fallback response blocks |
| 3 | `_assert_contract` test helper missing `redis_live` in the allowed `source_type` set — caused false failures when Redis is up | Added `redis_live` to the allowed set in `test_market_contract_routes.py:_assert_contract` |
| 4 | `test_market_contracts_return_structured_unavailable_states` didn't isolate Redis — live Redis data leaked into the unavailable-state assertion | Added `isolate_redis=True` parameter to `_client()` that monkeypatches `market_contracts.get_redis` to `lambda: None` for the unavailable-states test |

### Focused Backend Tests (all from repo root, `.venv/bin/pytest`)

| Suite | Result |
|-------|--------|
| Trainer domain + services (trainer_liveness, trainer_parity, trainer_prediction_output, trainer_worker_health, native_trainer) | **371 passed** |
| Paper trading domain + services (paper_mode, paper_execution_ledger, paper_trade_management, paper_guards) | **331 passed** |
| Risk gateway domain + services + risk_legacy_gates | **144 passed** |
| API unit + orchestrator_decision + rl_core | **134 passed** |
| Market data trust, market_state_integrity, adaptive_capital_allocator, shadow_mode_readiness | **87 passed** |
| Replay, report, runtime_alpha_dynamic_readiness, strategy_router, degraded_state_fail_closed_gates, lineage, liveness_stream_growth | **243 passed** |
| Pipeline trust, canonical candles + MTF snapshot | **79 passed** |
| External quarantine, operator_truth, profit_target_monitor, provenance_dedupe, local_secret_loader, website contracts | **119 passed** |
| Integration API full suite (including market_contract_routes) | **158 passed** |
| live_gate service | **48 passed** |
| rl_core direct trust guards | **5 passed** |

### Frontend

| Check | Result |
|-------|--------|
| `npm run typecheck` | **PASS** — 0 TypeScript errors, 2690 modules |
| `npm run build` | **PASS** — 2690 modules, 17.63s |

### Safety Scan Results

| Scan | Finding |
|------|---------|
| Real order submission paths (exchange new-order API, place_order method) | **CLEAN** — All V2 app paths raise/refuse on `place_order`. Only `legacy_preserved/` contains real exchange-order calls (expected, read-only preserved reference copy). |
| Leverage mutation (change_initial_leverage, margin_type change) | **CLEAN** — All CLI scripts declare `exchange_leverage_mutation: false`; live_canary_blocker_guard blocks ADJUST_LEVERAGE |
| test-order endpoint | **CLEAN** — Only referenced in safety-declaration strings (explicitly excluded from all execution paths) |
| Old Redis v1 key writes | **CLEAN** — No `v1:` key write patterns found in V2 app code |
| Fixed sizing (non-risk-based position sizing) | **CLEAN** — No hardcoded position quantities in the execution path; quantities derive from risk calculations |
| Guaranteed-profit wording | **CLEAN** — `shows_guaranteed_profit: false` and `guaranteed_profit_claimed: false` enforced in CLI safety artifacts |
| Raw credential exposure | **CLEAN** — No print/log of api_key or secret patterns found in app code |
| RL-core overwrite of primary CUDA predictions | **CLEAN** — rl_core reads `v2:prediction:*` but never writes to it; writes only `v2:paper:position_price_track:*` and `v2:paper:position_history:*`; `training_loop.py` explicitly declares `no_redis_writes` and `writes_legacy_redis: False` |

### Status After This Pass

| Gate | Status |
|------|--------|
| Live trading | **BLOCKED** (`blocked_human_only`, 5 enforcement layers intact) |
| Backend focused tests | **PASS** — all covered suites green after fixes |
| Frontend typecheck | **PASS** — 0 errors |
| Frontend build | **PASS** — 2690 modules |
| Safety scan | **PASS** — no violations found |
| Paper soak (500-trade target) | **BLOCKED** — 16 closed trades far below 500; 56.25% win rate on tiny sample |
| Full Chromium suite | **PENDING** — not re-run in this pass |
| Production HTTPS/smoke | **BLOCKED** — not validated |

### Remaining Critical Blockers (unchanged from prior pass)

1. Paper closed-trade count must reach 500 before live-gate proof window opens.
2. Paper win rate on the small sample (56.25%) is not statistically defensible.
3. 5/30 paper positions still rely on canonical paper marks instead of direct fresh live mark streams.
4. No 3-hour clean window, 12-hour post-remediation soak, or statistically defensible profitability evidence has passed.
5. Full Chromium suite remains pending current rerun.
6. `/api/v2/realtime/manifest` and `/api/v2/data-health` still return 404.
7. Production HTTPS/env/smoke validation not run.
8. Durable production auth/RBAC/MFA/live-gate final approval not complete.

**Real live trading: CONFIRMED BLOCKED.**

---

## 2026-06-18 Third Pass — PIT Audit Fix + Mark Stale + Report Regeneration

### Bugs Fixed This Pass

| # | Bug | Fix |
|---|-----|-----|
| 1 | `stale_mark_price_count=4` in summary but no per-position `mark_price_stale` boolean | Added `"mark_price_stale": mark_age_seconds is not None and mark_age_seconds > 90` to position output dict in `_enrich_paper_positions()` (market_contracts.py:6452) |
| 2 | `MISSING_TF_PREDICTION` rows incorrectly classified as PIT violations (`MISSING_DECISION_CUTOFF`) | Fixed `audit_prediction_row()` in prediction_signal_quality_auditor.py: missing-prediction rows now get `pit_safety.status = CLEAN` with N/A explanation — absence of a prediction is not a PIT safety violation |
| 3 | Prediction quality audit status was `BLOCKED_PIT_VIOLATIONS_DETECTED` (20 violations from 4 missing symbols) | Re-ran audit after fix — now `PARTIAL_STALE_PREDICTIONS`, `pit_violation_count=0`, `actionable_candidate_count=285` |
| 4 | paper_loss_cluster_report.json had stale data (381 trades, 41.78% win rate, 18 quarantine) | Regenerated from full Redis ledger: 446 trades, 33.63% win rate, PF=1.24, quarantine=17 (pre-remediation) |
| 5 | paper-performance-remediation-plan.md based on 200-row API-capped sample | Updated with full-ledger recalculation section; all stats corrected |

### New Tests Added

| Test file | Tests | Covers |
|---|---|---|
| `test_prediction_signal_quality.py` | `TestMissingTfPredictionPitBehavior` (3 tests) | MISSING_TF_PREDICTION PIT=CLEAN, not in pit_violations, excluded by NOT_FRESH not PIT_VIOLATION |
| `test_enrich_paper_positions_mark_stale.py` | `TestMarkPriceStaleFlagPresent` (6 tests) | mark_price_stale present, bool type, False@90s, True@91s, summary count matches per-position flags |

### Current State (2026-06-18T19:22Z)

| Metric | Value |
|---|---|
| Paper closed trades | 446 / 500 target (89.2%) |
| True win rate (full ledger) | 33.63% |
| Profit factor | 1.24 |
| Quarantine (pre-remediation) | 17 |
| PIT violations | 0 (was 20 — fixed) |
| Stale predictions (not PIT) | 140 (31 symbols w/ no recent publish — non-blocking) |
| Prediction quality status | PARTIAL_STALE_PREDICTIONS |
| Live trading | CONFIRMED BLOCKED |

### Remaining Blockers

1. Paper soak: 54 trades remaining to reach 500-trade target.
2. Win rate 33.63% below 35% soft threshold — system profitable (PF=1.24) but win rate gate NOT_MET.
3. 140 stale prediction rows from 31 symbols (BTCUSDT, ETHUSDT, etc.) not publishing fresh predictions.
4. Full Chromium Playwright suite not re-run this pass.
5. `/api/v2/realtime/manifest` and `/api/v2/data-health` still return 404.
6. Production HTTPS/env/smoke validation not run.

**Real live trading: CONFIRMED BLOCKED.**

---

## 2026-06-18 Fourth Pass — 504-Trade Soak Final + Report Regeneration

### Artifacts Regenerated

| Artifact | Previous | Now |
|---|---|---|
| `paper_loss_cluster_report.json` | 446 trades, WR=33.63%, PF=1.24 | **504 trades, WR=29.56%, PF=1.10** |
| `paper-performance-remediation-plan.md` | Partial soak, 446 trades | **Full soak analysis, 504 trades, 10-gate checklist** |
| `prediction_signal_quality_status.json` | stale=140, fresh=285 | **stale=22, fresh=403 (publisher refreshed)** |

### Current State (2026-06-18T23:30Z)

| Metric | Value | Gate |
|---|---|---|
| Paper closed trades | **504** (exceeded 500) | MET |
| True win rate (full ledger) | **29.56%** | NOT_MET (need 35%) |
| Profit factor | **1.10** | MET_MARGINAL |
| Negative-PnL timeframes | **5m (-$8.19), 4h (-$6.18)** | NOT_MET |
| PIT violations | **0** | MET |
| Quarantine (new failures) | **0 new** (19 pre-remediation) | MET |
| Stale predictions | **22** (down from 140 after publisher refresh) | PARTIAL |
| Live trading | **CONFIRMED BLOCKED** | — |

### Stale Prediction Root Cause (Resolved Operationally)

Publisher was idle for ~4h earlier in session (140 stale rows). After publisher resumed,
stale_count dropped to 22. Not a code bug — operational gap. Recommendation: add monitor
alert for stale_count > 50 or symbol with no fresh prediction > 30 min.

### Stale Mark Price Root Cause (Classified)

`stale_mark_price_count` fluctuates 0–3 because mark freshness is computed at API request
time from market price feed data; it is NOT stored in `v2:paper:positions`. The `mark_price_stale`
boolean added to each position output (2026-06-18) makes per-position staleness auditable.
90-second threshold is correct (ingestor cycle is 60s). No code change needed.

### Remaining Blockers for Live Gate

1. **Win rate 29.56% below 35% threshold** — must reach 35% on ≥ 200 new trades after changes.
2. **5m and 4h timeframes net-negative** — must exclude or remediate before live approval.
3. **Zero-WR symbols active** — NIGHTUSDT, TIAUSDT, TRUMPUSDT, PUMPUSDT need circuit-breaker or exclusion.
4. **Profit factor declining** — 1.099 vs 1.24 at 446 trades; trend monitoring required.
5. Full Chromium Playwright suite not re-run this pass.
6. `/api/v2/realtime/manifest` and `/api/v2/data-health` still return 404.
7. Production HTTPS/env/smoke validation not run.
8. Human operator explicit live-trading approval (required regardless of other gates).

**Real live trading: CONFIRMED BLOCKED. 3/10 live-gate criteria met.**
