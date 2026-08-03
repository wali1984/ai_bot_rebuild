# V2 Full Website Redesign Master Plan

Date: 2026-06-15
Scope root: `/home/wali/Desktop/AI BOT REBUILD/v2`
Status: PHASE A AUDIT ACTIVE. Not launch ready. Real live trading remains blocked.

## Non-negotiable operating posture

- Do not enable real live trading.
- Do not add live order submit, cancel, leverage, or margin mutation.
- Do not weaken RBAC.
- Do not present static snapshots as live data.
- Do not mark public/trader pages complete while normal modules render unavailable data.
- Admin pages may show broken sources only as actionable incidents with source, owner, last-success, error, and remediation.

## Current validation baseline

| Gate | Result | Evidence |
| --- | --- | --- |
| `git status --short` | BLOCKED | Dirty tree is extremely large, including existing backend/frontend/docs/public artifacts and current scoped frontend changes. No cleanup/revert performed. |
| `npm run typecheck` | GREEN in latest completed run | `tsc -b --noEmit` passed after market fallback and display cleanup. |
| `npm run build` | GREEN with warnings | Vite production build passed; existing warnings: large JS chunk and plugin timing. |
| `npm run lint --if-present` | NO-OP | No `lint` script exists in `frontend/package.json`; command exited 0 without output. |
| Backend pytest | GREEN in current pass | `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/ -q --maxfail=25` passed: `4111 passed, 4 skipped, 1 warning`. |
| Backend service startup | PARTIAL | FastAPI runs on `127.0.0.1:8000`; `/api/v2/status`, `/api/v2/market/overview`, `/api/v1/live-gate/status`, and auth routes are mounted. `/api/v2/realtime/manifest` and `/api/v2/data-health` still 404. |
| Full Chromium exact command | PENDING CURRENT RERUN | Backend recovery removes the previous backend-down blocker; current full Chromium evidence has not been rerun after latest route/API fixes. |
| Full Chromium diagnostic | PENDING CURRENT RERUN | Historical sandbox/port issues are not current acceptance evidence. |
| Focused route cleanliness | GREEN | `trader_nav_cleanliness.spec.ts` passed 35/35 before Phase A docs. |
| Focused derivatives/prediction controls | GREEN | `trader_signal_selector_controls.spec.ts --grep 'derivatives liquidation|shared prediction matrix'` passed 3/3. |
| Market fallback tests | GREEN | `market_public_fallback.spec.ts` passed 2/2. |
| Responsive overflow screenshots | GREEN for current crawler scope | `redesign_screenshot_overflow.spec.ts` passed 4/4. Not a full all-route visual matrix. |

## Phase sequence

1. Phase A: hard freeze, audit, route inventory, data surface inventory, screenshot/failure inventory.
2. Phase B: shared validated data envelope and source/freshness/quality metadata everywhere.
3. Phase C: backend source map and safe read-only wiring; no live mutation.
4. Phase D: split premium design system into tokens/theme/layout/component/chart/table/admin/responsive files.
5. Phase E: route migration to public/trader/admin/superadmin map.
6. Phase F/G: public and trader page redesign with only realtime/near-realtime valid data or gated modules.
7. Phase H/I: admin portal, monitoring, incident layer, backend/admin monitoring endpoints.
8. Phase J/K: full tests and screenshot matrix.
9. Phase L: paper/read-only launch only after all gates pass; real live trading stays blocked until separate approval process.

## Immediate blockers

- Full Chromium suite cannot be used as acceptance until a current full run completes against local `5173` plus backend `8000`.
- Backend full pytest is current-pass green and can be used as backend evidence for this pass.
- Public/trader pages still contain modules whose required realtime sources are missing or snapshot-backed; those modules must be wired or gated.
- Admin route map still includes legacy `/system/*` surfaces; target final map requires `/admin/*` canonical protection.
- Backend realtime manifest/data-health/data-coverage endpoints are not yet fully implemented; `/api/v2/realtime/manifest` and `/api/v2/data-health` currently return 404.
- Full screenshot matrix for every route/viewport is not yet captured.

