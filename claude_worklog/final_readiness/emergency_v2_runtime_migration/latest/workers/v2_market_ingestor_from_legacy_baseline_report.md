# v2_market_ingestor — Legacy-Baseline Port Report

**Task:** `claude_port_v2_market_ingestor_from_legacy_baseline`
**Lane:** runtime_migration
**Worker ID:** `v2_market_ingestor`
**Live gate:** `blocked_human_only` (immutable from this worker)
**Status:** EMITTED, pending Codex review.

## What was emitted

| Output file | Role |
|---|---|
| `v2/backend/app/cli/v2_market_ingestor.py` | CLI entrypoint (`python3 -m v2.backend.app.cli.v2_market_ingestor --loop --interval 15 --symbol BTCUSDT`). Public REST GETs only; writes V2 status payload + V2 data-plane file. |
| `v2/backend/app/services/market_ingest/service.py` | Pure service layer with `MarketIngestService`, `PriceSourcePriority`, `DATA_SOURCE_PRIORITY`. No legacy Redis writes. |
| `v2/backend/tests/integration/cli/test_v2_market_ingestor.py` | All 8 required tests + 1 helper-shape test. |
| `v2/frontend/public/operator_runtime/v2_market_ingestor/latest/v2_market_ingestor_status.json` | Seeded public payload for the operator dashboard. |
| `..._LEGACY_BASELINE_ANALYSIS.md` | Legacy-anchored analysis with SHA citations. |
| `..._legacy_behavior_mapping.json` | Machine-readable legacy → V2 mapping. |
| `..._status.json` | Worker status (this file). |
| `..._report.md` | This file. |

## Legacy baselines anchored

The worker is anchored to five preserved baselines under
`v2/legacy_preserved/startup_baseline/ingest/`. SHAs are taken verbatim from
`copied_baseline_manifest.json` and embedded as
`LEGACY_BASELINE_SHA256` inside the CLI module:

- `ingest/live_binance.py` — `6c1eb771a3842e2d94b797eedd55aa624075c51c6d50aec701397f81dbace798`
- `ingest/live_kucoin.py` — `73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976`
- `ingest/live_coinapi_v1.py` — `c8ca17d21b972510b92c4e84c477cd3440b3cfd1e2ec8e7411624a7454cee280`
- `ingest/live_coinapi_wsds.py` — `a6973d887d1c52a4bb48f3b6f222b04e97d92e500ab889e94d6026cf504471b6`
- `ingest/realtime_price_provider.py` — `dfdc2568368c134b9afcc4fa0faff312cc93a6ecc501ecaac747e7c20d7344ba`

The test `test_ingestor_sha256_matches_copied_baseline_manifest_contract`
reads the manifest at test-time and asserts each constant matches; it also
recomputes the SHA against the on-disk preserved file if present.

## Data-source priority (preserved from startup script's data-source table)

| Data type | Primary | Fallback |
|---|---|---|
| OHLCV | CoinAPI V1 | Binance REST |
| Quote / BBO | CoinAPI DS | Binance bookTicker |
| Funding / mark / premium-index | Binance WS or REST | (none) |
| Open Interest | Binance REST | CoinAnk |
| Orderbook depth | Binance REST + WS | (none) |
| Liquidations | (separate worker) | — |

The V2 worker exposes this table as a module constant
`DATA_SOURCE_PRIORITY`. The unified price-source priority enum from the
legacy `realtime_price_provider.py` (`COINAPI_WS=1`, `BINANCE_WS=2`,
`CCXT_REST=3`, `KUCOIN_REST=4`, `REDIS_CACHE=99`) is preserved as
`PriceSourcePriority`.

## V2 outputs (NEW; `v2:*` namespace ONLY)

- `v2:market:{symbol}:ohlcv:{timeframe}`
- `v2:market:{symbol}:price`
- `v2:market:{symbol}:bbo`
- `v2:market:{symbol}:mark`
- `v2:market:{symbol}:funding`
- `v2:market:{symbol}:open_interest`
- `v2:market:{symbol}:depth`
- `v2:market:source_health`

