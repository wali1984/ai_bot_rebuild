# Remaining-Dim Execution Queue — Remediation Report

GO/NO-GO: `V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`

Prior Codex FAIL: `V2_BUILDABLE_NOW_QUEUE_LACKS_EXACT_FIELD_SOURCE_BOUNDARY`

## What changed in `tools/v2_full_observation_remaining_dim_classifier.py`

1. Two missing source bindings added so no `V2_BUILDABLE_NOW` task carries the
   generic `v2:* (review builder code for exact source)` hint any more:
   - `portfolio_state.v2_orchestrator_keys_written_count` →
     `v2:orchestrator:decisions`
   - `position_context.v2_pre_trade_allowed_rate` → `v2:risk:decisions`
2. New `field_metadata_by_group` dict — every next-10 task carries:
   - `field_id`, `scope` (per_symbol|global), `exact_v2_source_keys`,
     `expected_payload_field`, `stale_or_missing_behavior`,
     `implementation_target_function`, `tests_required`.
3. Strict-source contract gate added at the top of `main()`:
   - counts generic hints, broad-bucket emission, and aggregate total;
   - flips GO_NO_GO to `…_REMEDIATION_BLOCKED` if any check fails.
4. Broad reserved `portfolio_state` bucket stays in
   `NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH` (via
   `MISSING_FROM_V2_PORTFOLIO_STATE_EXTENDED`), so it is never emitted as a
   buildable parent task.
5. Altdata-symbol-score fields remain `V2_LANE_EXISTS_PAYLOAD_ABSENT` until
   the V2 scorer republishes `v2:altdata:symbol_score:{symbol}`.

## Verified numbers (this run)

- aggregate_total_observed = 5733 (1911 × 3)
- aggregate_total_check = PASS
- strict_source_contract_pass = True
- generic_source_hint_hits = 0
- field_spec_hold_count = 0
- portfolio_state_broad_bucket_emitted = False

Category counts (5074 missing):

| category | count |
|---|---:|
| V2_BUILDABLE_NOW | 16 |
| V2_LANE_EXISTS_PAYLOAD_ABSENT | 18 |
| V2_EVENT_DEPENDENT_LIQUIDATION_WSS | 12 |
| V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED | 60 |
| EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS | 54 |
| EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC | 45 |
| EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH | 45 |
| OPERATOR_DECISION_REQUIRED_CCXT_OHLCV | 30 |
| LEGACY_V3_EXTRA_NO_V2_SOURCE | 3879 |
| NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH | 915 |

## Next-10 tasks (all exact-source, all with field metadata)

| group | exact V2 source key(s) |
|---|---|
| portfolio_state.v2_orchestrator_keys_written_count | v2:orchestrator:decisions |
| portfolio_state.portfolio_trainer_heartbeat_age_seconds | v2:trainer:heartbeat |
| portfolio_state.portfolio_symbol_risk_decision_present | v2:risk:decisions |
| portfolio_state.portfolio_symbol_pre_trade_allowed | v2:risk:decisions |
| portfolio_state.portfolio_symbol_fee_gate_allowed | v2:risk:decisions |
| portfolio_state.portfolio_symbol_churn_blocked | v2:risk:decisions |
| position_context.pre_trade_allowed | v2:risk:decisions |
| position_context.fee_gate_allowed | v2:risk:decisions |
| position_context.churn_blocked | v2:risk:decisions |
| position_context.v2_pre_trade_allowed_rate | v2:risk:decisions |

## Safety

No exchange call, no Redis write outside `v2:*` / local artifacts, no
approval token created, no live/canary/shutdown markers, no policy
architecture started, no checkpoint claim. `live_gate=blocked_human_only`,
`live_symbols=[]`.
