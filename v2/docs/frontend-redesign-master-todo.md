# Frontend Redesign Master Todo

Generated: 2026-06-13

Scope: AlphaForge public/trader/admin redesign and paper/read-only launch hardening. This is not a completion report. No route, component, or phase is marked `PASS` until screenshot, data/security, copy, and automated checks are all satisfied.

## Master Status

Ongoing readiness monitoring is recorded in `docs/product-readiness-monitor.md`. That monitor is authoritative for preserving blocked/in-progress status between implementation passes and for separating historical PASS evidence from current pending reruns.

| Phase | Status | Routes touched | Files changed | Data sources used | Screenshots captured | Tests added/run | Remaining blockers |
|---:|---|---|---|---|---|---|---|
| 0 | IN PROGRESS | all routes | docs + Playwright QA spec | route registry, product navigation | before/final captured: 84 each | screenshot/overflow spec run twice | screenshot review and defect remediation pending |
| 1 | IN PROGRESS | global shell | style layers | n/a | pending | build run | component extraction incomplete |
| 2 | IN PROGRESS | public/trader/system nav | shell/nav files | route metadata | pending | nav smoke existing | `/admin/*` canonical migration still partial |
| 3 | IN PROGRESS | login/admin routes | backend auth/RBAC, route guards, auth tests, safe exchange-account metadata, credential vault readiness metadata, admin audit readiness metadata with retention-policy metadata, production admin audit writes fail closed when retention-day metadata is missing, configurable session TTL, configured token revocation, protected admin user create/update/delete plus activation/reset with secret-free audit events, production fail-closed local auth-user, revocation-store, and admin-audit store access, explicit SQLAlchemy auth-store, revocation-store, and admin-audit adapter seams | `/api/auth/*`, `/api/admin/users`, `/api/admin/credential-status`, `/api/admin/users/{user_id}/activation` | login/admin auth gate/admin dashboard captured | backend auth tests PASS previously; latest auth/admin audit/auth-store/revocation-store/admin-audit adapter changes pending run | production DB migrations/provisioning, durable session hardening, revocation retention/rotation policy, durable credential vault integration, environment-backed admin step-up partial evidence, MFA/step-up, durable admin audit retention enforcement/policy, HTTPS smoke, and current validation remain missing |
| 4 | IN PROGRESS | data-heavy routes | safe `/api/v2` contracts, backend/browser-side read-only public market stream display, local stream-status alert state, local stream alert history, production stream alerting artifact metadata, production stream alerting smoke runner, outbound alert webhook notifier/active-only alert delivery status, authenticated local paper `/api/v2/alerts` CRUD contract with delivery disabled, local trader account repository with paper-account uniqueness rejection and readiness metadata, read-only multi-trader account-scope smoke runner, multi-trader account-scope smoke artifact metadata, explicit SQLAlchemy trader account repository adapter seam, trader context, typed chart polling, read-only Binance public market data | Binance public market API/stream display + safe stream fallback + scoped local account repository + static fallback + structured unavailable states + backend trader context | pending | frontend API contract spec PASS previously; backend pytest PASS previously; current stream/market/account/alerts/credential-status/backend credential binding/exchange-account read-only normalization/local repository readiness metadata/multi-trader account-scope smoke runner/multi-trader account-scope smoke artifact metadata/SQLAlchemy trader account repository adapter/credential vault readiness metadata/repository-credential docs guard evidence key/account-scope ProChart docs guard evidence key/phase blocker map repository/credential boundary evidence key/frontend scoped paper-account display/trader account binding copy/trade typed activity tabs/local paper fill writer/local paper audit events/ProChart realtime timestamp normalization/overlay timestamp normalization/focused ProChart spec/stream symbol-timeframe filter/typed candle envelope filter/docs guard changes pending rerun | Stream validation/telemetry, production alerting/dashboard current validation, production alert delivery/audit repositories, derivatives streams, production DB migrations/provisioning, production repository writer validation, and account-scoped portfolio/execution/signal sources missing |
| 5 | IN PROGRESS | `/`, `/status`, `/status-simple`, `/login` | public-safe status/login/home copy with Market stream freshness | `/api/v2/status`, safe frontend fallback, sanitized stream telemetry summary, production stream alerting artifact metadata, production stream alerting smoke runner | login/status screenshots captured; `/status-simple` current review pending | public status Playwright PASS previously; auth Playwright PASS previously; current status-health and `/status-simple` route changes pending rerun | human visual review, production alerting/dashboard current validation, incident source, `/status-simple` public route smoke, and production smoke remain pending |
| 6 | IN PROGRESS | `/dashboard` | dashboard route | typed V2 market overview, scoped paper account, AI, market aggregate fallback | pending | build run | screenshot/copy QA and current validation rerun pending |
| 7 | IN PROGRESS | `/markets`, `/market/:symbol` | market detail route, CSS, hook, tests | typed `/api/v2` contracts + V2 market overview public 24h ticker rows + backend/browser-side public stream display + Binance public market API + static fallback states | `market-detail-1920x1080.png`, `market-detail-1440x900.png`, `market-detail-768x1024.png`, `market-detail-390x844.png` | market detail spec PASS previously; screenshot overflow PASS previously; current stream/API/ProChart/V2 overview/docs guard changes pending rerun | Stream validation/telemetry and derivative analytics still missing |
| 8 | IN PROGRESS | `/trade` | trade terminal hook, market stream hook, typed chart polling, ProChart realtime merge hardening, scoped paper-account display, typed activity tabs, trader account strip, safe credential-status copy with credential permission-probe artifact metadata, signed-read validation artifact metadata, secret-redaction smoke artifact metadata, and safe secret-redaction smoke runner, paper ticket preview, paper open-order fill/cancel UI guarded by explicit local repository/audit evidence, API clients, tests | typed `/api/v2` contracts + backend/browser-side public stream display + backend trader context + Binance public market API + account fallback withholding + scoped account display + typed activity tabs + safe credential status + explicit partial local paper execution policy metadata + production paper actions fail closed + local paper fill writer + hash-chained local paper audit events + durable paper audit policy artifact metadata; direct legacy operator terminal, paper runtime, portfolio-state, live-gate runtime, and shared symbol-data legacy terminal fallbacks removed from public/trader terminal state; open-order local paper actions require explicit local repository/audit evidence | `trade-1920x1080.png`, `trade-1440x900.png`, `trade-390x844.png`, `trade-768x1024.png` | build/typecheck/trade spec/screenshot overflow PASS previously; current stream/account/market/credential-status/exchange-account read-only normalization/signed-read account/credential permission-probe artifact/signed-read validation artifact/secret-redaction smoke artifact/safe secret-redaction smoke runner/local paper-order/public-trader scoped account cleanup/trade typed activity tabs/trade terminal legacy runtime removal/symbol-data legacy fallback removal/open-order explicit local repository action guard/paper execution policy metadata/production paper actions fail closed/local paper fill writer/local paper audit events/durable paper audit policy artifact metadata/ProChart realtime timestamp normalization/overlay timestamp normalization/focused ProChart spec/stream symbol-timeframe filter/typed candle envelope filter/derivatives/docs guard changes pending rerun | Stream validation/telemetry, durable trader-scoped repositories, production credential vault hardening, production permission probe, production secret-redaction smoke execution, signed read-only account validation, and local paper submit/cancel/fill production validation remain pending; full product launch still blocked |
| 9 | IN PROGRESS | `/derivatives` | partial existing route | derivative payloads | pending | none this pass | heatmaps/maps/exchange comparison incomplete |
| 10 | IN PROGRESS | `/signals`, `/ai-predictions` | existing routes | signal/prediction payloads | pending | none this pass | plain-English signal/AI cleanup incomplete |
| 11 | IN PROGRESS | portfolio/backtests/research/alerts | `/portfolio`, `/portfolio/executions`, `/portfolio/history` scoped paper views; `/backtests` and `/research` read-only missing-state summaries; duplicate subroute redirects; `/alerts` authenticated local paper CRUD contract | typed account/activity contracts, typed local paper alert contract, market/signal context | pending | trader nav/API contract specs updated; pending rerun | durable repositories, production alert delivery/audit, screenshots, and workflow UX incomplete |
| 12 | IN PROGRESS | `/system/*` | shell/nav/style files | system payloads | pending | build run | confirmation/reason/audit controls incomplete |
| 13 | IN PROGRESS | `/`, `/login`, `/status`, `/dashboard`, `/markets`, `/market/:symbol`, `/trade` | Phase 13A review doc, copy/style fixes, visual gate | public/trader data with fallback/missing states | Phase 13A target matrix captured: 28 screenshots | `phase_13a_visual_gate.spec.ts` PASS previously; pending rerun after current stream/public status health/public market API/trader account-scope proof metadata/strict data match/partial-scope fail-closed/credential-status/exchange-account read-only normalization/public-trader scoped account cleanup/trade typed activity tabs/ProChart realtime timestamp normalization/overlay timestamp normalization/focused ProChart spec/stream symbol-timeframe filter/typed candle envelope filter/docs guard changes | full screenshot-matrix human review, admin visual review, and route-by-route visual approval remain pending |
| 14 | IN PROGRESS | all routes | Playwright QA specs + helper contracts | browser route crawl + mocked auth/API states | before/final captured: 84 each plus Phase 13A/login/status/admin captures | build/typecheck/lint/backend pytest/focused Playwright suites/full Chromium suite PASS previously; current stream/public status health/public market API/trader account-scope proof metadata/strict data match/partial-scope fail-closed/credential-status/exchange-account read-only normalization/local repository readiness metadata/credential vault readiness metadata/repository-credential docs guard evidence key/account-scope ProChart docs guard evidence key/phase blocker map repository/credential boundary evidence key/public-trader scoped account cleanup/trade typed activity tabs/ProChart realtime timestamp normalization/overlay timestamp normalization/focused ProChart spec/stream symbol-timeframe filter/typed candle envelope filter/docs guard changes pending rerun | production smoke, deployment verification, current rerun, and remaining route-specific visual/copy QA remain pending |
| 15 | BLOCKED | deploy target | docs | deployment/runtime checks | pending | build run | real auth/API/smoke/HTTPS checks pending |

