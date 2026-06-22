# V2 One Hour Trainer Risk Orchestrator Data Website Monitor Report

Gate: `V2_ONE_HOUR_TRAINER_RISK_ORCHESTRATOR_DATA_WEBSITE_MONITOR_READY`
Generated EST: `2026-06-15T18:46:34-04:00`
Sample count: `1`
Monitor finished: `True`

## Latest

- live_gate: `None`
- trainer_status: `None`
- prediction_primary_rows: `740`
- signal_rows: `740`
- risk_rows: `740`
- paper_equity: `10032.27063619`

## Issues

- `RUNTIME_TRUTH_TRAINER_STATUS_MISSING`: 1

Safety: monitor-only; no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, and no raw credential output.
