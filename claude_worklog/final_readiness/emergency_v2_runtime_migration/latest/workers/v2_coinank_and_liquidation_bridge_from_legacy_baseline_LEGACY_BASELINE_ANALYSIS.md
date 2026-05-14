# v2_coinank_and_liquidation_bridge — Legacy Baseline Analysis (BASELINE-ANCHORED)

This document anchors the V2 CoinAnk and liquidation bridge worker to the
legacy startup baseline copied into `v2/legacy_preserved/startup_baseline/`.
Every SHA256 below is cited from
`claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`
and must continue to match. If a SHA changes upstream, the V2 worker becomes
non-compliant and Codex review must fail.

## 1. legacy_source_paths

| legacy_rel_path                              | v2_preserved_path                                                                  | size_bytes | SHA256                                                             |
|----------------------------------------------|------------------------------------------------------------------------------------|-----------:|--------------------------------------------------------------------|
| ingest/live_coinank.py                       | v2/legacy_preserved/startup_baseline/ingest/live_coinank.py                        |    127414 | `cd13dab55c0906c379e4116102c05f960908dd28d6b6e883ca76347cd1f144c8` |
| ingest/live_coinank_global_aggregator.py     | v2/legacy_preserved/startup_baseline/ingest/live_coinank_global_aggregator.py      |     14475 | `1f85c4532e4829aa99ddadbd6a5cd2325ef9e5c4012208eb05876c1b0187eeae` |
| ingest/live_binance_liquidations.py          | v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py           |     46088 | `19711590a3d194fd05ae3be85ef7bd6dec397f6394d02f7e91008c44c310131b` |
| ingest/liquidation_bridge.py                 | v2/legacy_preserved/startup_baseline/ingest/liquidation_bridge.py                  |      6327 | `5d70e395938228b61162b531310cd751403ddfeebb8920429e73cdcdbe35d48a` |
| ingest/liquidation_levels_engine.py          | v2/legacy_preserved/startup_baseline/ingest/liquidation_levels_engine.py           |     18539 | `fed3c90b5193c27d24dc183089730bda49ff69a1758b597e23a154397f839df7` |

These five SHAs are embedded verbatim as a module constant
`LEGACY_BASELINE_SHA256` inside
`v2/backend/app/cli/v2_coinank_and_liquidation_bridge.py` and asserted by
the integration test
`test_ingestor_sha256_matches_copied_baseline_manifest_contract`.

## 2. closure scan (transitive local dependencies)

From the on-disk legacy preserved files:

- `ingest/live_coinank.py`                  → local_imports=`[config]`; unknown_imports=`[utils.symbol_manager, utils.logger, utils.redis_client, utils.data_normalizer, tools.health]`
- `ingest/live_coinank_global_aggregator.py`→ local_imports=`[config]`; unknown_imports=`[utils.symbol_manager]`
- `ingest/live_binance_liquidations.py`     → local_imports=`[config, telegram_alerts]`; unknown_imports=`[utils.*, tools.health]`
- `ingest/liquidation_bridge.py`            → local_imports=`[config]`; unknown_imports=`[]`
- `ingest/liquidation_levels_engine.py`     → local_imports=`[config]`; unknown_imports=`[]`

The transitive helpers (`utils.*`, `telegram_alerts`, `tools.health`,
`config.get_live_config`) are NOT copied into the preserved baseline. They
are intentionally classified `MISSING_IN_LEGACY_BASELINE_INTENTIONALLY_REPLACED`
because:

1. `utils.redis_client` / `utils.data_normalizer` / `utils.healthbeat` /
   `utils.websocket_limits` — V2 owns its own data-plane writer (V2 namespace
   `v2:coinank:*` and `v2:liquidations:*`). Copying the legacy implementation
   would re-introduce **legacy Redis writes**, which V2 forbids.
2. `telegram_alerts` — V2 does not page operators from the bridge worker.
   Notification routing moves to the operator dashboard.
