# 09 Multi-Exchange Connector Architecture

## Connector interface
- `list_symbols`
- `get_symbol_metadata`
- `get_ohlcv`
- `get_orderbook`
- `get_funding`
- `get_open_interest`
- `get_account_state`
- `create_order`
- `cancel_order`
- `set_leverage`
- `set_margin_mode`

## Execution safety
- Live mutation methods remain blocked until live readiness gates pass.
- Default mutation mode is blocked/simulated in architecture baseline.

## Rollout
- Binance Futures is first connector.
- Additional futures exchanges are pluggable without rewriting core services.

## Connector standards
- Capability declaration per connector.
- Unified error model.
- Health heartbeat.
- Audit envelope for all calls (with redaction).
