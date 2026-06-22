# GO / NO-GO — hardcoded_ta_macd

- Decision: **GO**
- Milestone: v2_zero_exception_parity_implementation_burndown
- Generated (EST): 2026-06-01T17:50:28-0400
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false

## Claim
TA feature `macd` is REAL_COMPUTED in live V2 Redis (pre: hardcoded 0.0). Live value=-40.546252656160505. Source: EMA(12)-EMA(26) MACD line over real OHLCV closes.

## Verification command
```
redis-cli get v2:features:latest:BTCUSDT:1m | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['real_feature_count'],d['missing_feature_count'],d['features'])"
```

## Confidence
HIGH

## Missing evidence
None for this field. (Full 562-field unified_features parity tracked separately under feature_pipeline_running_partial.)
