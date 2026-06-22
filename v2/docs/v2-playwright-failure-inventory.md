# V2 Playwright Failure Inventory

Date: 2026-06-15
Status: Full Chromium is failing. Do not mark Phase 14 pass.

## Commands and results

| Command | Result | Classification |
| --- | --- | --- |
| `npx playwright test --project=chromium --reporter=list` | Failed before tests | Playwright webServer could not start. Direct Vite start on default `5174` reports port in use, while `curl` to `5174` fails. |
| `PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test --project=chromium --reporter=list` | Failed | No valid server; broad route failures plus Chromium launch issues. |
| `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5180 npx playwright test --project=chromium --reporter=list` | Failed before tests | Playwright webServer startup still failed, though direct Vite start on 5180 worked. |
| `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5180 npx playwright test --project=chromium --reporter=list` | Failed | Parallel 16-worker run produced Chromium sandbox fatal errors. |
| `PLAYWRIGHT_NO_WEBSERVER=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:5180 npx playwright test --project=chromium --reporter=list --workers=1` | Invalid failure run | Server was no longer reachable; route tests failed rapidly. Do not use as product evidence. |
| `PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test tests/e2e/trader_nav_cleanliness.spec.ts --project=chromium --workers=1` | Passed 35/35 | Focused route cleanliness evidence only. |
| `PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test tests/e2e/trader_signal_selector_controls.spec.ts --project=chromium --workers=1 --grep 'derivatives liquidation|shared prediction matrix'` | Passed 3/3 | Focused selector/derivatives evidence only. |
| `PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test tests/e2e/market_public_fallback.spec.ts --project=chromium --workers=1` | Passed 2/2 | Market fallback contract evidence. |
| `PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium` | Passed 4/4 | Partial responsive overflow/screenshot evidence. |
| `npx playwright test --project=chromium --reporter=list` | Failed: 268 passed, 22 failed, 29 did not run | Escalated full Chromium evidence. Product is not launch-ready. |

## Primary failure signatures

- Default configured baseURL: `http://127.0.0.1:5174`.
- Direct Vite command on 5174: `Error: Port 5174 is already in use`.
- `curl http://127.0.0.1:5174/`: connection refused.
- Parallel full suite browser errors in sandboxed runs: `FATAL:content/browser/sandbox_host_linux.cc:41 Check failed: . shutdown: Operation not permitted (1)`.
- Escalated full Chromium run completes but reports 22 real product/test failures across dashboard proof/internal copy, market detail missing-source states, ProChart timestamps/overflow/source logic, public status raw-source exposure, trade terminal account/paper/signal contracts, AI Predictions trainer-runtime leakage, and legacy model-state redirects.
- Backend pytest collection blocker: duplicate module basename `test_service.py` imported from `services/e2e_verification` colliding with `services/profit_target_monitor` and `services/runtime_alpha_dynamic_readiness`.
- Local frontend dev server on `5173` must proxy `/api` to the FastAPI backend, not to itself. Self-proxying causes broad `unavailable` states even when the React app renders correctly.

## Required remediation

1. Fix the 22 full Chromium product/test failures; focused passing specs are not sufficient.
2. Keep Playwright on a deterministic single-worker port configuration for this environment unless the sandbox supports parallel browser launch.
3. Fix backend pytest import mismatch by package isolation or unique module basenames.
4. Re-run full Chromium and backend pytest before any launch readiness movement.

---

## 2026-06-15 full Chromium rerun against actual local frontend on 5173

Command:

`PLAYWRIGHT_BASE_URL=http://127.0.0.1:5173 PLAYWRIGHT_NO_WEBSERVER=1 npx playwright test --config=frontend/playwright.config.ts --project=chromium --reporter=list --workers=1`

Result: FAILED, `239 passed`, `34 failed`, `30 did not run`.

Important setup note: invoking Playwright from `v2` without `--config=frontend/playwright.config.ts` fails immediately because the root invocation has no configured `chromium` project. The full suite must use the frontend config for this repository layout.

Failed tests:

