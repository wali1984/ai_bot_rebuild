# V2 Adaptive Allocation And Trade Lifecycle 1h Paper Soak Report

Generated: `2026-06-15T23:48:28Z`
First observation EST: `2026-06-15T18:48:26-04:00`
Latest observation EST: `2026-06-15T19:48:28-04:00`

Gate:

```text
V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_1H_PAPER_SOAK_READY
```

Proof status: `SOAK_1H_COMPLETE`
Completion marker: `V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_1H_PAPER_SOAK_COMPLETE_READY`
Soak window: `1h`
Required seconds: `3600`
Observed hours: `1.0006`
Completion-window elapsed seconds: `3602`
Density-eligible observations: `61`
Expected observations: `60`
Minimum required observations: `48`
Observation density status: `CLEAR`
Last observation age seconds: `0`
Last observation freshness status: `CLEAR`
1h complete: `True`
1h complete: `True`
12h legacy alias complete: `False`
24h legacy alias complete: `False`

Current monitored metrics:

- Accepted allocations: `565`
- Blocked allocations: `580`
- Position source: `redis:v2:paper:positions.canonical_open_rows`
- Raw Redis position rows: `12`
- Canonical Redis open position rows: `12`
- Total paper exposure USDT: `741.76675371`
- Open positions: `12`
- Closed trades: `76`
- Realized PnL USD: `13.03713032`
- Unrealized PnL USD: `1.65103772`
- Outcome labels: `76`
- Trainer feedback rows: `32`
- Same-symbol stack status: `CLEAR`
- Same-symbol hedge status: `CLEAR`
- Static sizing regression status: `CLEAR`
- Live blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`
- Live balance-hold status: `CLEAR`

High-severity alerts:

- `none`

Success criteria:

- `no_fixed_runtime_sizing_appears` = `True`
- `no_runaway_symbol_exposure` = `True`
- `no_unbounded_position_stacking` = `True`
- `no_same_symbol_accidental_hedge_unless_explicit` = `True`
- `closed_trades_gt_0` = `True`
- `outcome_labels_gt_0` = `True`
- `trainer_feedback_rows_gt_0` = `True`
- `paper_equity_updates_from_pnl` = `True`
- `drawdown_guard_evidence_present` = `True`
- `live_remains_balance_held` = `True`
- `completion_window_elapsed_seconds_gte_required` = `True`
- `observation_density_ok` = `True`
- `last_observation_fresh` = `True`

Safety boundary:

- This monitor does not write Redis.
- This monitor does not place real orders or call test-order.
- This monitor does not change leverage or margin mode.
- Live remains held by available-margin gating.

Interpretation:

READY means the paper-only soak observer is wired and safe to run. It does not claim 1h proof until `soak_complete` is true.
