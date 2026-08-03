# API Gap Register (Pre-redesign)
Generated: 2026-06-12T22:22:41.000Z

## Scope
Inventory of frontend-required API/data contracts missing from production-grade trading/product usage and currently represented only by static payloads or placeholder behavior.

## Required vs current
| feature area | expected endpoint | current source/fallback | required fields | owner area | blocking severity | status |
|---|---|---|---|---|---|---|
| Public/trader login | `/api/auth/login` | No implemented auth handler in frontend code path (auth router metadata exists only) | username, password, token/mfa challenge, remember_me | Backend Auth / Security | HIGH | MISSING |
| Auth session refresh | `/api/auth/refresh` | Not implemented (session/token rotation missing) | refresh_token, rotated_access_token, expires_at | Backend Auth / Security | HIGH | MISSING |
| Session identity | `/api/auth/me` | Not implemented | sub, role, permissions, last_login | Backend Auth / Security | HIGH | MISSING |
| Auth logout | `/api/auth/logout` | Not implemented | session_invalidated, revocation_epoch | Backend Auth / Security | MED | MISSING |
| Admin user list | `/api/admin/users` | No CRUD endpoint body, metadata-only | users[], active, paper_account_id | Backend Admin / Identity | HIGH | MISSING |
| Admin user write | `/api/admin/users` (POST) | Not implemented | username, email, role, paper_account_id, alert_preferences | Backend Admin / Identity | HIGH | MISSING |
| Admin user update | `/api/admin/users/{id}` (PUT) | Not implemented | patchable user fields, audit_id, changed_by | Backend Admin / Identity | HIGH | MISSING |
| Admin user delete | `/api/admin/users/{id}` (DELETE) | Not implemented | id, deactivation_reason, audit_id | Backend Admin / Identity | HIGH | MISSING |
| Market listing | `/api/v2/market` | Static payloads under `/operator_runtime/...` | symbols[], last_price, change_1h/4h/24h, volume, ohlcv, freshness | Backend Market | CRITICAL | MISSING |
| Symbol market detail | `/api/v2/market/{symbol}` | Static payloads and mixed route fallback | symbol, price, high_low, funding, open_interest, freshness | Backend Market | CRITICAL | MISSING |
| Positions | `/api/v2/positions` | Static payloads + legacy files (`/operator_runtime/v2_portfolio_state/...`, `/paper_online/paper_positions.json`) | symbol, size, side, entry, pnl_unrealized, pnl_realized, paper| Backend Execution / Portfolio | CRITICAL | MISSING |
| Signals | `/api/v2/signals` | Static payload files and `signals` page adapters | signal_id, direction, entry, targets, confidence, expires_at, status | Backend Signals | CRITICAL | MISSING |
| Portfolio aggregate | `/api/v2/portfolio` | Static payload files | equity_curve, balances, pnl, exposures, source freshness | Backend Portfolio | CRITICAL | MISSING |
| Trade execution history | `/api/v2/executions` | Legacy static and page-level payloads | execution_id, symbol, side, size, status, fee, paper_flag | Backend Execution | HIGH | MISSING |
| Real-time market stream | `/ws/market-data` or `/events` | 5s-30s polling + stale static payloads | event_type, symbol, timestamp, received_at, lag_ms, stale | Backend Streams | CRITICAL | MISSING |
| Market orderbook/tape | `/api/v2/orderbook`, `/api/v2/trades/{symbol}` | Static/partial payloads in trade pages | bids/asks cumulative, trade_price, trade_size, side, time | Backend Market | HIGH | MISSING |
| Live readiness check | `/api/v1/risk/live-readiness` | Route referenced but currently not implemented in handler contract | risk_ok, blocked_reasons, paper_mode, gate_state | Backend Risk / Live Gate | HIGH | MISSING |
| Alert subscriptions | `/api/v2/alerts` (or equivalent) | `/api/v1/alerts` referenced but endpoint missing | symbol conditions, triggers, enabled flag, channels | Backend Alerts | MED | MISSING |
| Legacy alerts endpoint | `/api/v1/alerts` | Frontend references endpoint on alerts page; backend route missing | records[], total, next_page, stale_reason | Backend API | HIGH | MISSING |
| Ingestor control | `/api/v1/ingestors/{service}/control` | Route exists but behavior is control-only metadata in current code path | action, service, result, audit_id | Backend Ingestors / Admin | HIGH | SKELETON |
| Authenticated trader isolation | `/api/v2/trader/:id` context endpoints | Trader pages rely on shared/paper-wide runtime files | trader_id, watchlist, preferences, risk_profile | Backend Identity/Portfolio | HIGH | MISSING |
| Derivatives completeness | `/api/v1/derivatives/{funding|open-interest|liquidations|long-short|basis}` | Some route files exist and may be partial | symbol, exchange, exchange_timeframe, source_at | Backend Derivatives | MED | PARTIAL |
| Operator truth stream | `/api/v1/operator-runtime/stream` | `/api/v1/operator-runtime/truth` exists; stream path not observed in frontend | server_event, stream_token, lag_ms, stale | Backend Operator Runtime | MED | UNCONFIRMED |
