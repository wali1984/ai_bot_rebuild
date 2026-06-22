# V2 All-Symbol All-Timeframe Feature Trainer Signal GPU Parity Report

Gate: `V2_ALL_SYMBOL_ALL_TIMEFRAME_FEATURE_TRAINER_SIGNAL_GPU_PARITY_BLOCKED`
Generated EST: `2026-06-21T20:28:29-04:00`
live_gate: `blocked_human_only`
live_symbols: `[]`
execution_live_symbols: `[]`

## Summary

- prediction_rows_count: `430`
- current_prediction_count: `0`
- stale_prediction_count: `365`
- missing_prediction_count: `65`
- expected_move_missing_count: `65`
- invalid_or_missing_price_targets: `65`
- signal_count: `0`
- missing_lineage_count: `0`
- dynamic_pipeline_blocked_symbol_count: `86`
- feature_parity_blocked_field_rows_count: `7428`
- cuda_prediction_blocked_rows_count: `430`
- resource_status: `CUDA_CPU_RESOURCE_UTILIZATION_UPGRADE_READY`
- backtest_status: `BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM`
- website_board_status: `ALL_TIMEFRAME_SIGNAL_BOARD_WEBSITE_BLOCKED_OR_PARTIAL`
- production_truth_status: `PRODUCTION_ROUTE_HASH_CAPTURED_REQUIRES_DEPLOYMENT_HASH_COMPARE`

## Safety

No live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.

## Blockers

- Generate v2:prediction:AGTUSDT:15m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AGTUSDT:1h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AGTUSDT:1m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AGTUSDT:4h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AGTUSDT:5m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AXSUSDT:15m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AXSUSDT:1h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AXSUSDT:1m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AXSUSDT:4h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:AXSUSDT:5m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BELUSDT:15m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BELUSDT:1h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BELUSDT:1m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BELUSDT:4h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BELUSDT:5m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BICOUSDT:15m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BICOUSDT:1h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BICOUSDT:1m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BICOUSDT:4h from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- Generate v2:prediction:BICOUSDT:5m from CUDA/RL inference or a labelled, validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage.
- plus `414` more timeframe remediation tasks
