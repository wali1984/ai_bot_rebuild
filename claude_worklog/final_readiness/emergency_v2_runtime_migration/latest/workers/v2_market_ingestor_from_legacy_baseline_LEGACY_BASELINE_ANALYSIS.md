# v2_market_ingestor — Legacy Baseline Analysis (BASELINE-ANCHORED)

This document anchors the V2 market ingestor worker to the legacy startup
baseline copied into `v2/legacy_preserved/startup_baseline/`. Every SHA256
below is cited from
`claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`
and must continue to match. If a SHA changes upstream, the V2 worker becomes
non-compliant and Codex review must fail.

## 1. legacy_source_paths

| legacy_rel_path                         | v2_preserved_path                                                          | SHA256                                                             |
|-----------------------------------------|----------------------------------------------------------------------------|--------------------------------------------------------------------|
| ingest/live_binance.py                  | v2/legacy_preserved/startup_baseline/ingest/live_binance.py                | `6c1eb771a3842e2d94b797eedd55aa624075c51c6d50aec701397f81dbace798` |
| ingest/live_kucoin.py                   | v2/legacy_preserved/startup_baseline/ingest/live_kucoin.py                 | `73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976` |
| ingest/live_coinapi_v1.py               | v2/legacy_preserved/startup_baseline/ingest/live_coinapi_v1.py             | `c8ca17d21b972510b92c4e84c477cd3440b3cfd1e2ec8e7411624a7454cee280` |
| ingest/live_coinapi_wsds.py             | v2/legacy_preserved/startup_baseline/ingest/live_coinapi_wsds.py           | `a6973d887d1c52a4bb48f3b6f222b04e97d92e500ab889e94d6026cf504471b6` |
| ingest/realtime_price_provider.py       | v2/legacy_preserved/startup_baseline/ingest/realtime_price_provider.py     | `dfdc2568368c134b9afcc4fa0faff312cc93a6ecc501ecaac747e7c20d7344ba` |

These five SHAs are embedded verbatim as a module constant
`LEGACY_BASELINE_SHA256` inside `v2/backend/app/cli/v2_market_ingestor.py` and
asserted by the integration test
`test_ingestor_sha256_matches_copied_baseline_manifest_contract`.

## 2. closure scan (transitive local dependencies)

