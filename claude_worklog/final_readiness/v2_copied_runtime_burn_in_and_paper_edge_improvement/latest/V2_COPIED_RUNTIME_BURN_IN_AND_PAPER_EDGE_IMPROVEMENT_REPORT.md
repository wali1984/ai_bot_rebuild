# V2 Copied Runtime Burn-In and Paper-Edge Improvement - Snapshot Report

- **Task ID**: `v2_copied_runtime_burn_in_and_paper_edge_improvement`
- **Generated EST**: 2026-06-21T19:31:44-0400
- **GO/NO-GO**: `V2_COPIED_RUNTIME_BURN_IN_AND_PAPER_EDGE_IMPROVEMENT_BLOCKED`
- **Live gate**: `blocked_human_only`
- **Live symbols**: `[]`

## Status

Burn-in runtime is fresh enough for observation, but live/canary stays blocked: paper edge proven=False, liquidation events=10004, after-cost bps=-4.879330541891545, paper PnL=0.0.

## Runtime

- Active V2 services: 58 / 93
- Active V2 timers: 33
- Minimum required runtime uptime: 0.19h
- Minimum copied-component uptime: 0.19h
- Burn-in windows: 1h=False, 6h=False, 12h=False

## Liquidation Bridge / Levels

- Bridge active: False
- Levels active: True
- WSS active: True
- `v2:liquidations:events` XLEN: 10004
- `v2:market:liquidation_levels:*` keys: 0
- Operational proof: `MEASURED_EVENTS_OBSERVED`

## Symbols / Features / Trainer

- Dynamic symbols resolved: 86
- Dynamic discovered symbols: 89
- 25-symbol baseline retained: False
- Symbol profile: `dynamic_or_baseline`
- Trainer role: `copied_parity_baseline_bridge`

## Paper Edge

- Paper edge proven: False
- Paper PnL: 0.0
- After-cost expectancy bps: -4.879330541891545
- Post-hoc verdict: `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`
- Live recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`

## Trading Platform

- Current HTTP probes: 9 / 9 passed
- Prior rendered route crawl: 34 routes, 0 failed
- Execution adapter: `v2_default_blocked_execution_adapter`

## Block Reasons

- `required_runtime_services_missing`
- `required_runtime_services_inactive`
- `burn_in_12h_window_not_complete`
- `dynamic_symbol_baseline_not_held`
- `v2_market_liquidation_levels_zero_keys`
- `paper_edge_not_proven`
- `operator_edge_thresholds_not_set`

## Safety

No live/canary/shutdown/Redis-trim approval was created. No exchange mutation,
order endpoint, leverage, or margin path was invoked. Legacy root runtime was
not restarted.
