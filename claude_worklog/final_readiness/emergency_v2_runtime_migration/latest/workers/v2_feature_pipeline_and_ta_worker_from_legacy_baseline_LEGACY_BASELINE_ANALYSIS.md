# v2_feature_pipeline_and_ta_worker — Legacy Baseline Analysis (BASELINE-ANCHORED)

This document anchors the V2 feature-pipeline + TA worker to the legacy
startup baseline copied into `v2/legacy_preserved/startup_baseline/`.
Every SHA256 below is cited from
`claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`
and must continue to match. If a SHA changes upstream, the V2 worker
becomes non-compliant and Codex review must fail.

## 1. legacy_source_paths

| legacy_rel_path                              | v2_preserved_path                                                                | SHA256                                                             | size_bytes |
|----------------------------------------------|----------------------------------------------------------------------------------|--------------------------------------------------------------------|------------|
| feature_pipeline.py                          | v2/legacy_preserved/startup_baseline/feature_pipeline.py                         | `143938e735342179105155a12c50d7c495bdd1c16d570586cb369d03d7d4b2e8` | 69156      |
| ohlcv_resampler_hotfix.py                    | v2/legacy_preserved/startup_baseline/ohlcv_resampler_hotfix.py                   | `b83edf60a7d0db51556752cdcf9d713ee9d7175d05b26a6ce6c2235d214f4239` | 8795       |
| ingest/live_technical_analysis.py            | v2/legacy_preserved/startup_baseline/ingest/live_technical_analysis.py           | `5cdd4ea1d43271d0199e1ca92ecad3a8b76308838898a611df6ef4602f7388ac` | 6103       |
| scripts/validate_symbol_universe_data.py     | v2/legacy_preserved/startup_baseline/scripts/validate_symbol_universe_data.py    | `151720d7e9b1c3f9608df6404e20a912da4572dc66078d7cef001bc4ddd5ec07` | 10111      |
| scripts/paralysis_detectors.py               | v2/legacy_preserved/startup_baseline/scripts/paralysis_detectors.py              | `8fd4c4f55ac43e5af07c84cddea04328f7b4e5811a5230442f276caf33fc7c27` | 8801       |

These five SHAs are embedded verbatim as a module constant
`LEGACY_BASELINE_SHA256` inside
`v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py` and asserted by
`test_baseline_sha256_matches_copied_baseline_manifest_contract`.

## 2. closure scan (transitive local dependencies)

From the baseline files:

- `feature_pipeline.py` imports `redis`, `config.{REDIS_URL,TIMEFRAMES,SYMBOLS,...}`,
  `utils.symbol_manager.get_symbols_cached`,
  `rl.btc_correlation.compute_btc_correlation`.
- `ohlcv_resampler_hotfix.py` imports `redis`, `config.{SYMBOLS,TIMEFRAMES}`.
- `ingest/live_technical_analysis.py` imports `ingest.technical_analysis.TechnicalAnalysisEngine`,
  `utils.symbol_manager`, `config.SYMBOLS`.
- `scripts/validate_symbol_universe_data.py` imports `redis`, `config.{SYMBOLS,TIMEFRAMES}`.
- `scripts/paralysis_detectors.py` imports `redis`, `config.PORTFOLIO_EQUITY_MAX_AGE_MS`.

Transitive dependencies (`utils.*`, `rl.btc_correlation`,
`ingest.technical_analysis`, `talib`, `pandas`, `numpy`, `requests`,
`dateutil`, `pytz`) are NOT copied into the preserved baseline. They are
intentionally classified `MISSING_IN_LEGACY_BASELINE_INTENTIONALLY_REPLACED`
because:

1. `utils.symbol_manager` — V2 takes symbols via CLI args/snapshot input; no
   legacy Redis hot-reload key is read.
2. `redis.Redis.from_url(...)` — V2 does not write any legacy Redis key; the
   data plane is a V2 JSON file.
3. `talib` — V2 preserves the legacy ta_*_NN naming convention but computes
   indicator values inline in pure Python so the V2 control-plane venv stays
   lightweight. Indicator family set unchanged: RSI, MACD, ATR, SMA, EMA.
4. `pandas` / `numpy` — V2 does not pull pandas/numpy into the worker; the
   computations operate on plain Python sequences.
5. `rl.btc_correlation.compute_btc_correlation` — out of scope for this
   worker; V2 owns BTC correlation in a separate feature module.
6. `ingest.technical_analysis.TechnicalAnalysisEngine` — replaced by
   `FeaturePipelineAndTAService.compute_ta_indicators`, preserving the
   legacy hash naming.
7. `dateutil` / `pytz` — V2 uses stdlib `datetime`/`datetime.timezone.utc` only.
8. `config.PORTFOLIO_EQUITY_MAX_AGE_MS` — paralysis-detector equity-stale
   branch is dropped from the V2 worker (out of scope: equity health lives
   on the operator dashboard, not the feature/TA worker).

