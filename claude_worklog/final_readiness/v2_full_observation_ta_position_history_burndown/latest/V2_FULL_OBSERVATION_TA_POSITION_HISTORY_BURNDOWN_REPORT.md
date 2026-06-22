# V2 Full-Observation TA + Position-History Burndown Report

Generated: `2026-05-21T04:19:22Z`

GO/NO-GO: `V2_FULL_OBSERVATION_TA_POSITION_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS`

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT start policy architecture. It does NOT claim checkpoint
compatibility. It does NOT claim policy architecture parity.

## Scope

Continues internal V2-native full-observation expansion after the
liquidation WSS daemon registration. The work is limited to:

- stabilizing the TA final slot `htf_lf_trend_agreement`;
- expanding V2-owned position-history context from V2 paper data;
- surfacing MFE/MAE/ROE as unavailable unless V2-owned price tracking
  or realized-exit evidence exists;
- refreshing full-observation status mirrors.

No legacy filesystem, legacy Redis namespace, provider API, exchange
order endpoint, torch checkpoint, or policy architecture path is used.

## TA Slot

`htf_lf_trend_agreement` now computes only when `htf_ret_pct` and
`rsi_14` are present and the feature snapshot is `CURRENT`. Otherwise
it emits one of the explicit blockers:

- `MISSING_HTF_RET_PCT_AND_RSI_14_FROM_V2_FEATURES`
- `MISSING_HTF_RET_PCT_FROM_V2_FEATURES`
- `MISSING_RSI_14_FROM_V2_FEATURES`
- `BLOCKED_BY_FEATURE_FRESHNESS_NOT_CURRENT:<state>`
- `V2_DERIVED_FROM_FEATURES` when computed

The neutral RSI boundary (`rsi_14 == 50.0`) is treated consistently
instead of falling through by accident.

`macd_signal_strength` remains the current genuine TA gap when
`macd == 0.0`; it reports `MACD_ZERO_RATIO_UNDEFINED` rather than
fabricating a value.

## Position-History Aggregator

Updated module:

- `v2/backend/app/services/rl_core/position_history_aggregator.py`

The aggregator reads only V2-owned paper inputs:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- `v2:paper:position_price_track:{symbol}` when present
- `v2:paper:position_history:{symbol}` when present

It never writes Redis, never reads legacy Redis keys, never reads the
legacy filesystem, never imports torch, and never loads pickle.

New real V2-owned position-context fields include:

- position age / hold-time proxy from V2 paper position records;
- accepted, blocked, and held intent counts;
- pre-trade, fee-gate, and churn rates from V2 paper intents;
- block-reason counts for negative expected move, edge below threshold,
  feature freshness, checkpoint-required, trainer-malformed, and other;
- MFE/MAE/ROE fields with explicit `MISSING_V2_OWNED_*` source strings
  unless V2-owned tracking data exists.

The accepted-count path now refuses to count generic shadow intents as
accepted positions. It uses ledger `accepted` rows or explicitly
accepted paper rows only.

## Current Status

The refreshed full-observation status remains honest partial progress:

| Symbol | Prior generated dim | Current generated dim | Missing dim | Delta |
| --- | ---: | ---: | ---: | ---: |
| `BTCUSDT` | `148` | `157` | `1754` | `+9` |
| `ETHUSDT` | `148` | `157` | `1754` | `+9` |
| `SOLUSDT` | `143` | `151` | `1760` | `+8` |

The builder still reports:

- `state=FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- `target_full_observation_dim=1911`
- `zero_filled_field_count=0`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

Current live V2 paper evidence has no accepted open paper position
records, so position age, hold-time proxy, MFE, MAE, and ROE remain
unavailable with explicit V2-owned missing-source strings. SOLUSDT has
real held-by-paper-fill-gate blockers counted from V2 paper rows:
negative expected move, checkpoint required, and trainer output
malformed.

## Safety

This packet preserves:

- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `no_zero_fill_for_unknown_fields=true`
- `no_legacy_features_consumed_as_current_truth=true`
- `no_torch_imported=true`
- `no_pickle_loaded=true`

## Validation

- Burndown test suite: `24 passed`.
- Existing full-observation builder status tests: `9 passed`.
- `py_compile`: PASS for the aggregator, builder, status CLI, and
  burndown tests.
- Full-observation builder status refreshed: PASS.
- Worklog and public operator payloads refreshed: PASS.

## Outputs

- `claude_worklog/final_readiness/v2_full_observation_ta_position_history_burndown/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_full_observation_ta_position_history_burndown/latest/V2_FULL_OBSERVATION_TA_POSITION_HISTORY_BURNDOWN_REPORT.md`
- `claude_worklog/final_readiness/v2_full_observation_ta_position_history_burndown/latest/ta_position_history_burndown_status.json`
- `v2/frontend/public/operator_runtime/v2_full_observation_ta_position_history_burndown/latest/operator_dashboard_payload.json`
- `claude_worklog/final_readiness/v2_full_observation_builder/latest/full_observation_builder_status.json`
- `v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json`
- `v2/frontend/public/v2_full_observation_builder/latest/operator_dashboard_payload.json`
- `v2/backend/app/services/rl_core/full_observation_builder.py`
- `v2/backend/app/services/rl_core/position_history_aggregator.py`
- `v2/backend/tests/integration/cli/test_v2_full_observation_ta_position_history_burndown.py`

## Final Decision

`V2_FULL_OBSERVATION_TA_POSITION_HISTORY_BURNDOWN_READY_PARTIAL_PROGRESS`
