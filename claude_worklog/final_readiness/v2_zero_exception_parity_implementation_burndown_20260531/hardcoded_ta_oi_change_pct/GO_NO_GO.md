# GO / NO-GO — hardcoded_ta_oi_change_pct

- Decision: **GO**
- Milestone: v2_zero_exception_parity_implementation_burndown
- Generated (EST): 2026-06-01T17:50:28-0400
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false

## Claim
TA feature `oi_change_pct` is REAL_COMPUTED in live V2 Redis (pre: None (MISSING)). Live value=-0.0002398196770741531. Source: 1h OI delta from v2:market:open_interest_hist:{sym}:5m (Binance public openInterestHist).

## Verification command
```
redis-cli get v2:features:latest:BTCUSDT:1m | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['real_feature_count'],d['missing_feature_count'],d['features'])"
```

## Confidence
HIGH

## Missing evidence
None for this field. (Full 562-field unified_features parity tracked separately under feature_pipeline_running_partial.)
