
Do not mark anything PASS unless all gates below pass.
Do not enable real live trading.
Do not add live order submit/cancel/leverage/margin mutation.
Do not weaken RBAC.
Do not fake realtime data.
Do not present static payloads as live data.
Do not hide broken data wiring behind generic “unavailable” cards on public/trader pages.

====================================================================
NON-NEGOTIABLE PRODUCT RULES
====================================================================

1. Every visible public/trader/admin page must be redesigned, not patched.
2. Every visible card, table cell, chart, badge, number, signal, prediction, status, control, and label must have:
   - source endpoint or stream
   - source service/ingestor/repository
   - timestamp
   - received_at
   - lag/freshness
   - stale/not stale state
   - quality status
   - missing field list if incomplete
   - owner area
   - test coverage
3. Public/trader pages must not normally show unavailable data.
   - If a required realtime source does not exist, wire it.
   - If it cannot be wired in this pass, remove the module from public/trader nav or gate it behind “Coming soon / Data source not connected” with an explicit blocker.
   - Do not count that page/module as complete.
4. Admin pages may show unavailable/broken data states, but only as actionable monitoring:
   - exact source missing
   - owning service
   - last successful record
   - error
   - remediation action
   - control availability
5. Full product acceptance requires every page to render with valid realtime or near-realtime data where the system has that data.
6. Static files and payload snapshots are allowed only as:
   - local development fallback
   - admin/debug evidence
   - clearly labeled historical fallback during source outage
   - never as normal public/trader “live” data
7. All operator/admin/developer content must be removed from public/trader routes.
8. All admin/system controls must live under `/admin/*`.
9. Real live trading remains blocked unless separately approved through production auth, RBAC, MFA/step-up, audit, live-gate final approval, and superadmin authorization.

====================================================================
REFERENCE PRODUCT STANDARD
====================================================================

Use CoinAnk-style analytics architecture:
- market screener
- derivatives overview
- liquidation data
- liquidation heatmap
- liquidation map
- funding rate
- funding heatmap
- accumulated funding
- longs vs shorts
- open interest
- OI change
- order-book depth delta
- full price order book
- aggregated order book
- fund flow
- exchange comparison
- chart data
- fear/greed
- AI analysis
- pro chart/live chart
- columns: favorite, symbol, price, 1h/4h/24h change, funding, turnover, OI, market cap, OI change, liquidation totals, long/short, 7-day trend

Use Binance-style trading terminal architecture:
- chart-first layout
- configurable dark/light themes, but dark professional default
- modular panels
- order book
- market depth
- recent trades tape
- order ticket
- positions/open-orders/executions panel
- chart fullscreen
- pro/compact layouts
- add/remove/reorder modules where feasible

Do not copy branding, logos, proprietary text, or exact visual identity.

====================================================================
PHASE A — HARD FREEZE, AUDIT, AND FAILURE INVENTORY
====================================================================

Before redesigning more pages, perform a complete current-state audit.

Run:
- git status --short
- npm run typecheck
- npm run build
- npm run lint --if-present
- backend pytest suite
- npx playwright test --project=chromium --reporter=list
- route inventory
- data source inventory
- screenshot inventory

Create/update:
- docs/v2-full-redesign-master-plan.md
- docs/v2-route-inventory-complete.md
- docs/v2-data-surface-inventory-complete.md
- docs/v2-realtime-source-inventory.md
- docs/v2-page-data-coverage-matrix.md
- docs/v2-visual-defect-inventory.md
- docs/v2-playwright-failure-inventory.md
- docs/v2-admin-control-inventory.md
- docs/v2-launch-blockers.md

For every route, record:
- route path
- page/component
- surface: PUBLIC / TRADER / ADMIN / SUPERADMIN / REDIRECT / REMOVE
- current visual status
- current data status
- current auth status
- current realtime status
- current tests
- missing data
- missing controls
- forbidden copy
- screenshot names
- pass/fail

