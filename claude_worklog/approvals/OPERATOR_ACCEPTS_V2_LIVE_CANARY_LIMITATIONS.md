# OPERATOR ACCEPTS V2 LIVE CANARY LIMITATIONS

This is live canary only.
Legacy shutdown is not approved.
Redis trim is not approved.
Leverage change is not approved.
Margin mode change is not approved.

Approved live canary mode: LEGACY_SIGNAL_V2_EXECUTION_CANARY
Approved live symbols: BTCUSDT
Max notional USDT per order: 55
Max daily live trades: 1
Max daily loss USDT: 5

Emergency kill switch is required.

Operator accepts V2 limitations:
- full observation is partial
- checkpoint parity is false
- policy architecture parity is false
- this canary is legacy-signal-assisted
- this canary does not prove production equivalence
- this canary does not approve legacy shutdown

live_gate target for canary only: live_canary_operator_approved
live_symbols target for canary only: [BTCUSDT]
