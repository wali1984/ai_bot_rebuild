# 10 Multi-Trader Fleet Architecture

## Objective
Support many trader instances according to system capacity.

## Trader instance schema
- `trader_id`
- `account_id`
- `exchange_id`
- `strategy_profile`
- `symbol_scope`
- `risk_profile`
- `paper_live_mode`
- `assigned_symbols`
- `heartbeat`
- `pnl`
- `attribution_completeness`

## Fleet controls
- Dynamic trader add/remove.
- Capacity-aware assignment and sharding.
- Per-trader paper/live mode with safe defaults.
- Assignment rebalancing and quarantine workflows.

## Authority model
Risk Gateway remains final authority for allow/block of execution intents.
