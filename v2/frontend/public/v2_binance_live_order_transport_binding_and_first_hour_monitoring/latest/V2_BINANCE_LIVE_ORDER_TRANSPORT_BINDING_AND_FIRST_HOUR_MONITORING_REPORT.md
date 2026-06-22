# V2 Binance Live Order Transport Binding And First Hour Monitoring Report

Gate: `V2_BINANCE_LIVE_ORDER_TRANSPORT_BINDING_AND_FIRST_HOUR_MONITORING_BLOCKED`
Generated EST: `2026-06-07T15:21:01-04:00`
Live gate: `blocked_human_only`
Trader execution enabled: `False`
Live order transport bound: `True`
Writes exchange orders: `False`
Places real order: `False`
Accepted symbols: `['BNBUSDT', 'BTCUSDT', 'ETHUSDT', 'PAXGUSDT', 'XAUTUSDT', 'ZECUSDT']`

Transport state:
- status: `LIVE_ORDER_TRANSPORT_BLOCKED`
- order_submitted: `False`
- kill_switch_active: `False`
- runtime_validation: `False`
- blockers: `LIVE_GATE_RUNTIME_STATE_STALE, LIVE_ORDER_TRANSPORT_WRITE_ENV_NOT_ENABLED, RISK_GATEWAY_DECISION_ID_MISMATCH`

Safety: no leverage or margin mutation, no transfer/withdrawal call, no Redis trim, no legacy restart, no raw credential output.
