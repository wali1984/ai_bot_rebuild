# Legacy Code Function Inventory

Generated: 2026-05-06T21:40:14.642536+00:00

Read-only AST/hash inventory. No legacy files modified.

## ingest/live_binance.py
- sha256: `6c1eb771a3842e2d94b797eedd55aa624075c51c6d50aec701397f81dbace798`
- classes: BoundedDict, OrderBook
- functions: _dns_preflight, create_hardened_session, ws_connect_with_retry, _check_coinapi_ohlcv_healthy, _to_binance_sym, _compute_depth_bps_windows_from_top, _orderbook_worker, _start_orderbook_thread, _markprice_bookticker_worker, _get_tape_accum, _flush_tape_to_redis, _aggtrades_worker, _start_aggtrades_thread, _start_markprice_bookticker_thread, _websocket_kline_stream, _process_kline_message, _start_websocket_thread, _check_circuit_breaker, _activate_safe_mode, _deactivate_safe_mode, _check_alternative_feeds, _websocket_orderbook_stream, _process_orderbook_message, get_instant_spread, get_instant_price, detect_spoof_pattern, get_market_microstructure, _start_orderbook_websocket_thread, fetch_loop, main, __init__, __setitem__, __init__, apply_snapshot, apply_diffs, topN, summary, _runner, _runner, _runner, _runner, _runner

## ingest/live_kucoin.py
- sha256: `73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976`
- classes: -
- functions: debug_log, increment_counter, _dns_preflight, _test_kucoin_connectivity, safe_preflight_checks, get_redis, sym_spot_kucoin, sym_to_canonical, sym_futs_kucoin, _get, now_ms, _parse_ts_ms, _max_age_ms_for_tf, _should_write_market_key, wkey, heartbeat, _websocket_ticker_stream, _process_websocket_ticker, _start_kucoin_websocket_thread, poll_spot_tickers, poll_klines, poll_futures_meta, poll_orderbook20, write_unified_orderbook, main, main_loop, _runner

## ingest/live_coinank.py
- sha256: `7842fc2995c5d802d272dbaa45866a4e6f0fbc22cfabc4b84d58fc0ef37abfef`
- classes: -
- functions: debug_log, verbose_log, update_counter, _now_ms, _parse_cli_env_overrides, _start_dual_heartbeat, write_diagnostic_heartbeat, first_n_sample, _flatten_numeric_fields, _dns_preflight, _test_coinank_connectivity, _warn, _tf_seconds, _validate_params, _rate_gate, _selected_base_coins, _now_ms, _end_time, _plan3_historical_endtime, _align_end_time, _effective_end_time, _get_max_size, _plan3_endtime_for_interval, _stable_param_sig, _series_cursor_key, _enqueue_backfill, build_param_sets, fetch_endpoint, persist, loop, main, _loop, _cat_rank, _drain_backfill_once, _extract_numeric

## ingest/live_binance_liquidations.py
- sha256: `19711590a3d194fd05ae3be85ef7bd6dec397f6394d02f7e91008c44c310131b`
- classes: -
- functions: debug_log, verbose_log, update_counter, write_diagnostic_heartbeat, sample_first_n_message, _welford_update, _welford_get_z, _now_ms, _dns_preflight, _create_session, consume_force_orders, main_async, main, _hb

## ingest/liquidation_bridge.py
- sha256: `5d70e395938228b61162b531310cd751403ddfeebb8920429e73cdcdbe35d48a`
- classes: -
- functions: _dedup_key, _set_dedup, publish, process_binance_force, process_coinank_orders, main

## ingest/liquidation_levels_engine.py
- sha256: `fed3c90b5193c27d24dc183089730bda49ff69a1758b597e23a154397f839df7`
- classes: LevelEngine
- functions: tf_to_seconds, ensure_group, reset_consumer_group_to_tail, _bucket_step, _decay_weight, main, __init__, _get_latest_price, _batch_cleanup_deques, run, _parse_event, _publish_updates, _heartbeat_publish, _compute_mapping, _top_bucket, _maybe_log

## ingest/realtime_price_provider.py
- sha256: `dfdc2568368c134b9afcc4fa0faff312cc93a6ecc501ecaac747e7c20d7344ba`
- classes: PriceSource, SourceConfig, PriceData, SourceHealth, RealtimePriceProvider
- functions: _internal_to_ccxt_binance_futures_symbol, _ccxt_to_internal_symbol, get_price_provider, init_price_provider, get_realtime_price, main, to_dict, to_json, record_success, record_failure, __init__, _check_coinapi_price, _should_use_binance_redis_feed, _check_binance_redis_price, _start_binance_ws, _process_binance_message, _init_ccxt, _fetch_ccxt_prices, _fetch_kucoin_prices, _get_cached_price, _select_best_price, _update_price, _publish_to_redis, _health_check_loop, _ccxt_polling_loop, _kucoin_polling_loop, _log_health_summary, get_price, get_price_data, get_all_prices, start, stop

