# V2 Paper Fill Position Mark To Market Equity Repair Report

Gate: `V2_PAPER_FILL_POSITION_MARK_TO_MARKET_EQUITY_REPAIR_READY`
Generated EST: `2026-06-09T23:01:25-04:00`
Accepted paper fills: `1`
Economic paper fills: `1`
Held paper rows: `0`
Open paper positions: `1`
Paper current session equity: `9999.97494497`
Paper current session PnL: `-0.02505503`
Zero PnL reason: `EQUITY_RECOMPUTED_FROM_CURRENT_LEDGER_AND_V2_MARKET_PRICES`

## Blockers

- none

## Runtime Notes

- none

## Validation

- py_compile: `PASS`
- focused_paper_accounting_tests: `PASS: 36 passed`
- frontend_typecheck: `PASS`
- frontend_build: `PASS`
- route_crawl: `PASS_COMMAND_EXIT_0: production 33/34, local 32/34; remaining markers are admin monitor/script-registry classifications, not paper accounting blockers`
- old_redis_scan: `PASS`
- exchange_mutation_scan: `PASS`
- raw_secret_scan: `PASS`

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.