For every data surface, record:
- page
- component
- visible label
- field name
- current source
- expected source
- endpoint
- websocket/SSE topic
- repository/table/stream
- ingestor/service
- freshness threshold
- data quality rule
- fallback behavior
- current status: LIVE / PARTIAL / SNAPSHOT / MISSING / BROKEN
- owner
- test status

Do not proceed to page completion until this inventory exists.

====================================================================
PHASE B — REALTIME DATA DOCTRINE AND CONTRACT
====================================================================

Create a single shared data contract used by every frontend page and backend API response.

Backend type/shape:
- source
- source_type: websocket | sse | api | repository | stream | cache | static_snapshot | unavailable
- endpoint
- stream_topic
- repository
- ingestor_id
- service_id
- symbol
- exchange
- timestamp
- received_at
- lag_ms
- freshness_status: fresh | delayed | stale | offline | unavailable
- data_quality_status: valid | partial | invalid | missing | degraded
- missing_fields
- warnings
- errors
- mode: public | read_only | paper | live_blocked | admin
- audit_id where action-related
- run_id/job_id where model/trainer-related
- model_version where AI-related
- strategy_id where strategy-related
- order_id/trade_id where trading-related

Frontend shared helpers:
- ValidatedDataEnvelope
- useRealtimeResource()
- useDataFreshness()
- useRealtimeHealth()
- useSourceCoverage()
- DataQualityBadge
- FreshnessBadge
- SourceBadge
- EvidenceDrawer
- RealtimeConnectionBadge
- MissingSourceIncident
- DataContractViolationPanel
- AdminSourceRepairPanel

Rules:
- Every page consumes only validated data envelopes.
- Raw API responses must be normalized before display.
- Components cannot render a metric without source/freshness metadata.
- A metric with no valid source must fail test coverage unless explicitly marked as intentionally hidden.
- Public/trader pages should not display raw “unavailable” for normal core modules after this reset; they must either get real data or the module is removed/gated.
- Admin pages must display unavailable states as monitoring incidents.

Add tests:
- every public/trader metric has source/freshness metadata
- every admin metric has source/freshness or incident metadata
- no static_snapshot is displayed as live
- no stale data is displayed without warning
- no metric renders `undefined`, `null`, `NaN`, `source pending`, or raw enum text

====================================================================
PHASE C — BACKEND REALTIME SOURCE AUDIT AND WIRING
====================================================================

Find all real data currently available in the system.

Inspect:
- backend APIs
- FastAPI routers
- DB/repositories
- Redis streams/keys
- websocket/SSE code
- ingestors
- trainer outputs
- signal publishers
- prediction stores
- risk controllers
- trader/execution logs
- paper trading ledgers
- portfolio repositories
- exchange connectors
- derivatives adapters
- CoinAnk adapters
- payload writers
- runtime snapshot files
- monitoring/health services
- audit ledgers
- live_gate services

Create:
- docs/v2-backend-source-map.md

For each data category, identify the real source:
1. Market prices
2. Candles/OHLCV
3. Mark price
4. Index price
5. 24h ticker stats
6. Volume/turnover
7. Order book depth
8. Recent trades
9. Funding
10. Predicted funding
11. Open interest
12. OI changes
13. Liquidations
14. Liquidation heatmap/map
15. Long/short ratios
16. Basis
17. Exchange comparison
18. Market cap/dominance
19. Fear/greed if present
20. Signals
21. Signal evidence
22. AI predictions
23. Target prices
24. Stop/invalidation
25. Model confidence
26. Trainer jobs
27. Training metrics
28. Feature importance
29. Model registry
30. Strategy state
31. Orchestrator jobs
32. Risk decisions
33. Risk blocks
34. Traders/bots
35. Orders
36. Fills
37. Executions
38. Paper positions
39. Paper balances
40. Portfolio equity/PnL
41. Backtests
42. Alerts
43. Ingestor status
44. Data lag
45. Service health
46. Admin audit events
47. Live readiness
48. System logs/errors