## Work already useful but not completion evidence

- Public market fallback layer in `frontend/src/api/v2Market.ts` recovers read-only Binance USD-M data when local V2 market contracts are unavailable.
- Liquidation page supports BTC/ETH/SOL plus additional symbols from market overview and selector toggles.
- Global CSS visual system was strengthened, and focused overflow checks pass.
- Shared realtime/admin display labels were cleaned to reduce raw payload/source clutter.

## Definition for next implementation pass

A route can move from BLOCKED to IN PROGRESS only when its data surfaces are listed in `v2-page-data-coverage-matrix.md` and its missing sources are either wired or explicitly gated out of public/trader navigation. A route can move to candidate acceptance only after full backend tests, full Chromium, and screenshot matrix pass.

---

## 2026-06-15 Phase A active goal checklist update

This checklist is bound to the active Codex goal and supersedes any informal pass claims. No route, page, or launch phase is complete until the attached Phase A-L gates pass.

### Active phase checklist

| Phase | Scope | Current status | Gate to move forward |
| --- | --- | --- | --- |
| A | Hard freeze, audit, failure inventory, route/data/source/screenshot/control/blocker docs | IN PROGRESS | Required commands recorded; failure inventory updated; route/data/source gaps documented |
| B | Shared realtime data envelope and source/freshness/quality contract | PENDING | Backend/frontend contract and tests prove every visible metric has metadata |
| C | Backend source audit and real wiring through Redis, ingestors, scripts, repositories, routers, trainer, signals, risk, orchestrator, paper ledger | PENDING | Every visible unavailable field is checked against ingestors, Redis/artifacts, backend contract, and frontend mapper before being declared absent |
| D | Premium trading design system and responsive components | PENDING | Dark/light themes, shells, panels, tables, charts, badges, evidence drawers, mobile cards implemented |
| E | Route ownership and migration | PENDING | Public/trader/admin/superadmin routes canonicalized; legacy routes redirected/protected/removed |
| F | Public page redesign and wiring | PENDING | Landing/status/login/public preview are public-safe and not normalizing unavailable data |
| G | Trader page redesign and wiring | PENDING | Dashboard, markets, market detail, trade, derivatives, signals, AI predictions, portfolio, executions, history, backtests, replay, research, alerts are meaningful and sourced |
| H | Admin portal redesign and monitoring | PENDING | Admin pages are backend-protected and show actionable incidents/controls only |
| I | Monitoring and observability layer | PENDING | Route/data/realtime/frontend/backend/test/build/contract incidents exposed under admin monitoring |
| J | Tests and validation | PENDING | Frontend package build/typecheck/lint, backend pytest, full Chromium, auth/RBAC, data-contract tests pass |
| K | Screenshot and human visual review | PENDING | Every public/trader/admin/superadmin route captured at 1920x1080, 1440x900, 768x1024, 390x844 with PASS/FAIL/BLOCKED notes |
| L | Launch readiness | PENDING | Paper/read-only launch gates pass; real live trading remains blocked unless separately approved through live-gate |

### Current 5173 audit evidence

| Command | Result | Notes |
| --- | --- | --- |
| `git status --short` | Completed | Worktree is heavily dirty, including many unrelated files outside this V2 website pass. Do not revert unrelated changes. |
| `npm run typecheck` from `v2` | FAILED | Root `v2` package has no `typecheck` script. |
| `npm run build` from `v2` | FAILED | Root `v2` package has no `build` script. |
| `npm run lint --if-present` from `v2` | PASSED | Exited 0 with no output. |
| `npm run typecheck` from `v2/frontend` | PASSED | `tsc -b --noEmit` passed. |
| `npm run build` from `v2/frontend` | PASSED | `tsc -b && vite build` passed; Vite warned that a JS chunk exceeds 500 kB. |
| `npm run lint --if-present` from `v2/frontend` | PASSED | Exited 0 with no output. |
| Backend pytest from repo root | PASSED | Current full backend run: `4111 passed, 4 skipped, 1 warning in 383.06s`. |
| Full Chromium Playwright against `http://127.0.0.1:5173` | PENDING CURRENT RERUN | Historical failures are superseded as blocker inventory, not acceptance evidence. |
| Focused trader/public route cleanliness against `5173` | PASSED | `25 passed`; local evidence only, not launch acceptance. |

