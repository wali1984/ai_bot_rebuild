# V2 Market State Integrity Rejection Burndown And Paper Training Recovery Report

Gate: `V2_MARKET_STATE_INTEGRITY_REJECTION_BURNDOWN_AND_PAPER_TRAINING_RECOVERY_READY`
Generated EST: `2026-06-09T15:07:22-04:00`
Training accepted before/after: `0/603`
Training rejected before/after: `732/7`
Paper accepted fills before/after: `6/6`
Paper held rows before/after: `116/116`
Paper current session PnL: `0.0`
Paper current session equity: `10000.0`
Live submit allowed: `False`
Live submit blocker: `BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451`
Production bundle status: `PRODUCTION_BUNDLE_CURRENT`

Training recovery uses current `v2:features:latest:*` rows with core OHLC present. Optional/event-dependent gaps are masked for training only; explicit future leakage, unclosed candles, stale core data, and missing core OHLC still reject.

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy/evasion.
