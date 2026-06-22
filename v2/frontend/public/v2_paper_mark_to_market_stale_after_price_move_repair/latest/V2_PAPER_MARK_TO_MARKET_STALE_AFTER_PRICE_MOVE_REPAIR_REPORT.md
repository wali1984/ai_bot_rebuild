# V2 Paper Mark To Market Stale After Price Move Repair Report

Gate: `V2_PAPER_MARK_TO_MARKET_STALE_AFTER_PRICE_MOVE_REPAIR_READY`
Generated EST: `2026-06-09T23:02:26-04:00`
Accepted paper fills: `1`
Economic paper fills: `1`
Open paper positions: `1`
Paper current session equity: `9999.97494497`
Paper current session PnL: `-0.02505503`
Unrealized PnL: `-0.02505503`
Zero PnL reason: `EQUITY_RECOMPUTED_FROM_CURRENT_LEDGER_AND_V2_MARKET_PRICES`

## Result

The monitor condition triggered: market price moved while paper equity had been flat because the accepted fill entry/fill price was being rebuilt from current price. The paper ledger now preserves immutable fill economics and separates current mark price for mark-to-market.

Current HYPEUSDT evidence: `entry_price=55.877`, `current_mark_price=55.933`, `unrealized_pnl=-0.02505503`, `equity=9999.97494497`.

## Validation

- py_compile: `PASS`
- focused_paper_accounting_tests: `PASS: 36 passed`
- old_redis_scan: `PASS`
- exchange_mutation_scan: `PASS`
- raw_secret_scan: `PASS`

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.
