# V2 Full Paper-Only Startup Manifest Role Coverage Remediation

GO/NO-GO: V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_REMEDIATION_READY

live_gate=blocked_human_only. live_symbols=[]. approves_live=false.

## Coverage
- canonical_manifest_role_count: 38
- v2_runtime_role_count_after_remediation: 38
- missing_role_count: 0
- every_canonical_role_represented: True

## Status counts (after remediation)
- NOT_REQUIRED_FOR_PAPER_SHADOW: 3
- OPERATOR_DECISION_REQUIRED: 3
- V2_BRIDGE_READ_ONLY: 2
- V2_PLACEHOLDER_BLOCKED: 7
- V2_SERVICE_ACTIVE: 22
- V2_SERVICE_STARTABLE: 1

## Per-canonical-role rows
- duplicate_process_guard [NOT_REQUIRED_FOR_PAPER_SHADOW] bridge=False blocks_live=False
- force_kill_all_bot_py [NOT_REQUIRED_FOR_PAPER_SHADOW] bridge=False blocks_live=False
- vram_threshold_check [V2_PLACEHOLDER_BLOCKED] bridge=False blocks_live=True
- ram_threshold_check [V2_PLACEHOLDER_BLOCKED] bridge=False blocks_live=True
- disk_threshold_check [V2_PLACEHOLDER_BLOCKED] bridge=False blocks_live=False
- redis_running_check [V2_SERVICE_STARTABLE] bridge=False blocks_live=True
- vpn_monitor [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- system_telegram_monitor [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- monitor_system_memory [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- scripts_memory_monitor [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingestors_watchdog [V2_PLACEHOLDER_BLOCKED] bridge=False blocks_live=False
- monitor_trainer_predictions [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingest_live_binance [V2_SERVICE_ACTIVE] bridge=False blocks_live=True
- ingest_live_kucoin [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingest_live_coinank [V2_BRIDGE_READ_ONLY] bridge=True blocks_live=True
- ingest_live_coinank_global_aggregator [V2_SERVICE_ACTIVE] bridge=True blocks_live=True
- ingest_live_binance_liquidations [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingest_liquidation_bridge [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingest_liquidation_levels_engine [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingest_realtime_price_provider [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingest_live_coinapi_wsds [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ingest_live_coinapi_v1 [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- ohlcv_resampler_hotfix [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- feature_pipeline [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- live_technical_analysis [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- paralysis_detectors [V2_PLACEHOLDER_BLOCKED] bridge=False blocks_live=False
- validate_symbol_universe_data [V2_PLACEHOLDER_BLOCKED] bridge=False blocks_live=False
- health_probe [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- critical_health_monitor [V2_PLACEHOLDER_BLOCKED] bridge=False blocks_live=False
- rl_hybrid_trainer [V2_BRIDGE_READ_ONLY] bridge=True blocks_live=True
- rl_orchestrator_worker [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- signal_router [NOT_REQUIRED_FOR_PAPER_SHADOW] bridge=False blocks_live=False
- trading_trader_primary [V2_SERVICE_ACTIVE] bridge=False blocks_live=True
- trading_trader_asjad [OPERATOR_DECISION_REQUIRED] bridge=False blocks_live=False
- monitor_portfolio_primary [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- monitor_portfolio_asjad [OPERATOR_DECISION_REQUIRED] bridge=False blocks_live=False
- process_listing_and_resource_report [V2_SERVICE_ACTIVE] bridge=False blocks_live=False
- telegram_completion_notification [OPERATOR_DECISION_REQUIRED] bridge=False blocks_live=False

## Safety scoreboard
- approves_canary: False
- approves_legacy_shutdown: False
- approves_live: False
- approves_redis_trim: False
- did_not_adopt_any_symbol_universe_candidate: True
- did_not_call_exchange_mutation: True
- did_not_change_leverage_or_margin_mode: True
- did_not_claim_full_migration: True
- did_not_claim_trainer_native_readiness: True
- did_not_create_paper_only_shutdown_acceptance_file: True
- did_not_deserialize_legacy_checkpoint: True
- did_not_expose_raw_api_keys: True
- did_not_install_systemd_units_or_scheduler_daemons: True
- did_not_modify_legacy_tree: True
- did_not_mutate_live_symbols_paper_symbols_or_training_symbols: True
- did_not_start_live_network_feed: True
- did_not_stop_codex_governors: True
- did_not_stop_legacy_runtime: True
- did_not_stop_replay_miner: True
- did_not_stop_report_center: True
- did_not_stop_v2_runtime: True
- did_not_weaken_paper_fill_gate: True
- did_not_write_old_redis_keys: True
- live_gate: blocked_human_only
- live_symbols: []

## What this packet did NOT do
- Did not start or stop any daemon.
- Did not install any systemd unit.
- Did not run any raw legacy script.
- Did not start any new network feed.
- Did not load or log any API credential value.
- Did not modify the legacy bot tree.
- Did not write any old Redis key.
- Did not call the exchange.
- Did not enable production trading or canary.
- Did not approve legacy shutdown or Redis trim.
- Did not label any bridge data V2_NATIVE.
- Did not claim trainer native readiness.
- Did not claim full migration.
