# Phase 14A Playwright Failure Inventory

Generated: 2026-06-13

Scope: full Chromium suite triage after Phase 13A visual remediation. This is a test-contract stabilization report, not a product launch pass.

Evidence note: this inventory records the Phase 14A stabilization result. Later frontend, backend, and documentation changes require a fresh validation run before these results can be used as current launch evidence.

## Summary

| Item | Result |
|---|---:|
| Baseline full Chromium result | 120 passed / 71 failed |
| Final full Chromium result | 196 passed / 0 failed |
| Backend integration tests | 13 passed |
| Frontend typecheck | PASS during Phase 14A; current rerun pending after later changes |
| Frontend build | PASS during Phase 14A; current rerun pending after later changes |
| Frontend lint | PASS during Phase 14A; current rerun pending after later changes |
| Real live trading | BLOCKED |
| `/trade` | IN PROGRESS |
| `/market/:symbol` | IN PROGRESS |
| Phase 15 | BLOCKED |

## Failure Clusters

| Cluster | Classification | Baseline failures | Required action | Fixed | Retested |
|---|---|---:|---|---|---|
| Live-block banner expected old live runtime copy | OBSOLETE_LEGACY_EXPECTATION / SAFETY_SECURITY_EXPECTATION | 41 | Updated tests to require blocked paper/read-only banner, no dismiss control, and no `enabled_operator_approved` live-runtime copy. | yes | yes |
| Default-deny dangerous control inventory | SAFETY_SECURITY_EXPECTATION | 5 | Preserved safety coverage by asserting dangerous controls are absent or disabled, and live trading disabled banner is visible. | yes | yes |
| Mission-control readiness tests on trader dashboard | OBSOLETE_LEGACY_EXPECTATION / DEAD_ROUTE_OR_REDIRECT | 4 | Replaced old trader mission-control assertions with current contract: dashboard must not expose mission-control/operator copy and browser checks remain read-only. | yes | yes |
| Stale-state alert legacy dashboard | DATA_STATE_EXPECTATION / OBSOLETE_LEGACY_EXPECTATION | 2 | Updated to require professional freshness/missing-data messaging without raw payload/debug JSON. | yes | yes |
| Enterprise trading cockpit legacy raw-runtime checks | OBSOLETE_LEGACY_EXPECTATION / SAFETY_SECURITY_EXPECTATION | 2 | Replaced old live-runtime/operator expectations with blocked-mode, no live action, and backend-confirmed superadmin archive access checks. | yes | yes |
| Operator proof dashboard legacy route | DEAD_ROUTE_OR_REDIRECT / SAFETY_SECURITY_EXPECTATION | 1 | Moved test to canonical `/system/evidence` route and verified admin denial plus superadmin access. | yes | yes |
| Public status legacy expectations | OBSOLETE_LEGACY_EXPECTATION | 4 | Updated status tests to public-safe contract: platform/API/data freshness, paper/read-only, live disabled, no internals/raw JSON. | yes | yes |
| RBAC legacy redirect and fake role tests | AUTH_FIXTURE_ISSUE / SAFETY_SECURITY_EXPECTATION | 1 | Fixed tests to use backend-auth mock, verified query/session/local storage role escalation does not grant access. | yes | yes |
| Trader-first legacy route checks | AUTH_FIXTURE_ISSUE / VISUAL_COPY_EXPECTATION | 10 | Added backend-confirmed auth fixture, route contracts, forbidden nav helper, and route-specific role handling. | yes | yes |
| Market detail missing-state wording | VISUAL_COPY_EXPECTATION | 1 | Broadened assertion to current designed missing-data copy without weakening missing-source requirement. | yes | yes |
| Nav smoke superadmin routes | AUTH_FIXTURE_ISSUE / SAFETY_SECURITY_EXPECTATION | 9 discovered after first triage | Updated route contract so `/system/readiness`, `/system/reports`, audit/evidence/scripts/build/coverage/migrations/AI tools/quarantine use superadmin fixture. | yes | yes |
| Screenshot overflow crawler timeout | TEST_CONTRACT_STABILIZATION | 1 discovered in full run | Added route auth fixtures, bounded settling, and realistic timeout for route matrix screenshots. | yes | yes |
| `/ai-predictions/model-state` mobile overflow | APP_REGRESSION | 1 discovered by crawler | Fixed admin header/top-right mobile wrapping and shared cockpit mobile overflow rules. | yes | yes |
| Raw live-gate enum leakage on legacy trader pages | APP_REGRESSION / VISUAL_COPY_EXPECTATION | discovered during triage | Translated direct `enabled_operator_approved` labels in alerts, derivatives, backtests, positions, market intelligence, and realtime signal panels. | yes | yes |

## Files Edited By Cluster

