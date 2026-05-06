# Orchestrator / Trader Runtime Evidence

Generated: 2026-05-06T20:09:58.385882+00:00

Read-only process evidence.

```text
1502637 2253730  345583 python3 Desktop/AI BOT/monitor_portfolio_primary.py
2432997       1  574736 python3 trading/trader.py
2435672       1  574616 python3 -m rl.orchestrator_worker
3343513  146556  521714 tail -f Desktop/AI BOT/logs/orchestrator_worker.log
```

## Required V2 impact
- decisions must include decision_id
- risk gateway must default-deny stale/unsafe signals
- paper ledger must capture open/close/reduce/hedge/block
- shadow mode must compare legacy vs V2
