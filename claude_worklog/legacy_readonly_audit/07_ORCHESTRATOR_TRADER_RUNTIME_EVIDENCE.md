# Orchestrator / Trader Runtime Evidence

Generated: 2026-05-11T05:01:18.486140+00:00

Read-only process evidence.

```text
1042465 1011413 python3 -m rl.orchestrator_worker
1272209 1272100 tail -f Desktop/AI BOT/logs/orchestrator_worker.log
1272469 1272294 python3 Desktop/AI BOT/monitor_portfolio_primary.py
```

## Required V2 impact
- decisions must include decision_id
- risk gateway must default-deny stale/unsafe signals
- paper ledger must capture open/close/reduce/hedge/block
- shadow mode must compare legacy vs V2