| Cluster | Files |
|---|---|
| Shared test auth and route contracts | `frontend/tests/e2e/_shared.ts`, `frontend/tests/e2e/helpers/auth.ts`, `frontend/tests/e2e/helpers/routeContracts.ts`, `frontend/tests/e2e/helpers/forbiddenStrings.ts` |
| Legacy spec updates | `frontend/tests/e2e/live_block_banner.spec.ts`, `frontend/tests/e2e/default_deny_inventory.spec.ts`, `frontend/tests/e2e/enterprise_trading_cockpit.spec.ts`, `frontend/tests/e2e/mission_control_readiness_banner.spec.ts`, `frontend/tests/e2e/operator_proof_dashboard_historical_30d.spec.ts`, `frontend/tests/e2e/public_status_redesign.spec.ts`, `frontend/tests/e2e/rbac_visibility.spec.ts`, `frontend/tests/e2e/stale_state_alerts.spec.ts`, `frontend/tests/e2e/trader_first_redesign.spec.ts`, `frontend/tests/e2e/nav_smoke.spec.ts`, `frontend/tests/e2e/market_detail_redesign.spec.ts`, `frontend/tests/e2e/redesign_screenshot_overflow.spec.ts` |
| App copy/overflow fixes | `frontend/src/pages/market/index.tsx`, `frontend/src/pages/alerts/index.tsx`, `frontend/src/pages/liquidation-bridge/index.tsx`, `frontend/src/pages/strategy-backtesting/index.tsx`, `frontend/src/pages/positions/index.tsx`, `frontend/src/pages/market-intelligence/index.tsx`, `frontend/src/pages/edgeRecoveryQualityPanel.tsx`, `frontend/src/components/realtimeSignals/RealtimeSignalVisibilityPanel.tsx`, `frontend/src/styles/admin.css`, `frontend/src/styles/components.css` |

## Final Verification

| Command | Result |
|---|---|
| `npm run typecheck` | PASS during Phase 14A; current rerun pending after later changes |
| `npm run build` | PASS during Phase 14A, with existing large chunk warning; current rerun pending after later changes |
| `npm run lint --if-present` | PASS during Phase 14A; current rerun pending after later changes |
| `../.venv/bin/python -m pytest backend/tests/integration/api/test_auth_rbac_and_status.py backend/tests/integration/api/v2/test_market_contract_routes.py` | PASS, 13 tests during Phase 14A; current rerun pending after later changes |
| `npx playwright test tests/e2e/nav_smoke.spec.ts --project=chromium --reporter=list` | PASS, 42 tests during Phase 14A; current rerun pending after later changes |
| `npx playwright test tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium --reporter=list -g "390x844"` | PASS, 1 test during Phase 14A; current rerun pending after later changes |
| `npx playwright test --project=chromium --reporter=list` | PASS, 196 tests during Phase 14A; current rerun pending after later changes |

## Remaining Blockers

- Phase 14 remains IN PROGRESS, not PASS, because production smoke, deployment verification, and full route-by-route visual/copy adjudication are still incomplete.
- `/trade` remains IN PROGRESS until realtime streams and production-validated paper submit/cancel services exist.
- `/market/:symbol` remains IN PROGRESS until realtime depth/trades/derivatives data are durable.
- Phase 15 remains BLOCKED.
- Real live trading remains BLOCKED.

---

## 2026-06-16 Current Full Chromium Rerun After Backend Recovery

Command:

```bash
cd v2/frontend && npx playwright test --project=chromium --reporter=list
```

Current result:

| Item | Result |
|---|---:|
| Current full Chromium result | 174 passed / 98 failed / 31 did not run |
| Backend pytest current result | 4111 passed / 4 skipped / 1 warning |
| Frontend typecheck current result | PASS |
| Frontend build current result | PASS, with existing large chunk warning |
| Real live trading | BLOCKED |
| `/trade` | IN PROGRESS |
| `/market/:symbol` | IN PROGRESS |
| Phase 15 | BLOCKED |

Current failure clusters:

