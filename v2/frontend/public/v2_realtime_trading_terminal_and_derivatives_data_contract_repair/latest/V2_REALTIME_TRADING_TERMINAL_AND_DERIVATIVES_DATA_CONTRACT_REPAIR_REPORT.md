# V2 Realtime Trading Terminal And Derivatives Data Contract Repair Report

Gate: `V2_REALTIME_TRADING_TERMINAL_AND_DERIVATIVES_DATA_CONTRACT_REPAIR_READY`
Generated EST: `2026-06-09T18:18:15-04:00`
Trade terminal: `TRADE_TERMINAL_RUNTIME_PAYLOAD_READY`
Derivatives: `DERIVATIVES_TYPED_CONTRACT_READY`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Binance private execution: `SIGNED_READS_RECOVERED_BALANCE_HOLD`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`
Paper current session equity: `10000.0`
Paper current session PnL: `0.0`
Prediction source parity: `ALL_TIMEFRAME_SOURCE_PARITY_LABELLED`
Signal table mapping: `SIGNAL_TABLE_DISPLAY_FIELDS_READY`
Liquidation freshness: `CURRENT_OR_RECENT`
Production status: `PRODUCTION_ROUTES_FETCHED_NO_STALE_MARKERS`

Blockers:
- none

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.
