# V2 Exchange Filter Risk Profile Alignment And Min Order Execution Report

Gate: `V2_EXCHANGE_FILTER_RISK_PROFILE_ALIGNMENT_AND_MIN_ORDER_EXECUTION_BLOCKED`
Generated EST: `2026-06-07T22:40:33-04:00`
Live gate: `enabled_operator_approved`
Active risk profile: `conservative_min_executable`
Accepted symbols: `['BNBUSDT', 'BTCUSDT', 'ETHUSDT', 'PAXGUSDT', 'XAUTUSDT', 'ZECUSDT']`
Exchange-filter aligned candidate: `True`
Pre-submit status: `LIVE_ORDER_TRANSPORT_BLOCKED`
Submit result status: `LIVE_ORDER_TRANSPORT_SUBMIT_SKIPPED_PRECHECK_BLOCKERS`
Order submitted: `False`

Blockers:
- `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`

Safety: no test-order/cancel/modify, no leverage or margin mutation, no transfer/withdrawal, no legacy restart, no Redis trim, no raw credential output.