| Cluster | Classification | Evidence examples | Required action | Fixed | Retested |
|---|---|---|---|---|---|
| Auth/RBAC route and fixture drift | AUTH_FIXTURE_ISSUE / APP_REGRESSION | `auth_rbac_redesign.spec.ts`; login `Email` label missing; unauthenticated `/admin` resolves to `/landing`; admin dashboard lacks `admin-main` | Inspect login labels, admin route guard, and test auth helper after `/admin/*` canonicalization | no | yes, failing full run |
| Mission-control legacy contract | OBSOLETE_LEGACY_EXPECTATION / DEAD_ROUTE_OR_REDIRECT | `enterprise_trading_cockpit.spec.ts`, `mission_control_readiness_banner.spec.ts` | Move expectations to canonical admin/system contract or protect/redirect old mission-control route | no | yes, failing full run |
| Public status contract drift | APP_REGRESSION / VISUAL_COPY_EXPECTATION | `public_status_redesign.spec.ts` public-safe, posture, freshness, forbidden terms | Fix `/status` rendering/copy or update obsolete assertions to current public-safe contract | no | yes, failing full run |
| ProChart and screenshot mobile overflow | VISUAL_COPY_EXPECTATION / APP_REGRESSION | `pro_chart_realtime_contract.spec.ts`, `redesign_screenshot_overflow.spec.ts` at `390x844` | Fix horizontal overflow and recapture screenshots | no | yes, failing full run |
| Runtime-alpha/trainer proof leakage | APP_REGRESSION / VISUAL_COPY_EXPECTATION | `runtime_alpha_dynamic_readiness_visibility.spec.ts` on trader routes | Hide/gate trainer/runtime-alpha proof panels from public/trader surfaces; keep admin diagnostics protected | no | yes, failing full run |
| Legacy route canonicalization drift | DEAD_ROUTE_OR_REDIRECT / OBSOLETE_LEGACY_EXPECTATION | `/system/*`, `/markets/symbols`, `/trade/paper`, model-state/replay/technical-analysis alias tests | Align tests and app redirects to canonical `/admin/*`, `/trade`, `/markets`, `/backtests`, `/research`, `/signals`, `/ai-predictions` | partial route cleanup | yes, failing full run |
| Trade terminal UI regressions | APP_REGRESSION / DATA_STATE_EXPECTATION / VISUAL_COPY_EXPECTATION | `trade_terminal_redesign.spec.ts` no-console, overflow, modules, copy, scoped equity | Fix app first; do not fake live/paper data | no | yes, failing full run |
| Trader nav cleanliness | APP_REGRESSION / VISUAL_COPY_EXPECTATION | `trader_nav_cleanliness.spec.ts` public/trader nav internal/admin terminology and route expectations | Remove/gate forbidden public/trader terms and align helper route contracts | no | yes, failing full run |
| Signal selector controls | APP_REGRESSION / DATA_STATE_EXPECTATION | `trader_signal_selector_controls.spec.ts` missing selectors/panels | Restore or gate expected selector panels with honest data states | no | yes, failing full run |
| Stale-state alerts | DATA_STATE_EXPECTATION | `stale_state_alerts.spec.ts` category/task-id and clean-feed empty states | Preserve stale/fallback warnings and repair expected alert state rendering | no | yes, failing full run |
| Symbols route contract | DEAD_ROUTE_OR_REDIRECT / APP_REGRESSION | `symbols_route_readonly_contract.spec.ts` | Redirect/protect `/markets/symbols` or render trader-safe symbol universe without overflow | no | yes, failing full run |

Current notes:

- Backend is no longer the primary blocker for the full Chromium run.
- The current run proves Phase 14A is not clean after route canonicalization and backend recovery.
- Do not reuse the historical `196 passed / 0 failed` result as current launch evidence.
- Phase 15, paper/read-only launch, `/trade`, `/market/:symbol`, and real live trading remain not accepted.
- Real live trading remains BLOCKED.

### 2026-06-16 Auth/RBAC Cluster Remediation

Current focused result:

| Command | Result |
|---|---|
| `cd v2/frontend && npm run typecheck` | PASS |
| `cd v2/frontend && npx playwright test tests/e2e/rbac_visibility.spec.ts tests/e2e/auth_rbac_redesign.spec.ts --project=chromium --reporter=list` | PASS, 20 tests |
| `cd v2/frontend && npm run build` | PASS, existing large chunk warning |

Cluster status:

- Auth/RBAC route and fixture drift: focused remediation complete.
- Login page now uses backend-authenticated form controls and no longer exposes local role selector copy.
- Admin shell ignores query/browser-storage role mutation and uses backend-confirmed roles.
- Admin and superadmin aliases `/admin/system` and `/admin/evidence` are protected.
- Full Chromium still requires rerun; do not mark Phase 14A clean from focused evidence alone.
- Real live trading remains BLOCKED.

## 2026-06-16 current full Chromium after backend/local-access patch

Command:

```bash
cd /home/wali/Desktop/AI\ BOT\ REBUILD/v2/frontend && npx playwright test --project=chromium --reporter=list
```

Result: `185 passed`, `87 failed`, `31 did not run` in `3.8m`.

Delta from previous current full Chromium result: improved from `174 passed / 98 failed / 31 did not run` to `185 passed / 87 failed / 31 did not run`.

Failure inventory by cluster:

