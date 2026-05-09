# Trainer Runtime Evidence

Generated: 2026-05-09T06:26:02.815679+00:00

Read-only process/log evidence.

## Processes
```text
1039705 1039702 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
```

## Required V2 impact
- preserve GPU/checkpoint/batching assumptions
- detect process-alive / worker-dead
- emit prediction_id and feature_snapshot_id
- expose confidence attribution
- block stale/missing feature input
