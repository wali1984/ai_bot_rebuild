# Paper Loss Attribution Report

Generated: `2026-05-15T09:52:19Z`

## Executive Summary

- Current cumulative paper PnL: `-49.197409` USDT.
- Source-detailed pre-filter observed loss: `-22.75` USDT.
- Source-limited pre-observation/baseline loss: `-26.37` USDT.
- Post-filter PnL delta: `-0.077409` USDT with `4` fills.
- Post-filter safety classification: `POST_FILTER_FILLS_OBSERVED_LOSS_SOURCE_LIMITED`.
- Edge classification: `POST_FILTER_EDGE_PENDING`.

The important split is that most cumulative paper PnL is historical/pre-filter, while the current post-filter window now has `4` observed fills and `-0.077409` USDT realized delta. That does not prove positive edge; it keeps paper edge blocked until strict-gate fills close net-positive after fees/slippage over a sufficient sample.

## PnL Waterfall

| Bucket | PnL USDT | Evidence |
| --- | --- | --- |
| Source-limited prior baseline through first observed paper event | -26.37 | Cumulative PnL already negative at first JSONL event; no per-fill source detail for this portion |
| Observed pre-filter event delta | -22.75 | Paper JSONL cumulative PnL delta before filter activation |
| Observed post-filter event delta | -0.077409 | Paper JSONL cumulative PnL delta after filter activation |
| Current cumulative paper PnL | -49.197409 | Paper shadow status / latest paper event |

## Pre-Filter Vs Post-Filter

| Window | Events | Fills | Blocked | PnL Delta | Fees | Slippage Estimate | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pre-filter observed | 3910 | 2269 | 1641 | -22.75 | 22.69 | 11.345 | LOSS_OBSERVED_PRE_FILTER |
| Post-filter observed | 1229 | 4 | 1225 | -0.077409 | 0.04 | 0.02 | POST_FILTER_FILLS_OBSERVED_LOSS_SOURCE_LIMITED |

## Requested Attribution Dimensions

### Symbol

| Symbol / bucket | Observed pre-filter PnL | Post-filter PnL | Events / note |
| --- | --- | --- | --- |
| BTCUSDT | -22.75 | -0.077409 | 3910 pre-filter events, 1229 post-filter events |
| SOURCE_LIMITED_PRIOR_BASELINE | -26.37 | 0.0 | No source detail by symbol for this prior cumulative portion |

### Side / Risk Reason

| Side / reason | Observed pre-filter PnL | Fill count | Source |
| --- | --- | --- | --- |
| long / allow_proceed_long | -11.56 | 1156 | paper fill quality audit |
| short / allow_proceed_short | -11.19 | 1113 | paper fill quality audit |

### Reason Code / Risk Decision

| Reason code | Risk decision | Observed pre-filter PnL | Pre-filter count | Post-filter count |
| --- | --- | --- | --- | --- |
| allow_proceed_long | APPROVED_FOR_PAPER_ONLY | -11.56 | 1156 | 1 |
| allow_proceed_short | APPROVED_FOR_PAPER_ONLY | -11.19 | 1113 | 3 |
| deny_canary_profile_tightening | BLOCKED | 0.0 | 1276 | 1106 |
| deny_low_confidence | BLOCKED | 0.0 | 233 | 66 |
| deny_orchestrator_held | BLOCKED | 0.0 | 131 | 46 |
| deny_stale_market_feed | BLOCKED | 0.0 | 1 | 2 |

### Confidence Bucket

| Confidence bucket | Observed pre-filter PnL | Pre-filter fill count | Post-filter fill count |
| --- | --- | --- | --- |
| below_0.58 | 0.0 | 0 | 0 |
| 0.58_to_0.65 | -4.54 | 454 | 0 |
| 0.65_to_0.75 | -5.42 | 542 | 0 |
| 0.75_plus | -12.79 | 1273 | 4 |

### Fee / Slippage

| Metric | Pre-filter observed | Post-filter observed | Note |
| --- | --- | --- | --- |
| Explicit fee USDT | 22.69 | 0.04 | Booked in paper events |
| Slippage bps assumption | {'2.0': 2269} | {'2.0': 4} | Logged as bps, not separately booked as realized PnL |
| Estimated slippage USDT | 11.345 | 0.02 | Notional * slippage_bps / 10000 |
| Gross PnL if fees added back | -0.06 | N/A | From negative PnL diagnosis |

### Trainer Source And Feature Freshness

| Dimension | Classification | Evidence |
| --- | --- | --- |
| Per-fill trainer source | SOURCE_LIMITED_MIXED_POST_FILTER_COVERAGE | Coverage is measured on observed post-filter fills; older events remain source-limited |
| Current paper runtime trainer source | LEGACY_HYBRID_TRAINER_REDIS_READONLY | paper runtime status |
| Trainer bridge source | LEGACY_HYBRID_TRAINER_REDIS_READONLY | trainer bridge status |
| Per-fill feature freshness | SOURCE_LIMITED_MIXED_POST_FILTER_COVERAGE | Coverage is measured on observed post-filter fills; older events remain source-limited |
| Current feature freshness | CURRENT | paper runtime current lineage |
| Stale market feed risk decisions | 1 | Pre-filter denials, not filled-loss attribution |
| Post-filter stale market feed risk decisions | 2 | Post-filter denials; fills tracked separately |

### Edge-After-Costs / Cooldown / Churn

| Dimension | Pre-filter observed | Post-filter observed | Interpretation |
| --- | --- | --- | --- |
| missing_expected_move_after_costs | 1276 | 925 | Edge-after-costs unavailable on denied intents; not present for pre-filter allowed fills |
| same_symbol_same_direction_cooldown | 6 | 31 | Explicit cooldown blocker counts in event stream |
| flip_churn_cooldown | 3 | 2 | Explicit flip/churn blocker counts in event stream |
| churn_flip_count | 193 | 2 | Pre-filter audit count vs post-filter observation |

## Safety State

| Check | Value |
| --- | --- |
| live_gate | blocked_human_only |
| live_symbols | [] |
| old Redis write events in parsed paper JSONL | 0 |
| exchange order events in parsed paper JSONL | 0 |
| approval token | absent |
| approves live | False |
| approves legacy shutdown | False |

## Source Limitations

- Per-fill trainer source coverage: `SOURCE_LIMITED_MIXED_POST_FILTER_COVERAGE`.
- Per-fill feature freshness coverage: `SOURCE_LIMITED_MIXED_POST_FILTER_COVERAGE`.
- Edge-after-cost coverage for observed post-filter fills: `SOURCE_LIMITED_MIXED_POST_FILTER_COVERAGE`.
- Edge-after-costs value is missing for pre-filter allowed fills; post-filter denials carry `missing_expected_move_after_costs` blockers.
- Cooldown and flip/churn are explicit only when the canary tightening filter emits blockers; the pre-filter loss audit also reports aggregate churn.
- Invalid JSONL rows skipped: `1`.

## Decision

`PAPER_LOSS_ATTRIBUTION_READY_SOURCE_LIMITED`

This report does not approve live trading, canary trading, or legacy shutdown. It narrows the paper loss blocker to historical/pre-filter loss plus current post-filter edge evidence, which remains insufficient and edge-pending.
