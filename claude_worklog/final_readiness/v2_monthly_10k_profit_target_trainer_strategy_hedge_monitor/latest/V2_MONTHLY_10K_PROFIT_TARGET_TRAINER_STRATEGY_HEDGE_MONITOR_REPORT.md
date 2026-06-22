# V2 Monthly 10K Profit Target Trainer Strategy Hedge Monitor Report

Gate: `V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_READY`

This monitor treats 10,000+ USDT/month as an evidence-based net-profit objective, not a guaranteed return.

| Field | Value |
|---|---:|
| Goal status | `LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL` |
| Paper equity | `12820.20978661` |
| Paper monthly run-rate net PnL | `58895.1458247` |
| Drawdown-adjusted monthly projection | `28490.55123707709` |
| Required monthly return pct | `0.7800184370184369` |
| Live available margin | `0.0` |
| Live target executable | `False` |
| Trainer capability | `TRAINER_ACTIVE_BUT_INSUFFICIENT_FEEDBACK` |
| Hedge status | `HEDGING_BLOCKED_NO_VALID_HEDGE_CONTEXT` |
| Simulation status | `INSUFFICIENT_EVIDENCE` |

| Adaptive leverage/margin status | `LIVE_READY_BALANCE_HELD_NO_ACTION` |
| Paper recommended leverage | `1.0` |
| Paper recommended margin mode | `ISOLATED_PAPER_SIMULATION` |
| Live leverage/margin action | `LIVE_READY_BALANCE_HELD_NO_ACTION` |

Blockers:
- capital shortfall: live target is not executable because available margin is below minimum order margin
- trainer feedback missing strategy/hedge/regime fields on some closed-trade outcomes

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no trainer bridge unmask.

Strategy families monitored: `12`. Feedback status: `MISSING_STRATEGY_HEDGE_FEEDBACK_FIELDS`.
