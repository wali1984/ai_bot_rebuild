# GO / NO-GO — hardcoded_ta_htf_rsi_14

- Decision: **GO**
- Milestone: v2_zero_exception_parity_implementation_burndown
- Generated (EST): 2026-06-01T17:50:28-0400
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false

## Claim
TA feature `htf_rsi_14` is REAL_COMPUTED in live V2 Redis (pre: hardcoded/absent). Live value=19.35592315394628. Source: RSI(14) over 5x-downsampled higher-timeframe close series.

## Verification command
```
redis-cli get v2:features:latest:BTCUSDT:1m | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['real_feature_count'],d['missing_feature_count'],d['features'])"
```

## Confidence
HIGH

## Missing evidence
None for this field. (Full 562-field unified_features parity tracked separately under feature_pipeline_running_partial.)
