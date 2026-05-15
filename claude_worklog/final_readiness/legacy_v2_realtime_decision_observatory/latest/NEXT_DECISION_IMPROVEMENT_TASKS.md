# Next Decision Improvement Tasks

Generated: `2026-05-15T10:04:52Z`

This queue is V2 paper/shadow only and does not approve live trading or legacy shutdown.

## claude_v2_paper_edge_recovery_and_cost_aware_trade_selection

- priority: `P0`
- reason: Paper loss attribution found fee/slippage/churn loss and missing edge-after-cost evidence.
- required result: Confidence alone cannot permit paper fills; missing expected edge blocks and records shadow observation.

## claude_add_per_fill_trainer_source_and_feature_freshness

- priority: `P0`
- reason: Per-fill trainer source and feature freshness are missing from paper events.
- required result: Every intent/fill/block carries trainer_source and feature_freshness_state.

## claude_add_shadow_outcome_learning_for_blocked_intents

- priority: `P1`
- reason: Post-filter no-fill state is safe but cannot prove edge without outcome observations.
- required result: Blocked intents collect 5m/15m/30m/1h after-cost outcomes without paper fees.

## claude_map_legacy_protective_behaviors_to_v2_paper

- priority: `P1`
- reason: Legacy closure includes churn, lifecycle, TP/stop, reduce-only, and adaptive gate behavior not silently droppable.
- required result: Each protective behavior is implemented in paper-only form or emitted as an explicit blocker.
