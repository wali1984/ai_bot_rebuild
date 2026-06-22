# Implementation Report — hardcoded_ta_depth_imbalance

Milestone: **v2_zero_exception_parity_implementation_burndown**  
Generated (EST): 2026-06-01T17:50:28-0400  
Generated (UTC): 2026-06-01T21:50:28Z  
Status: **DONE_VERIFIED**

## Claim
TA feature `depth_imbalance` is REAL_COMPUTED in live V2 Redis (pre: hardcoded/absent). Live value=0.40957803081044875. Source: (bid-ask)/(bid+ask) from v2:market:orderbook:{sym} top of book.

## Raw evidence
`v2:features:latest:BTCUSDT:1m`.features.depth_imbalance = 0.40957803081044875 (generated_at=2026-06-01T21:50:20Z); BTC snapshot real_feature_count=25, missing_feature_count=0; 27 live v2:features:latest:*:1m keys. Code: v2/backend/app/cli/v2_feature_pipeline_native_loop.py _features_from_market().

## Verification command
```
redis-cli get v2:features:latest:BTCUSDT:1m | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['real_feature_count'],d['missing_feature_count'],d['features'])"
```

## Files modified
- `v2/backend/app/cli/v2_native_ingestors_live_loop.py`
- `v2/backend/app/cli/v2_feature_pipeline_native_loop.py`

## Confidence
HIGH

## Missing evidence
None for this field. (Full 562-field unified_features parity tracked separately under feature_pipeline_running_partial.)

## Live safety
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false | approves_live: false | approves_canary: false
