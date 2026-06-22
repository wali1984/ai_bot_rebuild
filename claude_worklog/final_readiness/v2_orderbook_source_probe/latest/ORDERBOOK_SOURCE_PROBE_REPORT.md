# V2 Orderbook Source Probe Report

GO/NO-GO: `V2_ORDERBOOK_SOURCE_PROBE_READY`

This probe is read-only. It does NOT modify `full_observation_builder.py`,
legacy, or any external feed. It does NOT approve live, canary,
leverage/margin, exchange mutation, legacy shutdown, or Redis trim.

## What was probed

Redis patterns scanned for any V2-native orderbook/depth data:

```
v2:market:depth*        : 0 keys
v2:market:orderbook*    : 0 keys
v2:market:order_book*   : 0 keys
v2:depth*               : 0 keys
v2:orderbook*           : 0 keys
```

No level-2 depth ladder exists in `v2:*` Redis today.

## V2-native partial sources present

These keys are populated and usable for partial orderbook projection:

- `v2:market:prices:{symbol}.ticker_24hr`: `bidPrice`, `askPrice`,
  `bidQty`, `askQty`.
- `v2:features:latest:{symbol}:{timeframe}.features`:
  `bid_ask_spread_bps`, `depth_imbalance`, `micro_price`,
  `toxicity_proxy`.

## Source availability classification

`V2_ORDERBOOK_PARTIAL_ONLY`.

V2 can build ~10 of 15 `binance_orderbook` subfamily slots today (best-
bid/ask price+qty, mid_price, spread_pct_derived, and four feature-
snapshot microstructure fields). The remaining ~5 slots require a new
V2-native depth ingestor.

## Operator decision options

- **DEFER_DEPTH_LADDER_SOURCE**: keep MISSING flags for level-2 fields
  (current default).
- **APPROVE_NEW_V2_DEPTH_INGESTOR**: build
  `v2/backend/app/cli/v2_orderbook_depth_ingestor_loop.py` writing
  `v2:market:depth:{symbol}`; requires operator scoping, rate-limit
  decision, and Codex review pair.

Current default state: **DEFER_DEPTH_LADDER_SOURCE**.

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