| Cluster | Classification | Examples | Required action | Fixed | Retested |
| --- | --- | --- | --- | --- | --- |
| Auth/RBAC access-denied edge states | APP_REGRESSION or AUTH_FIXTURE_ISSUE | `auth_rbac_redesign.spec.ts` access-denied assertions; `rbac_visibility.spec.ts` public/viewer redirects | Reconcile AdminShell full-suite auth state and ensure denied users get explicit `access-denied` without protected content | no | yes, failing |
| Default-deny dangerous controls | SAFETY_SECURITY_EXPECTATION | `default_deny_inventory.spec.ts` risk/config/strategy/execution/live-readiness | Add/restore disabled dangerous-control panel evidence on admin pages without enabling actions | no | yes, failing |
| Legacy admin cockpit expectations | OBSOLETE_LEGACY_EXPECTATION or DEAD_ROUTE_OR_REDIRECT | `enterprise_trading_cockpit.spec.ts`, `mission_control_readiness_banner.spec.ts`, operator proof dashboard | Update tests/routes to canonical `/admin/*` contract or restore admin-only evidence views without trader leakage | no | yes, failing |
| Market detail timeout/overflow | APP_REGRESSION or DATA_STATE_EXPECTATION | `market_detail_redesign.spec.ts` canonical route/timeouts/sections/overflow | Investigate `/market/BTCUSDT` load/networkidle behavior and mobile overflow | no | yes, failing |
| Public status contract drift | VISUAL_COPY_EXPECTATION or DATA_STATE_EXPECTATION | `public_status_redesign.spec.ts` posture/freshness/forbidden terms | Align `/status` copy and public-safe fields to current contract | no | yes, failing |
| Runtime-alpha leakage and legacy system routes | APP_REGRESSION | `runtime_alpha_dynamic_readiness_visibility.spec.ts` trader routes and `/system/*` | Hide proof panels from trader routes and make legacy `/system/*` fail closed or redirect admin-only | no | yes, failing |
| Stale-state alerts | DATA_STATE_EXPECTATION | `stale_state_alerts.spec.ts` categories/task IDs/empty states | Restore designed alert stale/empty states without fake data | no | yes, failing |
| Symbols route contract | DEAD_ROUTE_OR_REDIRECT or APP_REGRESSION | `symbols_route_readonly_contract.spec.ts` | Redirect/protect/render `/markets/symbols` per AlphaForge contract | no | yes, failing |
| Trade terminal console/copy | VISUAL_COPY_EXPECTATION or APP_REGRESSION | `trade_terminal_redesign.spec.ts` console/copy/raw enum checks | Remove forbidden trader copy/raw enums and console errors | no | yes, failing |
| Trader-first overflow | VISUAL_COPY_EXPECTATION or APP_REGRESSION | `trader_first_redesign.spec.ts` route overflow checks | Fix shell/page overflow across trader routes | no | yes, failing |
| Trader nav cleanliness and legacy redirects | OBSOLETE_LEGACY_EXPECTATION or APP_REGRESSION | `trader_nav_cleanliness.spec.ts` terminology/redirect/admin alias failures | Reconcile routeContracts helper and app redirects; fix trader/admin terminology leaks | no | yes, failing |
| Trader signal selector panels | APP_REGRESSION or DATA_STATE_EXPECTATION | `trader_signal_selector_controls.spec.ts` matrix/active signal panels | Restore expected trader-safe prediction/signal panels or update obsolete selectors to current contract | no | yes, failing |
| Mobile screenshot overflow | VISUAL_COPY_EXPECTATION | `redesign_screenshot_overflow.spec.ts` at `390x844` | Inspect generated screenshot/route overflow failure and fix mobile layout | no | yes, failing |

Safety status: real live trading remains BLOCKED; no live submit/cancel/leverage/margin/live-gate mutation was added.

## 2026-06-16 focused auth/RBAC remediation after full Chromium 87-failure run

Command:

```bash
cd /home/wali/Desktop/AI\ BOT\ REBUILD/v2/frontend && npm run typecheck
cd /home/wali/Desktop/AI\ BOT\ REBUILD/v2/frontend && npx playwright test tests/e2e/auth_rbac_redesign.spec.ts tests/e2e/rbac_visibility.spec.ts --project=chromium --reporter=list
```

Result:

- Frontend typecheck passed.
- Focused auth/RBAC Playwright passed: `20 passed in 6.8s`.

Fixes:

- `AdminShell` no longer maps canonical `/admin/system` and `/admin/evidence` back to legacy route IDs for RBAC lookup. It checks the actual canonical path so trader/admin downgrade cases render `access-denied` instead of protected children.
- Legacy `/admin/mission-control` now redirects to protected `/admin/system` instead of falling through to public `/landing`.
- Legacy `/admin/risk-control` now redirects to protected `/admin/risk` instead of falling through to public `/landing`.

Cluster status:

| Cluster | Previous current status | Current focused status | Full-suite status |
| --- | --- | --- | --- |
| Auth/RBAC access-denied edge states | failing in full Chromium | `20 passed` focused | pending full rerun |

Safety status: real live trading remains BLOCKED; no live submit/cancel/leverage/margin/live-gate mutation was added.