## Immediate Execution Queue

| Priority | Task | Status | Notes |
|---:|---|---|---|
| 1 | Create required redesign docs | IN PROGRESS | This document plus acceptance, route, string, defect, API, and launch docs. |
| 2 | Add screenshot crawler and overflow test | PASS | `redesign_screenshot_overflow.spec.ts` added and run for public/trader routes at required viewport widths. |
| 3 | Run frontend build | IN PROGRESS | Prior `npm run build` passed after Phase 4A/7A changes; current stream/public status health/local stream alert history/outbound alert webhook notifier/active-only alert delivery/public market API/trader account-scope proof metadata/strict data match/partial-scope fail-closed/credential-status/auth production-secret strength/rotation, issuer/audience, session TTL, password policy, cookie SameSite, and revocation-store required/error fail-closed/session security status/refresh token rotation/password-change session revocation/session-version invalidation/exchange-account read-only normalization/local paper-account uniqueness/local repository readiness metadata/credential vault readiness metadata/repository-credential docs guard evidence key/account-scope ProChart docs guard evidence key/phase blocker map repository/credential boundary evidence key/frontend scoped paper-account display/trader account binding copy/trade typed activity tabs/ProChart realtime timestamp normalization/overlay timestamp normalization/focused ProChart spec/stream symbol-timeframe filter/typed candle envelope filter/docs guard changes are pending rerun. |
| 4 | Run screenshot/overflow Playwright subset | IN PROGRESS | Prior run produced 84 files in `v2/screenshots/before` and 84 files in `v2/screenshots/final`; current stream/public status health/public market API/trader account-scope proof metadata/strict data match/partial-scope fail-closed/credential-status/exchange-account read-only normalization/local repository readiness metadata/credential vault readiness metadata/repository-credential docs guard evidence key/account-scope ProChart docs guard evidence key/phase blocker map repository/credential boundary evidence key/frontend scoped paper-account display/trader account binding copy/trade typed activity tabs/ProChart realtime timestamp normalization/overlay timestamp normalization/focused ProChart spec/stream symbol-timeframe filter/typed candle envelope filter/docs guard changes are pending rerun. |
| 5 | Clean `/trade` trader-facing raw/internal copy | IN PROGRESS | Terminal copy replaced with friendly paper/read-only states; visible-string spec added. |
| 6 | Clean `/market/:symbol` internal/debug panels | IN PROGRESS | Public read-only market detail page added and dedicated Playwright spec passed; remaining data blockers are depth/trades/derivatives streams. |
| 7 | Convert `/status` and `/status-simple` to public-safe status pages | IN PROGRESS | Public-safe `/api/v2/status`, Market stream freshness, production stream alerting artifact metadata, production stream alerting smoke runner, responsive status page, and unshadowed simple public status route added; production alerting/dashboard current validation, incident source, `/status-simple` public route smoke, and human visual review pending. |
| 8 | Replace fake auth with backend-enforced auth | IN PROGRESS | Backend auth/RBAC, frontend route guards, and tests added; production hardening and full admin coverage remain blockers. |
| 9 | Phase 13A public/trader visual remediation | IN PROGRESS | Targeted public/trader screenshots exist and focused visual gate passes; full Phase 13 remains incomplete until every route is visually adjudicated. |

