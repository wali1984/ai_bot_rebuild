# GO / NO-GO — realtime_price_provider_running_partial

- Decision: **GO**
- Milestone: v2_zero_exception_parity_implementation_burndown
- Generated (EST): 2026-06-01T17:50:28-0400
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false

## Claim
V2_RUNNING_PARTIAL resolved: order-book top/depth now written to v2:market:orderbook:{symbol} and consumed by the feature pipeline (depth_imbalance + bid_ask_spread_bps real).

## Verification command
```
redis-cli ttl v2:market:orderbook:BTCUSDT; redis-cli get v2:market:orderbook:BTCUSDT | head -c 80
```

## Confidence
HIGH

## Missing evidence
Per-symbol explicit spread key (instant:{sym}:spread) folded into feature, not a standalone key.
