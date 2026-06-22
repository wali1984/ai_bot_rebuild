# Implementation Report — realtime_price_provider_running_partial

Milestone: **v2_zero_exception_parity_implementation_burndown**  
Generated (EST): 2026-06-01T17:50:28-0400  
Generated (UTC): 2026-06-01T21:50:28Z  
Status: **DONE_VERIFIED**

## Claim
V2_RUNNING_PARTIAL resolved: order-book top/depth now written to v2:market:orderbook:{symbol} and consumed by the feature pipeline (depth_imbalance + bid_ask_spread_bps real).

## Raw evidence
`v2:market:orderbook:BTCUSDT` TTL=516s (60s refresh); feature depth_imbalance=0.40957803081044875, bid_ask_spread_bps=0.014072367148878013.

## Verification command
```
redis-cli ttl v2:market:orderbook:BTCUSDT; redis-cli get v2:market:orderbook:BTCUSDT | head -c 80
```

## Files modified
- `v2/backend/app/cli/v2_native_ingestors_live_loop.py`
- `v2/backend/app/cli/v2_feature_pipeline_native_loop.py`

## Confidence
HIGH

## Missing evidence
Per-symbol explicit spread key (instant:{sym}:spread) folded into feature, not a standalone key.

## Live safety
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false | approves_live: false | approves_canary: false
