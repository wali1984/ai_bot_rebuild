# UI Defect Log After Current Redesign Pass

Generated: 2026-06-13

This is an active defect log, not a pass report.

## Open Trader-Facing Defects

| Area | Severity | Status | Evidence/notes |
|---|---|---|---|
| `/trade` order ticket | High | IN PROGRESS | Paper-only ticket now calls preview-only `/api/v2/orders/preview` for valid inputs; local paper submit/cancel/fill endpoints and local paper audit-event rows exist and remain paper-only; production validation, durable audit policy, and policy approval remain pending. |
| `/trade` layout | Medium | IN PROGRESS | New chart-first terminal, right trading column, bottom tabs, and mobile segmented modules implemented; Phase 8 screenshots reviewed, endpoint gaps remain. |
| `/market/:symbol` | High | IN PROGRESS | Public read-only symbol detail page added with chart, microstructure, derivatives, signal, evidence, mobile layout, and screenshots/tests. Full depth, recent trades, and derivatives data remain unavailable until durable sources are wired. |
| `/signals` | High | OPEN | Needs compact signal cards, status buckets, evidence drawer, and plain-language raw enum translation. |
| `/ai-predictions` | High | OPEN | Needs AI Hub copy, calibration/performance visuals, and raw prediction ID de-emphasis. Phase 14A fixed raw live-gate enum copy and mobile overflow on `/ai-predictions/model-state`, but full visual/copy review remains pending. |
| `/portfolio` | Medium | OPEN | Needs equity curve, drawdown, exposure, and paper-mode labeling across positions/PnL. |
| `/alerts` | High | OPEN | Alert API and create/edit/disable workflows are incomplete. |
| `/status` | Medium | IN PROGRESS | Public-safe uptime/data freshness/incidents page and `/api/v2/status` added; production monitoring, incident source, and human visual review remain pending. |
| `/login` | Medium | IN PROGRESS | Professional backend-auth login added with no role selector; production session hardening, environment-backed admin step-up partial evidence, MFA/step-up, and deployment cookie verification remain pending. |
| all public/trader routes | High | IN PROGRESS | Final screenshots captured at 1920, 1440, 768, and 390 widths; Phase 13A target routes were reviewed, but non-target routes still need full route-by-route human review. |
| all public/trader routes | High | IN PROGRESS | Auth/status/nav/trade/market focused visible-string tests passed historically; current rerun is pending after later public/trader source-copy, ProChart, account-scope, and readiness-doc changes. Remaining public/trader routes still need full route-by-route review. |
| protected trader routes | High | IN PROGRESS | `/trade` now renders as public paper/read-only; other protected trader routes still need backend auth and route-specific review. |
| Phase 14A full-suite validation | Medium | HISTORICAL FIX; CURRENT RERUN PENDING | `npx playwright test --project=chromium --reporter=list` passed with 196 tests after Phase 14A triage. Later source-copy, ProChart, account-scope, repository, and readiness-doc changes require a fresh rerun before this can count as current evidence. Phase 14 remains IN PROGRESS pending current validation, production smoke, and deployment verification. |
| `/markets` visual density | Medium | IN PROGRESS | Phase 13A authenticated screener passes no-overflow/copy tests, but full-page screenshots are very tall because 135 rows render in one screener. Further pagination/virtualization/density tuning is still recommended. |
| mobile trader surfaces | Medium | IN PROGRESS | `/dashboard`, `/markets`, `/market/BTCUSDT`, and `/trade` pass 390px overflow checks, but remain dense and long on mobile. |
| `/chart/:symbol` chart sizing and realtime merge | Medium | IN PROGRESS | ProChart route now recalculates chart height on viewport changes, sanitizes malformed route symbols to a safe default, labels realtime only after stream frames arrive, shows read-only source posture, and merges fresh stream candle rows over REST/API history by candle time. Screenshots and current validation remain pending. |
| `/chart/:symbol` indicator-control clarity | Medium | FIXED, pending validation rerun | ProChart overlay controls now use field-specific typed-indicator titles, distinguishing EMA/Bollinger availability from AI target source-pending state without enabling static/fake-live indicators. |
| `/trade` activity source overclaim risk | Medium | FIXED, pending validation rerun | Activity source labels now require matching trader/paper account scope before showing trader-specific order, execution, audit, or signal source copy. |
| read-only market stream stale handling | High | FIXED, pending validation rerun | Stale stream transitions now mark cached ticker, depth, trades, and candle envelopes stale; ProChart labels aggregate stale stream state as `Stream data stale`; `/trade` stream-source copy shows stale/polling fallback posture. ProChart and `/trade` cannot keep old stream snapshots eligible as current realtime data. |
| `/market/:symbol` source label terminology | Medium | FIXED, pending validation rerun | Market detail source labels now use product-facing current/stale/read-only stream/fallback/unavailable copy instead of `Typed API data`. |
| `/market/:symbol` previous-symbol stream race | High | FIXED, pending validation rerun | Market detail now requires stream envelope symbol and candle timeframe proof before stream data can override typed polling state. |
| public/trader source terminology | Medium | IN PROGRESS | `/market/:symbol`, `/trade`, `/derivatives`, `/research`, `/ai-predictions`, `/status`, `/alerts`, and shared chart empty states now avoid main-UI `contract`, `typed source`, legacy unavailable-source wording, and dash-placeholder copy; validation and screenshot review remain pending. |

