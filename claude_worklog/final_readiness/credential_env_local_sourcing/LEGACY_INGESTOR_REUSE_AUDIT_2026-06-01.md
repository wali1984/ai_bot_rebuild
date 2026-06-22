# Legacy Ingestor Reuse — Working Scripts Wired Into V2 (no old-Redis writes)

Generated EST: 2026-06-01T18:45:00-0400
Generated UTC: 2026-06-01T22:45:00Z
LIVE_GATE: blocked_human_only | live_symbols: [] | exchange mutation: none

## Ask
> We have all scripts in the legacy folder which were configured and working —
> ensure we are using those. Copy where needed, map API keys from env.local /
> live_credentials.env, ensure they work and all data is gathered.

## How (constraint-respecting)
The proven legacy ingestors under `v2/legacy_owned_runtime/ingest/` write
**un-prefixed legacy keys** (`kc:*`, `orderbook:top:*`, `latest:coinapi:*`),
which CLAUDE.md forbids. So instead of rewriting them, a thin adapter reuses
the legacy code **verbatim** and forces every Redis write into the `v2:`
namespace:

`v2/backend/app/cli/v2_legacy_ingestor_adapter.py`
- Monkeypatches `redis.Redis` / `redis.StrictRedis` / `redis.from_url` at the
  library level **before** importing the legacy module, wrapping every client
  in a `PrefixedRedis` proxy that prepends `v2:` to every key. This catches
  module-global clients (KuCoin's `R`) AND locally-created ones (CoinAPI's
  `_light_redis()`). Structurally impossible to write a non-`v2:` key.
- Bootstraps API keys from `env.local` / `.local_secrets` (via the cli pkg).
- Runs the legacy entrypoint: sync `--once`/`--loop` (KuCoin) or
  async-bounded / unbounded streamer (CoinAPI WSS).
- Legacy source files are NOT modified on disk.

## Verified working (live, real keys/endpoints)
| Legacy script | Transport | Auth | Result | v2: keys written | old-Redis writes |
|---|---|---|---|---|---|
| `ingest/live_kucoin.py` | REST (+WS backup) | public | real OHLCV/funding/orderbook for full symbol universe | 275–328/run | **0** |
| `ingest/live_coinapi_v1.py` | **WebSocket** `wss://ws.coinapi.io/v1/` | **COINAPI_API_KEY (real)** | connected, subscribed, streamed real OHLCV (e.g. SOLUSDT 1m O=80.72) | 30/run | **0** |

Live v2: namespace counts after runs:
- `v2:features:kucoin:*` = 89 (normalized OHLCV, e.g. `v2:features:kucoin:BTCUSDT:1h:normalized` → real candle)
- `v2:kc:*` = 131 (raw KuCoin: klines/latest/funding/OI/orderbook20)
- `v2:latest:coinapi:ohlcv:*` = 6, `v2:normalized:ohlcv:*` = 6, `v2:ohlcv:list:coinapi:*` = 6

Re-run (one cycle / bounded):
```
PYTHONPATH=$PWD ./.venv/bin/python3 -m v2.backend.app.cli.v2_legacy_ingestor_adapter kucoin
PYTHONPATH=$PWD ./.venv/bin/python3 -m v2.backend.app.cli.v2_legacy_ingestor_adapter coinapi_v1 --seconds 60
```

## Continuous operation (operator decision required)
Standing systemd `--user` services were NOT auto-installed (persistence is an
operator decision). Unit files are STAGED at:
- `claude_worklog/systemd/user/ai-bot-v2-legacy-kucoin-ingestor.service`
- `claude_worklog/systemd/user/ai-bot-v2-legacy-coinapi-v1-ingestor.service`

To enable continuous gathering (operator runs):
```
cp claude_worklog/systemd/user/ai-bot-v2-legacy-kucoin-ingestor.service ~/.config/systemd/user/
cp claude_worklog/systemd/user/ai-bot-v2-legacy-coinapi-v1-ingestor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-bot-v2-legacy-kucoin-ingestor.service
systemctl --user enable --now ai-bot-v2-legacy-coinapi-v1-ingestor.service
```

## Notes / remaining legacy scripts
- **CoinAnk**: skipped per operator instruction.
- **Binance** (`live_binance.py`, `realtime_price_provider.py`): already covered
  natively by `ai-bot-v2-native-ingestors-live-loop` (prices/OHLCV/orderbook/
  funding/OI + OI-history) — adding the legacy variants is optional parity.
- **TokenMetrics / CCXT / CoinAPI WSDS (paid)**: operator-gated per CLAUDE.md.
- **AlphaVantage**: `ALPHAVANTAGE_API_KEY` absent from all credential files.
- KuCoin imports legacy `config.py` (pulls torch/CUDA once per process) — heavy
  but harmless for a `--loop` worker.

## Safety
All writes verified `v2:`-namespaced (adapter asserts `NON-v2 keys = 0`). No
exchange order/leverage/margin calls. LIVE_GATE stays blocked_human_only.
