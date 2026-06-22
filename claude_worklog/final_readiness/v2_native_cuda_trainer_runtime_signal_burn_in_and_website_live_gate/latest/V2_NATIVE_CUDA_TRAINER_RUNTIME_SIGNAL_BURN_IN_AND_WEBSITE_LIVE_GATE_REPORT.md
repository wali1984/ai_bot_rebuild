# V2 Native CUDA Trainer Runtime Signal Burn-In And Website Live Gate Report

Gate: `V2_NATIVE_CUDA_TRAINER_RUNTIME_SIGNAL_BURN_IN_AND_WEBSITE_LIVE_GATE_READY`
Generated EST: `2026-06-04T16:41:37-04:00`
Trainer source: `V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW`
Model source: `V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA`
CUDA active: `True`
GPU: `NVIDIA GeForce RTX 5080`
Training steps: `2`
Predictions checked: `202`
Lineage chains checked: `202`

Live remains blocked.

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`
- live_ready: `False`
- canary_ready: `False`
- primary recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`
- blockers: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN, BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY, BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED`

Edge recompute is conservative: paper outcomes are still pending burn-in, so no profitable edge or live/canary readiness is claimed.

- after-cost expectancy bps: `-41.03400662452868`
- CI lower bps: `-44.72233303670349`
- false positives: `null` until outcome labels exist
- false negatives: `null` until outcome labels exist
- drawdown: `null` until paper outcomes exist

Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.
