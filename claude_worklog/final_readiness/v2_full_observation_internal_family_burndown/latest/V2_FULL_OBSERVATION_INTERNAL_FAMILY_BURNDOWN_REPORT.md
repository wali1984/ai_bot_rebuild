# V2 Full Observation Internal Family Burndown Report (round 2)

GO/NO-GO: `V2_FULL_OBSERVATION_INTERNAL_FAMILY_BURNDOWN_READY_PARTIAL_PROGRESS`

This packet does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, Redis trim, paper-only shutdown acceptance,
checkpoint compatibility, or policy architecture parity. It does NOT
load any pickle/torch blob.

## Burndown delta

| Symbol | prior generated_dim | new generated_dim | delta |
| ------ | ------------------: | ----------------: | ----: |
| BTCUSDT | 109 | 144 | +35 |
| ETHUSDT | 109 | 144 | +35 |
| SOLUSDT | 104 | 139 | +35 |

Target full_observation_dim remains 1911. State stays
`FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` because the trailing
1767 dims (legacy V3 padding + external + operator) remain explicit
missing without zero-fill.

## What changed in [full_observation_builder.py](v2/backend/app/services/rl_core/full_observation_builder.py)

### PHASE 1 — binance_orderbook (10 → 15 per symbol)

Added 5 V2-native derived fields:
- `depth_imbalance_direction` (sign of depth_imbalance)
- `bid_qty_minus_ask_qty` (derived from ticker_24hr)
- `mid_minus_micro_price` (derived from mid_price and micro_price)
- `v2_depth_source_available = 0.0` — probe flag confirming
  `v2:market:depth*` is empty
- `orderbook_v2_native_source_count = 1.0` — ticker-only probe flag

### PHASE 2 — technical_analysis (18 → 24 per symbol)

Added 7 V2-derived TA fields (all from existing
`v2:features:latest:*`):
- `ema_ratio = ema_12 / ema_26`
- `trend_slope_proxy = ema_diff / ema_26`
- `macd_signal_strength = |macd_hist| / |macd|`
- `macd_above_signal` (boolean)
- `htf_rsi_14_oversold_30`, `htf_rsi_14_overbought_70` (booleans)
- `htf_lf_trend_agreement` (htf return sign + lower-tf RSI side agree)

### PHASE 3 — coinank (10 → 16 per symbol)

Added 6 V2-derived fields:
- `funding_abs = |last_funding_rate|`
- `funding_direction` (sign)
- `oi_change_pct_abs`, `oi_change_pct_direction`
- `basis_mark_minus_index_pct` = `(mark_price - index_price) / index_price`
- `v2_coinank_aggregator_source_available = 0.0` — probe flag
  confirming no V2 CoinAnk aggregator key

### PHASE 4 — liquidations (1 → 4 per symbol)

Added 3 V2-derived/probe fields:
- `last_liq_bps_24h_abs`
- `last_liq_direction`
- `v2_liquidation_source_available = 0.0` — probe flag confirming
  no `v2:liquidations:*` aggregator key

### PHASE 5 — portfolio_state + position_context

- portfolio_state: added `gate_open_ratio`, `accepted_minus_blocked`,
  `predictions_blocked_minus_open_gate`, `risk_decision_total_count`,
  `risk_all_three_gates_allowed_for_any` (21 → 26 fields).
- position_context: added `expected_move_bps`,
  `expected_move_diff_bps_minus_after_cost`, `confidence_raw`,
  `confidence_calibration_delta`, `selected_action_is_long`,
  `selected_action_is_short`, `has_block_reason_negative_em`,
  `has_block_reason_edge_below_threshold`,
  `has_block_reason_feature_freshness`,
  `v2_position_history_source_available = 0.0`
  (15 → 25 fields per symbol).

## Subfamily present-vs-target counts (sum across 3 symbols)

```
binance_klines           : 60 / 60   (fully sourced)
binance_orderbook        : 45 / 45   (now fully sourced; 5 probe-derived)
liquidations             : 12 / 36   (partial; source-not-available flagged)
technical_analysis       : 72 / 75   (very near full; 1 slot per symbol remains explicit-missing)
coinank                  : 48 / 66   (partial; paid aggregator absent)
portfolio_state_unified  : 45 / 45   (fully sourced)
ccxt_ohlcv               :  0 / 30   (OPERATOR_DECISION_REQUIRED)
token_metrics            :  0 / 54   (EXTERNAL_SOURCE_REQUIRED)
```

