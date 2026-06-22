# V2 Binance Signed Read 451 Hold And Compliant Connectivity Recovery Report

Gate: `V2_BINANCE_SIGNED_READ_451_HOLD_AND_COMPLIANT_CONNECTIVITY_RECOVERY_BLOCKED`
Generated EST: `2026-06-21T20:26:46-04:00`
Live gate: `blocked_human_only`
Trader execution enabled: `False`
Transport bound: `True`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Signed-read classification: `NO_451_DETECTED`
Critical account-read gate: `CRITICAL_ACCOUNT_READ_GATE_BLOCKED`
Available margin: `None`
Position mode verified: `True`
Open orders verified: `False`
Order submitted: `False`
Retry allowed: `False`

Blockers:
- `ACCOUNT_CRITICAL_SIGNED_READS_NOT_PROVEN`
- `BALANCE_HOLD_CURRENT_BALANCE_READ_UNAVAILABLE`
- `BALANCE_HOLD_USING_LAST_KNOWN_CANDIDATE`
- `BINANCE_ACCOUNT_MARGIN_READ_FAILED`
- `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`
- `LIVE_GATE_NOT_ENABLED`
- `LIVE_GATE_RUNTIME_HEARTBEAT_REFRESH_FAILED`
- `LIVE_GATE_RUNTIME_NOT_ENABLED`
- `LIVE_GATE_RUNTIME_STATE_STALE`
- `LIVE_ORDER_TRANSPORT_SUBMIT_NOT_ENABLED`
- `LIVE_SYMBOL_SETS_DO_NOT_MATCH_ACCEPTED_SYMBOLS`
- `NO_ACCEPTED_SYMBOL_SIGNAL_CANDIDATE`
- `ORDER_TRANSPORT_SUBMIT_NOT_ENABLED`
- `TRADER_EXECUTION_ENABLED_NOT_TRUE`
- `TRADER_EXECUTION_NOT_ENABLED`

Safety: no order/test-order/cancel/modify, no leverage or margin mutation, no transfer/withdrawal, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy evasion path. Public market, trainer, risk, orchestrator, paper/shadow, and website updates remain active.
