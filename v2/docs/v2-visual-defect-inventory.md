# V2 Visual Defect Inventory

Date: 2026-06-15
Status: Partial visual evidence only.

## Captured checks

| Check | Result | Notes |
| --- | --- | --- |
| `redesign_screenshot_overflow.spec.ts` | 4/4 passed | Current route screenshot crawler/body overflow check passed at 1920x1080, 1440x900, 768x1024, 390x844. This is not the full all-route screenshot matrix. |
| Focused trader route cleanliness | 35/35 passed | Confirms selected trader/public routes avoid known internal terms and route aliases. |
| Full visual gate | BLOCKED | Full Chromium suite cannot be accepted due Playwright/browser environment failures and incomplete route/data coverage. |

## Known visual/product defects to inventory in full matrix

- Some public/trader routes still show missing/unavailable modules as normal page content.
- `/system/*` admin color/language and route structure still exists; canonical target is `/admin/*`.
- Some pages remain dense card/table layouts rather than premium chart-first or CoinAnk-style analytics surfaces.
- Full mobile card replacement for every table is not proven.
- Full screenshot inventory for all public/trader/admin/superadmin routes is missing.
- Source/freshness metadata is not visually present on every metric/card/table cell.

## Screenshot matrix requirement

Required viewports: 1920x1080, 1440x900, 768x1024, 390x844 for every public/trader/admin/superadmin route. Current evidence is partial and cannot support launch.

---

## 2026-06-15 visual/test evidence from local 5173

Full Chromium route screenshot crawler evidence:

| Viewport | Result | Notes |
| --- | --- | --- |
| 1920x1080 | PASSED crawler | Broad body-overflow crawler passed, but route-specific visual gate still failed on public status. |
| 1440x900 | PASSED crawler | Broad crawler passed; ProChart route-specific overflow test failed at this viewport. |
| 768x1024 | PASSED crawler | Broad crawler passed. |
| 390x844 | PASSED crawler | Broad crawler passed; ProChart route-specific overflow test failed at this viewport. |

Confirmed visual/product defects still open:

- Public status page fails visual/content gate at 1920x1080 and public-safe status tests.
- ProChart overflows in route-specific checks at 1440x900 and 390x844.
- Trader pages still fail runtime-alpha/trainer proof-panel hiding tests, meaning admin/system proof content is not fully separated from trader surfaces.
- Mission Control/operator proof legacy surfaces do not match current test expectations and must be redesigned/migrated under canonical admin ownership.
- Full human visual review matrix for every route at all four viewports is still missing.

## 2026-06-15 public landing and trader dashboard visual remediation

Status: PARTIAL REMEDIATION, not launch-ready.

Updated surfaces:
- `/` and `/landing`: replaced the active operator-style public landing with the styled V2 market-intelligence landing. Removed Mission Control/admin CTAs, raw IDs, and public backend path clutter. Added BTC/ETH/SOL market cards, realtime health, source/freshness language, AI signal preview, and paper/live-block posture.
- `/dashboard`: replaced the inline placeholder dashboard with a trader-facing dashboard component using typed market, candle, signal, portfolio, position, and account readiness envelopes. Added six KPI max, BTC 5m native candlestick strip, current signal card, market pulse, paper positions panel, and source/freshness badges.

Validation evidence:
- `npm run typecheck` passed from `v2/frontend` after both edits.
- Focused public landing/nav Playwright passed: `public_landing_data_health.spec.ts` and selected `trader_nav_cleanliness.spec.ts`, 4 passed.
- Focused dashboard/trader shell Playwright passed: selected `runtime_alpha_dynamic_readiness_visibility.spec.ts`, `trader_first_redesign.spec.ts`, and `trader_nav_cleanliness.spec.ts`, 3 passed.

Remaining visual/product blockers:
- Full Chromium suite is still not green.
- Admin dangerous-control inventory, Mission Control readiness, operator-proof dashboard, legacy alias redirects, symbols route contract, and screenshot overflow failures remain unresolved.
- This entry does not mark Phase 13, Phase 14, Phase 15, or launch readiness as passed.

## 2026-06-15 focused visual gate fixes

- Public status duplicate text fixed so `Platform availability` and `Market stream` resolve to single visible route-module labels.
- Mission Control duplicate chart test IDs removed; one primary `cockpit-charting-market-data` module remains on the first-screen cockpit.
- Mission Control now exposes the expected admin evidence strip: `AI BOT V2 Mission Control`, `LIVE TRADING: blocked_human_only`, read-only topbar, market pulse, decision explainability, exchange manager, position quarantine, and live readiness blockers.
- Validation: focused Chromium route module gate passed 4/4 on port 5173.

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

