# V2 Compliant Exchange Connectivity Recovery Or Failover Report

Gate: `V2_COMPLIANT_EXCHANGE_CONNECTIVITY_RECOVERY_OR_FAILOVER_BLOCKED`
Generated EST: `2026-06-21T20:26:46-04:00`
Live gate: `blocked_human_only`
Trader execution enabled: `False`
Transport bound: `True`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Binance private execution: `SIGNED_READS_RECOVERED_REQUIRES_REVALIDATION`
Signed-read classification: `NO_451_DETECTED`
Public runtime status: `BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD`
Failover status: `FAILOVER_CANDIDATES_EVALUATED_AUDITED_APPROVAL_REQUIRED`
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

Safety: Binance private execution remains compliance-held while HTTP 451 persists. No order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy/evasion path. Public market, trainer, risk, orchestrator, paper-shadow, website, and monitoring continue.
