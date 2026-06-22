# V2 Market State Integrity Paper Equity And Website Realtime Full Repair Report

Gate: `V2_MARKET_STATE_INTEGRITY_PAPER_EQUITY_AND_WEBSITE_REALTIME_FULL_REPAIR_READY`
Generated EST: `2026-06-08T23:21:51-04:00`
Paper current session PnL: `0.0`
Paper current session equity: `10000.0`
Paper -49 classification: `STALE_OR_LIFETIME_PAPER_ONLINE_PNL_NOT_CURRENT_SESSION`
Current accepted paper fills: `0`
Current held paper rows: `122`
Market states scored: `732`
Training rows accepted/rejected: `0/732`
Website local routes OK: `9`
Website production routes OK: `7`
Live submit allowed: `False`

The current active paper source of truth is `v2:paper:ledger` and `v2:portfolio:state`. Historical paper-online `-49` PnL is labelled separately when it does not exist in the current ledger.

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy/evasion.