For each category:
- If real source exists, wire it.
- If only snapshot exists, trace snapshot writer and expose its upstream source.
- If no source exists, create an admin incident and mark the public/trader module blocked.
- If the data is not in the system at all, do not fake it.

Backend endpoints to implement/wire fully:
- GET /api/v2/realtime/manifest
- GET /api/v2/data-health
- GET /api/v2/data-coverage
- GET /api/v2/market/overview
- GET /api/v2/market/{symbol}
- GET /api/v2/market/{symbol}/ticker
- GET /api/v2/market/{symbol}/candles
- GET /api/v2/market/{symbol}/depth
- GET /api/v2/market/{symbol}/trades
- GET /api/v2/derivatives/overview
- GET /api/v2/derivatives/funding
- GET /api/v2/derivatives/open-interest
- GET /api/v2/derivatives/liquidations
- GET /api/v2/derivatives/long-short
- GET /api/v2/derivatives/basis
- GET /api/v2/signals
- GET /api/v2/signals/{id}
- GET /api/v2/ai/predictions
- GET /api/v2/ai/model-state
- GET /api/v2/trainer/status
- GET /api/v2/trainer/jobs
- GET /api/v2/portfolio
- GET /api/v2/account/positions
- GET /api/v2/execution/orders
- GET /api/v2/execution/executions
- GET /api/v2/backtests
- GET /api/v2/alerts
- POST /api/v2/alerts
- PUT /api/v2/alerts/{id}
- DELETE /api/v2/alerts/{id}
- GET /api/admin/ingestors
- GET /api/admin/trainer
- GET /api/admin/orchestrator
- GET /api/admin/risk
- GET /api/admin/traders
- GET /api/admin/execution
- GET /api/admin/exchanges
- GET /api/admin/system-health
- GET /api/admin/logs
- GET /api/admin/audit
- GET /api/admin/readiness

Realtime:
- Implement or wire `/ws/market-data` or `/events`.
- If WebSocket is too large, implement SSE first.
- Required event types:
  - ticker
  - candle
  - depth
  - trade
  - funding
  - open_interest
  - liquidation
  - long_short
  - signal
  - prediction
  - trainer
  - position
  - order
  - execution
  - risk
  - alert
  - ingestor
  - orchestrator
  - trader
  - system_health

Do not make frontend pages poll static files when backend streams/repositories exist.

====================================================================
PHASE D — FULL THEME AND DESIGN SYSTEM REDESIGN
====================================================================

The redesign must include theme, colors, pages, and layout, not just data wiring.

Create a premium trading design system.

Files:
- frontend/src/styles/tokens.css
- frontend/src/styles/theme-dark.css
- frontend/src/styles/theme-light.css
- frontend/src/styles/layout.css
- frontend/src/styles/components.css
- frontend/src/styles/tables.css
- frontend/src/styles/charts.css
- frontend/src/styles/admin.css
- frontend/src/styles/responsive.css

Dark theme default:
- base background: deep navy/black
- panels: layered dark graphite/navy
- borders: subtle blue-gray
- primary accent: cyan/teal
- AI accent: violet/cyan
- buy/up: green/teal
- sell/down: red
- warning: amber
- critical: red
- admin/system: purple, only in admin surfaces

Light theme:
- clean institutional light mode
- never default for trader terminal
- must be usable, not an afterthought

