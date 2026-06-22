# V2 Full Observation Feature-Family Burndown Report

GO/NO-GO: `V2_FULL_OBSERVATION_FEATURE_FAMILY_BURNDOWN_READY_PARTIAL_PROGRESS`

This packet does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, Redis trim, paper-only shutdown acceptance,
checkpoint compatibility, or policy architecture parity. It does NOT
load any pickle/torch blob.

## Burndown delta

| Symbol | generated_dim before | generated_dim after | delta |
| ------ | -------------------: | ------------------: | ----: |
| BTCUSDT | 44 | 109 | +65 |
| ETHUSDT | 44 | 109 | +65 |
| SOLUSDT | 39 | 104 | +65 |

Target full_observation_dim = 1911 (unchanged). State stays
`FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` because the trailing
1802 dims (legacy V3 padding + external + operator) remain explicit
missing without zero-fill.

## What changed in the builder

[v2/backend/app/services/rl_core/full_observation_builder.py](v2/backend/app/services/rl_core/full_observation_builder.py) now:

- Defines an explicit `SUBFAMILY_LAYOUT` matching the legacy
  `unified_feature_builder.FeatureDimensions` defaults
  (binance_klines=20, binance_orderbook=15, ccxt_ohlcv=10, liquidations=12,
  technical_analysis=25, token_metrics=18, coinank=22,
  portfolio_state_unified=15 — sums to 137; remaining 1293 dims are
  explicit `MISSING_LEGACY_V3_EXTRA_NO_V2_SOURCE`).
- Reads new V2-native sources from Redis: `v2:market:prices:{sym}`
  (ticker_24hr 21 fields), `v2:market:funding:{sym}` (7 fields),
  `v2:market:open_interest:{sym}` (1 numeric).
- Projects sub-families with named V2-native sources where data exists,
  and labels every other slot with a specific MISSING source code.
- Extends `portfolio_state` from 12 to 21 fields (long/short/flat counts,
  notional proxy, expected_move sum, confidence sum, prediction_blocked
  count, orchestrator counters).
- Extends `position_context` from 9 to 15 fields per symbol (side
  one-hot, held-by-paper-fill-gate flag, block_reason_count,
  trainer-confidence, selected_action_is_hold).
- Onchain_btc/eth remain `ONCHAIN_FEATURE_SOURCE_MISSING` (15+15 dims
  external-source-required).

## Subfamily present counts (sum across 3 symbols)

```
binance_klines           : 60  / target 60   (target per symbol = 20)
binance_orderbook        : 30  / target 45
liquidations             :  3  / target 36
technical_analysis       : 54  / target 75
coinank                  : 30  / target 66
portfolio_state_unified  : 45  / target 45
ccxt_ohlcv               :  0  / target 30   (OPERATOR_DECISION_REQUIRED)
token_metrics            :  0  / target 54   (EXTERNAL_SOURCE_REQUIRED)
```

Three sub-families are now fully sourced from V2-native data
(`binance_klines`, `portfolio_state_unified`), and three are partially
sourced with the gap explicitly labeled.

## Categories remaining

- `unified_features`: partial — V2 native sub-families filled,
  1293 trailing legacy-V3-padding dims still explicit missing.
- `portfolio_state`: partial — 21 of 401 dims filled.
- `position_context`: partial — 15 of 50 dims filled per symbol.
- `onchain_btc`: external-source-required.
- `onchain_eth`: external-source-required.

`next_required_family = binance_orderbook` (first sub-family with
present < target across all symbols, excluding external/operator
families). This drives the next burndown step.

## Continuous remediation integration

Continuous remediation tool still reports
`V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY` with
`gaps_severity_counts = {NO_ACTION_REQUIRED_SAFE_BLOCK: 3,
OPERATOR_DECISION_REQUIRED: 2, BLOCKS_PRODUCTION_EQUIVALENCE: 2}` —
unchanged checkpoint blocker visibility. No duplicate checkpoint task
created. The policy port task remains operator-decision-required (not
active implementation).

The 9 narrow source-family task pairs from the prior sprint remain on
disk (created earlier, idempotent across re-runs).

## Frontend Monitor Center

4 new cards reading
`/v2_full_observation_feature_family_burndown/latest/operator_dashboard_payload.json`:
- Feature-family burndown GO/NO-GO + state + next_required_family
- Per-sub-family present-vs-target counters (top 8)
- External / operator-decision families summary

`tsc --noEmit` exit 0.

## Tests

[test_v2_full_observation_feature_family_burndown.py](v2/backend/tests/integration/cli/test_v2_full_observation_feature_family_burndown.py): 5/5 new pass:
- subfamily layout sums to 137
- generated_dim >= 100 (was 44)
- sub-family present_counts populated for buildable families and zero
  for external/operator families
- subfamily totals aggregated in status payload
- state remains PARTIAL until 1911 dims filled
- external & operator-decision lists remain explicit

Plus the prior 31 tests in this lane keep passing after a single-line
update to the source-label expectation in
`test_v2_full_observation_builder_status.py` (slot 0 is now a
`binance_klines.last_price` projection rather than a flat feature
position).

## Safety invariants (raw)

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- `checkpoint_compatibility_claimed = false`
- `policy_architecture_parity_claimed = false`
- `no_torch_imported = true`
- `no_pickle_loaded = true`
- `no_legacy_filesystem_read = true`
- `no_zero_fill_for_unknown_fields = true`
- `no_legacy_features_consumed_as_current_truth = true`

## What this packet does NOT do

- Does not implement onchain_btc / onchain_eth (external-source-required).
- Does not adopt token_metrics (external-source-required).
- Does not implement ccxt_ohlcv (operator-decision-required).
- Does not implement the policy architecture port.
- Does not claim checkpoint compatibility.
- Does not modify the V2 runtime policy input (compact 26-dim remains).
- Does not modify legacy.
- Does not approve live, canary, legacy shutdown, or Redis trim.

## Outputs

- [GO_NO_GO.md](claude_worklog/final_readiness/v2_full_observation_feature_family_burndown/latest/GO_NO_GO.md)
- [feature_family_burndown_status.json](claude_worklog/final_readiness/v2_full_observation_feature_family_burndown/latest/feature_family_burndown_status.json)
- [operator_dashboard_payload.json](v2/frontend/public/v2_full_observation_feature_family_burndown/latest/operator_dashboard_payload.json)
- [full_observation_builder_status.json](v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json) (refreshed by the upstream builder CLI)
