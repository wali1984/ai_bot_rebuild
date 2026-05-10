# Config Env Map

| path | env_var_names_only | gui_equivalent | safety_critical_hidden_settings |
| --- | --- | --- | --- |
| legacy_reference/.backups/fix_signals_20251012_191010/hybrid_trainer.py | ['NUMEXPR_MAX_THREADS', 'PYTHONFAULTHANDLER', 'PYTHONUNBUFFERED'] | unknown | [] |
| legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py | ['BINANCE_API_MAX_CALLS_PER_MINUTE', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] | unknown | ['BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | ['ACCOUNT_ID', 'BINANCE_API_KEY', 'BINANCE_API_MAX_CALLS_PER_MINUTE', 'BINANCE_API_SECRET', 'BINANCE_TESTNET', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_SECRET', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] |
| legacy_reference/.backups/fix_signals_20251012_191330/hybrid_trainer.py | ['NUMEXPR_MAX_THREADS', 'PYTHONFAULTHANDLER', 'PYTHONUNBUFFERED'] | unknown | [] |
| legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py | ['BINANCE_API_MAX_CALLS_PER_MINUTE', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] | unknown | ['BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | ['ACCOUNT_ID', 'BINANCE_API_KEY', 'BINANCE_API_MAX_CALLS_PER_MINUTE', 'BINANCE_API_SECRET', 'BINANCE_TESTNET', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_SECRET', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_API_SECRET'] |
| legacy_reference/Documentation/Audits/scripts/audit_012426_session_changes.py | ['REDIS_DB', 'REDIS_HOST', 'REDIS_PASSWORD', 'REDIS_PORT'] | unknown | [] |
| legacy_reference/Documentation/Audits/scripts/critical_health_monitor.py | ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'] | unknown | ['TELEGRAM_BOT_TOKEN'] |
| legacy_reference/Documentation/Audits/scripts/drift_guard_monitor.py | ['REDIS_DB', 'REDIS_HOST', 'REDIS_PASSWORD', 'REDIS_PORT'] | unknown | [] |
| legacy_reference/IMPLEMENT_ALL_FEATURES.py | ['ALLOW_CHECKPOINT_OVERRIDE'] | unknown | [] |
| legacy_reference/alphavantage_client.py | ['ALPHAVANTAGE_API_KEY'] | unknown | ['ALPHAVANTAGE_API_KEY'] |
| legacy_reference/api/app.py | ['API_PORT', 'FLASK_DEBUG', 'FLASK_SECRET_KEY', 'PORT'] | unknown | ['FLASK_SECRET_KEY'] |
| legacy_reference/api/auth.py | ['ADMIN_PASSWORD', 'API_KEY', 'JWT_SECRET_KEY'] | unknown | ['API_KEY', 'JWT_SECRET_KEY'] |
| legacy_reference/api/routes/frontend_routes.py | ['ENVIRONMENT'] | unknown | [] |
| legacy_reference/binance_websocket.py | ['BINANCE_MAX_CONNECTIONS', 'BINANCE_MAX_STREAMS', 'BINANCE_REST_SEED_BACKOFF_SEC', 'BINANCE_REST_SEED_CONNECT_TIMEOUT', 'BINANCE_REST_SEED_READ_TIMEOUT', 'BINANCE_REST_SEED_RETRIES', 'BINANCE_WS_CHUNKS', 'BINANCE_WS_CHU | unknown | [] |
| legacy_reference/check_ltc_precision.py | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY'] | unknown | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY'] |
| legacy_reference/check_order_history.py | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY'] | unknown | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY'] |
| legacy_reference/config/settings.py | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY', 'CMC_API_KEY', 'LIQUIDATION_UPDATE_INTERVAL', 'MAX_POSITION_SIZE', 'MODEL_UPDATE_INTERVAL', 'ORDERBOOK_UPDATE_INTERVAL', 'PRICE_UPDATE_INTERVAL', 'REDIS_DB', 'REDIS_HOST', 'REDIS | unknown | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY', 'CMC_API_KEY', 'TOKENMETRICS_API_KEY'] |
| legacy_reference/config.py | ['ADAPTIVE_THRESHOLDS_ENABLED', 'ADAPTIVE_THRESHOLD_DECAY_CYCLES', 'ADAPTIVE_THRESHOLD_DECAY_ENABLED', 'ADAPTIVE_THRESHOLD_DECAY_MIN_FLOOR', 'ADAPTIVE_THRESHOLD_DECAY_STEP', 'BREAKOUT_LOSS_ACCEPT_COOLDOWN_SEC', 'BREAKOUT | unknown | ['DAILY_FEE_BUDGET_OVERRIDE_KEY_PREFIX', 'DECISION_EVAL_LAST_ID_KEY', 'EMERGENCY_MARGIN_UTIL_PCT', 'GRADUATED_KILL_HEDGE_MARGIN_FRAC', 'LIQ_SOURCE_BINANCE_FORCE_KEY', 'LIQ_SOURCE_COINANK_ORDERS_KEY', 'MARGIN_EMERGENCY_RA |
| legacy_reference/diagnose_trainer_binance.py | ['BINANCE_FUTURES_TESTNET_API_KEY', 'BINANCE_FUTURES_TESTNET_API_SECRET', 'TRADE_MODE'] | unknown | ['BINANCE_FUTURES_TESTNET_API_KEY', 'BINANCE_FUTURES_TESTNET_API_SECRET'] |
| legacy_reference/diagnostics.py | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY', 'PRIVATE_CHANNEL_ID', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'USE_TESTNET'] | unknown | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY', 'TELEGRAM_BOT_TOKEN'] |
| legacy_reference/docker-compose.yml | [] | unknown | [] |
| legacy_reference/final_system_validation.py | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY', 'REDIS_HOST', 'REDIS_PORT'] | unknown | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY'] |
| legacy_reference/frontend/src/contexts/WebSocketContext.tsx | ['NEXT_PUBLIC_API_URL'] | unknown | [] |
| legacy_reference/frontend/src/lib/api.ts | ['NEXT_PUBLIC_API_URL'] | unknown | [] |
| legacy_reference/get_channel_id.py | ['TELEGRAM_BOT_TOKEN'] | unknown | ['TELEGRAM_BOT_TOKEN'] |
| legacy_reference/ingest/ccxt_historical.py | ['BINANCE_MAX_CONNECTIONS', 'BINANCE_MAX_STREAMS', 'BINANCE_WS_CONNECTION_WINDOW_SECONDS', 'BINANCE_WS_STALE_SECONDS', 'CCXT_LOOKBACK_MINUTES', 'CCXT_LOOP', 'CCXT_LOOP_FIXED_SECONDS', 'REDIS_HOST', 'REDIS_PORT', 'RLBOT_D | unknown | [] |
| legacy_reference/ingest/clients/tokenmetrics_client.py | ['REDIS_URL', 'TM_API_KEY', 'TM_BASE_URL', 'TM_MONTHLY_BUDGET', 'TM_RPM_HARD', 'TM_RPM_SOFT', 'TOKENMETRICS_API_KEY'] | unknown | ['TM_API_KEY', 'TOKENMETRICS_API_KEY'] |
| legacy_reference/ingest/live_alphavantage_news.py | ['ALPHAVANTAGE_API_KEY', 'AV_NEWS_LIMIT', 'AV_RPD', 'AV_RPH', 'AV_TOPICS', 'AV_UNIVERSE', 'ENABLE_AV_NEWS', 'REDIS_HOST', 'REDIS_PORT'] | unknown | ['ALPHAVANTAGE_API_KEY'] |
| legacy_reference/ingest/live_binance.py | ['AIOHTTP_FORCE_SYSTEM_RESOLVER', 'BINANCE_MAX_CONNECTIONS', 'BINANCE_MAX_STREAMS', 'BINANCE_WEBSOCKET', 'BINANCE_WS_CONNECTION_WINDOW_SECONDS', 'COINAPI_OHLCV_ENABLED', 'COINAPI_OHLCV_STALE_THRESHOLD_SEC', 'DISABLE_BINA | unknown | [] |
| legacy_reference/ingest/live_binance_liquidations.py | ['AIOHTTP_FORCE_SYSTEM_RESOLVER', 'BINANCE_FORCE_WS_URL', 'BINANCE_MAX_CONNECTIONS', 'BINANCE_MAX_STREAMS', 'BINANCE_WS_CONNECTION_WINDOW_SECONDS', 'LIQ_SINGLETON', 'RLBOT_DEBUG'] | unknown | [] |
| legacy_reference/ingest/live_coinank.py | ['COINANK_BACKFILL', 'COINANK_BACKFILL_MAX_EMPTY', 'COINANK_BACKFILL_QUEUE_MAX', 'COINANK_EXPAND_ALL', 'COINANK_GLOBAL_RPM', 'COINANK_HARD_ENDTIME_MS', 'COINANK_MAX_MIN_INTERVAL_SEC', 'COINANK_MIN_SLEEP_SEC', 'COINANK_PR | unknown | [] |
| legacy_reference/ingest/live_coinank_global_aggregator.py | ['COINANK_GLOBAL_AGG_INTERVAL_SEC', 'COINANK_GLOBAL_AGG_LOCK_KEY', 'COINANK_GLOBAL_AGG_LOG_EVERY', 'COINANK_GLOBAL_AGG_LOG_LEVEL', 'COINANK_GLOBAL_AGG_TF', 'COINANK_GLOBAL_AGG_TTL_SEC', 'REDIS_DB', 'REDIS_HOST', 'REDIS_P | unknown | ['COINANK_GLOBAL_AGG_LOCK_KEY'] |
| legacy_reference/ingest/live_coinapi_rest.py | ['COINAPI_API_KEY'] | unknown | ['COINAPI_API_KEY'] |
| legacy_reference/ingest/live_coinapi_v1.py | ['COINAPI_API_KEY', 'COINAPI_DAILY_MSG_LIMIT', 'COINAPI_ENV', 'COINAPI_V1_BUDGET_PCT', 'REDIS_HOST', 'REDIS_PORT'] | unknown | ['COINAPI_API_KEY'] |
| legacy_reference/ingest/live_coinapi_wsds.py | ['COINAPI_ALLOW_FULL_BOOK', 'COINAPI_ALLOW_TRADE', 'COINAPI_API_KEY', 'COINAPI_ENV', 'COINAPI_PRIMARY_EXCHANGE_ID', 'COINAPI_WSDS_MICROFEAT_MIN_INTERVAL_MS', 'COINAPI_WSDS_PUBLISH_MIN_INTERVAL_MS', 'COINAPI_WSDS_URL', 'C | unknown | ['COINAPI_API_KEY'] |
| legacy_reference/ingest/live_kucoin.py | ['KUCOIN_MARKET_WRITE_MODE', 'KUCOIN_WEBSOCKET', 'REDIS_DB', 'REDIS_HOST', 'REDIS_PORT', 'REDIS_URL', 'RLBOT_DEBUG'] | unknown | [] |
| legacy_reference/ingest/live_tokenmetrics.py | ['PYTHONUNBUFFERED', 'REDIS_URL', 'TM_MONTHLY_BUDGET', 'TM_RPM_HARD', 'TM_RPM_SOFT', 'TM_START_AT', 'TM_UNIVERSE', 'TOKENMETRICS_API_KEY', 'TOKENMETRICS_BASE_URL'] | unknown | ['TOKENMETRICS_API_KEY', 'TOKENMETRICS_BASE_URL'] |
| legacy_reference/ingest/technical_analysis.py | ['TA_BACKFILL_LIMIT', 'TA_ENABLE_BINANCE_BACKFILL', 'TA_INCLUDE_1D', 'TA_MIN_CANDLES', 'TA_OHLCV_LIST_MAXLEN', 'TA_OHLCV_LIST_TTL_SEC'] | unknown | [] |
| legacy_reference/launch_monitors.py | ['BINANCE_FUTURES_TESTNET_API_KEY', 'BINANCE_FUTURES_TESTNET_API_SECRET', 'BINANCE_FUT_API_KEY', 'BINANCE_FUT_API_SECRET', 'TRADE_MODE'] | unknown | ['BINANCE_FUTURES_TESTNET_API_KEY', 'BINANCE_FUTURES_TESTNET_API_SECRET', 'BINANCE_FUT_API_KEY', 'BINANCE_FUT_API_SECRET'] |
| legacy_reference/monitor_portfolio.py | ['PORTFOLIO_MONITOR_ALERTS_ENABLED'] | unknown | [] |
| legacy_reference/monitor_portfolio_asjad.py | ['BINANCE_API_KEY_ASJAD', 'BINANCE_API_KEY_BROTHER', 'BINANCE_API_SECRET_ASJAD', 'BINANCE_API_SECRET_BROTHER'] | unknown | ['BINANCE_API_KEY_ASJAD', 'BINANCE_API_KEY_BROTHER', 'BINANCE_API_SECRET_ASJAD', 'BINANCE_API_SECRET_BROTHER'] |
| legacy_reference/monitor_trader_execution.py | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY'] | unknown | ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY'] |
| legacy_reference/monitor_trainer_signals.py | ['MONITOR_ENABLE_BINANCE_PORTFOLIO'] | unknown | [] |
| legacy_reference/monitoring/deep_troubleshooter.py | ['ENABLE_MICROSTRUCTURE_PROACTIVE', 'ENABLE_MICROSTRUCTURE_TF_AGG', 'STEALTH_STOP_LOSS_ENABLED', 'STEALTH_TAKE_PROFIT_ENABLED', 'STEALTH_TRAILING_ENABLED'] | unknown | [] |
| legacy_reference/monitoring/live_system_auditor.py | ['ASJAD_BINANCE_API_KEY', 'ASJAD_BINANCE_API_SECRET', 'BINANCE_API_KEY', 'BINANCE_API_SECRET', 'MIN_CONF_ENTRY', 'MIN_CONF_EXIT'] | unknown | ['ASJAD_BINANCE_API_KEY', 'ASJAD_BINANCE_API_SECRET', 'BINANCE_API_KEY', 'BINANCE_API_SECRET'] |
| legacy_reference/production_safe_fix.py | ['BINANCE_FUTURES_TESTNET_API_KEY', 'BINANCE_FUTURES_TESTNET_API_SECRET', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_SECRET_KEY'] | unknown | ['BINANCE_FUTURES_TESTNET_API_KEY', 'BINANCE_FUTURES_TESTNET_API_SECRET', 'BINANCE_TESTNET_API_KEY', 'BINANCE_TESTNET_SECRET_KEY'] |
| legacy_reference/quick_validate.py | ['ENABLE_SIGNAL_DECONFLICTION'] | unknown | [] |
| legacy_reference/quick_validation.py | ['TRADE_MODE'] | unknown | [] |
| legacy_reference/restart_hybrid_trainer_checkpoints.py | ['CUDA_LAUNCH_BLOCKING', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'PYTORCH_CUDA_ALLOC_CONF'] | unknown | [] |
| legacy_reference/risk/adaptive_gate.py | ['ADAPTIVE_GATE_ENTRY_HARD_BLOCK_CODES', 'ADAPTIVE_GATE_ENTRY_SOFT_MAX_BLOCKS', 'ADAPTIVE_GATE_FAST_MOVE_BLOCK_THRESHOLD', 'ADAPTIVE_GATE_TREND_DI_MULT'] | unknown | [] |
| legacy_reference/risk/assertions.py | ['CORR_BUCKET_CAP_ALT', 'CORR_BUCKET_CAP_MAJOR', 'CORR_BUCKET_CAP_MEME'] | unknown | [] |
| legacy_reference/risk/halt_manager.py | ['ENV', 'RAMP_PHASE'] | unknown | [] |
| legacy_reference/risk/kill_switch.py | ['KILL_SWITCH_TTL_SECONDS'] | unknown | [] |
| legacy_reference/rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py | ['BINANCE_API_BURST', 'BINANCE_API_SAFE_CALLS_PER_MINUTE', 'LEVERAGE_CACHE_SECONDS', 'ORDER_HISTORY_DAYS', 'ORDER_HISTORY_MAX_ORDERS', 'ORDER_HISTORY_MAX_ORDERS_CTX', 'ORDER_HISTORY_REFRESH_SECONDS', 'PORTFOLIO_DISABLE_W | unknown | ['LEVERAGE_CACHE_SECONDS'] |
| legacy_reference/rl/agents/masa_agent.py | ['MASA_INFER_AMP'] | unknown | [] |
| legacy_reference/rl/batch_utils.py | ['AUDIT_LOG_EVERY_N', 'ENABLE_PREFETCH'] | unknown | [] |
| legacy_reference/rl/churn_veto.py | ['CHURN_VETO_LOG_VERBOSE'] | unknown | [] |
| legacy_reference/rl/coinapi_symbol_map.py | ['COINAPI_API_KEY', 'COINAPI_SYMBOL_OVERRIDES_JSON'] | unknown | ['COINAPI_API_KEY'] |
| legacy_reference/rl/cpu_env.py | ['GPU_ENV_FEATURE_CACHE_SECONDS', 'GPU_ENV_MIN_STEP_SECONDS'] | unknown | [] |
| legacy_reference/rl/dynamic_runner_hedge.py | ['DYNAMIC_HEDGE_ALLOW_OPEN', 'DYNAMIC_RUNNER_HEDGE_CANARY_ONLY', 'DYNAMIC_RUNNER_HEDGE_LOG_INTERVAL_SEC', 'DYNAMIC_RUNNER_HEDGE_MAX_ACTIONS_PER_SYMBOL_PER_10MIN', 'DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_GROSS_PCT_EQUITY', 'DYNAM | unknown | ['DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_MARGIN_PCT_EQUITY'] |
| legacy_reference/rl/environment.py | ['SYMBOL_EPISODE_LOSS_PENALTY', 'SYMBOL_EPISODE_WIN_BONUS'] | unknown | [] |
| legacy_reference/rl/fee_ratio_reward_shaping.py | ['FEE_PENALTY_CATASTROPHIC', 'FEE_PENALTY_CRITICAL', 'FEE_PENALTY_HIGH', 'FEE_PENALTY_WARNING', 'FEE_RATIO_CATASTROPHIC', 'FEE_RATIO_CRITICAL', 'FEE_RATIO_HIGH', 'FEE_RATIO_REWARD_SHAPING_ENABLED', 'FEE_RATIO_WARNING'] | unknown | [] |
| legacy_reference/rl/gpu_environment.py | ['GPU_ENV_FEATURE_CACHE_SECONDS', 'GPU_ENV_MIN_STEP_SECONDS'] | unknown | [] |
| legacy_reference/rl/gpu_saturation.py | ['ENABLE_GRAD_ACCUMULATION', 'GPU_BATCH_MULTIPLIER', 'GRAD_ACCUMULATION_STEPS', 'TARGET_GPU_UTIL_HIGH', 'TARGET_GPU_UTIL_LOW', 'TARGET_VRAM_UTIL'] | unknown | [] |
| legacy_reference/rl/gymnasium_wrapper.py | ['ENV_IO_TIMEOUT_SECONDS'] | unknown | [] |
| legacy_reference/rl/hedge_harvest_engine.py | ['ENABLE_HEDGE_HARVEST', 'HEDGE_HARVEST_LOG_VERBOSE', 'HEDGE_HARVEST_MIN_ROE_PCT'] | unknown | [] |
| legacy_reference/rl/hedge_manager_v3.py | ['HEDGE_RANGE_MAX_CONT', 'HEDGE_RANGE_MAX_MARGIN_USD', 'HEDGE_RANGE_MAX_TOX', 'HEDGE_RANGE_MIN_MARGIN_USD', 'HEDGE_RANGE_MIN_WIDTH_PCT', 'HEDGE_RANGE_WINDOW_SEC', 'HEDGE_V3_REPAIR_MIN_LOSS_USD'] | unknown | ['HEDGE_RANGE_MAX_MARGIN_USD', 'HEDGE_RANGE_MIN_MARGIN_USD'] |
| legacy_reference/rl/hybrid_trainer.py | ['CUDA_DEVICE_ORDER', 'CUDA_VISIBLE_DEVICES', 'LOGS_DIR', 'MKL_NUM_THREADS', 'NUMEXPR_MAX_THREADS', 'OMP_NUM_THREADS', 'POST_TRAINING_PAUSE_SECONDS', 'PREDICTION_LOOP_SECONDS', 'PYTHONFAULTHANDLER', 'PYTHONUNBUFFERED', ' | unknown | ['TOKENIZERS_PARALLELISM'] |
| legacy_reference/rl/ingestor_quality_router.py | ['INGESTOR_QUALITY_CANONICALIZE_ORDERBOOK', 'INGESTOR_QUALITY_UPDATE_INTERVAL_SEC'] | unknown | [] |
| legacy_reference/rl/intent_engine.py | ['INTENT_LOG_VERBOSE'] | unknown | [] |
| legacy_reference/rl/light_worker.py | ['CUDA_DEVICE_ORDER', 'CUDA_VISIBLE_DEVICES', 'MKL_NUM_THREADS', 'NUMEXPR_MAX_THREADS', 'OMP_NUM_THREADS', 'SUBPROC_DEBUG_MODE', 'TOKENIZERS_PARALLELISM'] | unknown | ['TOKENIZERS_PARALLELISM'] |
| legacy_reference/rl/market_context.py | ['MARKET_CTX_PRICE_MAX_AGE_MS', 'OPEN_RISK_FEATURES_MAX_AGE_MS'] | unknown | [] |
| legacy_reference/rl/microstructure_overlay.py | ['ENABLE_MICROSTRUCTURE_OVERLAY', 'MICROSTRUCTURE_ABSTAIN_NO_TAPE', 'MICROSTRUCTURE_FAST_MOVE_THRESHOLD', 'MICROSTRUCTURE_OVERLAY_MODE', 'MICROSTRUCTURE_SIZE_REDUCTION_FACTOR', 'MICROSTRUCTURE_SPOOF_ACTION', 'MICROSTRUCT | unknown | [] |
| legacy_reference/rl/microstructure_proactive.py | ['PROACTIVE_HEDGE_RISK_HISTORY_MAXLEN', 'PROACTIVE_MID_HISTORY_MAXLEN', 'PROACTIVE_MID_HISTORY_MAX_AGE_MS'] | unknown | [] |
| legacy_reference/rl/obs_schema.py | ['OBS_SCHEMA_VERSION'] | unknown | [] |
| legacy_reference/rl/orchestrator_worker.py | ['ORCHESTRATOR_CONSUMER_GROUP', 'ORCHESTRATOR_CONSUMER_NAME', 'ORCHESTRATOR_COOLDOWN_HORIZON_MS', 'ORCHESTRATOR_EXEC_EVENT_STREAM', 'ORCHESTRATOR_FORBIDDEN_STREAM', 'ORCHESTRATOR_HEDGE_CHURN_GUARD_ENABLED', 'ORCHESTRATOR | unknown | [] |
| legacy_reference/rl/portfolio_policy_manager.py | ['BINANCE_API_KEY', 'BINANCE_API_KEY_ASJAD', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_ASJAD', 'DISABLE_ASJAD_TRAINER_API', 'PORTFOLIO_MICRO_ENTRY_MAX_MARGIN_USD', 'PORTFOLIO_MICRO_ENTRY_RESERVE_ZONE_ENABLED'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_KEY_ASJAD', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_ASJAD', 'PORTFOLIO_MICRO_ENTRY_MAX_MARGIN_USD'] |
| legacy_reference/rl/portfolio_recovery_allocator.py | ['PRA_ENABLED', 'PRA_MAX_DATA_STALENESS_MS', 'PRA_MAX_MARGIN_PCT_AVAILABLE', 'PRA_MAX_MARGIN_PCT_EQUITY', 'PRA_MAX_SUGGESTIONS_PER_ACCOUNT', 'PRA_PUBLISH_INTERVAL_SEC', 'PRA_SUGGEST_LEVERAGE'] | unknown | ['PRA_MAX_MARGIN_PCT_AVAILABLE', 'PRA_MAX_MARGIN_PCT_EQUITY', 'PRA_SUGGEST_LEVERAGE'] |
| legacy_reference/rl/profit_bank.py | ['PROFIT_BANK_LOG_VERBOSE'] | unknown | [] |
| legacy_reference/rl/profit_freespace_rebalancer.py | ['FREESPACE_LOG_VERBOSE'] | unknown | [] |
| legacy_reference/rl/promotion_controller.py | ['PROMOTION_CANARY_INCLUDE_OPEN_POSITIONS', 'PROMOTION_CANARY_MAX_SYMBOLS', 'PROMOTION_CANARY_MODE', 'PROMOTION_CANARY_ROTATION_SEC', 'PROMOTION_LEVEL', 'PROMOTION_MAX_REST_DAILY_USED', 'PROMOTION_MAX_WS_BYTES_TODAY_GB', | unknown | [] |
| legacy_reference/rl/target_exposure_controller.py | ['ENABLE_NO_LOSS_GATING', 'ENABLE_TARGET_EXPOSURE_CONTROLLER', 'TARGET_MAX_EXPOSURE_PCT', 'TARGET_MIN_CONF_ENTRY', 'TARGET_MIN_DELTA_PCT', 'TARGET_MIN_EXPOSURE_PCT', 'TARGET_MIN_INTERVAL_SEC', 'TARGET_MIN_PROFIT_FOR_CLOS | unknown | [] |
| legacy_reference/rl/toxicity_shield.py | ['TOXICITY_LOG_VERBOSE'] | unknown | [] |
| legacy_reference/rl/trainer_enhancements.py | ['REQUIRE_CUDA'] | unknown | [] |
| legacy_reference/rl/underwater_recovery_controller.py | ['URC_ENABLED', 'URC_MODE', 'URC_PRICE_HISTORY_MAXLEN', 'URC_PROTECT_COOLDOWN_SECONDS', 'URC_PROTECT_MAX_ADD_PCT_OF_MAIN', 'URC_PROTECT_SCALE_ENABLED', 'URC_RECOVER_COOLDOWN_SECONDS', 'URC_RECOVER_MAX_ADD_PCT_OF_MAIN', ' | unknown | [] |
| legacy_reference/run_hybrid_trainer_with_signals.py | ['CUDA_LAUNCH_BLOCKING', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'PYTORCH_CUDA_ALLOC_CONF'] | unknown | [] |
| legacy_reference/run_hybrid_trainer_wsl.py | ['CUDA_LAUNCH_BLOCKING', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS', 'PYTORCH_CUDA_ALLOC_CONF'] | unknown | [] |
| legacy_reference/scripts/acceptance_metrics_report.py | ['EPISODE_STREAM', 'REDIS_DB', 'REDIS_HOST', 'REDIS_PORT'] | unknown | [] |
| legacy_reference/scripts/audit_48h_live.py | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] |
| legacy_reference/scripts/audit_last_hours_pnl.py | ['REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/audit_orchestrator_last30m.py | ['REDIS_DB', 'REDIS_HOST', 'REDIS_PASSWORD', 'REDIS_PORT'] | unknown | [] |
| legacy_reference/scripts/breadth_allocator_audit.py | ['REDIS_DB', 'REDIS_HOST', 'REDIS_PORT'] | unknown | [] |
| legacy_reference/scripts/check_trainer_signal_health.py | ['REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/close_all_positions.py | ['BINANCE_API_KEY', 'BINANCE_API_KEY_BROTHER', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_BROTHER'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_KEY_BROTHER', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_BROTHER'] |
| legacy_reference/scripts/coinapi_health_check.py | ['COINAPI_METRICS_REDIS_PREFIX', 'COINAPI_REST_DAILY_CAP'] | unknown | [] |
| legacy_reference/scripts/comprehensive_24h_audit.py | ['BINANCE_API_KEY', 'BINANCE_API_KEY_ASJAD', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_ASJAD'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_KEY_ASJAD', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_ASJAD'] |
| legacy_reference/scripts/comprehensive_system_audit.py | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] |
| legacy_reference/scripts/episode_winrate_report.py | ['EPISODE_STREAM', 'REDIS_DB', 'REDIS_HOST', 'REDIS_PORT'] | unknown | [] |
| legacy_reference/scripts/force_paths.py | ['DRY_RUN_EXECUTION', 'ENABLE_POST_CASCADE_COOLDOWN', 'ENABLE_RECOVERY_POCKET', 'FORCE_FREE_MARGIN_RATIO', 'FORCE_MARGIN_UTIL', 'FORCE_PATHS_HARNESS', 'FORCE_PORTFOLIO_MODE', 'FORCE_REGIME', 'PROFIT_RECYCLE_MIN_USD', 'PR | unknown | ['FORCE_FREE_MARGIN_RATIO', 'FORCE_MARGIN_UTIL'] |
| legacy_reference/scripts/forensics_12h_correlation.py | ['EPISODE_STREAM', 'ORCHESTRATOR_UNIFIED_PROPOSAL_STREAM', 'REDIS_DB', 'REDIS_HOST', 'REDIS_PORT'] | unknown | [] |
| legacy_reference/scripts/go_nogo_dashboard.py | ['ORCH_LOG_FILE', 'REDIS_URL', 'TRADER_ASJAD_LOG', 'TRADER_PRIMARY_LOG'] | unknown | [] |
| legacy_reference/scripts/ingestor_probe_new_symbols.py | ['OUTPUT_JSON', 'REDIS_URL', 'WRITE_JSON'] | unknown | [] |
| legacy_reference/scripts/ingestors_watchdog.py | ['ALERT_COOLDOWN', 'REDIS_URL', 'WATCHDOG_INTERVAL', 'WATCHDOG_LOOP'] | unknown | [] |
| legacy_reference/scripts/inspect_liq_keys.py | ['REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/manage_limit_orders.py | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] |
| legacy_reference/scripts/monitor_orchestrator_shadow.py | ['ORCHESTRATOR_PROOF_STREAM', 'REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/monitor_trainer_predictions.py | ['REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/monitor_trainer_prices.py | ['REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/paralysis_detectors.py | ['DISABLE_BINANCE_OHLCV', 'REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/portfolio_analysis.py | ['BINANCE_API_KEY', 'BINANCE_API_KEY_BROTHER', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_BROTHER'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_KEY_BROTHER', 'BINANCE_API_SECRET', 'BINANCE_API_SECRET_BROTHER'] |
| legacy_reference/scripts/pre_scale_audit.py | ['ALERT_STREAM', 'ORCH_LOG_FILE', 'REDIS_URL', 'TRADER_LOG_FILE'] | unknown | [] |
| legacy_reference/scripts/probe_new_symbols_endpoints.py | ['COINANK_API_KEY', 'COINAPI_API_KEY'] | unknown | ['COINANK_API_KEY', 'COINAPI_API_KEY'] |
| legacy_reference/scripts/ramp_step.py | ['ENV', 'REDIS_URL'] | unknown | [] |
| legacy_reference/scripts/regime_binary_identical_audit.py | ['REGIME_HEDGE_ADAPTIVE_ENABLED', 'REGIME_LAYER_ENABLED', 'REGIME_POLICY_ENABLED'] | unknown | [] |
| legacy_reference/scripts/replay_sanity_check.py | ['PORTFOLIO_LONG_BUDGET_PCT', 'PORTFOLIO_MAX_LONG_SLOTS', 'PORTFOLIO_MAX_SHORT_SLOTS', 'PORTFOLIO_MAX_TOTAL_POSITIONS', 'PORTFOLIO_SHORT_BUDGET_PCT', 'PORTFOLIO_ULTRA_CONF_THRESHOLD', 'PORTFOLIO_ULTRA_MAX_TOTAL_POSITIONS | unknown | [] |
| legacy_reference/scripts/stop_all_services_production.sh | ['AI_SIGNALS_CHANNEL_ID', 'PORTFOLIO_CHANNEL_ID', 'PRIVATE_CHANNEL_ID', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID', 'TELEGRAM_CHAT_ID', 'TELEGRAM_TOKEN', 'TRADE_CHANNEL_ID'] | unknown | ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_TOKEN'] |
| legacy_reference/scripts/test_hedge_build.py | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] |
| legacy_reference/scripts/top_movers_futures.py | ['BINANCE_API_KEY', 'BINANCE_API_SECRET', 'TOP_MOVERS_LIMIT', 'TOP_MOVERS_QUOTE', 'TOP_MOVERS_REFRESH_SEC'] | unknown | ['BINANCE_API_KEY', 'BINANCE_API_SECRET'] |
| legacy_reference/scripts/trace_trade_lifecycle.py | ['ANTI_CHURN_WARM_START_WINDOW_SEC', 'REDIS_DB', 'REDIS_HOST', 'REDIS_PORT'] | unknown | [] |

Showing 120 of 292 rows. Full data is in JSON.