Required UI components:
- PlatformShell
- AdminPortalShell
- PublicShell
- TraderShell
- TopBar
- SecondaryNav
- SymbolSearch
- MarketTickerStrip
- RealtimeStatusBar
- PageHeader
- DataPanel
- MetricCard
- KPIGrid
- ProTable
- MobileDataCards
- ColumnChooser
- TimeframeSelector
- ExchangeSelector
- Watchlist
- Sparkline
- Heatmap
- CandlestickChart
- DepthChart
- OrderBook
- RecentTradesTape
- PredictionBandChart
- FundingChart
- OpenInterestChart
- LiquidationHeatmap
- LongShortChart
- EquityCurve
- DrawdownChart
- StatusPill
- FreshnessBadge
- SourceBadge
- EvidenceDrawer
- ControlConfirmationDialog
- AdminActionButton
- AuditResultPanel
- IncidentPanel
- DataCoveragePanel
- EmptyState
- ErrorState
- StaleState
- LoadingSkeleton

Visual rules:
- No Excel-like pages.
- No raw browser tables.
- No dense unaligned columns.
- No giant equal-weight card walls.
- No text overflow.
- No uncontrolled horizontal scroll.
- No tiny unreadable table text.
- No light default theme on trading terminal.
- No admin/system color language in public/trader UI.
- Mobile pages must use cards/segmented panels instead of broken tables.
- Charts must look like trading charts, not placeholder graphics.

====================================================================
PHASE E — ROUTE MAP AND PAGE OWNERSHIP
====================================================================

Final public/trader/admin route map:

Public:
- /
- /login
- /status
- /markets
- /market/:symbol
- /signals/public if intentionally public preview

Trader:
- /dashboard
- /trade
- /markets
- /market/:symbol
- /derivatives
- /signals
- /ai-predictions
- /portfolio
- /portfolio/executions
- /portfolio/history
- /backtests
- /backtests/replay
- /research
- /research/technical-analysis
- /alerts

Admin:
- /admin
- /admin/system
- /admin/ingestors
- /admin/trainer
- /admin/orchestrator
- /admin/risk
- /admin/traders
- /admin/execution
- /admin/exchanges
- /admin/config
- /admin/readiness
- /admin/users
- /admin/logs
- /admin/reports

Superadmin:
- /admin/audit
- /admin/evidence
- /admin/scripts
- /admin/build-validation
- /admin/coverage
- /admin/migrations
- /admin/codex
- /admin/ai-tools

Legacy routes:
- Redirect to canonical route, protect under `/admin`, or remove from nav.
- No legacy route may leak operator/developer content to public/trader users.

Create:
- docs/v2-route-migration-map.md

====================================================================
PHASE F — PUBLIC PAGES FULL REDESIGN
====================================================================

1. `/`
Must become a premium public landing page:
- professional hero
- live market pulse
- BTC/ETH/SOL live cards with an otion to select all universe symbols in system
- top movers
- derivatives preview
- AI signal preview
- risk-gated paper execution explanation
- evidence lineage explanation
- CTAs: Open Markets, View Signals, Sign In
- no admin/operator/system CTA as primary
- no unavailable data as normal state

2. `/status`
Must be public-safe:
- platform status
- API status
- market data freshness
- signal data freshness
- paper/read-only status
- live trading disabled
- incidents/maintenance
- no internals, logs, stack traces, payloads, build/Codex/migration/coverage info

3. `/login`
Must be professional:
- email/password
- password visibility
- secure sign-in
- read-only demo if allowed
- no role selector
- no fake admin
- no local/session role text

====================================================================
PHASE G — TRADER PAGES FULL REDESIGN AND REALTIME WIRING
====================================================================

1. `/dashboard`
Must show:
- six KPI max
- live portfolio/paper equity
- today PnL
- active signals
- AI confidence
- market regime
- data status
- main chart
- current signal
- positions
- market pulse
- realtime status strip
No operator matrices, logs, payloads, raw JSON.

2. `/markets`
Must show CoinAnk-style screener:
- overview
- gainers/losers
- derivatives
- funding
- open interest
- liquidations
- heatmap
- watchlist
- columns:
  favorite, symbol, price, 1h %, 4h %, 24h %, volume, turnover, funding, predicted funding, OI, OI 1h/4h/24h, 1h liquidation, 24h liquidation, long/short, market cap, AI confidence, AI direction, target price, 7-day trend, freshness