## Non-Negotiable Blocks

| Block | Reason |
|---|---|
| Real live trading | Live execution remains blocked until backend auth, RBAC, audit, environment-backed admin step-up partial evidence, MFA/step-up, and live-gate controls pass. |
| Production-ready claim | Blocked until every visible route passes visual, data/security, and copy QA plus automated build/e2e. |
| Fake data | Any static payload fallback must remain labeled with freshness/source state. |
| Multi-trader completion | Account-sensitive contracts now use local scoped repository state or withhold unscoped fallback data for signed-in traders; local paper order and fill-generated position rows now carry row-level trader/paper-account scope. Completion still requires production account-scoped database repositories, writer services, durable backend-only credential vault integration, and trader-specific portfolio/execution/signal data. |
| Operator/debug content in trader portal | Must be removed, renamed, or moved to protected system/superadmin pages. |

## Latest Phase 9/14 note

- Market derivatives contract pass is IN PROGRESS: `/api/v2/market/{symbol}/derivatives` and `/market/:symbol` consumption were added for read-only funding/OI snapshots with explicit missing states. Current validation and full realtime derivatives coverage remain pending.

## Latest Phase 4/8 note

- Trader-scoped signed read-only account pass is IN PROGRESS: `/api/v2/account/exchange-readonly`, `/trade` display, backend-only env/local vault-file credential binding, credential permission-probe artifact metadata, signed-read validation artifact metadata, secret-redaction smoke artifact metadata, and safe secret-redaction smoke runner were added. Validation, production permission probe, production secret-redaction smoke execution, signed read-only account adapter validation, durable credential-vault hardening, persistence, screenshots, and full suite rerun remain pending.