3. `tools.health.assert_redis_up` — V2 has its own fail-closed gates.
4. `config.get_live_config` — V2 does not load legacy live config; it
   accepts the symbol universe and timeframes via CLI args. This preserves
   the **behavior** (multi-symbol, multi-TF ingest) while removing the
   legacy live-config coupling.

This classification is the documented reason required by the LEGACY-FIRST
MANDATE clause (3) and is mirrored in `legacy_behavior_mapping.json`.

## 3. legacy_functions_preserved (responsibility mapping)

The V2 worker preserves the **responsibilities** (not exact code shapes) of
the following legacy functions. Each row cites the preserved baseline file
and the line range that defines the responsibility, and names the V2 method
that owns it.

| legacy function (file:line range)                                                       | V2 mapping                                                                |
|-----------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| `live_coinank._plan3_endtime_for_interval` (`live_coinank.py` L970-993)                 | `CoinankBridgeService.plan3_endtime_for_interval`                         |
| `live_coinank._plan3_historical_endtime` (`live_coinank.py` L915-927)                   | `CoinankBridgeService.plan3_historical_endtime`                           |
| `live_coinank._align_end_time` (`live_coinank.py` L929-946)                             | `CoinankBridgeService.align_end_time`                                     |
| `live_coinank.persist` Plan-3 endpoint dispatch (`live_coinank.py` L1527-2158)           | `CoinankBridgeService.persist_endpoint_into_v2_namespace`                 |
| `live_coinank._publish_endpoint_manifest` (`live_coinank.py` L2159-2195)                 | `CoinankBridgeService.endpoint_manifest_snapshot`                         |
| `live_coinank._publish_cycle_complete` (`live_coinank.py` L2196-2228)                    | `CoinankBridgeService.cycle_complete_snapshot`                            |
| `live_coinank_global_aggregator.compute_and_persist` (file L116-306)                     | `CoinankBridgeService.compute_global_11_keys`                             |
| `live_binance_liquidations.consume_force_orders` raw queue (file L223 RAW_KEY)           | `CoinankBridgeService.accept_binance_force_event` (in-memory; no WS here) |
| `live_binance_liquidations` 1m/5m/15m/30m/1h aggregations (file L225-231 AGG_WINDOWS)    | `CoinankBridgeService.aggregate_force_window` (per-window roll-up)        |
| `liquidation_bridge.process_binance_force` (file L63-126)                                | `CoinankBridgeService.bridge_binance_force_into_v2_events`                |
| `liquidation_bridge.process_coinank_orders` (file L129-196)                              | `CoinankBridgeService.bridge_coinank_orders_into_v2_events`               |
| `liquidation_bridge._set_dedup` (file L51-53)                                            | `CoinankBridgeService._dedup_set` (in-memory TTL map)                     |
| `liquidation_levels_engine.LevelEngine._parse_event` (file L267-295)                     | `CoinankBridgeService.parse_v2_liquidation_event`                         |
| `liquidation_levels_engine.LevelEngine._compute_mapping` (file L341-460)                 | `CoinankBridgeService.compute_liquidation_levels_mapping`                 |
| `liquidation_levels_engine.LevelEngine._top_bucket` (file L462-468)                      | `CoinankBridgeService._top_bucket`                                        |
| `liquidation_levels_engine.BUCKET_WIDTH_PCT` constant (file L51-58)                      | `CoinankBridgeService.BUCKET_WIDTH_PCT`                                   |
| `liquidation_levels_engine.STALENESS_STALE_MS` constant (file L46)                       | `CoinankBridgeService.STALENESS_STALE_MS`                                 |

The legacy WS connectivity (`!forceOrder@arr` consumer in
`live_binance_liquidations.consume_force_orders`) is explicitly **delegated**
to a separate V2 WS worker. The V2 bridge does **not** open WS sessions;
it consumes V2 in-memory events provided by either:

- the operator (test fixture / replay),
- a downstream V2 WS worker (out of scope for this CLI), or
- a CoinAnk REST liquidation-orders snapshot when the public endpoint is
  reachable.