From `legacy_dependency_closure_matrix.json` (ingest/* analyses):

- `ingest/live_binance.py`     → local_imports=`[config]`; unknown_imports=`[telegram_alerts, tools, utils]`
- `ingest/live_kucoin.py`      → local_imports=`[config]`; unknown_imports=`[utils]`
- `ingest/live_coinapi_v1.py`  → local_imports=`[config]`; unknown_imports=`[dateutil, utils]`
- `ingest/live_coinapi_wsds.py`→ local_imports=`[config]`; unknown_imports=`[pytz, utils]`
- `ingest/realtime_price_provider.py` → local_imports=`[config]`; unknown_imports=`[utils]`

The transitive helpers (`utils.*`, `telegram_alerts`, `tools.health`,
`config.get_live_config`) are NOT copied into the preserved baseline. They are
intentionally classified `MISSING_IN_LEGACY_BASELINE_INTENTIONALLY_REPLACED`
because:

1. `utils.redis_client`, `utils.binance_rate_limiter`, `utils.data_normalizer`,
   `utils.healthbeat`, `utils.websocket_limits` — V2 owns its own rate limiter,
   normalizer, and data-plane stream layer (V2 namespace `v2:market:*`).
   Copying legacy implementations would re-introduce legacy Redis writes,
   which V2 forbids.
2. `telegram_alerts` — V2 does not page operators from market ingestor.
   Notification routing moves to the operator dashboard.
3. `tools.health.assert_redis_up` — V2 has its own fail-closed gates.
4. `config.get_live_config` — V2 does not load legacy live config; it accepts
   symbols/timeframes via CLI args. This preserves the **behavior** (multi-
   symbol, multi-TF ingest) while removing the legacy live-config coupling.

This classification is the documented reason required by the LEGACY-FIRST
MANDATE clause (3).

## 3. legacy_functions_preserved

The V2 worker preserves the **responsibilities** (not the exact code shapes)
of the following legacy functions:

| legacy function (file:line range)                                | V2 mapping                                              |
|------------------------------------------------------------------|---------------------------------------------------------|
| `live_binance._check_coinapi_ohlcv_healthy` (233-291)            | `MarketIngestService._coinapi_v1_healthy`               |
| `live_binance.fetch_loop` REST OHLCV branch (~2290-2440)         | `MarketIngestService._binance_rest_klines`              |
| `live_binance._markprice_bookticker_worker` (833-961)            | `MarketIngestService.ingest_mark_premium_funding`       |
| `live_binance._aggtrades_worker` / tape flush (1029)             | (out of scope; covered by separate tape worker)         |
| `live_binance._orderbook_worker` (438-806)                       | `MarketIngestService.ingest_orderbook_depth_top`        |
| `live_kucoin` ticker/kline (`kc:*` keys)                         | `MarketIngestService.ingest_kucoin_quote` (optional)    |
| `realtime_price_provider.RealtimePriceProvider` failover (226+)  | `MarketIngestService.PRICE_SOURCE_PRIORITY` + selector  |
| `live_coinapi_v1.CoinAPIWebSocketV1` OHLCV health writers (348)  | `MarketIngestService._coinapi_v1_klines`                |
| `live_coinapi_wsds` quote/BBO snapshot writers (1348-1361)       | `MarketIngestService.ingest_bbo` (CoinAPI DS primary)   |

The exponential-backoff loop in `live_binance.fetch_loop` (lines 2399-2435)
is the canonical source for the rate-limit behavior the V2 worker preserves
(see Section 6).

## 4. legacy_inputs

- Binance USD-M futures REST: `GET https://fapi.binance.com/fapi/v1/klines`,
  `/fapi/v1/premiumIndex`, `/fapi/v1/fundingRate`, `/fapi/v1/openInterest`,
  `/fapi/v1/depth`, `/fapi/v1/ticker/bookTicker`, `/fapi/v1/ticker/price`.
- Binance USD-M futures WS: `wss://fstream.binance.com` streams
  (`<sym>@kline_<tf>`, `<sym>@bookTicker`, `<sym>@markPrice@1s`, `@depth@<ms>`).
- KuCoin public REST: `https://api.kucoin.com`, `https://api-futures.kucoin.com`
  (ticker, klines, funding, OI, mark, optional partial L2).
- CoinAPI V1 WS: `wss://ws.coinapi.io/v1/` (OHLCV candles + symbol metadata).
- CoinAPI DS WS: `wss://ws.coinapi.io/v1/` (quote/BBO/trade for L1).
- Symbol universe + timeframes: legacy `config.get_live_config().SYMBOLS`,
  `TIMEFRAMES`. **V2 replacement:** CLI args (`--symbol`, `--timeframe`).

## 5. legacy_outputs (LEGACY Redis keys — READ-ONLY REFERENCES; V2 must NEVER write these)

| legacy Redis key                                  | written by                       | V2 status                              |
|---------------------------------------------------|----------------------------------|----------------------------------------|
| `market:{symbol}:{timeframe}`                     | live_binance L1293               | V2 must NOT write (replaced)           |
| `latest:binance:ohlcv:{symbol}:{timeframe}`       | live_binance L1294               | V2 must NOT write (replaced)           |
| `latest:binance:mark_price:{symbol}`              | live_binance L895                | V2 must NOT write (replaced)           |
| `latest:binance:index_price:{symbol}`             | live_binance L896                | V2 must NOT write (replaced)           |
| `latest:binance:premium_index:{symbol}`           | live_binance L897                | V2 must NOT write (replaced)           |
| `latest:binance:funding:{symbol}` / `:8h`         | live_binance L2306/2308          | V2 must NOT write (replaced)           |
| `latest:binance:depth:{symbol}:20`                | live_binance L1714               | V2 must NOT write (replaced)           |
| `price:{symbol}`, `price:last:{symbol}`           | live_binance L1331/1335          | V2 must NOT write (replaced)           |
| `volatility:{symbol}`, `spark:{symbol}`           | live_binance L1339               | V2 must NOT write (replaced)           |
| `safe_mode:binance`                               | live_binance L1485               | V2 must NOT write (replaced)           |
| `alerts:safe_mode` (publish)                      | live_binance L1488/L1524         | V2 must NOT write (replaced)           |
| `orderbook:top:{sym}`                             | live_binance L936; coinapi_wsds  | V2 must NOT write (replaced)           |
| `orderbook:bids:{sym}` / `orderbook:asks:{sym}`   | live_coinapi_wsds L784-785       | V2 must NOT write (replaced)           |
| `heartbeat:OrderBook:{sym}`                       | live_binance L937                | V2 must NOT write (replaced)           |
| `instant:{symbol}:spread`                         | live_binance L1713               | V2 must NOT write (replaced)           |
| `msnap:binance_tape:{symbol}`                     | live_binance L1029               | V2 must NOT write (replaced)           |
| `kc:latest:{SYMBOL}`, `kc:kline:{SYM}:{TF}`       | live_kucoin (module docstring)   | V2 must NOT write (replaced)           |
| `kc:funding:{SYM}`, `kc:open_interest:{SYM}`      | live_kucoin                      | V2 must NOT write (replaced)           |
| `kc:mark_index:{SYM}`, `kc:orderbook20:{SYM}`     | live_kucoin                      | V2 must NOT write (replaced)           |
| `kc:ws:ticker:{SYM}`                              | live_kucoin L476                 | V2 must NOT write (replaced)           |
| `metrics:coinapi:v1:*`                            | live_coinapi_v1 L49-53           | V2 must NOT write (replaced)           |
| `metrics:coinapi:ws:*`                            | live_coinapi_wsds L442-495       | V2 must NOT write (replaced)           |
| `metrics:price_provider:{symbol}`                 | realtime_price_provider L794     | V2 must NOT write (replaced)           |
| `backup_feed:{SYMBOL}`                            | live_kucoin L487                 | V2 must NOT write (replaced)           |

### V2 outputs (NEW; v2:* namespace ONLY)

| V2 namespaced key                                    | producer                              |
|------------------------------------------------------|---------------------------------------|
| `v2:market:{symbol}:ohlcv:{timeframe}`               | `MarketIngestService.ingest_klines`   |
| `v2:market:{symbol}:bbo`                             | `MarketIngestService.ingest_bbo`      |
| `v2:market:{symbol}:price`                           | `MarketIngestService.ingest_klines`   |
| `v2:market:{symbol}:mark`                            | `MarketIngestService.ingest_mark_*`   |
| `v2:market:{symbol}:funding`                         | `MarketIngestService.ingest_mark_*`   |
| `v2:market:{symbol}:open_interest`                   | `MarketIngestService.ingest_oi`       |
| `v2:market:{symbol}:depth`                           | `MarketIngestService.ingest_depth`    |
| `v2:market:{symbol}:source_health`                   | `MarketIngestService.health_snapshot` |

These are persisted to the **V2 data-plane stream file**
`v2/runtime/v2_market_ingestor/latest/v2_market_data_plane.json` (NOT old
Redis). A future Redis adapter MAY mirror them to a `v2:` Redis prefix, but
that adapter is out of scope here.

## 6. legacy_edge_cases (rate-limit backoff, reconnect/retry, market hours, CoinAPI fallback)

- **CoinAPI fallback policy** (live_binance L233-291): when
  `metrics:coinapi:v1:last_ohlcv_ts` is stale > 60s OR connection flag is "0",
  fall back to Binance REST `fetch_ohlcv`. V2 preserves this: if
  `_coinapi_v1_healthy()` returns False, the V2 service routes OHLCV through
  the Binance REST path.
- **Rate-limit ban (-1003)** (live_binance L2416-2435): exponential backoff
  starting 60s, doubling, capped at 300s; on success the consecutive-ban
  counter resets. V2 preserves this exactly in
  `MarketIngestService._record_rate_limit_ban`.
- **Geo-restriction (HTTP 451)** (live_binance L2399-2410): backoff starts
  300s, doubles up to 1800s; after 3 geo-blocks, sleep escalates to 3600s.
  V2 preserves this in `MarketIngestService._record_geo_block`.
- **Generic 5xx** (legacy fetch_loop main except L2492-2511): backoff starts
  at 5s and doubles, capped at 180s. V2 is **stricter**: starts at 30s,
  doubles to 300s, and is `fail_closed_on_5xx` (no klines persisted while
  backoff is active).
- **WS reconnect** (live_binance L179-225, `ws_connect_with_retry`):
  exponential backoff 1.0 → 15s, max_retries=8. V2 does not open WS in this
  worker; the V2 service is REST-pull oriented and a separate worker handles
  WS streams.
- **CoinAPI shared-rate-limit coordination** (live_coinapi_v1 L55-58):
  V1 budget ≤ 30% of shared 10k/day quota. V2 preserves the **budget config
  knob** (`coinapi_daily_budget_pct`) but enforces it locally on a per-process
  counter (the legacy shared-Redis counter is removed because V2 forbids old
  Redis writes).
- **Market hours**: crypto markets are 24/7; no market-hours gating in legacy
  ingestors. V2 preserves this (no gating).

## 7. legacy_failure_modes

- Binance returning HTTP 451 in restricted regions → legacy backed off and
  logged action-required. V2 surfaces `rate_limit_state="geo_blocked"`.
- Binance `-1003 Way too many requests` → legacy set `set_ban(...)` in
  Redis. V2 surfaces `rate_limit_state="rate_limit_ban"` and persists the
  backoff window in the V2 data plane only (no legacy `set_ban`).
- CoinAPI WS disconnects → legacy reconnected via `ws_connect_with_retry`.
  V2 trusts the CoinAPI V1 health gauges (`metrics:coinapi:v1:connected`)
  as **read-only** for the fallback decision.
- KuCoin disabled by default (legacy `KUCOIN_ENABLED=0`) → V2 ingest_kucoin
  is opt-in via `enable_kucoin=True`.

## 8. legacy_tests_or_expected_behavior

The legacy code had no formal unit tests for the ingestors (verified by
file listing). Expected behavior is documented in the file docstrings:

- `live_kucoin.py` docstring (head): enumerates the `kc:*` Redis keys it
  produced and the feature flag `KUCOIN_ENABLED`.
- `realtime_price_provider.py` docstring (L1-26): enumerates the source
  priority and the `price:realtime:{SYMBOL}` contract.
- `live_coinapi_v1.py` docstring (L1-21): documents the health-coordination
  pattern and the 30% V1 budget split.

V2 tests are written against this documented expected behavior; see
`v2/backend/tests/integration/cli/test_v2_market_ingestor.py`.

## 9. V2_mapping (data-source priority table — preserved from startup script)

| data type           | primary               | fallback                | V2 producer                                    |
|---------------------|-----------------------|-------------------------|------------------------------------------------|
| OHLCV               | CoinAPI V1            | Binance REST            | `MarketIngestService.ingest_klines`            |
| Quote / BBO         | CoinAPI DS            | Binance bookTicker      | `MarketIngestService.ingest_bbo`               |
| Microstructure      | CoinAPI DS            | (none)                  | separate V2 WS worker                          |
| Funding rate        | Binance WS            | (none)                  | `MarketIngestService.ingest_mark_premium_funding` |
| Mark price          | Binance WS            | (none)                  | `MarketIngestService.ingest_mark_premium_funding` |
| Premium index       | Binance REST          | (none)                  | `MarketIngestService.ingest_mark_premium_funding` |
| Open Interest       | Binance REST          | CoinAnk                 | `MarketIngestService.ingest_oi`                |
| Orderbook depth     | Binance REST + WS     | (none)                  | `MarketIngestService.ingest_depth`             |
| Liquidations        | Binance WS            | (none)                  | covered by separate worker (`v2_coinank_and_liquidation_bridge_from_legacy_baseline`) |

## 10. intentional_changes

1. **V2 never writes legacy Redis keys.** Confirmed by the
   `no_old_redis_write_contract` test. This is the central V2 contract.
2. **Persistence is V2 data-plane file** (`v2:market:*` keys serialized to
   `v2/runtime/v2_market_ingestor/latest/v2_market_data_plane.json`)
   instead of legacy Redis. A V2 Redis adapter MAY mirror later.
3. **No exchange mutating method invocation.** Confirmed by the
   `no_real_exchange_mutating_method_invoked_contract` test.
4. **Public REST GETs only** (no API credentials required).
5. **Rate-limit backoff for generic 5xx is stricter than legacy** (30→300s
   vs. legacy 5→180s) AND is fail-closed: while the backoff window is
   active, the worker refuses to persist klines.
6. **CoinAPI shared-rate-limit budget is enforced locally**, not via legacy
   shared Redis counter (`metrics:coinapi:shared:msgs_today`).
7. **Telegram alerts removed** from the ingestor; alert routing moves to
   the operator dashboard.
8. **Live gate is always `blocked_human_only`** in the public status.
   The worker has no codepath that can change this.

## 11. removed/deprecated behavior (with reason)

| removed legacy behavior                                       | reason                                                  |
|---------------------------------------------------------------|---------------------------------------------------------|
| `set_ban(r, ...)` Redis write                                 | legacy Redis key; V2 forbids                            |
| `redis_client.publish('alerts:safe_mode', ...)`               | alert routing moved to operator dashboard               |
| direct `ccxt.fetch_ohlcv` via the live API key                | V2 uses unauthenticated public REST GETs only           |
| `dm.append_live_bar(...)` writes to legacy DataManager        | replaced by V2 data-plane writer                        |
| in-process spark buffer (`spark:{sym}`)                       | V2 does not own UI charting in the ingestor             |
| WS-based ingest in this worker                                | scoped to REST-pull; WS handled by separate V2 worker   |
| reading from `config.get_live_config()`                       | V2 takes symbols/timeframes via CLI flags               |
| `tools.health.assert_redis_up()` fail-fast                    | V2 has its own fail-closed gates                        |

## 12. Codex review pointer

The V2 implementation is asserted by `test_v2_market_ingestor.py` to match
this analysis along every dimension above. The `codex_review_v2_market_
ingestor_from_legacy_baseline` task verifies that:

- Every SHA in Section 1 matches `copied_baseline_manifest.json` byte-for-
  byte.
- The legacy_behavior_mapping.json sibling file enumerates the same V2
  mappings as Section 9.
- The V2 worker module does not contain any of the legacy write keys from
  Section 5.