- realtime updates
- no source-pending as normal state
- if a column has no source, hide it by default and show in admin coverage as missing

3. `/market/:symbol`
Must show:
- live symbol header
- candlestick + volume
- order book summary
- depth chart
- recent trades
- derivatives panel
- active signal
- AI prediction
- evidence drawer
- realtime freshness

4. `/trade`
Must show:
- professional chart-first terminal
- symbol header
- candlestick chart
- order book
- depth chart
- recent trades
- paper order ticket
- preview endpoint
- positions
- open orders
- executions
- history
- signal evidence
- paper/read-only mode
- no live submit button
- paper submit only if verified paper service exists

5. `/derivatives`
Must become a full CoinAnk-style analytics area:
- funding chart
- funding heatmap
- accumulated funding
- OI chart
- OI by exchange
- OI change leaderboard
- liquidation heatmap
- liquidation map
- long/short ratio
- basis
- exchange comparison
- realtime freshness
If the system lacks realtime derivatives data, wire the adapters or block this page from PASS.

6. `/signals`
Must show:
- active signals
- pending signals
- expired signals
- rejected/blocked signals
- executed paper signals
- entry
- targets
- stop
- invalidation
- confidence
- expected move
- risk/reward
- status
- strategy
- model version
- risk decision
- evidence drawer
- realtime stream

7. `/ai-predictions`
Must show:
- prediction matrix
- forecast bands
- target prices
- realized vs predicted
- calibration
- model performance
- feature importance
- latest emitted/blocked signals
- trainer status
- no “AI brain” developer copy

8. `/portfolio`
Must show:
- paper portfolio value
- equity curve
- PnL
- drawdown
- exposure
- positions
- risk
- source/freshness
- trader isolation

9. `/portfolio/executions`
Must show:
- orders
- fills
- rejects
- slippage
- fees
- risk denial
- audit/evidence
- paper mode

10. `/portfolio/history`
Must show:
- trade journal
- signal history
- performance stats
- filters
- evidence

11. `/backtests`
Must show:
- equity curve
- drawdown
- win rate
- profit factor
- expectancy
- trades
- benchmark
- signal overlays

12. `/backtests/replay`
Must show:
- replay timeline
- candles
- signal decisions
- risk decisions
- execution simulation
- controls

13. `/research`
Must show:
- market regime
- trend/volatility
- derivatives context
- AI summary
- no ingestor/admin panels

14. `/research/technical-analysis`
Must show:
- chart indicators
- support/resistance
- volatility
- trend regime
- signals

15. `/alerts`
Must show:
- create alert
- price threshold
- funding threshold
- OI change
- liquidation spike
- AI signal
- risk event
- enable/disable/delete
- notification history
- realtime alerts
If no alerts backend exists, implement it or keep page BLOCKED.

====================================================================
PHASE H — ADMIN PORTAL FULL REDESIGN AND MONITORING
====================================================================

Admin pages must show live system truth, not raw clutter.

All admin pages require backend-confirmed admin/superadmin role.

Admin dashboard:
- realtime service map
- data coverage
- ingest lag
- trainer state
- orchestrator state
- risk state
- traders state
- execution state
- live readiness
- critical incidents

Ingestors:
- every ingestor
- every dataset
- source coverage
- heartbeat
- last record
- lag chart
- throughput
- error rate
- gap count
- duplicate count
- downstream consumers
- controls: start, stop, restart, resync, backfill, replay, clear error, disable source
- all controls confirmed, reason-required, backend-authorized, audit-logged

Trainer:
- every active job
- current step/epoch
- progress
- dataset
- symbols/timeframes
- features
- labels/targets
- hyperparameters
- train/validation/test metrics
- loss curves
- feature importance
- model registry
- predictions
- target prices
- emitted/blocked signals
- failures
- controls: start, pause, cancel, rerun, promote, rollback, generate predictions, approve/block signal

