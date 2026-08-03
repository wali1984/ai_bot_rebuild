# Phase 13A Visual Review

Generated: 2026-06-13

Scope: targeted visual, copy, responsive, and evidence-gate remediation for public and trader surfaces only.

This is not a launch pass. `/trade` and `/market/:symbol` remain `IN PROGRESS`; Phase 15 and real live trading remain `BLOCKED`.

## Summary

| Area | Result | Evidence |
|---|---|---|
| Screenshot matrix | EXISTS | 28 Phase 13A target screenshots captured in `screenshots/final` at 1920x1080, 1440x900, 768x1024, and 390x844. |
| Human visual review | PERFORMED FOR TARGET ROUTES | Contact sheets were reviewed for `/`, `/login`, `/status`, `/dashboard`, `/markets`, `/market/BTCUSDT`, and `/trade`. Full route-by-route review remains incomplete. |
| Copy cleanup | HISTORICAL FOCUSED PASS | Phase 13A Playwright gate blocked forbidden public/trader strings, snake_case, backend enums, and raw JSON in main UI. Current rerun is pending after later changes. |
| Responsive/overflow | HISTORICAL FOCUSED PASS | `phase_13a_visual_gate.spec.ts` passed the Phase 13A target route/viewport checks. Current rerun is pending after later changes. |
| Full suite | HISTORICAL PHASE13A FAIL; PHASE14A LATER PASSED | Phase 13A full Chromium result was 120 passed and 71 failed. Phase 14A later stabilized the Chromium suite to 196 passed, but current validation is pending after subsequent changes. |

## Defects Found And Fixed

| Defect | Route/component | Fix |
|---|---|---|
| Default light theme made terminal surfaces look inconsistent and less professional. | `ThemeToggle` | Defaulted unknown/no stored theme to dark. |
| Global live banner used strong live/runtime wording and aggressive armed styling. | `LiveBlockBanner`, `PublicShell` | Reworded to paper/read-only mode and live-trading-disabled copy. |
| `/status` rendered backend `source_pending` as visible `Source Pending`. | `pages/public-status/index.tsx` | Mapped pending/unavailable states to `Data source unavailable`. |
| `/dashboard` chart exposed `payload`, source keys, and backend chart source enums in the main UI. | `V2ProfessionalMarketChart`, `AdminShell` | Replaced with source/freshness labels and moved raw detail to collapsed technical evidence. |
| `/markets` authenticated screener still rendered unavailable-source placeholders in table cells. | `pages/markets/index.tsx` | Added local public/trader formatter wrappers that render `Data source unavailable`. |
| `/` had horizontal overflow at 390px. | `components.css` | Added mobile containment rules for public shell, banner, landing CTA, and route cards. |
| `/market/BTCUSDT` still included public-facing candidate publisher/debug copy risk. | `pages/market/index.tsx` | Removed candidate publisher panel and cleaned unavailable-source strings. |

## Screenshot Review Matrix

