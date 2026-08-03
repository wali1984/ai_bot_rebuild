# V2 Data Surface Inventory Complete

Date: 2026-06-15
Status: Initial Phase A inventory. No public/trader page is marked complete.

| Category | Primary pages | Current source | Expected source | Endpoint/stream | Repository/ingestor/service | Freshness rule | Fallback behavior | Current status | Owner | Test status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Market prices | `/`, `/markets`, `/market/:symbol`, `/trade`, `/chart/:symbol` | V2 API if running; Binance USD-M public fallback in frontend | Backend normalized market API plus stream | `/api/v2/market/*`, `/ws/market-data` | market ingestor, Binance adapter | fresh under seconds for ticker | public fallback allowed read-only | PARTIAL | Market Data | focused fallback tests pass |
| Candles/OHLCV | market/trade/chart/research | V2 API; Binance public klines fallback | Backend candle store/stream, closed candles only | `/api/v2/market/{symbol}/candles` | market ingestor | only final candles | public fallback filters unfinished candles | PARTIAL | Market Data | fallback finality test passes |
| Mark/index price | market/trade/derivatives | Binance premium index fallback | Backend normalized derivatives feed | `/api/v2/market/{symbol}` | derivatives adapter | fresh funding tick | read-only fallback | PARTIAL | Derivatives | partial |
| 24h stats/volume/turnover | markets/landing | Binance 24hr fallback | Backend market overview | `/api/v2/market/overview` | market ingestor | fresh under minutes | read-only fallback | PARTIAL | Market Data | fallback test passes |
| Order book depth | market/trade/chart | V2 API; Binance depth fallback | Backend depth stream | `/api/v2/market/{symbol}/depth`, depth event | orderbook ingestor | fresh seconds | read-only fallback | PARTIAL | Market Data | focused tests partial |
| Recent trades | market/trade/chart | V2 API; Binance recent trades fallback | Backend trade stream | `/api/v2/market/{symbol}/trades`, trade event | market ingestor | fresh seconds | snapshot fallback labelled current read-only | PARTIAL | Market Data | partial |
| Funding | derivatives/markets/market | Binance premium index fallback | Backend derivatives service | `/api/v2/derivatives/funding` | derivatives adapter | funding interval current | read-only fallback | PARTIAL | Derivatives | partial |
| Predicted funding | markets/derivatives | not verified | prediction/derivatives backend | `/api/v2/derivatives/funding` | derivatives/model service | current model run | hide until wired | MISSING | Derivatives/AI | missing |
| Open interest | derivatives/markets | Binance open interest fallback | backend OI stream/history | `/api/v2/derivatives/open-interest` | derivatives adapter | fresh minutes | read-only fallback | PARTIAL | Derivatives | partial |
| OI changes | markets/derivatives | not verified | OI history repository | `/api/v2/derivatives/open-interest` | derivatives repository | 1h/4h/24h windows | hide until wired | MISSING | Derivatives | missing |
| Liquidations | derivatives | local backend if present only; no fake fallback | verified liquidation stream | `/api/v2/derivatives/liquidations`, liquidation event | liquidation WSS/ingestor | fresh seconds/minutes | admin incident if absent | MISSING/PARTIAL | Derivatives | selector UI test only |
| Liquidation heatmap/map | derivatives | not verified | derived backend analytics | derivatives endpoints | liquidation analytics | fresh windowed | gate module | MISSING | Derivatives | missing |
| Long/short ratios | derivatives | Binance global ratio fallback | derivatives backend | `/api/v2/derivatives/long-short` | derivatives adapter | fresh 5m | read-only fallback | PARTIAL | Derivatives | partial |
| Basis | derivatives | computed from mark/index fallback | derivatives backend | `/api/v2/derivatives/basis` | derivatives adapter | fresh minutes | read-only fallback | PARTIAL | Derivatives | partial |
| Exchange comparison | derivatives | not verified | exchange comparison backend | `/api/v2/derivatives/*` | derivatives service | fresh minutes | gate module | MISSING | Derivatives | missing |
| Market cap/dominance/fear-greed/fund flow | markets/research | not verified | provider/alt-data backend | TBD | alt-data providers | fresh provider window | hide/gate | MISSING | Research/Alt Data | missing |
| Signals | dashboard/signals/market/trade | `/api/v2/signals` if backend | typed signal repository/stream | `/api/v2/signals`, signal event | signal publisher | fresh/current signal | fail-closed | PARTIAL/MISSING | Signals | focused scope tests |
| Signal evidence/targets/stops | signals/AI/market/trade | partial typed data | signal evidence backend | `/api/v2/signals/{id}` | signal repository | current by emitted_at | fail-closed | PARTIAL | Signals | partial |
| AI predictions/target prices | AI/markets/signals | partial/static payloads exist | prediction repository/stream | `/api/v2/ai/predictions`, prediction event | trainer/prediction publisher | latest model run | gate if absent | PARTIAL/MISSING | AI/Trainer | selector tests partial |
| Trainer status/jobs/metrics | admin/trainer/AI | static/admin payloads | backend admin trainer API | `/api/v2/trainer/*`, `/api/admin/trainer` | trainer service | heartbeat/run freshness | admin incident | SNAPSHOT/PARTIAL | Trainer | missing full admin tests |
| Strategy/orchestrator/risk | dashboard/admin | static/admin payloads | backend admin APIs/streams | `/api/admin/orchestrator`, `/api/admin/risk` | orchestrator/risk workers | heartbeat and event timeline | admin incident only | SNAPSHOT/PARTIAL | Orchestrator/Risk | missing full pass |
| Orders/fills/executions | trade/portfolio/admin | paper endpoints if backend | paper repository/execution stream | `/api/v2/execution/*`, order/execution event | paper engine/execution ledger | trader-scoped current | fail-closed | PARTIAL/MISSING | Execution | focused tests partial |
| Paper positions/balances/equity/PnL | dashboard/trade/portfolio | backend if authenticated/scoped | paper portfolio repository | `/api/v2/portfolio`, `/api/v2/account/positions` | portfolio repository | trader-scoped current | fail-closed | PARTIAL/MISSING | Portfolio | focused scope tests |
| Backtests/replay | backtests/replay | static/snapshot likely | backend backtest service | `/api/v2/backtests` | backtest runner | run timestamp | gate if absent | SNAPSHOT/PARTIAL | Research/Backtest | missing |
| Alerts | alerts/status | `/api/v2/alerts` wrapper | alert repository/delivery backend | `/api/v2/alerts`, alert event | alert service | current preferences/actions | fail-closed | PARTIAL/MISSING | Alerts | partial |
| Ingestor/data lag/service health | status/admin | static/admin payloads | admin monitoring APIs | `/api/admin/monitoring/*`, ingestor event | monitoring service | heartbeat/lag thresholds | admin incident | SNAPSHOT/PARTIAL | Platform Ops | missing |
| Audit events/live readiness/logs | admin/status | static/admin payloads and `/api/v2/execution/audit-events` | audit/readiness backend | `/api/admin/audit`, `/api/admin/readiness` | audit service/live gate | immutable timestamped | admin only | PARTIAL | Security/Ops | missing full pass |

## Required per-metric metadata not yet universal

Every visible metric still needs a normalized envelope carrying source, source_type, endpoint/stream, repository/service/ingestor, timestamp, received_at, lag_ms, freshness_status, data_quality_status, missing_fields, owner, and test coverage. Current `ApiV2Envelope` covers some fields but not all Phase B requirements.

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

