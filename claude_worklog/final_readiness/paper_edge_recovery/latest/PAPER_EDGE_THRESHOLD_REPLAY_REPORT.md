# Paper Edge Threshold Replay Report

Generated: `2026-05-15T05:39:50Z`

Decision: `THRESHOLD_REPLAY_NOT_YET_RUN_SOURCE_LIMITED`

The hard entry gate is now implemented, but quantitative threshold replay has not been rerun. Old pre-filter events lack `trainer_source`, `feature_freshness_state`, and `expected_move_after_cost_bps`, so they remain useful for loss attribution but source-limited for exact replay.

Replay must not claim positive edge unless post-filter fills exist and are net-positive after fees/slippage. If all threshold combinations block all fills, the correct classification is `NO_TRADE_EDGE_NOT_FOUND`.
