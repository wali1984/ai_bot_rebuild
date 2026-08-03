# V2 Realtime Source Inventory

Date: 2026-06-15
Status: Initial source inventory. Not all sources are wired through backend-normalized realtime contracts.

| Source area | Current evidence | Expected realtime contract | Current frontend behavior | Status | Owner | Blocker/remediation |
| --- | --- | --- | --- | --- | --- | --- |
| Market ticker | V2 market API if available; Binance USD-M public REST fallback | ticker event via `/ws/market-data` or `/events`; normalized `/api/v2/market/*` | fetches API first, public fallback if unavailable | PARTIAL | Market Data | backend stream/manifest not fully validated |
| Candles | V2 candles API; Binance public klines fallback | candle event with final candle proof | fallback filters unfinished candles | PARTIAL | Market Data | backend final-candle contract must be audited |
| Depth | V2 depth API; Binance depth REST fallback | depth event/orderbook snapshot stream | fallback snapshot | PARTIAL | Market Data | true realtime depth stream not proven |
| Trades | V2 trades API; Binance recent trades fallback | trade event/tape stream | fallback snapshot | PARTIAL | Market Data | streaming tape not proven |
| Funding/OI/long-short/basis | Binance public read-only fallbacks for basics | derivatives events and history endpoints | fallback for basic derivatives only | PARTIAL | Derivatives | liquidation/heatmap/exchange comparison missing |
| Liquidations | backend stream only if configured | liquidation event, heatmap/map derived endpoints | no fake fallback; null levels if absent | MISSING/PARTIAL | Derivatives | wire verified local liquidation source or gate public module |
| Signals | `/api/v2/signals` wrapper | signal event | fail-closed if unavailable | PARTIAL/MISSING | Signals | signal stream and evidence endpoint not fully validated |
| AI predictions | static/partial payloads and page logic | prediction event and `/api/v2/ai/predictions` | partial/gated | PARTIAL/MISSING | AI/Trainer | backend prediction repository/stream audit needed |
| Trainer jobs | admin snapshots | trainer event and admin API | admin display only | SNAPSHOT/PARTIAL | Trainer | backend admin trainer endpoint needed |
| Portfolio/positions/orders/executions | typed V2 endpoints if backend/scoped | position/order/execution events | fail-closed; no fake account data | PARTIAL/MISSING | Execution/Portfolio | verified paper repository and trader isolation required |
| Risk/orchestrator/ingestors/system health | public static evidence folders and admin payloads | admin events and `/api/admin/monitoring/*` | admin snapshots | SNAPSHOT/PARTIAL | Platform Ops | monitoring APIs not fully implemented/validated |
| Alerts | alerts API wrapper | alert event and alert repository | fail-closed | PARTIAL/MISSING | Alerts | delivery/audit backend needed |

## Required event types from target contract

ticker, candle, depth, trade, funding, open_interest, liquidation, long_short, signal, prediction, trainer, position, order, execution, risk, alert, ingestor, orchestrator, trader, system_health.

## Current critical gap

The frontend still relies on direct static/public payload reads in some admin/status areas. Under the reset doctrine, static payloads can remain only as admin/debug/historical fallback, never as normal public/trader live data.

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

