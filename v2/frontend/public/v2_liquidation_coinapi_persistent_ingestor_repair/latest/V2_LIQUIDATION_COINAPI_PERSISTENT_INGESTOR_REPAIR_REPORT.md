# V2 Liquidation And CoinAPI Persistent Ingestor Repair Report

Generated EST: `2026-06-04T20:25:08-04:00`

Gate: `V2_LIQUIDATION_COINAPI_PERSISTENT_INGESTOR_REPAIR_READY`

## Scope

Rechecked the legacy `start_all_services_production.sh` service inventory without running it. The legacy script includes live trader paths, so repair was scoped to V2 read-only paper/shadow services only.

## Root Causes Fixed

- Binance forced-liquidation WSS used the old unrouted path `wss://fstream.binance.com/ws/!forceOrder@arr`; current Binance USD-M futures docs require routed market streams, so V2 now uses `wss://fstream.binance.com/market/ws/!forceOrder@arr`.
- V2 persistent runtime coverage was missing CoinAPI WSDS and had incomplete fallback startup coverage for Binance liquidation WSS, liquidation levels, and CoinAPI WSDS.
- CoinAPI WSDS was incorrectly represented as closed/native by credential presence instead of a persistent operator-gated read-only websocket service.
- Native worker routing pointed `live_coinapi_wsds` at the REST worker instead of the WSDS loop.
- Ingestor dashboard status did not include the WSDS service or its freshness keys.
- Binance WSS and CoinAPI WSDS status counters could appear idle while active sessions were writing Redis data.

## Runtime Evidence

- `ai-bot-v2-liquidation-wss-paper-shadow.service`: `active`
- `ai-bot-v2-liquidation-levels-engine.service`: `active`
- `ai-bot-v2-coinapi-wsds-loop.service`: `active`
- Binance WSS heartbeat: `stream_connected=true`, `events_received=18`, `events_parsed=18`, `events_written=5`, `last_error_type=null`
- Liquidation event stream: `v2:liquidations:events` length `118`
- Liquidation levels engine: `events_processed=118`, `symbols_count=101`, timeframes `1m,5m,15m,1h,4h`
- Liquidation level keys: `506`
- CoinAPI WSDS heartbeat: `V2_COINAPI_WSDS_CONNECTED`
- CoinAPI WSDS counters: `messages_received=5000`, `messages_parsed=5000`, `snapshots_written=4999`, `microfeatures_written=14997`, `redis_write_failures=0`
- Sample CoinAPI WSDS key fresh: `v2:market:coinapi:wsds:BTCUSDT`
- Ingestor status publisher: `INGESTORS_OK`, `active_count=14`

## Safety

No live/canary enablement. No exchange order/test-order/cancel/modify. No leverage or margin mutation. No old Redis writes. No legacy restart. No Redis trim. Raw CoinAPI credential values were not emitted.

