# Paper Edge Post-Filter Observation Window

Generated at: `2026-05-15T08:25:55Z`
Task: `paper_edge_post_filter_observation_window`
Live gate: `blocked_human_only`
Live symbols: `[]`
Final approval token: `absent`
Redis trim approval: `absent`
Classification: **POST_FILTER_EDGE_PENDING**

## Decision

`POST_FILTER_EDGE_PENDING`

This packet does not approve live, canary, or legacy shutdown. The current evidence proves the strict cost-aware paper-fill gate is active, but it does not prove positive paper edge.

## Important Correction

The earlier packet was stale and said the full post-filter window had zero fills. Current paper JSONL evidence shows two fills after the original `paper_canary_aligned_filter_v1` activation:

| Window | Start | Events | Fills | Unsafe fills | PnL delta | Fees | Classification |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Post-canary filter | `2026-05-14T22:40:46Z` | 1067 | 2 | 1 | -0.02 | 0.02 | `SOURCE_LIMITED_FILL_BEFORE_STRICT_EDGE_GATE` |
| Post-strict cost-aware gate | `2026-05-15T08:11:06Z` | 27 | 1 | 0 | -0.01 | 0.01 | `QUALIFIED_FILL_OBSERVED_EDGE_PENDING` |

The unsafe source-limited fill occurred at `2026-05-15T08:03:05Z`, before the strict native expected-move / trainer-source / feature-freshness gate was active. It had no `expected_move_after_cost_bps`, no `trainer_source`, no `feature_freshness_state`, and no paper-symbol evidence. That confirms the original canary filter alone was insufficient.

The qualified strict-gate fill occurred at `2026-05-15T08:20:27Z`. It had:

| Field | Value |
| --- | --- |
| symbol | `BTCUSDT` |
| expected_move_after_cost_bps | `12.51149373` |
| expected_move_source | `native_trainer_expected_move_bps` |
| trainer_source | `LEGACY_HYBRID_TRAINER_REDIS_READONLY` |
| feature_freshness_state | `CURRENT` |
| paper_symbol_allowed | `true` |
| live_gate | `blocked_human_only` |
| live_symbols | `[]` |
| exchange_order | `false` |
| legacy_redis_write | `false` |

This is a qualified paper-only simulated fill under the current hard gate. It booked `0.01 USDT` fee and moved cumulative paper PnL to `-49.14 USDT`, so it is not positive edge proof.

## Current PnL Split

| Bucket | PnL / value | Evidence |
| --- | ---: | --- |
| Historical cumulative paper PnL before this correction window | `-49.12` USDT | Paper loss attribution / prior paper runtime |
| Current cumulative paper PnL | `-49.14` USDT | Latest paper JSONL event at `2026-05-15T08:25:28Z` |
| Post-canary filter PnL delta | `-0.02` USDT | Two paper-only fees after `2026-05-14T22:40:46Z` |
| Post-strict cost-aware gate PnL delta | `-0.01` USDT | One qualified paper-only fee after `2026-05-15T08:11:06Z` |
| Post-strict unsafe fills | `0` | Strict-gate window JSONL audit |

## Safety Interpretation

- `POST_FILTER_NO_UNSAFE_FILLS` remains true only for the strict cost-aware gate window beginning `2026-05-15T08:11:06Z`.
- It is not true for the broader original canary-filter window, because a source-limited fill was recorded at `2026-05-15T08:03:05Z`.
- `POST_FILTER_POSITIVE_EDGE_PROVEN` is false. The strict-gate fill is a sample, not proof; realized paper PnL is still negative after fee.
- The correct next action is to keep observing strict-gate fills and blocked-intent shadow outcomes without loosening the gate.

## Current Blockers

- `PAPER_EDGE_UNPROVEN`
- `LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED`
- `LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE`
- `LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED`
- `PAPER_PNL_NEGATIVE_BLOCKS_CANARY`
- `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`

## Safety State

| Check | Value |
| --- | --- |
| live_gate | `blocked_human_only` |
| live_symbols | `[]` |
| final approval token | `absent` |
| Redis trim approval | `absent` |
| old Redis writes | `absent` in audited paper JSONL events |
| exchange actions | `absent` in audited paper JSONL events |
| leverage / margin changes | `absent` |

## Non-Approvals

This report does not approve live trading, canary trading, legacy shutdown, approval-token creation, Redis trim approval, exchange mutation, leverage change, or margin-mode change.
