# V2 Backend Source Map

Date: 2026-06-15
Status: Initial audit map. This is not a wiring-complete claim.

| Data category | Current source found/expected | API target | Realtime target | Status | Notes |
| --- | --- | --- | --- | --- | --- |
| Market prices/candles/depth/trades | backend market API plus frontend Binance public fallback | `/api/v2/market/*` | ticker/candle/depth/trade | PARTIAL | Backend availability not confirmed locally; fallback is read-only only. |
| Funding/OI/long-short/basis | Binance public fallback and expected derivatives backend | `/api/v2/derivatives/*` | funding/open_interest/long_short | PARTIAL | No fake liquidation/exchange comparison. |
| Liquidations/heatmap/map | expected local liquidation ingestor/WSS evidence | `/api/v2/derivatives/liquidations` | liquidation | MISSING/PARTIAL | Must wire or gate. |
| Signals/evidence | expected signal repository/publisher | `/api/v2/signals`, `/api/v2/signals/{id}` | signal | PARTIAL/MISSING | Trader scope checks exist; full lifecycle missing. |
| AI predictions/model state | expected trainer prediction publisher/model registry | `/api/v2/ai/predictions`, `/api/v2/ai/model-state` | prediction | PARTIAL/MISSING | Static/snapshot payloads must not appear live. |
| Trainer status/jobs | expected trainer service/admin endpoint | `/api/v2/trainer/*`, `/api/admin/trainer` | trainer | SNAPSHOT/PARTIAL | Admin incident until backend endpoint validated. |
| Strategy/orchestrator | expected orchestrator worker/service | `/api/admin/orchestrator` | orchestrator | SNAPSHOT/PARTIAL | Do not modify strategy logic without explicit approval. |
| Risk decisions/blocks | expected risk controller/service | `/api/admin/risk` | risk | SNAPSHOT/PARTIAL | Do not change risk logic. |
| Traders/bots | expected trader runtime state | `/api/admin/traders` | trader | SNAPSHOT/PARTIAL | Admin only. |
| Orders/fills/executions | expected paper execution ledger | `/api/v2/execution/*`, `/api/admin/execution` | order/execution | PARTIAL/MISSING | No live mutation. |
| Portfolio/positions/balances | expected trader-scoped paper repository | `/api/v2/portfolio`, `/api/v2/account/positions` | position | PARTIAL/MISSING | Fail closed without scope proof. |
| Backtests/replay | expected backtest runner/repository | `/api/v2/backtests` | optional replay events | SNAPSHOT/PARTIAL | Public/trader modules blocked until real source. |
| Alerts | expected alert repository/delivery | `/api/v2/alerts` | alert | PARTIAL/MISSING | CRUD requires audit. |
| Ingestor status/data lag/service health | expected monitoring service | `/api/admin/monitoring/*`, `/api/admin/ingestors` | ingestor/system_health | SNAPSHOT/PARTIAL | Admin actionable incidents required. |
| Logs/errors/audit/live readiness | expected logs/audit/readiness services | `/api/admin/logs`, `/api/admin/audit`, `/api/admin/readiness` | system_health/risk | PARTIAL | Superadmin protection required for sensitive pages. |

## Required backend endpoints still needing audit/implementation proof

`/api/v2/realtime/manifest`, `/api/v2/data-health`, `/api/v2/data-coverage`, derivatives endpoints, AI/trainer endpoints, admin monitoring endpoints, admin logs/audit/readiness endpoints.
