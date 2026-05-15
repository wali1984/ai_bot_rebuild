# Next Decision Improvement Tasks

Generated: `2026-05-15T10:52:29Z`

This queue is V2 paper/shadow only and does not approve live trading or legacy shutdown.

## claude_add_shadow_outcome_learning_for_blocked_intents

- priority: `P1`
- reason: Post-filter no-fill state is safe but cannot prove edge without outcome observations.
- required result: Blocked intents collect 5m/15m/30m/1h after-cost outcomes without paper fees.

## claude_map_legacy_protective_behaviors_to_v2_paper

- priority: `P1`
- reason: Legacy closure includes churn, lifecycle, TP/stop, reduce-only, and adaptive gate behavior not silently droppable.
- required result: Each protective behavior is implemented in paper-only form or emitted as an explicit blocker.
