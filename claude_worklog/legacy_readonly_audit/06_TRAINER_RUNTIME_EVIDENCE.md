# Trainer Runtime Evidence

Generated: 2026-05-12T16:04:59.058053+00:00

Read-only process/log evidence.

## Processes
```text
3980694 3980692 python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
```

## Required V2 impact
- preserve GPU/checkpoint/batching assumptions
- detect process-alive / worker-dead
- emit prediction_id and feature_snapshot_id
- expose confidence attribution
- block stale/missing feature input
