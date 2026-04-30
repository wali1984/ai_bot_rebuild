# Exchange Unknown Resolution Policy

## Blocking policy
- `unknown_exchange_use` in production code is blocking.
- `exchange_context_only` is non-blocking and counted.
- `docs_exchange_context` is non-blocking.
- `test_exchange_context` is non-blocking.
- `comment_exchange_context` is non-blocking.

## Class-specific policy
- `exchange_error_handling` is non-blocking unless it wraps order/leverage/margin mutation paths.
- `exchange_client_init` is Tier A when used by trader/execution/risk paths.
- `market_data` and `websocket_market_data` are Tier A only when they feed live trading or trainer signal generation.
- `order_create`, `order_cancel`, `leverage_change`, `margin_change`, `stop_loss`, `take_profit`, `reduce_only` are always Tier A P0.

## Escalation
- Any unresolved `unknown_exchange_use` with `production_relevance=production` remains a blocker until converted to a concrete class or explicitly risk-reviewed with deterministic evidence.
