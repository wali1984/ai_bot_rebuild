# Orchestrator / Trader Runtime Evidence

Generated: 2026-05-09T06:26:02.839758+00:00

Read-only process evidence.

```text
1042465 1042463 python3 -m rl.orchestrator_worker
```

## Required V2 impact
- decisions must include decision_id
- risk gateway must default-deny stale/unsafe signals
- paper ledger must capture open/close/reduce/hedge/block
- shadow mode must compare legacy vs V2
