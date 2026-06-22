# V2 Adaptive AI Capital Allocation And Dynamic Risk Budget Report

Gate: `V2_ADAPTIVE_AI_CAPITAL_ALLOCATION_AND_DYNAMIC_RISK_BUDGET_READY`
Generated EST: `2026-06-11T16:19:38-04:00`
Allocator: `V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR`
Paper allocator active: `true`
Live pre-submit allocator active: `true`
Paper candidates with allocation: `1440`
Accepted allocation count: `412`
Blocked allocation count: `1028`
Fixed runtime 200 USDT sizing: `false`
Static trade size used: `false`
Live submit changed: `false`

## Result

Current paper trade-management and live pre-submit sizing now use adaptive
capital allocation from confidence, expected move after cost, market-state
integrity, volatility, liquidity, spread/slippage, drawdown, exposure, account
equity, available margin, and exchange filters. The risk layer remains a hard
percentage-based safety envelope; it no longer acts as a fixed dollar trade-size
rule in the current paper/live pre-submit path.

Older operator-packet and canary enablement scripts still contain legacy
`max_notional_per_trade` compatibility fields. They are not the active allocator
runtime path. The live one-order canary path was not changed because changing
that exchange-touching path requires explicit operator approval beyond this
paper/pre-submit lane.

## Validation

- `python -m py_compile`: PASS
- focused backend tests: PASS, `133 passed`
- frontend typecheck: PASS
- frontend build: PASS, latest asset `index-aZ5zSjcz.js`
- paper loop run: PASS, `V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK`
- local dashboard route crawl: PASS
- production route crawl: PASS with admin caveats on monitor-center and script-registry proof markers
- static sizing scan: PASS for current runtime, with legacy packet/canary caveats recorded
- old Redis scan: PASS, touched runtime writes are `v2:` only
- exchange mutation scan: PASS, no validation order/test-order/cancel/modify/leverage/margin mutation
- raw secret scan: PASS
- trainer bridge scan: PASS

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation,
no old Redis write, no legacy restart, no Redis trim, no raw credential output,
and no trainer bridge unmask.
