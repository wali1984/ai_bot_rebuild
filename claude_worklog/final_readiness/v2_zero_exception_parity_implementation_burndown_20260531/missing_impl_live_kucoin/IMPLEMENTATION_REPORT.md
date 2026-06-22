# V2 Missing Implementation Fix — KuCoin Public REST Ingestor

Generated EST: 2026-06-03T18:32:40-0400  
Generated UTC: 2026-06-03T22:32:40Z  
LIVE_GATE: blocked_human_only | live_symbols: [] | exchange mutation: none

## Implemented

`v2/backend/app/cli/v2_kucoin_ingestor_worker.py` now has an explicit public REST runtime path:

- `--fetch-public-rest` fetches real KuCoin public market data.
- `--write-v2-redis` writes only V2-prefixed Redis keys.
- No API key is required.
- No exchange SDK is imported.
- No live/canary/trading path is enabled.

Fetched endpoints, based on the copied legacy worker contract:

- spot level1 ticker
- spot 1m candles
- spot level2_20 orderbook
- funding endpoint
- futures contract detail

V2 Redis keys written:

- `v2:market:kucoin:latest:{symbol}`
- `v2:market:kucoin:kline:{symbol}:{tf}`
- `v2:market:kucoin:orderbook20:{symbol}`
- `v2:market:kucoin:funding:{symbol}`
- `v2:market:kucoin:contract:{symbol}`
- `v2:features:kucoin:{symbol}:latest`
- `v2:market:kucoin:heartbeat`

## Evidence

Command:

```bash
PYTHONPATH=$PWD ./.venv/bin/python3 -m v2.backend.app.cli.v2_kucoin_ingestor_worker --write-evidence --fetch-public-rest --fetch-symbol-limit 2 --symbols BTCUSDT,ETHUSDT --fetch-timeframes 1m --write-v2-redis
```

Result:

- `classification=NATIVE_V2_PUBLIC_REST_OK`
- BTCUSDT endpoint statuses: spot level1 200, kline 200, orderbook20 200, funding 200, contract 200
- ETHUSDT endpoint statuses: spot level1 200, kline 200, orderbook20 200, funding 200, contract 200
- `v2:market:kucoin:*` = 11
- `v2:features:kucoin:*` = 2

Public payload updated:

`v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json`

## Safety

- No legacy source files modified.
- No old Redis keys written.
- No order, cancel, leverage, margin, live, or canary path invoked.
