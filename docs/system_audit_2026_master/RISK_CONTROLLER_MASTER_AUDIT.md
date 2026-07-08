# Risk Controller Master Audit — AI BOT V2
Generated: 2026-07-01T22:56:31Z

## How the Risk Controller Works

The risk gateway (**v2_risk_gateway_live_loop** + **v2_risk_gateway_runtime_worker**) sits between the orchestrator and the paper/live trader. It evaluates every orchestrator proposal against a comprehensive set of risk rules and either ALLOWS or DENIES each intent.

**Current behavior**: ALL intents → DENY (reason: `deny_default` — live gate is `blocked_human_only`)

## Runtime Status (from `v2:risk:gateway:heartbeat`)

```json
{
  "classification": "V2_RISK_GATEWAY_LIVE_OK",
  "current_gate_state": "blocked_human_only",
  "decisions_processed_total": 130,
  "denials_breakdown": {"deny_default": 130},
  "fail_closed": true,
  "gate_always_blocked_invariant": true,
  "v2_live_gate_enabled": false,
  "approves_live": false,
  "approves_canary": false,
  "current_gate_state_must_equal_blocked_human_only": true,
  "writes_legacy_redis": false
}
```

## Risk Rule Matrix

| Rule Category | Rule | Action if Fail |
|---------------|------|----------------|
| Gate Control | live_gate must equal blocked_human_only | DENY ALL |
| Gate Control | order_transport_submit_enabled must be true | DENY ALL |
| Gate Control | kill_switch must be inactive | DENY ALL |
| Data Freshness | feature_cutoff must be recent (< staleness threshold) | DENY symbol |
| Lineage | feature_snapshot_id must be valid | DENY symbol |
| Confidence | confidence_calibrated >= minimum threshold | DENY signal |
| Expected Move | expected_move_after_cost_bps must be positive (long) or negative (short) | DENY signal |
| Market State | market_state_integrity_score >= threshold | DENY symbol |
| Spread/Slippage | estimated slippage must be below max | DENY signal |
| Liquidity | sufficient order book depth required | DENY signal |
| Liquidation Risk | liq levels not too close to entry | DENY signal |
| Drawdown | portfolio drawdown within limits | DENY new positions |
| Symbol Exposure | single symbol exposure < max | DENY |
| Total Exposure | total portfolio notional < max | DENY |
| Portfolio Correlation | position correlations < max | DENY |
| Margin | margin sufficient for position | DENY |
| Leverage | leverage within max (1.0x at gate level) | DENY |

## What It Currently Blocks
- **Everything** — deny_default fires because live_gate = blocked_human_only
- This is correct and intended behavior

## What It Would Allow (if live gate were enabled)
- Signals meeting all the data freshness, confidence, expected move, spread, liquidity, liquidation, drawdown, and exposure checks
- In paper mode: any signal passing rules would route to paper trader

## Current Top Block Reasons
- `deny_default`: all 130 decisions denied with this reason
- Root cause: `current_gate_state: blocked_human_only`
- This is the correct expected behavior for the current non-live system

## Is Risk Too Strict, Too Loose, or Correct?
- **Correct** for current non-live mode: deny_default is the right behavior when live gate is off
- For paper mode evaluation: the deny_default means paper fills are also not being generated (paper trader receives orchestrator decisions but risk gateway blocks them all)
- **P1 concern**: Paper trading PnL and feedback are limited by this full block. Paper fills need to operate even when live gate is blocked to generate training data. The paper trader should be receiving some ALLOW decisions in paper mode.

## Keys Written
- `v2:risk:gateway:decisions`
- `v2:risk:gateway:latest`
- `v2:risk:gateway:heartbeat`
- `v2:risk:gateway:paper_online_decisions`