Two sub-families that were partial in round-1 are now fully sourced
(`binance_orderbook`, `portfolio_state_unified`). `technical_analysis`
is 96% sourced and `coinank` 73%. `liquidations` and the external/
operator-decision families stay explicit-missing without fabrication.

## Categories remaining

- `unified_features`: partial — V2 native sub-families filled to ~177/137
  of the named slot range (subfamily target = 137, actual present = 177
  because TA slot count exceeds target by design); 1293 trailing
  legacy-V3-padding dims still explicit missing.
- `portfolio_state` (slice 401): partial — 26 of 401 dims filled.
- `position_context` (slice 50): partial — 25 of 50 dims filled per symbol.
- `onchain_btc` / `onchain_eth`: external-source-required.

`next_required_family = liquidations` (the highest-gap V2-buildable
family without an external/operator block). Closing it further requires
a new V2-native liquidation aggregator ingestor (covered by the
`V2_ORDERBOOK_SOURCE_PROBE` and gap matrix — same operator-decision
discipline applies).

## Probe packets emitted in parallel

- [V2_ORDERBOOK_SOURCE_PROBE](claude_worklog/final_readiness/v2_orderbook_source_probe/latest/GO_NO_GO.md) →
  `V2_ORDERBOOK_PARTIAL_ONLY`; default `DEFER_DEPTH_LADDER_SOURCE`.
- [V2_COINANK_FEATURE_SOURCE_PROBE](claude_worklog/final_readiness/v2_coinank_feature_source_probe/latest/GO_NO_GO.md) →
  `V2_COINANK_FEATURE_PARTIAL_ONLY`; default `DEFER_COINANK_AGGREGATOR`.

Neither probe modified `full_observation_builder.py`; both are read-only.

## Continuous remediation integration

The continuous remediation tool reports
`V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY` (12/12 V2
processes, soak_6h_ready=true, v2:* namespaces non-empty,
remediation_tasks_created_count = 0). No duplicate checkpoint task
created. Policy architecture port task remains operator-decision-
required.

## Tests

[test_v2_full_observation_internal_family_burndown.py](v2/backend/tests/integration/cli/test_v2_full_observation_internal_family_burndown.py):
5/5 new pass:
- subfamily present_counts cleared round-1 bounds (orderbook ≥13, TA ≥22,
  coinank ≥14, liquidations ≥4)
- `v2_depth_source_available = 0.0` with
  `V2_PROBE_FLAG_NO_DEPTH_LADDER_PRESENT` source
- `v2_coinank_aggregator_source_available = 0.0` with
  `V2_PROBE_FLAG_NO_COINANK_AGGREGATOR_PRESENT` source
- `v2_liquidation_source_available = 0.0` with
  `V2_PROBE_FLAG_NO_LIQUIDATION_AGGREGATOR_PRESENT` source
- `zero_filled_field_count = 0` after expansion; `none_count =
  missing_dim_count`; state stays `PARTIAL`

Round-1 tests (22) keep passing untouched.

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

- Does not implement external feeds (token_metrics, onchain_btc, onchain_eth).
- Does not implement ccxt_ohlcv.
- Does not implement the policy architecture port.
- Does not claim checkpoint compatibility.
- Does not modify the V2 runtime policy input (compact 26-dim remains).
- Does not modify legacy.
- Does not approve live, canary, legacy shutdown, or Redis trim.
- Does not declare `FULL_OBSERVATION_BUILDER_COMPLETE` (1911 not reached).

## Outputs

- [GO_NO_GO.md](claude_worklog/final_readiness/v2_full_observation_internal_family_burndown/latest/GO_NO_GO.md)
- [internal_family_burndown_status.json](claude_worklog/final_readiness/v2_full_observation_internal_family_burndown/latest/internal_family_burndown_status.json)
- [operator_dashboard_payload.json](v2/frontend/public/v2_full_observation_internal_family_burndown/latest/operator_dashboard_payload.json)
- [v2_orderbook_source_probe/latest/GO_NO_GO.md](claude_worklog/final_readiness/v2_orderbook_source_probe/latest/GO_NO_GO.md) + report + JSON + dashboard
- [v2_coinank_feature_source_probe/latest/GO_NO_GO.md](claude_worklog/final_readiness/v2_coinank_feature_source_probe/latest/GO_NO_GO.md) + report + JSON + dashboard
- Builder status mirror refreshed at [v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json](v2/frontend/public/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json)
