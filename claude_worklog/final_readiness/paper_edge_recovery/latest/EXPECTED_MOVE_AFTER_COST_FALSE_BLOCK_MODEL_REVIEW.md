# Expected Move After Cost False-Block Model Review

Generated: `2026-05-15T11:18:55Z`

## Decision

`EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING`

This does not approve live trading, canary trading, or legacy shutdown. Future shadow outcomes are model-review evidence only; they must not be used to permit current fills.

## Current Evidence

| Metric | Value |
| --- | ---: |
| candidate trade observations | 131 |
| completed observations | 80 |
| pending observations | 51 |
| allowed paper fills | 0 |
| false blocks that later beat costs | 19 |
| no-trade correct count | 61 |
| after-cost correct count | 19 |
| sample status | PRELIMINARY_SAMPLE |

Current paper runtime remains non-live: realized PnL `-49.228096`, open positions `0`, live gate `blocked_human_only`, live symbols `[]`.

## False-Block Attribution

False-block reason counts:

| Reason | Count |
| --- | ---: |
| confidence_below_canary_threshold | 7 |
| deny_canary_profile_tightening | 7 |
| deny_low_confidence | 1 |
| expected_edge_below_costs | 5 |
| same_symbol_same_direction_cooldown | 3 |

False blocks by expected-move source:

| Source | Count |
| --- | ---: |
| missing_expected_move | 0 |
| native_trainer_expected_move_bps | 18 |
| unknown_or_blank_source | 1 |


The actionable gap is expected-move calibration and coverage from evidence available at decision time. Several blocked signals later had enough favorable excursion to beat estimated costs, but that is hindsight evidence. V2 must not use future outcome labels to authorize current fills.

## Current Safe Behavior

- Missing or low expected move after costs still blocks paper fills.
- Low confidence still blocks paper fills.
- Missing trainer source and feature freshness are enforced by the paper edge gate.
- `live_gate=blocked_human_only`.
- `live_symbols=[]`.
- No old Redis write or exchange action was observed in the current evidence packet.

## Next Action

improve native expected_move_after_cost coverage and calibration from trainer/feature evidence without loosening the strict paper fill gate
