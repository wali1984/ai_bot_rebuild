# Expected Move After-Cost Current-Sample Model Review

Generated: `2026-05-15T20:44:42Z`

GO/NO-GO: `EXPECTED_MOVE_AFTER_COST_CURRENT_SAMPLE_READY_EDGE_PENDING`

Codex took over this safe reporting/classification packet after the V2 Claude child produced zero output and no artifacts. This does not approve live, canary, legacy shutdown, or Redis trim.

## Current Sample

- observations_total: `413`
- completed_observations: `350`
- pending_observations: `63`
- no_trade_correct_count: `224`
- no_trade_correct_rate: `0.64`
- false_block_count: `126`
- false_block_rate: `0.36`
- safe_threshold_candidate_count: `0`
- recommended_gate_action: `KEEP_GATE_STRICT`

## False-Block Breakdown

- false_block_reason_counts: `{'confidence_below_canary_threshold': 48, 'deny_canary_profile_tightening': 7, 'deny_low_confidence': 6, 'expected_edge_below_costs': 70, 'expected_move_model_review_required': 36, 'flip_churn_cooldown': 1, 'loss_cooldown_active': 62, 'missing_expected_move_after_costs': 1, 'same_symbol_same_direction_cooldown': 8}`
- false_blocks_by_symbol: `{'BTCUSDT': 126}`
- false_blocks_by_side: `{'long': 43, 'short': 83}`
- false_blocks_by_confidence_bucket: `{'0.58_to_0.65': 26, '0.65_to_0.75': 22, '0.75_plus': 72, 'below_0.58': 6}`
- false_blocks_by_expected_move_after_cost_bps_bucket: `{'0_to_4': 21, '10_to_12': 3, '12_to_15': 3, '15_plus': 5, '4_to_6': 5, '6_to_8': 7, '8_to_10': 6, 'MISSING': 1, 'negative': 75}`
- false_blocks_by_feature_freshness_state: `{'CURRENT': 126}`
- false_blocks_by_trainer_source: `{'LEGACY_HYBRID_TRAINER_REDIS_READONLY': 125, 'V2_PAPER_TRAINER_WRAPPER': 1}`

## Decision

Keep the strict paper fill gate. The current sample has false blocks, but there are still zero safe threshold candidates. Future shadow outcomes remain analysis-only and cannot authorize fills.

## Native Sources To Improve

- `native_trainer_expected_move_bps`
- `confidence_calibration_to_after_cost_edge`
- `loss_cooldown_context_model`
- `symbol_timeframe_expected_move_model`

## Safety

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- approves_live: `false`
- approves_canary: `false`
- approves_legacy_shutdown: `false`
- old Redis mutation: `false`
- exchange action: `false`
