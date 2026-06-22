# NERVYX Realtime Parity Matrix

| Category | Web subscription | iOS subscription | Fallback API | Freshness | Reconnect/stale behavior | Permission | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ticker | useMarketDataStream/useRealtimeResource | mobile API polling; WebSocketClient available | /api/v2/market/overview | 15s | bounded reconnect in web hook; iOS WebSocketClient lifecycle | public/trader | accounted |
| candle | V2RealtimeMarketChart/market chart payloads | mobile market detail planned | /operator_runtime/v2_market_chart/latest/*.json | 30s | last valid chart state retained | public/trader | accounted |
| depth | OrderBookPanel | not primary iOS screen yet | /api/v2/market/depth or payload fallback | 10s | show delayed/stale | trader | accounted |
| recent trade | RecentTradesTape | not primary iOS screen yet | market detail fallback | 10s | show delayed/stale | trader | accounted |
| funding | derivatives/market intelligence panels | not primary iOS screen yet | /api/v2/market/overview | 60s | show delayed/stale | public/trader | accounted |
| open interest | derivatives/market intelligence panels | not primary iOS screen yet | /api/v2/market/overview | 60s | show delayed/stale | public/trader | accounted |
| liquidation | liquidation bridge panels | not primary iOS screen yet | operator runtime payload fallback | 60s | show delayed/stale | public/trader | accounted |
| long/short | market intelligence panels | not primary iOS screen yet | operator runtime payload fallback | 60s | show delayed/stale | public/trader | accounted |
| basis | derivatives panels | not primary iOS screen yet | operator runtime payload fallback | 60s | show delayed/stale | trader | accounted |
| signal | useRealtimeResource/usePaperActivityStream | SignalsView polling models | /api/v2/signals | 15s | dedupe by server id where available | trader | accounted |
| prediction | AI pages/trainer monitor | Dashboard/Signals model fields | /api/v2/trainer/* and mobile dashboard | 30s | show stale state | trader/admin | accounted |
| trainer state | trainer monitor/admin | Dashboard/Monitor/Admin views | /api/v2/mobile/dashboard and admin | 30s | show stale state | admin/trader summary | accounted |
| strategy/regime | orchestrator/admin pages | admin only planned summary | /api/v2/orchestrator/status | 30s | show stale state | admin | accounted |
| risk state | risk panels | RiskControlView | /api/v2/risk/status and mobile risk | 15s | last valid + stale label | trader/admin | accounted |
| position | portfolio/positions | PositionsView | /api/v2/portfolio or mobile positions | 15s | last valid + stale label | trader | accounted |
| order | executions/order tables | paper summary only | /api/v2/orders or execution payload | 15s | last valid + stale label | trader | accounted |
| execution | executions tables | paper summary only | /api/v2/paper/fills | 15s | last valid + stale label | trader/admin | accounted |
| portfolio | portfolio panels | PositionsView/Dashboard | /api/v2/portfolio and mobile positions | 15s | last valid + stale label | trader | accounted |
| alert | alerts pages | AlertsView | /api/v2/alerts/mobile alerts | 30s | last valid + stale label | trader/admin | accounted |
| ingestor | admin ingestors/status | MonitorView summary | admin status payloads | 30s | admin-only stale diagnostics | admin | accounted |
| orchestrator | admin orchestrator | admin only planned summary | /api/v2/orchestrator/status | 30s | admin-only stale diagnostics | admin | accounted |
| trader | account/session | AuthManager session | /api/auth/me | session | backend authoritative roles | authenticated | accounted |
| system health | monitor/status | MonitorView/Dashboard | /health /api/v2/mobile/health | 30s | last valid + stale label | public/admin | accounted |
| live readiness | live readiness banner | RiskControlView/Admin | /api/v2/live-readiness or v1 banner | 30s | must show blocked state | public/trader/admin | accounted |

Rule: snapshot or polling paths are not labeled as live. UI must show Delayed, Stale, Offline, or Reconnecting when event freshness is not current.
