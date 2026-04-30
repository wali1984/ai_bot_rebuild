# 12 Multi-Exchange Connector Requirements

## Requirement ID
V2-EXCHANGE-CONNECTOR-001

## Objective
Provide a pluggable futures-exchange connector interface with Binance Futures as first implementation.

## Connector interface (mandatory methods)
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

## Design constraints
1. Pluggable architecture
- Connector registry supports multiple futures exchanges without rewiring platform core.

2. Safety gates on mutation methods
- `create_order`, `cancel_order`, `set_leverage`, `set_margin_mode` remain blocked until live gates pass.
- Default mode for all connectors is non-live/blocked for mutations.

3. Capability declaration
- Each connector must publish capability profile (supported methods, limits, market/data caveats).

4. Error and health contract
- Standardized connector error model.
- Health heartbeat per connector instance.
- Circuit-breaker compatible responses.

5. Audit requirements
- Every connector call emits structured audit envelope with request/response metadata (redacted secrets).

## Initial rollout order
1. Binance Futures connector (reference implementation)
2. Additional futures connectors integrated via same interface without core platform rewrite

## Security requirements
- Exchange secrets stored server-side only; never exposed to GUI payloads.
- Per-connector credentials isolated by account/exchange scope.

## Pre-architecture acceptance
- Interface locked with mandatory methods.
- Live mutation gate policy explicitly defined.
- Binance-first + pluggable-next strategy documented.