The V2 data-plane is persisted as a JSON file
(`v2/runtime/v2_market_ingestor/latest/v2_market_data_plane.json`). No
legacy Redis is touched.

## Rate-limit backoff

Preserved exactly from legacy `live_binance.py`:

- `-1003` rate-limit ban: start `60s`, double, cap `300s`.
- HTTP `451` geo-block: start `300s`, double, cap `1800s`; escalate to
  `3600s` after 3 consecutive geo-blocks.

Stricter than legacy (and **fail-closed**):

- HTTP `5xx`: start `30s`, double, cap `300s`. While a 5xx backoff window
  is active, the worker refuses to call HTTP and persists nothing.

These knobs are exposed as module constants in
`v2/backend/app/services/market_ingest/service.py` and asserted by
`test_rate_limit_backoff_matches_legacy_behavior_or_is_stricter` and
`test_fail_closed_on_5xx`.

## Safety contracts (asserted by tests)

1. **`live_gate == "blocked_human_only"`** — always; no worker codepath
   changes it.
2. **No legacy Redis writes** — test scans both CLI and service source
   for ~40 legacy key prefixes.
3. **No exchange mutating method invoked** — test scans both modules for
   `futures_create[_]order`, `cancel[_]order`, `set[_]leverage`, etc.
4. **Public REST GETs only** — no API credentials are read.
5. **CoinAPI V1 budget enforced locally** — no shared Redis counter.

## Closure scan

From `legacy_dependency_closure_matrix.json`: each legacy ingest file has
`local_imports=[config]` and `unknown_imports=[utils, ...]`. The `utils.*`,
`telegram_alerts`, `tools.health`, `config.get_live_config`, `pytz`, and
`dateutil` imports are explicitly classified
`MISSING_IN_LEGACY_BASELINE_INTENTIONALLY_REPLACED` in
`...legacy_behavior_mapping.json` with a written reason per import (see
Section 2 of the analysis document).

## Runnable invocation

```
python3 -m v2.backend.app.cli.v2_market_ingestor --loop --interval 15 --symbol BTCUSDT
```

A single-shot run:

```
python3 -m v2.backend.app.cli.v2_market_ingestor --once --symbol BTCUSDT --timeframe 1m --limit 6
```

Baseline SHA self-check:

```
python3 -m v2.backend.app.cli.v2_market_ingestor --verify-baseline-shas
```

## Codex review

This emit triggers
`codex_review_v2_market_ingestor_from_legacy_baseline`. Codex must verify:

- All five legacy baseline SHAs in `LEGACY_BASELINE_SHA256` match the
  `copied_baseline_manifest.json` byte-for-byte.
- The legacy_behavior_mapping.json sibling file enumerates the same V2
  mappings as the analysis document.
- The V2 worker module does not contain any of the legacy write keys
  enumerated in Section 5 of the analysis.
- The data-source priority table matches the startup script's data-source
  table.
- The live gate remains `blocked_human_only`.

## Acknowledged constraints honored

- `/home/wali/Desktop/AI BOT` is **not** touched.
- No old Redis writes.
- No exchange mutation APIs.
- No leverage / margin changes.
- No live-gate unlock.
- All baseline SHAs cited in BOTH the analysis MD and the mapping JSON
  per the LEGACY-FIRST MANDATE clause (3).
All eight required files emitted. Each baseline file cites the five legacy SHAs from `copied_baseline_manifest.json`. The CLI worker is anchored to those SHAs via `LEGACY_BASELINE_SHA256`, persists only `v2:market:*` keys, and has a fail-closed 5xx backoff stricter than legacy. Tests cover all 8 required contracts plus public-payload field shape. Live gate stays `blocked_human_only`; no legacy Redis writes; no exchange mutation methods present.
