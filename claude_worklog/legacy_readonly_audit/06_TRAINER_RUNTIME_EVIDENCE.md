# Trainer Runtime Evidence

Generated: 2026-05-06T23:35:26.937876+00:00

Read-only process/log evidence.

## Processes
```text
147111  146976  850718 python3 Desktop/AI BOT/scripts/monitor_trainer_prices.py
1504039  146781  357888 python3 Desktop/AI BOT/scripts/monitor_trainer_predictions.py
2422445  130149  587423 python3 scripts/monitor_trainer_predictions.py
3355777  130149  533486 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
```

## Required V2 impact
- preserve GPU/checkpoint/batching assumptions
- detect process-alive / worker-dead
- emit prediction_id and feature_snapshot_id
- expose confidence attribution
- block stale/missing feature input