Orchestrator:
- jobs
- queues
- blocked jobs
- schedules
- dependencies
- event timeline
- decisions
- deconfliction
- next action
- controls

Risk:
- every controller
- thresholds
- pass/fail
- blocked orders/signals
- exposure
- leverage/margin/drawdown if available
- kill switch
- overrides
- audit

Traders:
- each bot/trader
- mode
- assigned symbols/strategies
- positions
- intended next actions
- orders/fills/rejections
- slippage
- fees
- PnL
- heartbeat
- risk result
- controls

Execution:
- order router
- paper engine
- orders
- executions
- rejects
- queue
- latency
- slippage
- exchange ACKs if any
- no live mutation unless live-gated

Exchanges:
- connectivity
- REST/websocket state
- rate limits
- balances if allowed
- permissions
- masked key status
- errors

Readiness:
- live_gate wizard
- final live approval disabled unless all security gates pass

Logs:
- structured logs
- severity
- service
- correlation ID
- no sensitive secrets
- filters

Audit:
- immutable audit
- actor
- action
- reason
- result
- timestamp
- resource
- evidence

Superadmin tools must remain hidden from admins/traders/public.

====================================================================
PHASE I — MONITORING AND OBSERVABILITY LAYER
====================================================================

Add a full website + backend monitoring layer.

Backend endpoints:
- GET /api/admin/monitoring/routes
- GET /api/admin/monitoring/data-surfaces
- GET /api/admin/monitoring/realtime-streams
- GET /api/admin/monitoring/frontend-errors
- GET /api/admin/monitoring/backend-errors
- GET /api/admin/monitoring/test-status
- GET /api/admin/monitoring/build-status
- GET /api/admin/monitoring/data-contract-violations

Frontend:
- capture render errors
- capture data contract violations
- capture missing source incidents
- capture stale data incidents
- capture websocket disconnects
- capture route load failures
- capture chart render failures

Admin monitoring page:
- page coverage
- data coverage
- realtime stream health
- route health
- frontend error count
- backend error count
- stale data count
- missing source count
- test status
- deploy status

Every incident must link to:
- page
- component
- source
- owner
- remediation

====================================================================
PHASE J — TESTS AND VALIDATION
====================================================================

No page passes without tests.

Backend tests:
- all API contracts
- auth/RBAC
- admin/superadmin protection
- status public safety
- realtime manifest
- data health
- market endpoints
- derivatives endpoints
- signals endpoints
- portfolio/execution endpoints
- trainer/admin endpoints
- ingestor/admin endpoints
- action confirmation/audit where controls exist
- no live mutation without superadmin/live_gate

Frontend Playwright:
- every route renders at:
  - 1920x1080
  - 1440x900
  - 768x1024
  - 390x844
- no horizontal scroll
- no forbidden public/trader strings
- no raw JSON by default
- no undefined/null/NaN
- no source pending
- no static snapshot shown as live
- every visible metric has source/freshness
- every visible page has realtime valid data or is blocked from PASS
- admin routes reject public/trader
- superadmin routes reject admin
- login works
- logout works
- status is public-safe
- trade terminal renders
- markets screener renders
- derivatives analytics renders
- signals/AI renders
- portfolio renders
- admin monitoring renders

Full suite:
- `npm run typecheck`
- `npm run build`
- `npm run lint --if-present`
- backend pytest full suite
- full Playwright Chromium suite
- production build smoke

Full Chromium suite must be green before launch readiness can move.

====================================================================
PHASE K — SCREENSHOTS AND HUMAN VISUAL REVIEW
====================================================================

Capture screenshots for every public/trader/admin/superadmin page at:
- 1920x1080
- 1440x900
- 768x1024
- 390x844

Create:
- docs/v2-final-visual-review.md

For every screenshot:
- route
- viewport
- PASS / FAIL / BLOCKED
- defects
- fixes
- data validity
- permission validity
- copy validity

