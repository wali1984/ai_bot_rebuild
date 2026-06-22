# V2 Persistent CUDA Trainer Resource Utilization And Paper Drawdown Guard Report

Gate: `V2_PERSISTENT_CUDA_TRAINER_RESOURCE_UTILIZATION_AND_PAPER_DRAWDOWN_GUARD_READY`
Generated EST: `2026-06-21T20:21:47-04:00`
Persistent trainer service active: `True`
PID: `2463`
Training steps total/last hour: `445654/6`
Trainer symbols: `86` symbols, BTC/ETH/SOL-only scope `False`
Prediction grid: `430/430`
Resource bottleneck: `MODEL_TOO_SMALL_TO_SATURATE_GPU`
GPU/VRAM: `1.0% / 912.0 MB of 16303.0 MB`
Checkpoint count/size: `10/0.047614 GB`
Paper PnL delta from trial baseline: `2437.06674464`
Paper trial guard: `TRIAL_ACTIVE`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`

The native trainer now has a persistent resident loop and publishes current resource, checkpoint, and paper drawdown guard status. The confidence-threshold overlay is paper-only and is paused when the drawdown guard is breached or attribution is insufficient. Live thresholds and exchange execution are unchanged.

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, no trainer bridge unmask, and no live threshold change.