This classification is the documented reason required by the LEGACY-FIRST
MANDATE clause (3).

## 3. legacy_functions_preserved

| legacy function (file:line range) | V2 mapping |
|---|---|
| `feature_pipeline.FeatureAggregator.aggregate_symbol_tf` (L127-646) | `FeaturePipelineAndTAService.compute_unified_features` |
| `feature_pipeline.DualSpeedFeaturePipeline.fast_timeframes/slow_timeframes` (L666-668) | service constants `FAST_TIMEFRAMES`, `SLOW_TIMEFRAMES` |
| `feature_pipeline.DualSpeedFeaturePipeline.fast_lane_interval/slow_lane_interval` (L682-683) | service constants `FAST_LANE_INTERVAL_SEC`, `SLOW_LANE_INTERVAL_SEC` |
| `ohlcv_resampler_hotfix.OHLCVResampler.process_combination` (L122-165) | `FeaturePipelineAndTAService.resample_ohlcv` |
| `ohlcv_resampler_hotfix.OHLCVResampler` `expiry_map` (L150-152) | service constant `OHLCV_RESAMPLER_TF_EXPIRY_SEC` (preserved verbatim) |
| `ohlcv_resampler_hotfix.UPDATE_INTERVAL` (L68) | service constant `OHLCV_RESAMPLER_INTERVAL_SEC` (= 12) |
| `ingest/live_technical_analysis.LiveTechnicalAnalysisService` (L28-149) | `FeaturePipelineAndTAService.compute_ta_indicators` + CLI loop |
| `ingest/live_technical_analysis.update_interval=60` (L154) | service constant `TA_UPDATE_INTERVAL_SEC` |
| `scripts/validate_symbol_universe_data.main` (L68-255) | `FeaturePipelineAndTAService.validate_universe_coverage` |
| `scripts/paralysis_detectors._read_stream_window` + `_window_reason_stats` + `_bucket_coverage` (L81-133) | `FeaturePipelineAndTAService.detect_paralysis` |

## 4. legacy_inputs

- Per-symbol per-tf snapshot (OHLCV + orderbook + mark + TA hash) read from
  Redis keys (`market:*`, `unified_features:*`, `orderbook:top:*`, `ta:*`,
  `latest:binance:mark_price:*`, etc.). **V2 replacement:** snapshot dict
  passed to `FeaturePipelineAndTAService` (built by the CLI from a JSON file
  or from a public Binance REST GET).
- Universe symbols/timeframes from `config.{SYMBOLS,TIMEFRAMES}` and Redis
  hot-reload via `utils.symbol_manager`. **V2 replacement:** snapshot input
  field `symbols`/`timeframes`, with CLI flag overrides.
- Paralysis events from Redis streams `signals:execution:skips`,
  `executed_signals`. **V2 replacement:** `snapshot.paralysis_events` list
  (each event: `{ts_ms, reason_code, ...}`).
- Equity snapshots from `portfolio:equity:{account}`. **V2 replacement:**
  out of scope (operator dashboard owns equity health).

## 5. legacy_outputs (LEGACY Redis keys — READ-ONLY REFERENCES; V2 must NEVER write these)

| legacy Redis key                                     | written by                                       | V2 status                              |
|------------------------------------------------------|--------------------------------------------------|----------------------------------------|
| `unified_features:{symbol}:{timeframe}` (HSET)       | feature_pipeline.aggregate_symbol_tf             | V2 must NOT write (replaced by `v2:features:{symbol}:{tf}:unified`) |
| `ta:{symbol}:{timeframe}` (HSET)                     | ingest/technical_analysis (via live_TA service)  | V2 must NOT write (replaced by `v2:features:{symbol}:{tf}:ta`) |
| `unified_features:{symbol}:{tf}` (6-field overwrite) | ohlcv_resampler_hotfix.process_combination       | V2 must NOT write (replaced by `v2:features:{symbol}:{tf}:ohlcv_resampled`) |
| `features:resampler:last_run_ms`                     | ohlcv_resampler_hotfix.run_cycle                 | V2 must NOT write (heartbeat surfaces in public payload) |
| `features:resampler:last_success_ms`                 | ohlcv_resampler_hotfix.run_cycle                 | V2 must NOT write (heartbeat surfaces in public payload) |
| `features:symbols:active`                            | feature_pipeline._maybe_refresh_symbol_combos    | V2 must NOT write (CLI flags + snapshot input) |
| `features:coinank:{family}:{symbol}:...`             | live_coinank (read by feature_pipeline)          | V2 must NOT write (input only; replaced by V2 coinank bridge worker) |
| `features:coinank_endpoint:{ep}:{symbol}:...`        | live_coinank (read by feature_pipeline)          | V2 must NOT write |
| `metrics:coinapi:v1:{...}`                           | live_coinapi_v1 (read by validate_universe...)   | V2 must NOT write |
| `signals:execution:skips` (XADD)                     | execution path (read by paralysis_detectors)     | V2 must NOT write (input only; alerts emitted via public payload) |
| `executed_signals` (XADD)                            | execution path (read by paralysis_detectors)     | V2 must NOT write |
| `portfolio:equity:{account}`                         | portfolio worker (read by paralysis_detectors)   | V2 must NOT read or write (out of scope for this worker) |
| `market:{symbol}:{timeframe}` (input read)           | live_binance/live_coinapi (read input only)      | V2 must NOT read or write (replaced by V2 market ingestor) |
| `latest:binance:{mark_price,index_price,premium_index,depth}:{symbol}` | live_binance | V2 must NOT write (read via V2 market ingestor) |
| `orderbook:top:{symbol}` (input read)                | live_binance/live_coinapi_wsds (input only)      | V2 must NOT read or write |
| `msnap:coinapi_wsds:{symbol}` / `msnap:binance_tape:{symbol}` | live_coinapi_wsds / live_binance        | V2 must NOT read or write |
| `ohlcv:list:{src}:{symbol}:{tf}` (input read)        | live_binance/live_coinapi_v1 (input only)        | V2 must NOT read or write |

