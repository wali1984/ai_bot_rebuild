# Paper Loss Attribution Report

Generated: `2026-05-15T03:34:08Z`

## Executive Summary

- Current cumulative paper PnL: `-49.12` USDT.
- Source-detailed pre-filter observed loss: `-22.75` USDT.
- Source-limited pre-observation/baseline loss: `-26.37` USDT.
- Post-filter PnL delta: `0.0` USDT with `0` fills.
- Post-filter safety classification: `POST_FILTER_NO_UNSAFE_FILLS`.
- Edge classification: `POST_FILTER_EDGE_PENDING`.

The important split is that the current `-49.12` paper PnL is historical/pre-filter. The post-filter window has no fills and no additional realized loss, so it proves no unsafe fills in the observed window, not positive edge.

## PnL Waterfall

| Bucket | PnL USDT | Evidence |
| --- | --- | --- |
| Source-limited prior baseline through first observed paper event | -26.37 | Cumulative PnL already negative at first JSONL event; no per-fill source detail for this portion |
| Observed pre-filter event delta | -22.75 | Paper JSONL cumulative PnL delta before filter activation |
| Observed post-filter event delta | 0.0 | Paper JSONL cumulative PnL delta after filter activation |
| Current cumulative paper PnL | -49.12 | Paper shadow status / latest paper event |

## Pre-Filter Vs Post-Filter

| Window | Events | Fills | Blocked | PnL Delta | Fees | Slippage Estimate | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pre-filter observed | 3910 | 2269 | 1641 | -22.75 | 22.69 | 11.345 | LOSS_OBSERVED_PRE_FILTER |
| Post-filter observed | 532 | 0 | 532 | 0.0 | 0.0 | 0.0 | POST_FILTER_NO_UNSAFE_FILLS |

## Requested Attribution Dimensions

### Symbol

| Symbol / bucket | Observed pre-filter PnL | Post-filter PnL | Events / note |
| --- | --- | --- | --- |
| BTCUSDT | -22.75 | 0.0 | 3910 pre-filter events, 532 post-filter events |
| SOURCE_LIMITED_PRIOR_BASELINE | -26.37 | 0.0 | No source detail by symbol for this prior cumulative portion |

### Side / Risk Reason

| Side / reason | Observed pre-filter PnL | Fill count | Source |
| --- | --- | --- | --- |
| long / allow_proceed_long | -11.56 | 1156 | paper fill quality audit |
| short / allow_proceed_short | -11.19 | 1113 | paper fill quality audit |

### Reason Code / Risk Decision

| Reason code | Risk decision | Observed pre-filter PnL | Pre-filter count | Post-filter count |
| --- | --- | --- | --- | --- |
| allow_proceed_long | APPROVED_FOR_PAPER_ONLY | -11.56 | 1156 | 0 |
| allow_proceed_short | APPROVED_FOR_PAPER_ONLY | -11.19 | 1113 | 0 |
| deny_canary_profile_tightening | BLOCKED | 0.0 | 1276 | 494 |
| deny_low_confidence | BLOCKED | 0.0 | 233 | 17 |
| deny_orchestrator_held | BLOCKED | 0.0 | 131 | 19 |
| deny_stale_market_feed | BLOCKED | 0.0 | 1 | 2 |

### Confidence Bucket

| Confidence bucket | Observed pre-filter PnL | Pre-filter fill count | Post-filter fill count |
| --- | --- | --- | --- |
| below_0.58 | 0.0 | 0 | 0 |
| 0.58_to_0.65 | -4.54 | 454 | 0 |
| 0.65_to_0.75 | -5.42 | 542 | 0 |
| 0.75_plus | -12.79 | 1273 | 0 |

### Fee / Slippage

| Metric | Pre-filter observed | Post-filter observed | Note |
| --- | --- | --- | --- |
| Explicit fee USDT | 22.69 | 0.0 | Booked in paper events |
| Slippage bps assumption | {'2.0': 2269} | {} | Logged as bps, not separately booked as realized PnL |
| Estimated slippage USDT | 11.345 | 0.0 | Notional * slippage_bps / 10000 |
| Gross PnL if fees added back | -0.06 | N/A | From negative PnL diagnosis |

### Trainer Source And Feature Freshness

| Dimension | Classification | Evidence |
| --- | --- | --- |
| Per-fill trainer source | MISSING_IN_PAPER_EVENTS | Paper JSONL has prediction_id but no trainer source field |
| Current paper runtime trainer source | V2_PAPER_TRAINER_WRAPPER | paper runtime status |
| Trainer bridge source | LEGACY_HYBRID_TRAINER_LOG_READONLY | trainer bridge status |
| Per-fill feature freshness | MISSING_IN_PAPER_EVENTS | Paper JSONL has feature_snapshot_id but no freshness field |
| Current feature freshness | CURRENT | paper runtime current lineage |
| Stale market feed risk decisions | 1 | Pre-filter denials, not filled-loss attribution |
| Post-filter stale market feed risk decisions | 2 | Post-filter denials, no fills |

### Edge-After-Costs / Cooldown / Churn

| Dimension | Pre-filter observed | Post-filter observed | Interpretation |
| --- | --- | --- | --- |
| missing_expected_move_after_costs | 1276 | 494 | Edge-after-costs unavailable on denied intents; not present for pre-filter allowed fills |
| same_symbol_same_direction_cooldown | 6 | 0 | Explicit cooldown blocker counts in event stream |
| flip_churn_cooldown | 3 | 0 | Explicit flip/churn blocker counts in event stream |
| churn_flip_count | 193 | 0 | Pre-filter audit count vs post-filter observation |

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

- Per-fill trainer source is missing from paper events.
- Per-fill feature freshness is missing from paper events.
- Edge-after-costs value is missing for pre-filter allowed fills; post-filter denials carry `missing_expected_move_after_costs` blockers.
- Cooldown and flip/churn are explicit only when the canary tightening filter emits blockers; the pre-filter loss audit also reports aggregate churn.
- Invalid JSONL rows skipped: `1`.

## Decision

`PAPER_LOSS_ATTRIBUTION_READY_SOURCE_LIMITED`

This report does not approve live trading, canary trading, or legacy shutdown. It narrows the paper loss blocker to historical/pre-filter loss plus source-limited attribution gaps, while post-filter behavior remains no-fill/no-loss and edge-pending.