If neither source is available, the worker labels `missing_api_blockers`
and refuses to synthesize events.

## 4. legacy_inputs

- CoinAnk public REST: `https://open-api.coinank.com/api/...` Plan-3 endpoints
  (e.g. `liquidation_orders`, `instruments/liquidationRank`, `fundingRate/getWeiFr`,
  `indicator/smc`, `ls/buy_sell`, `ls/toptrader/positions`,
  `marketOrder/getCvd`, `marketOrder/getAggCvd`). The V2 worker forwards
  Plan-3 `endTime` selection through `plan3_endtime_for_interval` for the
  six TFs `(5m, 15m, 30m, 1h, 4h, 1d)`.
- Binance USD-M futures WS `wss://fstream.binance.com/stream?streams=!forceOrder@arr`
  — **NOT** owned by this CLI; delegated to a separate V2 WS worker.
- Symbol universe + timeframes: legacy
  `config.get_live_config().SYMBOLS` / `TIMEFRAMES`. **V2 replacement:**
  CLI args (`--symbols`, `--tf`).

## 5. legacy_outputs (LEGACY Redis keys — READ-ONLY REFERENCES; V2 must NEVER write these)

| legacy Redis key                                            | written by                                  | V2 status                              |
|-------------------------------------------------------------|---------------------------------------------|----------------------------------------|
| `coinank:{endpoint}:last`                                   | live_coinank L1582-1595                     | V2 must NOT write (replaced)           |
| `coinank:series:oi:{base}`                                  | live_coinank L1941                          | V2 must NOT write (replaced)           |
| `coinank:series:funding:{base}`                             | live_coinank L1953                          | V2 must NOT write (replaced)           |
| `coinank:series:buyVol:{base}`                              | live_coinank L1968                          | V2 must NOT write (replaced)           |
| `coinank:series:sellVol:{base}`                             | live_coinank L1977                          | V2 must NOT write (replaced)           |
| `coinank:series:buysell_volume:{base}`                      | live_coinank L1988                          | V2 must NOT write (replaced)           |
| `coinank:series:buysell_value:{base}`                       | live_coinank L2012                          | V2 must NOT write (replaced)           |
| `coinank:series:agg_cvd:{base}`                             | live_coinank L2040                          | V2 must NOT write (replaced)           |
| `coinank:series:liquidations:{base}`                        | live_coinank L2076                          | V2 must NOT write (replaced)           |
| `coinank:series:liq_breakdown:{base}`                       | live_coinank L2091                          | V2 must NOT write (replaced)           |
| `coinank:endpoint_manifest`                                 | live_coinank L2177-2178                     | V2 must NOT write (replaced)           |
| `coinank:feature_manifest`                                  | live_coinank L2180-2181                     | V2 must NOT write (replaced)           |
| `coinank:endpoints`                                         | live_coinank L2182-2183                     | V2 must NOT write (replaced)           |
| `coinank:cycle_complete`                                    | live_coinank L2211-2212                     | V2 must NOT write (replaced)           |
| `coinank:runtime`                                           | live_coinank L2213-2214                     | V2 must NOT write (replaced)           |
| `coinank:runtime:last_cycle_id`                             | live_coinank L2216-2217                     | V2 must NOT write (replaced)           |
| `coinank:cycle_log`                                         | live_coinank L2218-2219                     | V2 must NOT write (replaced)           |
| `coinank:call_log`                                          | live_coinank L2539-2587                     | V2 must NOT write (replaced)           |
| `coinank:metrics`                                           | live_coinank L2420                          | V2 must NOT write (replaced)           |
| `latest:coinank:{family}:{symbol}:{tf}`                     | live_coinank L1814-1879                     | V2 must NOT write (replaced)           |
| `features:coinank:{family}:{base}:{exchange}:{interval}:*`  | live_coinank L1698-1812                     | V2 must NOT write (replaced)           |
| `features:global_coinank:{name}:latest`                     | live_coinank_global_aggregator L275-285     | V2 must NOT write (replaced)           |
| `raw:coinank:{endpoint}:global`                             | live_coinank L1618                          | V2 must NOT write (replaced)           |
| `meta:coinank:last_update`                                  | live_coinank L1657                          | V2 must NOT write (replaced)           |
| `meta:coinank_global:last_update`                           | live_coinank_global_aggregator L288         | V2 must NOT write (replaced)           |
| `heartbeat:IngestCoinAnk` / `heartbeat:CoinAnkIngest`       | live_coinank L166-168                       | V2 must NOT write (replaced)           |
| `heartbeat:writer:coinank`                                  | live_coinank L168                           | V2 must NOT write (replaced)           |
| `coinank:validator:warn` / `coinank:validator:latest`       | live_coinank L311-312, L328-329             | V2 must NOT write (replaced)           |
| `cursor:liq_bridge:binance_force_raw`                       | liquidation_bridge L65                      | V2 must NOT write (replaced)           |
| `cursor:liq_bridge:coinank_orders_last_ts`                  | liquidation_bridge L144                     | V2 must NOT write (replaced)           |
| `dedup:liq:{source}:{src_id}`                               | liquidation_bridge L48                      | V2 must NOT write (replaced)           |
| `liquidations:events` (`LIQ_EVENTS_STREAM`)                 | liquidation_bridge L34, L58                 | V2 must NOT write (replaced)           |
| `binance:force:raw` / `binance:force:raw:{symbol}`          | live_binance_liquidations L223-224          | V2 must NOT write (replaced)           |
| `binance:force:stats:{1m,5m,15m,30m,1h}`                    | live_binance_liquidations L225-231          | V2 must NOT write (replaced)           |
| `unified_features:{symbol}:{tf}` (liquidation_* fields)     | liquidation_levels_engine L310-317          | V2 must NOT write (replaced)           |
| `heartbeat:IngestLiquidations`                              | live_binance_liquidations L198              | V2 must NOT write (replaced)           |
| `features:liquidations:{symbol}:{tf}:normalized`            | live_binance_liquidations L46               | V2 must NOT write (replaced)           |
| `proc:last_error:IngestLiquidations`                        | live_binance_liquidations L233              | V2 must NOT write (replaced)           |

