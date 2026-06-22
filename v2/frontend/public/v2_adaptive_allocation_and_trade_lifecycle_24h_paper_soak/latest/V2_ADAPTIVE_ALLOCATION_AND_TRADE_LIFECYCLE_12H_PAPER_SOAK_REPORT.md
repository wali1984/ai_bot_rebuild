# V2 Adaptive Allocation And Trade Lifecycle 12h Paper Soak Report

Generated: `2026-06-16T11:50:08Z`
First observation EST: `2026-06-15T19:49:19-04:00`
Latest observation EST: `2026-06-16T07:50:08-04:00`

Gate:

```text
V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_READY
```

Proof status: `SOAK_12H_COMPLETE`
Completion marker: `V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_COMPLETE_READY`
Soak window: `12h`
Required seconds: `43200`
Observed hours: `12.0136`
Completion-window elapsed seconds: `43249`
Density-eligible observations: `147`
Expected observations: `144`
Minimum required observations: `115`
Observation density status: `CLEAR`
Last observation age seconds: `0`
Last observation freshness status: `CLEAR`
12h complete: `True`
1h complete: `False`
12h legacy alias complete: `True`
24h legacy alias complete: `False`

Current monitored metrics:

- Accepted allocations: `663`
- Blocked allocations: `588`
- Position source: `operator_runtime:v2_portfolio_state.open_positions`
- Raw Redis position rows: `0`
- Canonical Redis open position rows: `0`
- Total paper exposure USDT: `1421.80845952`
- Open positions: `25`
- Closed trades: `89`
- Realized PnL USD: `12.8520687`
- Unrealized PnL USD: `-7.95003066`
- Outcome labels: `89`
- Trainer feedback rows: `44`
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

READY means the paper-only soak observer is wired and safe to run. It does not claim 12h proof until `soak_complete` is true.
