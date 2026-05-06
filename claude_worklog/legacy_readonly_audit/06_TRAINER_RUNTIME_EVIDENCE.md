# Trainer Runtime Evidence

Generated: 2026-05-06T23:37:49.567703+00:00

Read-only process/log evidence.

## Processes
```text
147111  146976 python3 Desktop/AI BOT/scripts/monitor_trainer_prices.py
1504039  146781 python3 Desktop/AI BOT/scripts/monitor_trainer_predictions.py
2422445  130149 python3 scripts/monitor_trainer_predictions.py
3355777  130149 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
```

## Required V2 impact
- preserve GPU/checkpoint/batching assumptions
- detect process-alive / worker-dead
- emit prediction_id and feature_snapshot_id
- expose confidence attribution
- block stale/missing feature input
