# V2 Full Observation Liquidation Burndown Report

GO/NO-GO: `V2_FULL_OBSERVATION_LIQUIDATION_BURNDOWN_READY_PARTIAL_PROGRESS`

This packet does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, Redis trim, paper-only shutdown acceptance,
checkpoint compatibility, or policy architecture parity. It does NOT
load any pickle/torch blob.

## Burndown delta

| Symbol | prior generated_dim | new generated_dim | delta | liq subfamily before | liq subfamily after |
| ------ | ------------------: | ----------------: | ----: | -------------------: | ------------------: |
| BTCUSDT | 144 | 148 | +4 | 4 / 12 | 8 / 12 |
| ETHUSDT | 144 | 148 | +4 | 4 / 12 | 8 / 12 |
| SOLUSDT | 139 | 143 | +4 | 4 / 12 | 8 / 12 |

Target full_observation_dim remains 1911. State stays
`FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`.

Liquidation subfamily total: **12 → 24** of 36 across 3 symbols.

## What changed

### New module: [liquidation_observation_aggregator.py](v2/backend/app/services/rl_core/liquidation_observation_aggregator.py)

Computes the 12-slot per-symbol liquidation subfamily from V2 sources
only:

- `v2:features:latest:{symbol}:{tf}.features.last_liq_bps_24h`
- `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/
  coinank_market_intelligence_status.json`
  - `freshness_seconds`
  - `global_aggregate_result.total_liquidations`

12 named slots per symbol:

| Slot | Source | V2 today |
| ---- | ------ | -------- |
| `latest_liquidation_notional` | per-symbol aggregator | **MISSING** |
| `latest_liquidation_side_long` | per-symbol aggregator | **MISSING** |
| `latest_liquidation_side_short` | per-symbol aggregator | **MISSING** |
| `last_liq_bps_24h` | V2_NATIVE_FEATURE_SNAPSHOT | filled |
| `last_liq_bps_24h_abs` | V2_DERIVED_FROM_FEATURES | filled |
| `last_liq_direction` | V2_DERIVED_FROM_FEATURES | filled |
| `liquidation_count_proxy_global` | V2_COINANK_GLOBAL_AGGREGATE_NOT_PER_SYMBOL | filled (with explicit not-per-symbol label) |
| `liquidation_notional_1h_proxy` | per-symbol aggregator | **MISSING** |
| `liquidation_notional_24h_proxy` | V2_NATIVE_FEATURE_SNAPSHOT | filled |
| `liquidation_direction_bias` | V2_DERIVED_FROM_FEATURES | filled |
| `liquidation_freshness_seconds` | V2_COINANK_MARKET_INTELLIGENCE | filled |
| `v2_liquidation_source_available` | V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT | filled = `0.0` |

8 of 12 slots filled per symbol — up from 4 in round 2. **No silent
zero-fill**: the 4 unfilled slots are all explicitly
`MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`.

### Builder wired to the aggregator

[full_observation_builder.py](v2/backend/app/services/rl_core/full_observation_builder.py):
`_project_liquidations` now delegates to
`build_liquidation_subfamily` with a lazy module-level import (keeps
zero-dependency at sub-family-registration time).

### CLI: [v2_liquidation_observation_aggregator_status.py](v2/backend/app/cli/v2_liquidation_observation_aggregator_status.py)

Emits `liquidation_aggregator_status.json` at:
- `claude_worklog/final_readiness/v2_full_observation_liquidation_burndown/latest/`
- `v2/frontend/public/v2_full_observation_liquidation_burndown/latest/`

Reports `subfamily_total_present_across_symbols=24`,
`subfamily_total_target_across_symbols=36`,
`v2_liquidation_aggregator_per_symbol_source_available=false`.

## Why per-symbol liquidation aggregator is missing

V2 has no `v2:liquidations:*` or `v2:market:liquidations:*` Redis keys
today. Available evidence:

- `v2:liquidations*`, `v2:market:liquidations*`, `v2:liquidation*`,
  `v2:ingestor:liquidations*`, `v2:binance:liquidations*` — **0 keys**.
- `coinank_market_intelligence_status.liquidations_persisted_total` = 0.
- `global_aggregate_result.total_liquidations` = 0.0 (aggregate, not
  per-symbol time-series).

So `latest_liquidation_notional`, `latest_liquidation_side_long/short`,
and `liquidation_notional_1h_proxy` remain `MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`.
A V2-native per-symbol liquidation aggregator is the next narrow lane
(operator-decision-required to scope rate-limits and ingestor wire-up).

## Subfamily totals (sum across 3 symbols)

```
binance_klines           : 60 / 60   (fully sourced)
binance_orderbook        : 45 / 45   (fully sourced)
technical_analysis       : 72 / 75   (96% sourced; 1 slot per symbol explicit-missing)
coinank                  : 48 / 66   (partial; paid aggregator absent)
portfolio_state_unified  : 45 / 45   (fully sourced)
liquidations             : 24 / 36   (was 12; +12 from aggregator wiring)
ccxt_ohlcv               :  0 / 30   (OPERATOR_DECISION_REQUIRED)
token_metrics            :  0 / 54   (EXTERNAL_SOURCE_REQUIRED)
```

`next_required_family` rotates back to `binance_orderbook` only because
the trailing 1293 dims of unified_features padding remain explicit-
missing across all sub-families; the named-subfamily progress story is
in this table.

## Continuous remediation integration

The continuous remediation tool still reports
`V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY` with
`gaps_severity_counts = {BLOCKS_PE:2, OPERATOR:2, SAFE_BLOCK:3}` — no
new gaps, no duplicate checkpoint task, no policy port activation.

## Parallel probe packets emitted (this sprint)

- [V2_TA_FINAL_SLOT_SOURCE_PROBE_READY](claude_worklog/final_readiness/v2_ta_final_slot_source_probe/latest/GO_NO_GO.md)
- [V2_COINANK_AGGREGATOR_DECISION_REFINEMENT_READY](claude_worklog/final_readiness/v2_coinank_aggregator_decision_refinement/latest/GO_NO_GO.md)
- [V2_POSITION_HISTORY_SOURCE_PROBE_READY](claude_worklog/final_readiness/v2_position_history_source_probe/latest/GO_NO_GO.md)

None modify `full_observation_builder.py`. All read-only.

## Tests

[test_v2_liquidation_observation_aggregator.py](v2/backend/tests/integration/cli/test_v2_liquidation_observation_aggregator.py):
8/8 new pass — 12-slot layout, V2-features paths filled, coinank global
labeled "NOT_PER_SYMBOL", per-symbol source flag = 0.0, missing-when-no-
inputs path, payload safety invariants, no-torch-import guard, builder
integration lifts the liquidation subfamily count past 6.

Plus the prior 27 tests in this lane pass (35/35 total) after a single
backward-compat assertion update for the source-flag label.

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

- Does not implement a V2-native per-symbol liquidation ingestor.
- Does not adopt external feeds (token_metrics, onchain_btc, onchain_eth).
- Does not implement ccxt_ohlcv.
- Does not implement the policy architecture port.
- Does not claim checkpoint compatibility.
- Does not modify the V2 runtime policy input (compact 26-dim remains).
- Does not modify legacy.
- Does not approve live, canary, legacy shutdown, or Redis trim.
- Does not declare `FULL_OBSERVATION_BUILDER_COMPLETE` (1911 not reached).
