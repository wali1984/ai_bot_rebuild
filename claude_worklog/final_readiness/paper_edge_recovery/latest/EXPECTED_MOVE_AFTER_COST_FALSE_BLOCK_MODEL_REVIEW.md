# Expected Move After-Cost False-Block Model Review

Generated: `2026-05-15T16:43:11Z`

Classification: `EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING`

This packet keeps the strict paper fill gate active. Shadow outcomes are model-review evidence only; they do not authorize current fills, live trading, canary trading, or legacy shutdown.

## Current Evidence

- candidate_trade_count: `293`
- completed_observations: `238`
- pending_observations: `55`
- false_block_count: `91`
- no_trade_correct_count: `147`
- false_block_classification: `{'expected_move_present_model_review': 90, 'expected_move_source_unknown': 4, 'historical_missing_expected_move': 1, 'native_expected_move_model_review': 86}`
- false_block_reason_counts: `{'confidence_below_canary_threshold': 31, 'deny_canary_profile_tightening': 7, 'deny_low_confidence': 4, 'expected_edge_below_costs': 43, 'expected_move_model_review_required': 2, 'flip_churn_cooldown': 1, 'loss_cooldown_active': 63, 'missing_expected_move_after_costs': 1, 'same_symbol_same_direction_cooldown': 8}`
- false_block_by_symbol: `{'BTCUSDT': 91}`
- false_block_by_side: `{'short': 61, 'long': 30}`
- false_block_by_expected_move_source: `{'native_trainer_expected_move_bps': 86, 'unknown_or_blank_source': 4, 'missing': 1}`

## Safety

- future_shadow_outcomes_used_as_entry_signal: `false`
- allowed_paper_fill_count_from_this_review: `0`
- live_gate: `blocked_human_only`
- live_symbols: `[]`

## Required Next Action

Keep V2 paper/shadow running with the fill gate fail-closed while the expected-move model is calibrated from native trainer and feature evidence. Do not lower thresholds or use hindsight labels as fill permission.
