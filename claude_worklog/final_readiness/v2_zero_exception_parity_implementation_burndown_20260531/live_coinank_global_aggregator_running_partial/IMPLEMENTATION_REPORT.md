# V2 Running Partial Fix — CoinAnk Global Aggregator

Generated EST: 2026-06-03T18:32:40-0400  
Generated UTC: 2026-06-03T22:32:40Z  
LIVE_GATE: blocked_human_only | live_symbols: [] | exchange mutation: none

## Implemented

- Added V2 Redis input loading to `v2/backend/app/cli/v2_coinank_and_liquidation_bridge.py`.
- Reads only `v2:` keys:
  - `v2:unified_features:{symbol}:{tf}`
  - `v2:features:latest:{symbol}:{tf}`
  - `v2:market:open_interest:{symbol}`
  - `v2:market:funding:{symbol}`
  - `v2:market:prices:{symbol}`
- Added explicit V2-only Redis writes for the preserved 11-key global contract:
  - `v2:coinank:global:{name}:latest`
  - `v2:market:coinank:global:{name}:latest`
  - `v2:features:global_coinank:{name}:latest`
- Extended the service fallback logic to use real V2 market/feature fields when CoinAnk-specific buy/sell fields are absent. Undirected quote volume is split evenly so volume is counted without fabricating market sentiment.

## Evidence

Command:

```bash
PYTHONPATH=$PWD ./.venv/bin/python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --once --symbols BTCUSDT ETHUSDT SOLUSDT XRPUSDT --tf 1m --write-v2-redis
```

Result:

- `v2_redis_feature_input.enabled=true`
- `symbols_with_any_input=4`
- `v2_redis_global_keys_written_count=34`
- `writes_legacy_redis=false`
- `global_aggregate_result.total_oi=330218796.53`
- `global_aggregate_result.total_volume=3711223040.671856`
- `global_aggregate_result.market_sentiment=0.0`

Public payload updated:

`v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`

Redis proof:

- `v2:coinank:global:*` = 12
- `v2:market:coinank:global:*` = 11
- `v2:features:global_coinank:*` = 11

## Safety

- No legacy source files modified.
- No old Redis keys written.
- No exchange order/cancel/leverage/margin path invoked.
- CoinAnk liquidation orders are still not synthesized; missing upstream events remain labelled as missing API blockers.