## Latest multi-trader isolation note

- Trader account repository strict matching is IN PROGRESS: local paper repository operations now match both `trader_id` and `paper_account_id` when available. Protected admin repository status also exposes local readiness metadata, but validation and production persistence remain pending.
- Paper execution policy status is IN PROGRESS: paper preview/stage/cancel/fill contracts expose explicit partial local policy metadata, disabled live transport, disabled exchange mutation, disabled live order cancel, disabled leverage/margin/live-gate mutation, production validation pending, production paper actions fail closed, and missing production paper/audit fields.
- Local paper fill writer is IN PROGRESS: authenticated manual fills can write scoped local paper execution/position rows and hash-chained local paper audit events without exchange mutation, but production validation, audit hardening, durable persistence, screenshots, and full suite rerun remain pending.

## 2026-06-14 ProChart follow-up

- [x] Add read-only typed indicator derivation for EMA/Bollinger from public closed klines.
- [ ] Rerun backend/frontend/Playwright validation after ProChart indicator change.
- [ ] Capture/review `/chart/:symbol` screenshots at required Phase 13 viewports.
- [ ] Add typed current prediction overlay before enabling AI target controls.
- [ ] Keep real live trading blocked.

## 2026-06-14 continuation todo - ProChart and multi-trader scope

- [x] Prefer backend-authenticated trader watchlist in ProChart favorites.
- [x] Prefer typed `/api/v2/market/overview` for ProChart symbol universe.
- [x] Render fresh typed EMA/Bollinger/AI-target overlay series in ProChart instead of only enabling controls.
- [x] Display backend-confirmed account binding/read-only exchange posture on `/chart/:symbol`.
- [x] Remove operator runtime payload dependency from the shared public/trader shell ticker.
- [ ] Rerun typecheck, build, backend pytest, focused Playwright, full Chromium, and screenshots.
- [ ] Produce production stream validation/alerting evidence.
- [ ] Produce durable trader repository/writer validation and smoke evidence.
- [ ] Verify paper submit/cancel/fill production service before enabling any submit path.
- [ ] Keep real live trading blocked until a separately approved live-readiness gate is complete.