## ingest/live_coinank_global_aggregator.py
- sha256: `046d5fd84bbf79fcf477155374997409b5482125c08d86a7c151c257f7a14d62`
- classes: -
- functions: _safe_float, _first_float, get_redis, _acquire_lock, _refresh_lock, _write_value, compute_and_persist, main

## ohlcv_resampler_hotfix.py
- sha256: `b83edf60a7d0db51556752cdcf9d713ee9d7175d05b26a6ce6c2235d214f4239`
- classes: OHLCVResampler
- functions: main, __init__, extract_ohlcv, process_combination, run_cycle, run

## feature_pipeline.py
- sha256: `143938e735342179105155a12c50d7c495bdd1c16d570586cb369d03d7d4b2e8`
- classes: FeatureAggregator, DualSpeedFeaturePipeline
- functions: main, __init__, _safe_float, _get_market_ohlcv, _get_orderbook_top, _get_binance_mark, _get_ta_hash, aggregate_symbol_tf, __init__, _get_active_symbols, _maybe_refresh_symbol_combos, aggregate_symbol_tf, fetch_all_redis_data_batch, calculate_features_fast, process_fast_lane_combo, process_slow_lane_combo, run_fast_lane, run_slow_lane, start

## ingest/live_technical_analysis.py
- sha256: `5cdd4ea1d43271d0199e1ca92ecad3a8b76308838898a611df6ef4602f7388ac`
- classes: LiveTechnicalAnalysisService
- functions: main, __init__, initialize, calculate_and_store, run

## scripts/monitor_trainer_predictions.py
- sha256: `38068905908317415f91f76ed19797c393ee01f20135d59030289e2d697a495a`
- classes: Monitor
- functions: _col, _lcol, _now_str, _fmt_price, _fmt_age, _sf, _tf_cell, main, __init__, _price, _predictions, _proposals, _status, display, run

## scripts/monitor_trainer_prices.py
- sha256: `ced3b14ee493d3e28a2222167dcda77b06ae6f1c3049ccab35751178fab87620`
- classes: PriceMonitor
- functions: _now_str, _sf, _pad, _cpad, _fmt_price, _fmt_age, _dir_str, _conf_str, _pct_str, main, __init__, _price, _all_predictions, _regime, display, run

## monitor_portfolio_primary.py
- sha256: `ba51097c8229eb489e94c9af058b24680b41f8bcd6a8c4912bd18f73a31908cf`
- classes: PrimaryPortfolioMonitor
- functions: _sf, _pad, _cpad, _fmt_px, _fmt_age, __init__, run, _fetch_account, _fetch_positions, _resolve_mark, _margin_ratio, _stealth_stops, _regime, _prediction, _redis_pos, _display

## monitor_portfolio_asjad.py
- sha256: `e957f2d2f80ee2ad3f9676e4c7d9f330015a9dbebe3645f71b77c7f4089d3b1e`
- classes: AsjadPortfolioMonitor
- functions: _sf, _pad, _cpad, _fmt_px, _fmt_age, __init__, run, _fetch_account, _fetch_positions, _resolve_mark, _margin_ratio, _stealth_stops, _regime, _prediction, _redis_pos, _display

## vpn_monitor.py
- sha256: `87e48f03e78ec64fab12d5ee5a184b615d43152cf607aee0694043ae0de701e8`
- classes: VPNMonitor
- functions: main, __init__, _check_interface_exists, _check_vpn_process, _check_dns_resolution, _check_connection_to_binance, _get_vpn_ip, _check_vpn_status, _send_telegram_alert, _send_alert_sync, _handle_disconnect, _handle_reconnect, monitor

## system_telegram_monitor.py
- sha256: `1580409eb5b8aa4e716f6a3f940f5b39812114653424d4139d4226cd8b00e666`
- classes: SystemMonitor
- functions: main, __init__, safe_telegram_send, _ensure_exec_group, _extract_payload, _index_executed, _match_executed, _format_trade_executed, _process_executed_signals, _process_trader_claims, send_system_startup_alert, send_system_shutdown_alert, _is_service_running, _get_service_pid, check_service_health, _send_service_restart_alert, _send_service_start_alert, _send_service_stop_alert, _check_service_hang, _send_service_hang_alert, check_system_health, _send_performance_alert, monitor_loop, stop_monitoring

## monitor_system_memory.py
- sha256: `6c55131bf44dcbe6088578f6a6caeb6c810ca74548b12a7ea8002a11cf550930`
- classes: MemoryMonitor
- functions: main, __init__, get_gpu_memory, get_process_memory, check_oom_events, get_system_metrics, log_metrics, save_snapshot, _find_trainer_pid, set_trainer_oom_score, kill_trainer_for_swap_pressure, run, shutdown, signal_handler