## 6. legacy_edge_cases

| edge case                                                | legacy behavior                                                                                                                       | V2 behavior                                                                                                                            |
|----------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| OHLCV missing for a TF                                   | `OHLCVResampler.process_combination` returns False, logs warning; cycle continues                                                     | preserved: `resample_ohlcv` returns `skipped_reason="missing_required_field"`, no v2 key written for that combination                  |
| TA cycle exception                                       | `LiveTechnicalAnalysisService.calculate_and_store` logs error, returns False, retries next cycle                                      | preserved: CLI loop logs nothing externally, returns to next cycle; tests assert `insufficient_history` short-circuit                  |
| Universe validation TF-aware floor                       | `max_age = max(base_floor, period * 2.0)` per TF (L147-148)                                                                           | preserved verbatim in `validate_universe_coverage`                                                                                     |
| Universe validation startup retry                        | Wrapper script runs validator up to 10 times with 15s sleep (`STARTUP_VALIDATE_RETRIES=10`, `STARTUP_VALIDATE_SLEEP_SEC=15`)          | preserved as service constants surfaced on the public payload; retry orchestration belongs to the supervisor (not this worker)         |
| Paralysis sustained = present in every minute bucket     | `expected_buckets = max(1, int(args.minutes))`; alert when `bucket_coverage(reason) >= expected_buckets`                              | preserved verbatim in `detect_paralysis`                                                                                               |
| Paralysis routing                                        | Legacy script prints alerts to stdout; no Redis stream is emitted by the script itself                                                | V2 surfaces alerts via `paralysis_detector.result.alerts` in the public payload (NOT a legacy Redis stream)                            |

## 7. legacy_failure_modes

- `unified_features` missing or stale per (symbol, tf)
- `ta:{symbol}:{tf}` missing or stale
- `market:{symbol}:{tf}` missing or stale (input)
- `ohlcv:list:{src}:{symbol}:{tf}` shorter than `min_candles` (50)
- Sustained `MICROSTRUCTURE_FAIL_CLOSED`, `PORTFOLIO_BUDGET_BLOCK`, or
  `Margin is insufficient` events in the configured window
- `DISABLE_BINANCE_OHLCV=1` config drift (V2 worker does not honour this
  legacy env; it has no Binance kill switch — the V2 market ingestor owns
  Binance gating).

## 8. v2_required_tests

- `unified_features_built_from_snapshot_into_v2_namespaced_data_plane`
- `ta_indicators_preserve_legacy_indicator_set`
- `ohlcv_resampler_writes_six_fields_with_legacy_tf_expiry_map`
- `universe_validation_uses_legacy_freshness_thresholds_and_retry_window`
- `paralysis_detector_emits_sustained_bucket_alert_into_public_payload`
- `no_old_redis_write_contract`
- `no_real_exchange_mutating_method_invoked_contract`
- `baseline_sha256_matches_copied_baseline_manifest_contract`
- `live_gate_is_always_blocked_human_only`
- `data_plane_keys_use_v2_features_prefix_only`

## 9. intentional_changes

- V2 never writes any legacy Redis key; persistence is a V2 data-plane file.
- TA library: legacy `talib` replaced with pure-Python implementation that
  preserves the legacy `ta_*` indicator naming.
- Paralysis-detector alerts route via the V2 public payload only.
- Universe-validation startup retry window is exposed on the public payload
  but the retry loop itself is supervisor-orchestrated, not in-worker.
- Equity-stale branch from paralysis_detectors removed from this worker.
- Live gate is permanently `blocked_human_only`.
