# Files Changed — V2_STOP_THE_LINE Remediation

## Phase 5 — Stale Prediction Fix (2026-06-16)

### Runtime Crash Fix
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/runtime.py`
  - Line 249: Guard `min()` with `default=0.0` to prevent crash when predictions list is empty

- `v2/backend/app/services/native_trainer/persistent_cuda_trainer_runtime.py`
  - Line 1327: Catch `(RuntimeError, ValueError)` instead of only `RuntimeError`

### Feature Trust Gate Fix
- `v2/backend/app/services/market_state_integrity/scoring.py`
  - Added `num_trades`, `quote_volume`, `taker_buy` to `OPTIONAL_OR_EVENT_FEATURE_TOKENS`
  - These fields come from Binance 24hr ticker endpoint; absent when rate-limited (HTTP 418)

## Previous Session — Paper Trading Enhancement (prior session)
- `v2/backend/app/services/paper_trade_management/exits.py` — trailing stop guard
- `v2/backend/app/services/paper_trade_management/high_precision_gate.py` — new gate
- `v2/backend/app/services/paper_trade_management/rolling_metrics.py` — new metrics
- `v2/backend/app/services/market_move_detection/contracts.py` — feature coverage gate
- `v2/backend/app/services/market_move_detection/breakout_squeeze.py` — coverage check
- `v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py` — sign convention fix