## 6. patched_legacy_coinank_plan3_contracts (preserved verbatim)

The patched Plan-3 historical-lookback contract from `live_coinank.py` L576-580
is preserved verbatim in
`v2.backend.app.services.coinank_bridge.service.PLAN3_INTERVAL_LIMITS`:

```python
PLAN3_INTERVAL_LIMITS = {
    "1m": 7, "3m": 15, "5m": 30, "15m": 60, "30m": 120,
    "1h": 180, "2h": 180, "4h": 360, "6h": 360, "8h": 360,
    "12h": 360, "1d": 360, "1w": 360, "1M": 360,
}
```

The per-interval maximum size cap from `live_coinank.py` L583-598 is also
preserved verbatim as `MAX_SIZE_LIMITS`, and the default required TFs from
`live_coinank.py` L606-608 are preserved as `REQUIRED_COINANK_TFS =
("5m", "15m", "30m", "1h", "4h", "1d")` (read also from the
`COINANK_TFS` env var as the legacy did).

The endTime computation
`plan3_endtime_for_interval(interval) ->
align_end_time(max(now - 60min, now - max_days*86400_000 + 60min), interval)`
matches `live_coinank._plan3_endtime_for_interval` (L970-993) at the
field level. The integration test
`test_patched_legacy_coinank_plan3_contracts_preserved` asserts each
field-level constant matches the legacy and asserts the endTime
computation aligns to the interval boundary.

## 7. global_11_key_contract (preserved verbatim)

The 11 keys consumed by `rl/hybrid_trainer.py::_load_global_features` (the
contract the legacy aggregator was built to satisfy) are preserved verbatim
in `CoinankBridgeService.GLOBAL_11_KEY_CONTRACT`:

