# V2 Native Hybrid Trainer Full Function Parity And Paper Reverify Report

Gate: `V2_NATIVE_HYBRID_TRAINER_FULL_FUNCTION_PARITY_AND_PAPER_REVERIFY_READY`
Generated EST: `2026-06-09T21:56:25-04:00`
Trainer bridge: `inactive` / `masked`
Native CUDA predictions: `655` rows, blocked `0`
HybridTrainer methods inventoried: `324`
Required missing parity methods: `0`
Paper current session equity: `10000.0`
Paper current session PnL: `0.0`

## Result

The native trainer bridge remains masked/inactive and the native CUDA trainer output is current across valid symbols/timeframes. Paper runtime/equity was re-read from current V2 sources.

## Parity Status

All 324 legacy `HybridTrainer` methods are inventoried and assigned to an implemented native trainer capability, an explicit V2 runtime owner, or an intentional fail-closed trainer boundary. The trainer bridge remains masked and native CUDA predictions are current across the valid symbol/timeframe grid.

## Safety

No legacy trainer bridge unmask, no legacy hybrid_trainer.py wrapper run, no real order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.
