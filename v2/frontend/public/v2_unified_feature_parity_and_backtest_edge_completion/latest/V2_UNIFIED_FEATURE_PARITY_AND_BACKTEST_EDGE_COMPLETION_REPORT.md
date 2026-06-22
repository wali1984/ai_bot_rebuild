# V2 Unified Feature Parity And Backtest Edge Completion Report

Gate: `V2_UNIFIED_FEATURE_PARITY_AND_BACKTEST_EDGE_COMPLETION_BLOCKED`
Generated EST: `2026-06-04T22:10:00-04:00`
Prediction grid: `505/505` current
Signals: `505`
Missing lineage rows: `0`
Invalid/missing price targets: `0`
Operator-reported prior feature blockers: `13688`
Available prior row-level feature blockers: `6260`
Current feature blockers: `5569`
Tensor coverage avg: `71.07550449701459`
Backtest worker metrics written: `True`
Backtest sample count: `18426`
Edge verdict: `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`
Recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`

Live/canary remain blocked. This artifact does not emit live-ready or canary-ready approval markers.

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`
- blockers: `UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL, BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM, LIVE_RISK_CAPS_OPERATOR_REQUIRED`

Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no Redis trim, no legacy restart.
