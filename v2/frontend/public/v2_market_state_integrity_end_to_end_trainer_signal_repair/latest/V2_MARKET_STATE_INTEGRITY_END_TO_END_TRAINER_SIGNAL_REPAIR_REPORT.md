# V2 Market State Integrity End To End Trainer Signal Repair Report

Gate: `V2_MARKET_STATE_INTEGRITY_END_TO_END_TRAINER_SIGNAL_REPAIR_READY`
Generated EST: `2026-06-10T12:25:31-04:00`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`

## Result

The market-state integrity layer is now attached end to end:

- Native CUDA trainer prediction rows carry `market_state_id`, `market_state_integrity_score`, `valid_for_training`, `valid_for_prediction`, `valid_for_risk`, `valid_for_orchestrator`, and `valid_for_paper`.
- All-timeframe signal rows preserve the same integrity fields for paper/risk/orchestrator display and website explainability.
- Current market-state integrity keys are published as `v2:market_state_integrity:{symbol}:{timeframe}`.
- The natural-language explainer now uses the canonical all-timeframe signal payload instead of broad stale Redis scans.
- Native trainer preview lineage no longer overwrites canonical `v2:paper:ledger`, `v2:risk:decisions`, or `v2:orchestrator:decisions`.

## Current Runtime Sample

- Prediction rows: `670`
- Current prediction rows: `670`
- Valid for training: `670`
- Valid for prediction: `670`
- Valid for paper: `670`
- Missing market-state ids: `0`
- Published signal rows: `670`
- Signal rows missing market-state ids: `0`
- Paper-fill allowed signal rows: `18`
- Paper accepted fills: `22`
- Paper held rows: `0`
- Paper shadow observations: `261`
- Paper equity: `10000.32588729`
- Paper PnL: `0.32588729`
- Explanation rows: `30`

Current dominant paper block reasons are model gates, not missing integrity:

- `confidence_below_threshold`: `646`
- `expected_move_after_cost_below_threshold`: `187`

## Safety

No real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.

## Validation

- `python -m py_compile`: `PASS`
- focused backend tests: `PASS: 53 passed`
- frontend typecheck: `PASS`
- frontend build: `PASS`
- local dashboard route crawl: `PASS: console 200/no-repair markers`
- production route crawl: `PASS_WITH_REPAIR_MARKERS: all crawled routes HTTP 200; /admin/mission-control?role=admin and /admin/monitor-center?role=admin still marked repair by crawler`
- systemd failed units: `PASS: 0 failed`
- exchange mutation scan over touched files: `PASS: no mutation implementation`
- old Redis scan over touched files: `PASS: V2 writes only; intentional test fixture covers rejected legacy key`
- raw secret scan over touched files: `PASS`
