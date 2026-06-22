# V2 CoinAnk Feature Source Probe Report

GO/NO-GO: `V2_COINANK_FEATURE_SOURCE_PROBE_READY`

This probe is read-only. It does NOT modify `full_observation_builder.py`,
legacy, or any external feed. It does NOT approve live, canary,
leverage/margin, exchange mutation, legacy shutdown, or Redis trim.

## V2-native sources present

- `v2:market:funding:{symbol}`: 7 fields (lastFundingRate, markPrice,
  indexPrice, interestRate, estimatedSettlePrice, nextFundingTime, time).
- `v2:market:open_interest:{symbol}`: 2 fields (openInterest, time).
- `v2:features:latest:{symbol}:{tf}.features`: `funding_rate`,
  `oi_change_pct`.

## V2-native sources absent

- `v2:market:coinank*` — 0 keys.
- `v2:coinank*` — 0 keys.

The CoinAnk paid aggregator (`long_short_ratio`,
`global_funding_aggregator`, `exchange_netflow`,
`whale_position_signals`, regional intelligence) is NOT in `v2:*` Redis.

## Buildable today (per symbol)

- last_funding_rate, mark_price, index_price, interest_rate,
  estimated_settle_price (from `v2:market:funding`)
- open_interest (from `v2:market:open_interest`)
- basis_mark_minus_last, basis_mark_minus_index (derived from market)
- funding_rate_feature, oi_change_pct (from v2:features)
- funding_abs (derived: `abs(funding_rate)`)
- funding_direction (derived: sign of funding_rate)
- funding_freshness_seconds, oi_freshness_seconds (derived from
  funding.time / open_interest.time)

Approximately **14** of the 22 `coinank` subfamily slots are buildable
today. The remaining ~8 slots require a paid aggregator or operator-
approved alternative.

## Source availability classification

`V2_COINANK_FEATURE_PARTIAL_ONLY`.

## Operator decision options

- **DEFER_COINANK_AGGREGATOR**: keep MISSING flags for non-public CoinAnk
  intelligence fields (current default).
- **APPROVE_COINANK_AGGREGATOR_SCOPE**: provide credentials and V2
  ingestor scope (separate Codex review pair required).

Current default state: **DEFER_COINANK_AGGREGATOR**.

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
