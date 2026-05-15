# Next Decision Improvement Tasks

Generated: `2026-05-15T09:30:05Z`

This file does not approve live trading or legacy shutdown.

## claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks

- priority: `P0`
- reason: Shadow outcome observer found 26 blocked intents that beat costs; current false-block reasons show expected-move coverage/model review is required.
- required result: Increase native or explicitly accepted expected_move_after_cost_bps coverage from trainer/feature evidence; do not use future outcome labels to permit fills and do not loosen the strict paper fill gate.

## claude_v2_paper_edge_recovery_and_cost_aware_trade_selection

- priority: `P0`
- reason: Paper loss attribution found fee/slippage/churn loss and missing edge-after-cost evidence.
- required result: Confidence alone cannot permit paper fills; missing expected edge blocks and records shadow observation.

## claude_add_shadow_outcome_learning_for_blocked_intents

- priority: `P1`
- reason: Post-filter no-fill state is safe but cannot prove edge without outcome observations.
- required result: Blocked intents collect 5m/15m/30m/1h after-cost outcomes without paper fees.

## claude_map_legacy_protective_behaviors_to_v2_paper

- priority: `P1`
- reason: Legacy closure includes churn, lifecycle, TP/stop, reduce-only, and adaptive gate behavior not silently droppable.
- required result: Each protective behavior is implemented in paper-only form or emitted as an explicit blocker.
