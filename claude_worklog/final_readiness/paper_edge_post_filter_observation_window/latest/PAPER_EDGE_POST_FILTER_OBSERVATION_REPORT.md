# Paper Edge Post-Filter Observation Window

Generated at: `2026-05-15T08:36:30Z`
Task: `paper_edge_post_filter_observation_window`
Live gate: `blocked_human_only`
Live symbols: `[]`
Final approval token: `absent`
Redis trim approval: `absent`
Classification: **POST_FILTER_EDGE_PENDING**

## Decision

`POST_FILTER_EDGE_PENDING`

This does not approve live, canary, or legacy shutdown.

## Current Split

| Window | Start | Events | Fills | Unsafe fills | PnL delta | Fees | Classification |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Original post-canary filter | `2026-05-14T22:40:46Z` | 1087 | 3 | 1 | -0.03 | 0.03 | `SOURCE_LIMITED_FILL_BEFORE_STRICT_GATE_PLUS_FEE_ONLY_SAMPLES` |
| Strict cost-aware gate before outcome guard | `2026-05-15T08:11:06Z` | 42 | 2 | 0 | -0.02 | 0.02 | `QUALIFIED_FILLS_FEE_ONLY_EDGE_PENDING` |
| Outcome-model fee-bleed guard | `2026-05-15T08:32:56Z` | 2 | 0 | 0 | 0.0 | 0.0 | `NO_FEE_BLEED_SHADOW_OBSERVE_ONLY` |

The original canary filter was insufficient: it allowed a source-limited fill at `2026-05-15T08:03:05Z` without expected move, trainer source, feature freshness, or paper-symbol evidence.

The strict cost-aware gate then allowed two qualified paper-only fills, but the paper runtime still booked fee-only realized PnL because it has no exit/outcome simulator. Codex added an outcome-model guard at `2026-05-15T08:32:56Z`; after that, qualified intents are shadow-observed and no fee-charging paper fills are recorded while the paper outcome model is missing.

## PnL Split

| Bucket | Value |
| --- | ---: |
| Historical cumulative paper PnL before paper-edge work | `-49.12` USDT |
| Current cumulative paper PnL | `-49.15` USDT |
| Original post-canary filter PnL delta | `-0.03` USDT |
| Strict cost-aware gate pre-outcome-guard PnL delta | `-0.02` USDT |
| Outcome-model guard PnL delta | `0.0` USDT |

## Safety Interpretation

- Positive paper edge is not proven.
- The current active safety boundary is the outcome-model fee-bleed guard.
- No further fee-charging paper fill should occur until a non-live paper exit/outcome simulator is available.
- Blocked qualified intents should continue feeding shadow outcome observation.

## Current Blockers

- `PAPER_EDGE_UNPROVEN`
- `PAPER_EXIT_OUTCOME_SIMULATOR_MISSING`
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
