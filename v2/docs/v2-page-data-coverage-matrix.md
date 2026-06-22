# V2 Page Data Coverage Matrix

Date: 2026-06-15
Status: Initial coverage matrix. No public/trader page is accepted.

| Page | Required data | Current valid data | Missing/blocked data | Public/trader action | Status |
| --- | --- | --- | --- | --- | --- |
| `/` | live market pulse, BTC/ETH/SOL cards, top movers, derivatives preview, AI signal preview | read-only market fallback can cover market cards/top movers | AI/signal preview and derivatives completeness | wire or gate previews | BLOCKED |
| `/status` | platform/API/market/signal/paper status, incidents, live disabled | partial public-safe status | backend data-health and source metadata | wire `/api/v2/data-health` or mark incident | BLOCKED |
| `/login` | auth form only | UI exists | production auth/session backend validation | keep no role selector | BLOCKED |
| `/markets` | screener columns and heatmaps | price/24h/volume fallback | predicted funding, OI windows, liquidations, market cap, AI, trend | hide missing columns by default; admin coverage incidents | BLOCKED |
| `/market/:symbol` | chart, order book, trades, derivatives, signal, AI, evidence | market basics fallback | signal/AI evidence completeness, all metadata | wire or gate AI/signal modules | BLOCKED |
| `/dashboard` | six KPIs, portfolio, active signal, market regime | market and some signal status partial | scoped paper equity/PnL/positions/regime | gate portfolio KPIs without scoped source | BLOCKED |
| `/trade` | chart-first terminal, order book, trades, paper ticket, positions/orders/executions | market basics; scoped fail-closed logic | verified paper submit service and account state | no live submit; paper submit only if backend verified | BLOCKED |
| `/derivatives` | funding/OI/liquidations/heatmaps/long-short/basis/exchange comparison | funding/OI/long-short/basis basics | liquidation heatmap/map, exchange comparison, accumulated funding | gate missing modules | BLOCKED |
| `/signals` | active/pending/expired/rejected/executed, entry/targets/stop/invalidation/risk | partial active/evidence | full signal lifecycle and risk decision stream | wire lifecycle or gate sections | BLOCKED |
| `/ai-predictions` | matrix, bands, targets, calibration, feature importance, trainer status | selector matrix partial | realized-vs-predicted, model performance, feature importance | wire backend or gate | BLOCKED |
| `/portfolio` | equity/PnL/drawdown/exposure/positions/risk | fail-closed placeholders | trader-scoped paper repository data | gate until authenticated source | BLOCKED |
| `/portfolio/executions` | orders/fills/rejects/slippage/fees/risk denial/audit | fail-closed partial | execution ledger/reject reasons/fees | gate action modules | BLOCKED |
| `/portfolio/history` | journal/stats/filters/evidence | partial | full history repository | gate until source exists | BLOCKED |
| `/backtests` | equity/drawdown/win rate/profit factor/benchmark/trades | snapshot partial | backend backtest service source metadata | gate incomplete cards | BLOCKED |
| `/backtests/replay` | replay timeline/candles/signals/risk/execution simulation | snapshot partial | replay backend and source metadata | gate until wired | BLOCKED |
| `/research` | market regime/trend/volatility/derivatives/AI summary | market partial | research API and AI summary | gate missing research module | BLOCKED |
| `/research/technical-analysis` | indicators/support/resistance/volatility/trend/signals | public candle indicators possible | support/resistance and signal source | redirect or wire | BLOCKED |
| `/alerts` | alert CRUD, notification history, realtime alerts | wrapper exists; actions fail-closed | durable alert repository/delivery/audit | implement or keep blocked | BLOCKED |
| `/admin/*` | live system truth and actionable incidents | snapshots/partial | admin monitoring APIs and controls | admin-only incidents | BLOCKED |

## Required policy

Public/trader modules that lack source metadata must be hidden/gated, not displayed as normal unavailable cards. Admin pages must retain missing-source incidents with owner/remediation.

## 2026-06-15 trainer/admin evidence coverage update

- `/admin/trainer-prediction-monitor` no longer renders placeholder unavailable cards as the primary state.
- Current trainer lineage source: `/operator_gui_real_data_and_explainability/latest/operator_cockpit_payload.json`, field `trainer_prediction_monitor.rows`.
- Historical preserved winner source: `/historical_30d_replay_and_paper_proof/latest/operator_dashboard_payload.json`, field `preserved_winners`.
- Visible fields now include `prediction_id`, `feature_snapshot_id`, symbol, confidence, risk decision, and paper PnL evidence.
- Historical proof is labeled as a paper/historical artifact and is not presented as live trading output.

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

