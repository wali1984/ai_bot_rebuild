# Expected Move After Cost False-Block Model Review

Generated: `2026-05-15T09:10:40Z`

## Decision

`EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING`

This does not approve live trading, canary trading, or legacy shutdown. Future shadow outcomes are model-review evidence only; they must not be used to permit current fills.

## Current Evidence

| Metric | Value |
| --- | ---: |
| candidate trade observations | 65 |
| completed observations | 44 |
| allowed paper fills | 0 |
| false blocks that later beat costs | 14 |
| no-trade correct count | 30 |
| after-cost correct count | 14 |
| sample status | PRELIMINARY_SAMPLE |

Post-lifecycle paper runtime remains fail-closed: `47` observed events since `2026-05-15T08:47:22Z`, `0` fills, `0` fees, paper PnL still `-49.15`.

## False-Block Attribution

| Dimension | Count |
| --- | ---: |
| expected move present, model review required | 9 |
| expected move source unknown | 6 |
| historical missing expected move | 5 |
| native expected move model review | 3 |

False-block reason counts:

| Reason | Count |
| --- | ---: |
| confidence_below_canary_threshold | 5 |
| deny_low_confidence | 1 |
| expected_edge_below_costs | 4 |
| missing_expected_move_after_costs | 4 |
| paper_outcome_model_missing | 1 |
| same_symbol_same_direction_cooldown | 3 |

The actionable gap is not permission to loosen the gate. It is native expected-move model calibration and coverage. Some blocked shorts later had enough favorable excursion to beat estimated costs, but several had missing expected-move evidence at decision time. That means V2 should improve trainer/feature-side expected move coverage and calibration, not trade from hindsight.

## Current Safe Behavior

- Missing or low expected move after costs still blocks paper fills.
- Low confidence still blocks paper fills.
- Missing trainer source and feature freshness are enforced by the paper edge gate.
- `live_gate=blocked_human_only`.
- `live_symbols=[]`.
- No old Redis write or exchange action was observed.

## Next Action

Keep observing blocked intents across 5m/15m/30m/1h horizons. The next implementation task is model-side expected-move coverage/calibration from native trainer and feature evidence, with tests proving future outcomes cannot authorize fills.