## Screenshot Evidence

| Directory | Count/status | Notes |
|---|---|---|
| `v2/screenshots/before` | 84 | Current-state baseline for 21 public/trader routes at four viewport sizes. |
| `v2/screenshots/final` | 84+ | Current final-pass route crawl plus targeted login, status, admin auth-gate, admin dashboard, trade, and market captures. |
| `v2/screenshots/final` | Phase 13A target 28 | `home-*`, `login-*`, `status-*`, `dashboard-*`, `markets-*`, `market-detail-*`, and `trade-*` recaptured by `phase_13a_visual_gate.spec.ts`. |

## Recently Improved

| Area | Result | Remaining QA |
|---|---|---|
| `/dashboard` | Replaced operator-heavy dashboard with trader KPI/chart/signal/positions/status layout and later cleaned market-overview/source wording. | Current screenshot, overflow, and visible-string QA rerun pending. |
| `/markets` | Added professional screener controls and CoinAnk-style columns with honest missing-data states. Phase 13A removed visible unavailable-source fallbacks and authenticated screenshots pass no-overflow checks. | Density, pagination/virtualization, and deeper human review remain. |
| `/market/:symbol` | Replaced debug-heavy detail surface with public read-only market detail page and focused Playwright coverage. | Realtime depth/trades/derivatives sources and human visual adjudication pending. |
| auth/RBAC | Added backend auth endpoints, admin/superadmin role helpers, protected admin shell, login page, secret-free admin user mutation audit events, SQLAlchemy auth/revocation/admin-audit adapter seams, production fail-closed local auth/revocation/audit-store guards, and focused backend/Playwright tests. | Production migrations/provisioning, production session hardening, environment-backed admin step-up partial evidence, MFA/step-up, durable admin audit retention policy, and current validation pending. |
| `/status` | Replaced public status with safe platform/API/data/paper/live-disabled status page. | Production monitoring source and deployment smoke pending. |
| Phase 13A visual/copy/responsive pass | Fixed public/trader banner wording, status data-source wording, dashboard chart source jargon, `/market/:symbol` debug panel exposure, `/markets` formatter fallbacks, default dark theme, and mobile landing overflow. | Full Chromium suite later passed in Phase 14A, but current rerun after subsequent changes and full-route triple-check remain incomplete. |
| API data surfaces | Added safe read-only/paper-only `/api/v2` data states and previously got focused backend auth/status tests running through the repo venv. | Current backend pytest rerun, realtime sources, durable repositories, and production smoke remain pending. |
| shell/nav | Trader and system route groups separated by route surface/role, with backend-confirmed admin nav tests passing. | Production auth hardening remains incomplete. |
| Phase 14A test stabilization | Full Chromium suite historically passed 196/196; screenshot crawler has bounded settling and route-specific auth fixtures. | Current full-suite rerun, production smoke, and full route visual adjudication remain incomplete. |
| style layers | Added component/table/chart/admin CSS layers imported by `main.tsx`. | Component extraction and visual QA pending. |

## Market derivatives contract visual follow-up

| Route | Defect / risk | Status | Notes |
|---|---|---|---|
| `/market/:symbol` | Derivatives panel now has funding/OI snapshot state but needs screenshot review after current changes. | IN PROGRESS | Re-run Phase 13A visual gate and market detail screenshots before any visual PASS claim. |

## 2026-06-14 continuation defects remediated

| Route/area | Defect | Fix | Status |
|---|---|---|---|
| Trader app shell | Trader-visible chrome exposed operational telemetry such as ingestors, failed services, Redis, and training rows. | Hid operational telemetry for non-admin users and showed trader-safe data freshness instead. | FIXED - validation pending |
| Local paper repository | Staged local paper order rows did not carry row-level `trader_id` / `paper_account_id`, so scoped activity endpoints could withhold the trader's own staged orders. | Stamped local paper order rows with owning trader and paper-account scope; added backend contract assertions. | FIXED - validation pending |
| Local paper fill writer | Generated/updated local paper position rows did not carry row-level `trader_id` / `paper_account_id`, so scoped position endpoints could withhold the trader's own filled positions. | Stamped local fill-writer position rows with owning trader and paper-account scope; added backend contract assertions. | FIXED - validation pending |
| `/markets` | Symbol universe/freshness relied on fallback prediction/CoinAnk/top-10 payloads instead of the typed V2 market overview where available. | Added `/api/v2/market/overview` polling for current public symbol universe/source freshness while retaining missing data states for derivatives/predictions. | FIXED - validation pending |
| `/dashboard` | Market universe/freshness did not surface the typed V2 market overview when available. | Added `/api/v2/market/overview` polling to dashboard market universe, status, freshness, and evidence copy. | FIXED - validation pending |