### Current top blockers from 5173 full Chromium

- Query/browser-storage role mutation can still leave `/dashboard?role=admin` instead of redirecting to `/login` under mocked unauthenticated state.
- Legacy Mission Control and readiness-banner tests fail; route/test ownership must be reconciled with canonical `/admin/*` design.
- Public status tests fail on public-safe rendering, freshness/incidents/last-updated context, and forbidden internal terms.
- RBAC visibility tests fail for viewer/reviewer/public access expectations.
- Trader routes still fail runtime-alpha/trainer proof-panel hiding tests on `/dashboard`, `/ai-predictions`, `/signals`, `/trade`, `/portfolio`, and `/backtests`.
- Legacy `/system/trainer`, `/system/risk-controllers`, and `/system/readiness` diagnostic expectations fail under the current route migration state.
- ProChart fails signed-in watchlist handling and horizontal overflow at 1440x900 and 390x844.
- Stale-state alert coverage fails for category/task-id and clean-feed empty states.
- Trade/account settings fail safe account status, private-looking metadata validation, and paper-scope versus exchange-metadata labeling.
- Trader signal panel scope filtering fails: expected one visible scoped row, currently shows zero and withholds both active rows.

### Non-negotiable carry-forward rule

Before any visible field is marked unavailable, check the relevant ingestor, Redis key/artifact, backend endpoint/contract, and frontend mapper. If the source exists, wire it. If it does not exist, gate/remove the public/trader module and record an admin incident instead of showing generic unavailable content.

---

## 2026-06-16 current-truth reconciliation addendum

Authoritative detail: see `docs/v2-current-truth-after-june15.md`.

- Data-contract primitives are EXISTS/PARTIAL, not MISSING: `ValidatedDataEnvelope`, `useRealtimeResource`, `useDataFreshness`, `DataQualityBadge`, `FreshnessBadge`, `SourceBadge`, `EvidenceDrawer`, `RealtimeStatusBar`, `ProTable`, `MetricCard`, and `KPIGrid` exist in `frontend/src`.
- Adoption is PARTIAL. Any public/trader page or visible component still importing `usePayloadFile`, `operatorTruthData`, raw `/operator_runtime/*` paths, raw payload filenames, or legacy cockpit/operator surfaces remains DATA-BLOCKED until rewired to `/api/v2/*` envelopes/realtime streams or gated behind admin incident views.
- Backend collection currently succeeds: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/pytest v2/backend/tests/ --collect-only -q` collected `4093` tests with no collection/import errors.
- Local viewing is restored with Vite on `5173`, Cloudflare serving the Vite shell, and FastAPI on `8000` using detached 4-worker Uvicorn. This is local smoke evidence only, not launch readiness.
- `/` renders the public landing page directly; `/landing` remains a compatibility route; `/market` redirects to `/markets`; `/dashboard` redirects to `/trade`; unauthenticated `/trade` fails closed to `/login?returnTo=%2Ftrade`.
- Full backend pytest is proven clean in the current pass; full Chromium, route-by-route data coverage, and screenshot matrix are still UNPROVEN.
- Do not mark Phase 14, Phase 15, `/trade`, `/market/:symbol`, realtime data, paper/read-only launch, admin security, or real live trading as PASS from this evidence.
- Real live trading remains BLOCKED.

### 2026-06-16 targeted backend evidence update

- Scoped backend auth/RBAC/status plus market-contract target now passes: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/integration/api/test_auth_rbac_and_status.py v2/backend/tests/integration/api/v2/test_market_contract_routes.py -q` -> `119 passed in 57.67s`.
- Superseded by current full backend evidence: `4111 passed, 4 skipped, 1 warning in 383.06s`. Full Chromium, production smoke, route-by-route data coverage, and screenshot matrix remain UNPROVEN/BLOCKED for launch purposes.
- Real live trading remains BLOCKED.