| Spec | Failure |
| --- | --- |
| `auth_rbac_redesign.spec.ts` | Query/browser storage mutations do not grant admin: unauthenticated `/dashboard?role=admin` stayed on dashboard instead of `/login`. |
| `enterprise_trading_cockpit.spec.ts` | Mission Control cockpit expectations fail against current admin surface copy/layout. |
| `mission_control_readiness_banner.spec.ts` | READY/BLOCKED/divergent/read-only request checks fail. |
| `operator_proof_dashboard_historical_30d.spec.ts` | Operator proof dashboard professional cockpit evidence check fails. |
| `phase_13a_visual_gate.spec.ts` | Public status route fails 1920x1080 visual gate; later visual-gate cases did not run. |
| `pro_chart_realtime_contract.spec.ts` | Signed-in trader watchlist favorite handling fails; read-only ProChart has horizontal overflow at 1440x900 and 390x844. |
| `public_status_redesign.spec.ts` | Public-safe rendering, freshness/incidents/last-updated context, and forbidden internal term checks fail. |
| `rbac_visibility.spec.ts` | Viewer/reviewer/public admin-surface expectations fail. |
| `runtime_alpha_dynamic_readiness_visibility.spec.ts` | Trader routes still expose or fail to hide runtime-alpha/trainer proof-panel content; legacy `/system/*` diagnostic checks also fail. |
| `stale_state_alerts.spec.ts` | Five alert categories with task IDs and clean-feed empty states fail. |
| `trade_terminal_redesign.spec.ts` | Trader-specific account and safe account access status without secrets fails. |
| `trader_nav_cleanliness.spec.ts` | Private-looking account metadata validation and complete paper-scope/missing-exchange metadata labeling fail. |
| `trader_signal_selector_controls.spec.ts` | Account-specific signal scope filtering withholds both rows instead of showing the scoped BTC row. |

Passing evidence worth preserving:

- API v2 contract state tests passed.
- Auth/RBAC screenshot capture tests mostly passed except mutation case.
- Live-block banner passed across public/admin routes.
- Market detail redesign and market public fallback tests passed, including closed-candle fallback checks.
- Screenshot overflow crawler passed at 1920x1080, 1440x900, 768x1024, and 390x844.
- Trader-first nav and many trader cleanliness checks passed.
- Signal selector controls passed for pinned majors/all overview symbols, symbol/timeframe toggles, hydration of missing matrix cells, and liquidation card updates.

Current conclusion: Full Chromium remains RED. Do not move Phase 14 or launch readiness forward.

---

## 2026-06-16 current-truth reconciliation addendum

Authoritative detail: see `docs/v2-current-truth-after-june15.md`.

- Data-contract primitives are EXISTS/PARTIAL, not MISSING: `ValidatedDataEnvelope`, `useRealtimeResource`, `useDataFreshness`, `DataQualityBadge`, `FreshnessBadge`, `SourceBadge`, `EvidenceDrawer`, `RealtimeStatusBar`, `ProTable`, `MetricCard`, and `KPIGrid` exist in `frontend/src`.
- Adoption is PARTIAL. Any public/trader page or visible component still importing `usePayloadFile`, `operatorTruthData`, raw `/operator_runtime/*` paths, raw payload filenames, or legacy cockpit/operator surfaces remains DATA-BLOCKED until rewired to `/api/v2/*` envelopes/realtime streams or gated behind admin incident views.
- Backend collection currently succeeds: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/pytest v2/backend/tests/ --collect-only -q` collected `4093` tests with no collection/import errors.
- Local viewing is restored with Vite on `5173`, Cloudflare serving the Vite shell, and FastAPI on `8000` using detached 4-worker Uvicorn. This is local smoke evidence only, not launch readiness.
- `/` redirects to `/landing`; `/market` redirects to `/markets`; `/dashboard` redirects to `/trade`; unauthenticated `/trade` fails closed to `/login?returnTo=%2Ftrade`.
- Full backend pytest, full Chromium, route-by-route data coverage, and screenshot matrix are still UNPROVEN in the current pass.
- Do not mark Phase 14, Phase 15, `/trade`, `/market/:symbol`, realtime data, paper/read-only launch, admin security, or real live trading as PASS from this evidence.
- Real live trading remains BLOCKED.

### 2026-06-16 targeted backend evidence update

- Scoped backend auth/RBAC/status plus market-contract target now passes: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/integration/api/test_auth_rbac_and_status.py v2/backend/tests/integration/api/v2/test_market_contract_routes.py -q` -> `119 passed in 57.67s`.
- This is targeted evidence only. Full backend pytest, full Chromium, production smoke, route-by-route data coverage, and screenshot matrix remain UNPROVEN/BLOCKED for launch purposes.
- Real live trading remains BLOCKED.