```
features:global_coinank:total_oi:latest
features:global_coinank:total_volume:latest
features:global_coinank:total_liquidations:latest
features:global_coinank:long_short_ratio:latest
features:global_coinank:funding_rate_avg:latest
features:global_coinank:btc_dominance:latest
features:global_coinank:eth_dominance:latest
features:global_coinank:alt_season_index:latest
features:global_coinank:fear_greed:latest
features:global_coinank:market_sentiment:latest
features:global_coinank:volatility_index:latest
```

V2 writes these as **V2-namespaced** mirror keys
(`v2:coinank:global:{name}:latest`) in the V2 data plane. The trainer
contract names are kept verbatim inside the payload so a downstream V2
trainer can map by name without re-translating.

## 8. liquidation_event_canonical_schema (preserved verbatim)

Adapted from `liquidation_bridge.publish` and consumed by
`liquidation_levels_engine.LevelEngine._parse_event`:

```python
{
  "ts": int,            # ms epoch
  "symbol": str,        # upper-case symbol
  "side": "LONG_LIQ" | "SHORT_LIQ",
  "price": float,
  "qty": float,
  "notional": float,
  "source": "binance" | "coinank",
  "src_key": str,       # READ-ONLY legacy reference; NOT a V2 write
  "src_id": str,
  "ingest_ts": int,
}
```

V2 publishes these into the V2 data plane under
`v2:liquidations:events` as an ordered list of events. The legacy stream
`liquidations:events` is **NOT** written. The legacy
`config.LIQ_EVENTS_STREAM` value is treated as an immutable reference only
and is not configurable in V2.

## 9. v2_namespace (only place V2 writes)

| V2 key                                                     | role                                                                              |
|------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `v2:coinank:global:{name}:latest`                          | global 11-key aggregator output                                                   |
| `v2:coinank:endpoint:{endpoint}:latest`                    | latest Plan-3 endpoint snapshot                                                   |
| `v2:coinank:endpoint_manifest`                             | active endpoint manifest (in-memory mirror of `coinank:endpoint_manifest`)        |
| `v2:coinank:cycle_runtime`                                 | last completed cycle metadata                                                     |
| `v2:liquidations:events`                                   | canonical liquidation event list                                                  |
| `v2:liquidations:stats:{1m,5m,15m,30m,1h}`                 | windowed aggregations (count_buy, count_sell, notional, pressure)                 |
| `v2:liquidations:levels:{symbol}:{tf}`                     | computed long/short level mapping                                                 |
| `v2:liquidations:dedup_index`                              | in-memory dedup record (per-event TTL'd)                                          |
| `v2:liquidations:missing_api_blockers`                     | list of `missing_api_blocker` records (NEVER replaced by synthesis)               |

All keys are written into an in-memory `data_plane` dict and snapshotted to
a JSON file by the CLI. The worker does **not** open any Redis client.

## 10. forbidden_v2_writes (asserted by tests)

The integration tests `test_no_old_redis_write_contract` and
`test_no_real_exchange_mutating_method_invoked_contract` scan the CLI and
service source for forbidden substrings, including but not limited to:

```
"coinank:..."  "raw:coinank:..."  "features:global_coinank:..."
"features:coinank:..."  "latest:coinank:..."  "meta:coinank..."
"binance:force:..."  "heartbeat:Ingest..."  "liquidations:events"
"unified_features:..."  "cursor:liq_bridge:..."  "dedup:liq:..."
"features:liquidations:...:normalized"  "proc:last_error:..."
"futures[_]create[_]order"  "futures[_]change[_]leverage"
"futures[_]change[_]margin[_]type"  "create[_]order"  "cancel[_]order"
"set[_]leverage"  "set[_]margin[_]mode"
```

The analysis doc itself MAY reference these (it documents them); the
contract applies to executable code only (`v2/backend/app/cli/*.py`,
`v2/backend/app/services/coinank_bridge/*.py`).
