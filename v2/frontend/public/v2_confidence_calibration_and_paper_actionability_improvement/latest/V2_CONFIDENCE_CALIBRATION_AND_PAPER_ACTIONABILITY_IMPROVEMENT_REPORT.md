# V2 Confidence Calibration And Paper Actionability Improvement Report

Gate: `V2_CONFIDENCE_CALIBRATION_AND_PAPER_ACTIONABILITY_IMPROVEMENT_READY`
Generated EST: `2026-06-10T14:15:07-04:00`
Prediction rows: `675`
Paper-allowed prediction rows: `20`
Confidence-blocked rows: `654`
Under-confident paper-only candidates: `163`
Recommended paper-only trial threshold: `0.54`
Current allowed clean positive-edge overlap: `2`
Paper threshold auto-applied: `False`
Live threshold changed: `False`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`
Paper equity: `10008.23058933`
Paper PnL: `8.23058933`

## Result

The confidence/actionability lane is complete as a read-only analysis and
paper-only simulation. The current model confidence head remains compressed near
the paper gate; no live risk, live threshold, leverage, margin, or exchange
execution behavior was changed.

## Blockers

- none

## Recommendation

Use the proposed threshold only as an operator-approved paper-only trial with
clean market-state, positive after-cost expected move, and one-hour monitoring.
Keep live in balance hold until available margin satisfies the minimum order.

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation,
no old Redis write, no legacy restart, no Redis trim, no raw credential output,
and no live threshold change.
