# V2 Native CUDA Trainer Edge Calibration And Outcome Burn-In Report

Gate: `V2_NATIVE_CUDA_TRAINER_EDGE_CALIBRATION_AND_OUTCOME_BURN_IN_READY`
Generated EST: `2026-06-04T17:25:23-04:00`
Trainer source: `V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW`
Model source: `V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA`
CUDA active: `True`
GPU: `NVIDIA GeForce RTX 5080`
Predictions checked: `202`
Lineage checked: `202`
Outcome sample count 5m: `197`
After-cost expectancy bps: `-7.039571167326742`
CI lower bps: `-15.222695156211167`
False positives: `0`
False negatives: `43`
Confidence calibration: `CONFIDENCE_CALIBRATION_READY`
High-confidence losers: `0`

Live/canary remain blocked. This artifact does not emit a live-ready or canary-ready approval.

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`
- recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`
- blockers: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN, BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY, BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED`

Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.
