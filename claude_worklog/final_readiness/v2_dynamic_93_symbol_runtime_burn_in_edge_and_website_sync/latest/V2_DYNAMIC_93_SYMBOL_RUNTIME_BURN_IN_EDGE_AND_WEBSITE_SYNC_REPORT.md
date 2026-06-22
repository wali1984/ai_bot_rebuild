# V2 Dynamic 93-Symbol Runtime Burn-In, Edge, and Website Sync

Generated EST: 2026-06-21T19:36:10-04:00

GO/NO-GO: `V2_DYNAMIC_93_SYMBOL_RUNTIME_BURN_IN_EDGE_AND_WEBSITE_SYNC_BLOCKED`

## Summary

- dynamic_symbol_count: `86`
- candidate_count: `86`
- trainer_row_count: `172`
- edge_verdict: `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`
- after_cost_expectancy_bps: `-4.879330541891545`
- primary_live_recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`

## Blockers

- `SYMBOL_COUNT_NOT_93`: symbol_count=86
- `PAPER_BACKTEST_EDGE_NOT_PROVEN`: EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED
- `WEBSITE_SYMBOLS_PAGE_NOT_WIRED`: Symbols page does not read the dynamic 93 payload.

## Safety

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`
- writes_legacy_redis: `false`
- writes_exchange_orders: `false`
- canary/live approval: `false`