No live submit/cancel/leverage/margin/live-gate mutation was added. `/trade`, `/market/:symbol`, `/chart/:symbol`, Phase 15, paper/read-only launch, and real live trading remain incomplete or blocked as previously recorded.

| Trader app shell | Trader shell hid operational telemetry but still polled legacy operator/runtime/system payload files for non-admin users. | Added hook-level `enabled` controls and disabled those payload reads for non-admin shell contexts; trader chrome now uses read-only public market stream state. | FIXED - validation pending |

| `/trade` open orders | Local paper fill/cancel controls required row-level scope but did not require the parent orders endpoint to be repository-backed. | Added a repository-backed scoped orders-envelope guard before showing local paper fill/cancel controls; added denied-path Playwright coverage for static payload rows. | FIXED - validation pending |
| `/markets` | V2 market overview provided current public symbol inventory but not current public ticker rows for table values. | Added read-only public USD-M 24h ticker rows to `/api/v2/market/overview` and wired `/markets` price/change/turnover cells to prefer them. | FIXED - validation pending |

| Shared shell | Browser theme preference used a legacy internal product key `ai_bot_v2_theme`. | Renamed to `alphaforge_theme` with one-time migration/removal of the legacy key. | FIXED - validation pending |

| `/market/:symbol` derivatives | Liquidation section only showed generic unavailable feed copy even when runtime stream/level evidence existed. | Added separate source-labeled `Liquidation stream` and `Liquidation levels` cards while keeping 1h/24h totals unavailable. | FIXED - validation pending |

| `/market/:symbol` derivatives | Liquidation stream card could have implied active stream status without its own stale flag. | Added stream-level `lag_ms`/`stale` fields and UI copy for stale stream status. | FIXED - validation pending |

## Phase 15 account settings defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/account-settings` | Exchange metadata form could rely only on backend rejection for private-looking labels. | Added client-side friendly warning and disabled submit state for private-looking account metadata. | FIXED, pending validation rerun. |

## Phase 15 ProChart defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/chart/:symbol` | Symbol sidebar prices could appear without a visible source freshness cue. | Added compact freshness/stale/source-unavailable chip per symbol. | FIXED, pending validation rerun. |
| `/api/v1/chart/*` | Chart helper endpoints returned legacy status without full source/freshness/stale fields. | Added structured source, source_type, endpoint, timestamp, received_at, lag_ms, stale, missing_fields, warnings, and read-only/no-mutation flags. | FIXED, pending backend validation rerun. |

## Phase 15 Alerts defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/alerts` | Header and readiness copy implied alert creation was unavailable even when scoped paper alert records were available, and an unavailable source could read as `source present`. | Updated copy to distinguish trader-scoped paper alert records from disabled production notification delivery and changed unavailable state to `Alert source unavailable`. | FIXED, pending validation rerun. |

## Phase 15 Portfolio defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/portfolio` | Header source helper could classify `Trader account source` as `Fallback data`. | Updated source-label mapping to preserve scoped trader source, source-required, unavailable, and withheld states separately. | FIXED, pending validation rerun. |

## Phase 15 Derivatives defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/derivatives` | Partial typed derivatives data could display as `Current data source` / `Data source checked` even while missing fields remained. | Added partial/stale/current source labeling based on missing-field count and stale state. | FIXED, pending validation rerun. |
| `/derivatives` | Liquidation stream and level evidence was not visible on the dedicated derivatives route. | Added `Liquidation stream` and `Liquidation levels` metrics with stale/unavailable handling. | FIXED, pending validation rerun. |

## Phase 15 Research defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/research` | Current market context could be labeled as generic `Data source checked`, implying the research workbench itself was connected. | Added explicit `Research source pending`, `Research API`, and market-context labels while keeping missing research capabilities visible. | FIXED, pending validation rerun. |

## Phase 15 Backtests defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/backtests` | Paper account metrics could be interpreted as backtest results beside the missing-engine state. | Added `Backtest API`, `Paper account context only`, and explicit note that current metrics are not backtest results or strategy-performance proof. | FIXED, pending validation rerun. |

## Phase 15 AI predictions defect remediation - 2026-06-15

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/ai-predictions` | Forecast metrics could be read as strategy-performance proof or live-trading approval. | Added `Paper forecast evidence only`, prediction source, and explicit note that forecast evidence is not strategy-performance proof and does not approve live trading. | FIXED, pending validation rerun. |

## 2026-06-14 `/markets/symbols` remediation note

| Route | Defect | Fix | Status |
|---|---|---|---|
| `/markets/symbols` | Underlying symbols page still used admin/operator-style runtime copy and raw source-path language if route migration exposed it. | Reworked visible copy to read-only account-aware symbol coverage, removed operator evidence panel, added friendly status labels, and added a focused route contract spec. | IN PROGRESS: validation and screenshot review pending |
