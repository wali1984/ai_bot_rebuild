# Codex Review: V2 Full-Observation Unified-Features Burndown

Generated: `2026-05-22T02:47:03Z`

GO/NO-GO: `V2_FULL_OBSERVATION_UNIFIED_FEATURES_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`

## Decision

Codex passes the V2 full-observation unified-features burndown as partial progress. The generated dimensions increased beyond the portfolio-state baseline using V2-owned market/feature evidence, external-source gaps remain explicit, and the builder still does not claim checkpoint compatibility, policy architecture parity, or full-observation completion.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, external feed adoption, or legacy shutdown.

## Scope Reviewed

Reviewed:

- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_unified_features_burndown.py`
- `claude_worklog/final_readiness/v2_full_observation_unified_features_burndown/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_full_observation_unified_features_burndown/latest/unified_features_burndown_status.json`
- `claude_worklog/final_readiness/v2_full_observation_unified_features_burndown/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_unified_features_burndown/latest/operator_dashboard_payload.json`
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`

## Dimension Increase

The portfolio-state burndown baseline was:

- `BTCUSDT=217`
- `ETHUSDT=217`
- `SOLUSDT=207`

After refreshing `v2_full_observation_builder_status --once`, current generated dimensions are:

| Symbol | Baseline | Current | Delta | Missing | State |
| --- | ---: | ---: | ---: | ---: | --- |
| `BTCUSDT` | `217` | `223` | `+6` | `1688` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |
| `ETHUSDT` | `217` | `223` | `+6` | `1688` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |
| `SOLUSDT` | `207` | `213` | `+6` | `1698` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |

The increase comes from completing the `coinank` subfamily from `16/22` to `22/22` per symbol. `FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed.

## V2 Source Boundary

The six added fields are:

- `coinank.seconds_until_next_funding`
- `coinank.funding_payload_age_seconds`
- `coinank.oi_payload_age_seconds`
- `coinank.funding_oi_direction_agreement`
- `coinank.funding_rate_bps`
- `coinank.mark_premium_to_index_bps`

Codex verified they are derived only from existing V2-owned inputs:

- `v2:market:funding:{symbol}`
- `v2:market:open_interest:{symbol}`
- `v2:market:prices:{symbol}`
- `v2:features:latest:{symbol}:1m`

Current runtime proof showed `source_freshness_state=CURRENT` for all three symbols. The new fields carried `V2_DERIVED_FROM_FUNDING`, `V2_DERIVED_FROM_FUNDING_TIMESTAMP`, `V2_DERIVED_FROM_OPEN_INTEREST_TIMESTAMP`, or `V2_DERIVED_FROM_FUNDING_AND_FEATURES` source labels. Runtime funding/OI payload ages were approximately 50-61 seconds during review.

No legacy Redis `features:*` key or old production key is consumed as current truth. Source-scan hits for legacy terms are schema metadata, comments, or safety flags such as `no_legacy_features_consumed_as_current_truth=true`, not legacy current-truth reads.

## Missing Fields

External and operator-gated families remain explicit:

- `unified_feature_family.token_metrics`
- `onchain_btc`
- `onchain_eth`
- `unified_feature_family.ccxt_ohlcv`

The refreshed payload reports `next_required_family=liquidations`, preserving the missing liquidation slots instead of fabricating per-symbol liquidation state. Missing field samples remain visible in the worklog and public payloads.

## Safety

Codex verified:

- `zero_filled_field_count=0`;
- `no_zero_fill_for_unknown_fields=true`;
- `checkpoint_compatibility_claimed=false`;
- `policy_architecture_parity_claimed=false`;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- `approves_live=false`;
- `approves_canary=false`;
- `approves_legacy_shutdown=false`;
- `approves_redis_trim=false`;
- no Redis write call in the reviewed builder path;
- no old Redis write path in reviewed source/status payloads;
- no exchange order, cancel, modify, leverage, margin, `/fapi/`, or test-order mutation path;
- raw credential-value scan over reviewed source/tests/worklog/public payloads found `0` hits outside `.local_secrets`.

Frontend/public payloads show partial status honestly: generated dimensions, missing dimensions, explicit missing families, zero-fill count, and blocked live state are visible in the refreshed public/operator-runtime mirrors.

## Validation

- Full-observation status refresh: PASS.
- Focused unified/full-observation test sweep: `49 passed`.
- `py_compile`: PASS.
- Direct current-Redis CoinAnk field proof: PASS.
- V2-only read inspection: PASS.
- External-family explicit-missing inspection: PASS.
- Redis write scan: PASS, no writes in reviewed builder path.
- Old Redis/current-truth scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- Raw credential scan: PASS, `0` hits.
- Validation sweep: PASS, `22` files scanned, `0` secret hits, `0` approval-true hits, `0` legacy Redis hits, `0` exchange mutation hits.

## Final Decision

`V2_FULL_OBSERVATION_UNIFIED_FEATURES_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`