| Route | Viewport | Screenshot | Result | Review notes | Action items |
|---|---|---|---|---|---|
| `/` | 1920x1080 | `screenshots/final/home-1920x1080.png` | FIXED | Dark branded hero, market preview, signal preview, and paper/read-only posture are coherent. | Continue deeper route-by-route launch review. |
| `/` | 1440x900 | `screenshots/final/home-1440x900.png` | FIXED | Layout remains centered and readable. | None for Phase 13A. |
| `/` | 768x1024 | `screenshots/final/home-768x1024.png` | FIXED | Tablet layout stacks cleanly. | None for Phase 13A. |
| `/` | 390x844 | `screenshots/final/home-390x844.png` | FIXED | Mobile no longer has body horizontal overflow; page is long but usable. | Revisit mobile content density before launch. |
| `/login` | 1920x1080 | `screenshots/final/login-1920x1080.png` | PASS | Professional auth card, no role selector, no fake admin shortcut. | Production session hardening still required. |
| `/login` | 1440x900 | `screenshots/final/login-1440x900.png` | PASS | Auth layout remains balanced. | None for Phase 13A. |
| `/login` | 768x1024 | `screenshots/final/login-768x1024.png` | PASS | Tablet stack is readable. | None for Phase 13A. |
| `/login` | 390x844 | `screenshots/final/login-390x844.png` | PASS | Mobile auth controls are usable and contained. | None for Phase 13A. |
| `/status` | 1920x1080 | `screenshots/final/status-1920x1080.png` | FIXED | Public-safe availability cards, paper mode, live disabled, and incidents are visible. | Production monitoring source still pending. |
| `/status` | 1440x900 | `screenshots/final/status-1440x900.png` | FIXED | Layout remains clean. | None for Phase 13A. |
| `/status` | 768x1024 | `screenshots/final/status-768x1024.png` | FIXED | Tablet stack is clear. | None for Phase 13A. |
| `/status` | 390x844 | `screenshots/final/status-390x844.png` | FIXED | Mobile status cards are contained; no debug JSON or internal logs. | None for Phase 13A. |
| `/dashboard` | 1920x1080 | `screenshots/final/dashboard-1920x1080.png` | FIXED | Authenticated trader dashboard shows KPI/chart/signal/positions without chart payload jargon. | Broader trader surfaces still need full review. |
| `/dashboard` | 1440x900 | `screenshots/final/dashboard-1440x900.png` | FIXED | Desktop layout remains coherent. | None for Phase 13A. |
| `/dashboard` | 768x1024 | `screenshots/final/dashboard-768x1024.png` | FIXED | Tablet is stacked and usable. | Mobile density review remains. |
| `/dashboard` | 390x844 | `screenshots/final/dashboard-390x844.png` | FIXED | No horizontal overflow; page is very long and dense. | Reduce mobile density in a later pass. |
| `/markets` | 1920x1080 | `screenshots/final/markets-1920x1080.png` | FIXED | Authenticated screener renders professional controls and CoinAnk-style columns with clean missing-data copy. | Full-page capture is tall due many rows; density tuning remains. |
| `/markets` | 1440x900 | `screenshots/final/markets-1440x900.png` | FIXED | No forbidden unavailable-source placeholder copy remains in main UI. | Continue column density review. |
| `/markets` | 768x1024 | `screenshots/final/markets-768x1024.png` | FIXED | Mobile/tablet cards avoid broken wide table behavior. | Continue readability tuning. |
| `/markets` | 390x844 | `screenshots/final/markets-390x844.png` | FIXED | No horizontal overflow; rows are cardized but long. | Mobile density remains an improvement target. |
| `/market/BTCUSDT` | 1920x1080 | `screenshots/final/market-detail-1920x1080.png` | FIXED | Symbol header, chart, microstructure, derivatives, signal, and evidence sections are present. | Realtime depth/trades/derivatives still missing. |
| `/market/BTCUSDT` | 1440x900 | `screenshots/final/market-detail-1440x900.png` | FIXED | Desktop page is coherent and public-safe. | None for Phase 13A. |
| `/market/BTCUSDT` | 768x1024 | `screenshots/final/market-detail-768x1024.png` | FIXED | Tablet layout stacks without wide table overflow. | None for Phase 13A. |
| `/market/BTCUSDT` | 390x844 | `screenshots/final/market-detail-390x844.png` | FIXED | Mobile has no uncontrolled horizontal scroll, but is dense. | Realtime data and mobile density remain blockers. |
| `/trade` | 1920x1080 | `screenshots/final/trade-1920x1080.png` | FIXED | Chart-first terminal, order book, depth/tape, paper ticket, and tabs appear coherent. | Realtime streams and local paper submit/cancel exists; production validation and policy approval remain pending. |
| `/trade` | 1440x900 | `screenshots/final/trade-1440x900.png` | FIXED | Desktop terminal remains professional and read-only/paper state is obvious. | None for Phase 13A. |
| `/trade` | 768x1024 | `screenshots/final/trade-768x1024.png` | FIXED | Tablet modules stack without page overflow. | Continue density review. |
| `/trade` | 390x844 | `screenshots/final/trade-390x844.png` | FIXED | Mobile no longer renders as a broken wide table; terminal remains long/dense. | Realtime/paper execution blockers remain. |

## Validation

| Command | Result |
|---|---|
| `npm run typecheck` | PASS during Phase 13A; current rerun pending after later changes |
| `npm run build` | PASS during Phase 13A, with existing large chunk warning; current rerun pending after later changes |
| `npm run lint --if-present` | PASS/no lint output during Phase 13A; current rerun pending after later changes |
| `../.venv/bin/python -m pytest backend/tests/integration/api/test_auth_rbac_and_status.py backend/tests/integration/api/v2/test_market_contract_routes.py` | PASS, 13 tests during Phase 13A; current rerun pending after later changes |
| `npx playwright test tests/e2e/phase_13a_visual_gate.spec.ts --project=chromium` | PASS, 29 tests during Phase 13A; current rerun pending after later changes |
| `npx playwright test --project=chromium` | HISTORICAL PHASE13A FAIL, 120 passed and 71 failed; Phase 14A later passed 196 tests; current rerun pending after later changes |

## Remaining Blockers

| Blocker | Status |
|---|---|
| Full Phase 13 triple-check | IN PROGRESS, not PASS. Target public/trader Phase 13A gate passed, but full route/card/string/table/chart review remains. |
| Full Playwright suite | Historical Phase 13A blocker was resolved in Phase 14A with 196 passing Chromium tests; current full-suite rerun remains pending after later changes. |
| `/trade` completion | IN PROGRESS because realtime streams and production validation and policy approval for local paper submit/cancel are missing. |
| `/market/:symbol` completion | IN PROGRESS because realtime depth/trades/derivatives data are missing. |
| Phase 15 | BLOCKED pending auth hardening, production smoke, deployment, HTTPS, and full route checks. |
| Real live trading | BLOCKED. No live order submit/cancel/leverage/margin/live-gate mutation was added. |
