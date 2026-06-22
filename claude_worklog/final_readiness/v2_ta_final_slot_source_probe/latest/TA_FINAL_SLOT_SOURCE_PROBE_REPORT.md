# V2 Technical Analysis Final-Slot Source Probe Report

GO/NO-GO: `V2_TA_FINAL_SLOT_SOURCE_PROBE_READY`

Read-only probe. Does NOT modify `full_observation_builder.py`,
legacy, or any external feed. Does NOT approve live, canary,
leverage/margin, exchange mutation, legacy shutdown, or Redis trim.

## Current state

- `technical_analysis` target per symbol: **25**
- `technical_analysis` present per symbol: **24**
- `technical_analysis` missing per symbol: **1**

## Filled fields (25 V2-derived projections)

- `rsi_14`, `rsi_14_oversold_30`, `rsi_14_overbought_70`
- `macd`, `macd_signal`, `macd_hist`, `macd_hist_sign`,
  `macd_signal_strength`, `macd_above_signal`
- `ema_12`, `ema_26`, `ema_diff`, `ema_ratio`, `trend_slope_proxy`
- `bb_width_pct`
- `htf_rsi_14`, `htf_rsi_14_oversold_30`, `htf_rsi_14_overbought_70`,
  `htf_ret_pct`, `htf_lf_trend_agreement`
- `body_pct`, `range_pct`, `true_range_pct`, `gap_pct`,
  `volatility_proxy`

## Diagnosis of the missing slot

The 25-slot subfamily target is matched by the projector. The single
observed gap per symbol corresponds to **`htf_lf_trend_agreement`**
evaluating to `None` when either `htf_ret_pct` or `rsi_14` is itself
absent from the V2 feature snapshot for that cycle. This is a
data-availability artifact, not a structural V2 source gap.

## Classification

`V2_SOURCE_PRESENT_WHEN_BOTH_HTF_RET_AND_LF_RSI_AVAILABLE`

- `computable_from_existing_v2_features_today = true`
- `operator_decision_required = false`
- `external_source_required = false`

## Next actionable step

No new V2 ingestor required. The V2 feature pipeline already emits
both `htf_ret_pct` and `rsi_14`. The slot will fill on cycles where
both are present (the steady-state case during the current 6h+ soak).

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- `modifies_full_observation_builder = false`
- `modifies_legacy = false`
- `creates_external_feed = false`
- `creates_credentials = false`
- `loads_any_blob = false`
- `no_raw_credentials_in_packet = true`
