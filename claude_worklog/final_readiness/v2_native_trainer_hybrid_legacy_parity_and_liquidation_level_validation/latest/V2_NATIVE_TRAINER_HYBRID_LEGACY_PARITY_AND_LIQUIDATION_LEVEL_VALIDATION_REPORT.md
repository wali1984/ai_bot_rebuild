# V2 Native Trainer Hybrid Legacy Parity And Liquidation Level Validation Report

Gate: `V2_NATIVE_TRAINER_HYBRID_LEGACY_PARITY_AND_LIQUIDATION_LEVEL_VALIDATION_BLOCKED`
Generated EST: `2026-06-09T21:23:25-04:00`
Trainer always-on guard: `V2_NATIVE_PPO_MASA_CONTINUOUS_TRAINING_AND_EXPLORATION_GUARD_READY`
Native CUDA predictions: `655` rows, blocked `0`
Trainer source: `V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW`
Valid runtime symbols: `131`
Timeframes: `1m, 5m, 15m, 1h, 4h`
Liquidation runtime: `LIQUIDATION_RUNTIME_OK`
Liquidation level coverage: `655` valid symbol/timeframe keys
Full hybrid_trainer.py parity: `PARTIAL_PARITY_REMAINING`

## Result

The native PPO/MASA CUDA trainer is running, guarded, CUDA-active, and generating predictions/signals for every valid runtime symbol across all five timeframes. The old 1m RL-core sidecar preference was fixed; current 1m rows now resolve to native CUDA primary predictions.

The liquidation level engine is active and publishing long/short liquidation levels, strengths, and distance fields into V2 liquidation and unified-feature keys for all valid symbols/timeframes. The legacy liquidation bridge remains inactive/masked.

## Remaining Blocker

This is still blocked for the literal requirement "all functionalities from hybrid_trainer.py". The legacy file is `57250` lines with `HybridTrainer` method count `324`; the native package is not method-for-method parity yet. The remaining gaps are recorded in `hybrid_trainer_legacy_parity_matrix.json`.

## Safety

No real order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.
