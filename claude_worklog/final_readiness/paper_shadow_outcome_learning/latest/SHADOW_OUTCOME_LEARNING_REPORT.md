# Shadow Outcome Learning For Blocked Intents

Generated: `2026-05-15T16:39:20Z`

GO/NO-GO: `SHADOW_OUTCOME_LEARNING_READY_EDGE_PENDING`

## Decision

The blocked-intent shadow outcome layer is ready for continued paper/shadow learning, but edge remains pending. This does not approve live trading, canary trading, or legacy shutdown.

## Current Evidence

- observations_total: `292`
- completed_observations: `237`
- pending_observations: `55`
- no_trade_correct_count: `146`
- false_block_count: `91`
- false_block_classification: `{'expected_move_present_model_review': 90, 'expected_move_source_unknown': 4, 'historical_missing_expected_move': 1, 'native_expected_move_model_review': 86}`
- false_block_reason_counts: `{'confidence_below_canary_threshold': 31, 'deny_canary_profile_tightening': 7, 'deny_low_confidence': 4, 'expected_edge_below_costs': 43, 'expected_move_model_review_required': 2, 'flip_churn_cooldown': 1, 'loss_cooldown_active': 63, 'missing_expected_move_after_costs': 1, 'same_symbol_same_direction_cooldown': 8}`
- minimum_sample_status: `PRELIMINARY_SAMPLE`
- recommended_next_action: `EXPECTED_MOVE_MODEL_REVIEW_REQUIRED_KEEP_FILL_GATE_STRICT`

## Safety Contract

- Future outcome labels are analysis-only and cannot authorize paper fills.
- Shadow observations keep `fill_allowed=false`, `paper_fill_recorded=false`, and `fee_charged_usdt=0.0`.
- `no_trade_correct` is tracked separately from `after_cost_correct` / false-block evidence.
- Positive edge is not claimed while sample evidence remains limited and post-filter PnL remains unproven.
- Live remains `blocked_human_only`; `live_symbols` remains `[]`.

## Runtime Context

- paper edge recovery: `V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING`
- paper edge proven: `False`
- current cumulative paper PnL: `-49.186177`
- post-filter PnL delta: `-0.066177`
- post-filter fills: `5`
- post-filter safety classification: `POST_FILTER_FILLS_OBSERVED_LOSS_SOURCE_LIMITED`

## Codex Review Marker

`codex_review_shadow_outcome_learning_for_blocked_intents` is queued for review. Codex must fail if future outcomes can permit fills, if false-block evidence is used to loosen the gate without validation, if old Redis/exchange/live-gate safety regresses, or if positive edge/live/shutdown readiness is claimed without evidence.

## Validation

- `py_compile`: PASS
- targeted pytest: `18 passed`
- JSON validation: PASS
- high-confidence secret scan: PASS; only the literal validation key `secret_scan` was matched.
- forbidden mutation scan: PASS; matches were textual forbidden-list/status labels, not mutation calls.
