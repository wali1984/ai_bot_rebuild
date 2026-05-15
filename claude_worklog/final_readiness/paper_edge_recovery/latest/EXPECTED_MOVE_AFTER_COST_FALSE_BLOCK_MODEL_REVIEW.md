# Expected Move After Cost False-Block Model Review

Generated: `2026-05-15T10:00:33Z`

## Decision

`EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING`

This does not approve live trading, canary trading, or legacy shutdown. Future shadow outcomes are model-review evidence only; they must not be used to permit current fills.

## Current Evidence

| Metric | Value |
| --- | ---: |
| candidate trade observations | 90 |
| completed observations | 43 |
| pending observations | 47 |
| preserved completed outcomes | 2 |
| allowed paper fills | 0 |
| false blocks that later beat costs | 15 |
| no-trade correct count | 28 |
| after-cost correct count | 15 |
| sample status | PRELIMINARY_SAMPLE |

Current paper runtime remains non-live: realized PnL `-49.197409`, open positions `0`, live gate `blocked_human_only`, live symbols `[]`.

## False-Block Attribution

False-block reason counts:

| Reason | Count |
| --- | ---: |
| confidence_below_canary_threshold | 6 |
| deny_canary_profile_tightening | 5 |
| deny_low_confidence | 2 |
| expected_edge_below_costs | 3 |

False blocks by expected-move source:

| Source | Count |
| --- | ---: |
| missing | 2 |
| native_trainer_expected_move_bps | 13 |

The actionable gap is model calibration and expected-move coverage. Several blocked signals later had enough favorable excursion to beat estimated costs, but this is hindsight evidence. V2 must improve trainer/feature-side expected move estimates available at decision time; it must not trade from future outcome labels.

## Current Safe Behavior

- Missing or low expected move after costs still blocks paper fills.
- Low confidence still blocks paper fills.
- Missing trainer source and feature freshness are enforced by the paper edge gate.
- `live_gate=blocked_human_only`.
- `live_symbols=[]`.
- No old Redis write or exchange action was observed in the current evidence packet.

## Next Action

improve native expected_move_after_cost coverage and calibration from trainer/feature evidence without loosening the strict paper fill gate
