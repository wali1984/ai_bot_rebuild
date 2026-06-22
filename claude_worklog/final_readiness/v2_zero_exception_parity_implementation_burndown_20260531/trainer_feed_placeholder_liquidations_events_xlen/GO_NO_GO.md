# GO / NO-GO — trainer_feed_placeholder_liquidations_events_xlen

- Decision: **GO**
- Milestone: v2_zero_exception_parity_implementation_burndown
- Generated (EST): 2026-06-01T17:50:28-0400
- LIVE_GATE: blocked_human_only
- live_symbols: []
- writes_legacy_redis: false

## Claim
Trainer-feed liquidation placeholder removed: last_liq_bps_24h is now a REAL computed value read from the live v2:liquidations:events stream (XLEN=0). XLEN=0 is event-dependent reality (no forceOrder events in window), yielding a real 0.0 — not a placeholder.

## Verification command
```
redis-cli xlen v2:liquidations:events; redis-cli get v2:features:latest:BTCUSDT:1m | python3 -c "import json,sys;print(json.load(sys.stdin)['features']['last_liq_bps_24h'])"
```

## Confidence
HIGH

## Missing evidence
Non-zero liquidation flow not yet observed (forceOrder stream quiet). Aggregate path v2:market:liquidations:aggregate:{sym} will be preferred automatically once WSS populates it.