No route passes if it:
- looks like Excel
- looks like an operator console on public/trader
- has broken mobile layout
- has unavailable data as normal state
- has static data pretending to be live
- leaks admin/dev terms
- has text overflow
- has broken charts
- has missing source metadata

====================================================================
PHASE L — LAUNCH READINESS
====================================================================

Paper/read-only launch may pass only when:
- full route inventory complete
- all public/trader pages redesigned
- all public/trader pages use realtime valid data or non-ready modules are removed/gated
- admin pages protected
- full Chromium suite passes
- backend tests pass
- production build passes
- public status safe
- production monitoring wired
- HTTPS verified
- env verified
- no localhost hardcoding
- no console errors
- no core asset 404s
- smoke tests pass on deployed URL

Real live trading remains BLOCKED unless:
- production auth/RBAC complete
- durable user store complete
- secure session/JWT rotation/revocation complete
- MFA/step-up complete
- full audit complete
- live_gate final approval complete
- superadmin approval complete
- exchange controls verified
- legal/risk approval documented
- explicit separate instruction authorizes it

====================================================================
DEFINITION OF DONE
====================================================================

Do not write “done”, “complete”, “pass”, “ready”, or “live” unless every item below is true:

1. Every route is inventoried.
2. Every page is redesigned with the new theme/design system.
3. Every visible metric has realtime valid data or the module is removed/gated.
4. Every data source has source/freshness/quality metadata.
5. Every realtime stream/API is validated.
6. Every public/trader page is free of operator/admin/dev wording.
7. Every admin page is backend-protected.
8. Every admin control is permission-safe, confirmed, reason-required, and audited.
9. No static snapshot is shown as live.
10. No unavailable data appears as the normal state of a completed public/trader page.
11. Before any visible field is marked unavailable, the relevant ingestor, Redis key/artifact, backend contract, and frontend mapper must be checked and either wired or explicitly documented as absent.
12. Full backend tests pass.
13. Full frontend Playwright Chromium suite passes.
14. Full screenshot matrix is captured and visually reviewed.
15. Production build passes.
16. Production smoke passes.
17. Launch readiness is updated.
18. Phase 15 remains BLOCKED unless production deployment/smoke is complete.
19. Real live trading remains BLOCKED unless explicitly approved through the separate live-gate process.

Final report must include:
- full route inventory status
- full data surface coverage status
- realtime source coverage status
- pages redesigned
- pages removed/gated
- backend endpoints added/wired
- websocket/SSE topics added/wired
- admin controls added/wired
- tests run and results
- full Chromium result
- backend pytest result
- screenshots captured
- visual review result
- remaining unavailable data surfaces
- remaining blockers
- launch status
- confirmation that real live trading remains blocked

---

## 2026-06-16 current-truth reconciliation addendum

Authoritative detail: see `docs/v2-current-truth-after-june15.md`.

The earlier June 15 inspection in this file is stale where it says the data-contract layer is missing. Current repo evidence shows the contract primitives and UI badges exist, but adoption remains partial. Backend collection now succeeds with `4093` tests collected. Local viewing through `5173` and `dashboard.wajidali.us` is restored with FastAPI on `8000`, but full backend pytest and full Chromium are not proven clean in the current pass. Phase 15 and real live trading remain BLOCKED.

### 2026-06-16 targeted backend evidence update

- Scoped backend auth/RBAC/status plus market-contract target now passes: `PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD .venv/bin/python -m pytest v2/backend/tests/integration/api/test_auth_rbac_and_status.py v2/backend/tests/integration/api/v2/test_market_contract_routes.py -q` -> `119 passed in 57.67s`.
- This is targeted evidence only. Full backend pytest, full Chromium, production smoke, route-by-route data coverage, and screenshot matrix remain UNPROVEN/BLOCKED for launch purposes.
- Real live trading remains BLOCKED.

