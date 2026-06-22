# GO / NO-GO — ingest_live_binance_running_partial

- Decision: **GO**
- Milestone: v2_zero_exception_parity_implementation_burndown
- Generated (EST): 2026-06-01T17:50:28-0400
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false

## Claim
V2_RUNNING_PARTIAL resolved: Binance OHLCV bars written to v2:market:ohlcv:binance:{symbol}:1m; feature pipeline now derives all OHLCV-based TA from real candles.

## Verification command
```
redis-cli ttl v2:market:ohlcv:binance:BTCUSDT:1m
```

## Confidence
HIGH

## Missing evidence
Multi-timeframe OHLCV (5m/15m/1h) — only 1m currently written; tracked under feature_pipeline full parity.
