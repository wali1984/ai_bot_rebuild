# Trader Canonical Field Registry

Generated: 2026-06-24

This registry is the single interpretation layer for repeated trader-facing business fields. Pages must consume canonical selectors or the trader snapshot store; they must not independently reinterpret units, freshness, null handling, or source meaning.

Source of truth in code: `frontend/src/data/canonicalFieldRegistry.ts`.

## Display Rules

- Missing values stay missing. They are not converted to zero.
- Zero is valid only when the registry marks `zeroIsValid: true` and the rendered metric has source, source type, timestamp, age, and quality metadata.
- Account fields prefer `/api/v2/trader/snapshot.account`; identity-only fallback may use `/api/auth/me`.
- Position fields prefer `/api/v2/trader/snapshot.positions`; fallback is scoped paper account repository data only.
- Market fields prefer `/api/v2/trader/snapshot.market_status`; fallback is read-only market feed data.
- Signal fields prefer `/api/v2/trader/snapshot.signals`; fallback is signal truth data with stable IDs.
- All rendered metric elements must include `data-field-id`, `data-source`, `data-source-type`, `data-timestamp`, `data-age-ms`, and `data-quality`.

## Required Fields

| Field ID | Type | Unit | Precision | Null behavior | Zero valid | Preferred source | Fallback source | Freshness | Formatter | Pages allowed |
|---|---|---|---:|---|---|---|---|---|---|---|
| `account.trader_id` | string | id | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | id | account-settings |
| `account.account_id` | string | id | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | id | account-settings, portfolio |
| `account.mode` | enum | status | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | enumStatus | account-settings, dashboard, portfolio, positions, executions, history, markets, market-detail, trade, derivatives, signals, ai-predictions, backtests, replay, research, technical-analysis, alerts |
| `account.connection_status` | enum | status | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | enumStatus | account-settings, dashboard, portfolio, trade |
| `account.equity` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.available_balance` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.used_balance` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.realized_pnl` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.unrealized_pnl` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.daily_pnl` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.total_pnl` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.exposure` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | usd | account-settings, dashboard, portfolio, trade |
| `account.drawdown` | decimal | percent | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | percent | account-settings, dashboard, portfolio, trade |
| `account.open_position_count` | integer | count | 0 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | integer | account-settings, dashboard, portfolio, trade |
| `account.open_order_count` | integer | count | 0 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | integer | account-settings, dashboard, portfolio, trade |
| `account.execution_count` | integer | count | 0 | blocked_for_required_display | yes | /api/v2/trader/snapshot.account | /api/auth/me for identity only | account_refresh 30000ms | integer | account-settings, dashboard, portfolio, trade |
| `position.id` | string | id | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | id | dashboard, portfolio, positions, trade, history |
| `position.symbol` | string | symbol | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | symbol | dashboard, portfolio, positions, trade, history |
| `position.side` | enum | side | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | side | dashboard, portfolio, positions, trade, history |
| `position.quantity` | decimal | base_asset | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | quantity | dashboard, portfolio, positions, trade, history |
| `position.entry_price` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | price | dashboard, portfolio, positions, trade, history |
| `position.entry_price_source` | string | text | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | text | dashboard, portfolio, positions, trade, history |
| `position.mark_price` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | price | dashboard, portfolio, positions, trade, history |
| `position.mark_price_source` | string | text | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | text | dashboard, portfolio, positions, trade, history |
| `position.mark_age_ms` | integer | milliseconds | 0 | blocked_for_required_display | yes | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | ageMs | dashboard, portfolio, positions, trade, history |
| `position.exit_price` | decimal | usd | 8 | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | price | dashboard, portfolio, positions, trade, history |
| `position.exit_price_source` | string | text | n/a | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | text | dashboard, portfolio, positions, trade, history |
| `position.notional` | decimal | usd | 2 | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | usd | dashboard, portfolio, positions, trade, history |
| `position.unrealized_pnl` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | usd | dashboard, portfolio, positions, trade, history |
| `position.realized_pnl` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | usd | dashboard, portfolio, positions, trade, history |
| `position.pnl_percent` | decimal | percent | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | percent | dashboard, portfolio, positions, trade, history |
| `position.stop` | decimal | usd | 8 | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | price | dashboard, portfolio, positions, trade, history |
| `position.targets` | array | usd | 8 | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | jsonList | dashboard, portfolio, positions, trade, history |
| `position.liquidation_price` | decimal | usd | 8 | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | price | dashboard, portfolio, positions, trade, history |
| `position.strategy_id` | string | id | n/a | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | id | dashboard, portfolio, positions, trade, history |
| `position.signal_id` | string | id | n/a | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | id | dashboard, portfolio, positions, trade, history |
| `position.prediction_id` | string | id | n/a | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | id | dashboard, portfolio, positions, trade, history |
| `position.risk_status` | enum | status | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | enumStatus | dashboard, portfolio, positions, trade, history |
| `position.decision_reasoning` | string | text | n/a | allowed_when_not_applicable | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | text | dashboard, portfolio, positions, trade, history |
| `position.updated_at` | timestamp | timestamp | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.positions | scoped paper account repository | realtime 10000ms | timestamp | dashboard, portfolio, positions, trade, history |
| `market.symbol` | string | symbol | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | symbol | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.last_price` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | price | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.mark_price` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | price | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.index_price` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | price | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.change_1h` | decimal | percent | 2 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.change_4h` | decimal | percent | 2 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.change_24h` | decimal | percent | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.high_24h` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | price | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.low_24h` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | price | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.volume_24h` | decimal | base_asset | 4 | blocked_for_required_display | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | quantity | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.turnover_24h` | decimal | usd | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | usd | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.spread` | decimal | usd | 8 | blocked_for_required_display | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | price | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.funding_rate` | decimal | percent | 4 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.predicted_funding` | decimal | percent | 4 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.open_interest` | decimal | contract | 4 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | quantity | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.oi_change_1h` | decimal | percent | 2 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.oi_change_4h` | decimal | percent | 2 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.oi_change_24h` | decimal | percent | 2 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | percent | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.liquidations_1h` | decimal | usd | 2 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | usd | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.liquidations_24h` | decimal | usd | 2 | allowed_when_source_missing | yes | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | usd | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `market.long_short_ratio` | decimal | ratio | 4 | allowed_when_source_missing | no | /api/v2/trader/snapshot.market_status | /api/v2/market/overview or symbol detail read-only market feed | realtime 5000ms | ratio | dashboard, markets, market-detail, trade, positions, derivatives, technical-analysis |
| `signal.id` | string | id | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | id | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.symbol` | string | symbol | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | symbol | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.direction` | enum | side | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | side | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.timeframe` | string | text | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | text | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.entry` | decimal | usd | 8 | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | price | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.targets` | array | usd | 8 | allowed_when_not_applicable | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | jsonList | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.stop` | decimal | usd | 8 | allowed_when_not_applicable | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | price | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.invalidation` | decimal | usd | 8 | allowed_when_not_applicable | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | price | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.confidence` | decimal | percent | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | percent | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.expected_move` | decimal | percent | 2 | blocked_for_required_display | yes | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | percent | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.risk_reward` | decimal | ratio | 2 | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | ratio | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.status` | enum | status | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | enumStatus | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.strategy` | string | text | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | text | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.model_version` | string | text | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | text | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.risk_decision` | enum | status | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | enumStatus | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.created_at` | timestamp | timestamp | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | timestamp | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.expires_at` | timestamp | timestamp | n/a | allowed_when_not_applicable | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | timestamp | dashboard, signals, ai-predictions, trade, market-detail |
| `signal.evidence` | array | text | n/a | blocked_for_required_display | no | /api/v2/trader/snapshot.signals | /api/v2/signals/all-timeframe-truth | realtime 30000ms | jsonList | dashboard, signals, ai-predictions, trade, market-detail |

## Role Visibility

All fields in this registry are visible to authenticated `trader`, `admin`, and `superadmin` roles unless page RBAC denies the route. No field in this registry is public.

## Release Blockers Found In Before Audit

- Deployed trader pages rendered zero canonical field metadata attributes.
- Several requested surfaces required direct-route fallback instead of visible menu navigation.
- The before audit recorded HTTP failures on deployed trader pages.
- Replay landed on `/backtests`; technical analysis landed on `/landing`.
