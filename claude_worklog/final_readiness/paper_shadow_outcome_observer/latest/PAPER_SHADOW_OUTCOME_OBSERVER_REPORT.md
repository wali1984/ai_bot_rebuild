# Paper Shadow Outcome Observer Report

Generated: `2026-05-15T09:59:41Z`
GO/NO-GO: `PAPER_SHADOW_OUTCOME_OBSERVER_READY_MODEL_REVIEW_REQUIRED`
Outcome status: `BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED`

This observer evaluates blocked V2 paper intents against future price paths.
It never creates fills, charges fees, writes old Redis, calls exchanges, or changes live state.

## Counts

- observations_total: `90`
- completed_observations: `43`
- pending_observations: `47`
- no_trade_correct_count: `28`
- false_block_count: `15`
- false_block_missing_expected_move_count: `0`
- false_block_with_expected_move_count: `15`
- false_block_native_expected_move_count: `13`
- false_block_unknown_expected_move_source_count: `2`
- false_block_classification: `{'historical_missing_expected_move': 0, 'expected_move_present_model_review': 15, 'native_expected_move_model_review': 13, 'expected_move_source_unknown': 2}`
- false_block_reason_counts: `{'confidence_below_canary_threshold': 6, 'deny_canary_profile_tightening': 5, 'deny_low_confidence': 2, 'expected_edge_below_costs': 3}`
- minimum_sample_status: `PRELIMINARY_SAMPLE`
- recommended_next_action: `EXPECTED_MOVE_MODEL_REVIEW_REQUIRED_KEEP_FILL_GATE_STRICT`

## Decision

Positive paper edge remains unproven until qualified post-filter fills or enough completed shadow observations show after-cost correctness. If false blocks appear, keep the fill gate strict and repair expected-move coverage instead of allowing missing-edge fills. Live remains blocked.