## 2026-06-14 account settings monitoring continuation

- [x] Add `/account-settings` to readiness monitoring as an `IN_PROGRESS` trader account/preferences route.
- [ ] Validate `/account-settings` screenshots, copy, responsive behavior, auth/session hardening, durable trader repository writes, and backend-only credential vault binding.

## 2026-06-14 account settings validation queue note

- [x] Add focused `/account-settings` copy-safety test coverage to the trader navigation cleanliness spec.
- [ ] Rerun `npx playwright test tests/e2e/trader_nav_cleanliness.spec.ts --project=chromium` and the full validation queue after the latest account settings changes.

## 2026-06-14 ProChart navigation continuation

- [x] Expose `/chart/BTCUSDT` from the public/trader shell navigation as `Chart`.
- [ ] Validate ProChart realtime behavior, source/freshness states, responsive screenshots, and full current test queue.

## 2026-06-14 - Trader account access copy cleanup

- Public/trader account access copy no longer uses backend-oriented credential tooltip wording in the main terminal shell.
- Pending: rerun focused trader-nav, trade terminal, ProChart, screenshot, typecheck, build, and backend pytest validation.

## 2026-06-14 - Dashboard compact performance panel cleanup

- Trader-facing `/dashboard` compact performance panel no longer exposes live-margin/trainer/hedging internals.
- Pending: dashboard screenshots, Phase 13 visual review rerun, focused Playwright, typecheck, build, and full validation queue.

## 2026-06-14 - Website contract validation queue update

- Pending validation now includes backend website page contract unit tests after `/account-settings` and `/chart/:symbol` were added to the website contract registry.
- No validation was run in this pass.

## 2026-06-14 ProChart route resize/status-strip continuation

- [x] Make `/chart/:symbol` resize-aware so the chart canvas updates after viewport changes.
- [x] Add page-level read-only realtime/source posture copy for Binance public stream plus market API fallback, trader scope, and live trading disabled.
- [ ] Rerun ProChart focused Playwright, typecheck, build, screenshot/overflow, and full Chromium validation.
- [ ] Capture/review `/chart/:symbol` screenshots at Phase 13 viewports.
- [ ] Keep `/chart/:symbol`, `/trade`, `/market/:symbol`, Phase 13, Phase 14, Phase 15, paper/read-only launch, and real live trading in their current incomplete/blocked status until evidence closes the blockers.
