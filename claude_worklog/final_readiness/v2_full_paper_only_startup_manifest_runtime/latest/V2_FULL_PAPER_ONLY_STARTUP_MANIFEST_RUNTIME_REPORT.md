# V2 Full Paper-Only Startup Manifest Runtime Report

GO/NO-GO: V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_READY

live_gate=blocked_human_only. live_symbols=[]. approves_live=false. approves_legacy_shutdown=false.

## Phase 1 - V2 paper startup manifest
- role_count: 30
  - NOT_REQUIRED_FOR_PAPER_SHADOW: 2
  - OPERATOR_DECISION_REQUIRED: 4
  - V2_BRIDGE_READ_ONLY: 2
  - V2_PLACEHOLDER_BLOCKED: 7
  - V2_SERVICE_ACTIVE: 10
  - V2_SERVICE_STARTABLE: 5

## Phase 2 - Safe components verify state
- preflight_duplicate_guard [NOT_REQUIRED_FOR_PAPER_SHADOW] process=False redis_keys=None payload_age_s=None
- preflight_redis_running [V2_SERVICE_STARTABLE] process=False redis_keys=None payload_age_s=None
- monitoring_trainer_predictions [V2_SERVICE_ACTIVE] process=True redis_keys=1 payload_age_s=50.403928995132446
- monitoring_ingestors_watchdog [V2_PLACEHOLDER_BLOCKED] process=False redis_keys=None payload_age_s=None
- ingest_binance_prices [V2_SERVICE_ACTIVE] process=True redis_keys=3 payload_age_s=32.31301021575928
- ingest_binance_ohlcv_dynamic [V2_PLACEHOLDER_BLOCKED] process=False redis_keys=0 payload_age_s=None
- ingest_binance_orderbook_dynamic [V2_PLACEHOLDER_BLOCKED] process=False redis_keys=0 payload_age_s=None
- ingest_kucoin [OPERATOR_DECISION_REQUIRED] process=False redis_keys=None payload_age_s=None
- ingest_coinank_bridge [V2_BRIDGE_READ_ONLY] process=False redis_keys=0 payload_age_s=None
- ingest_coinapi_wsds [OPERATOR_DECISION_REQUIRED] process=False redis_keys=None payload_age_s=None
- ingest_binance_liquidations [V2_SERVICE_ACTIVE] process=True redis_keys=1 payload_age_s=None
- ingest_realtime_price_provider [V2_SERVICE_ACTIVE] process=True redis_keys=3 payload_age_s=None
- feature_pipeline [V2_SERVICE_ACTIVE] process=True redis_keys=3 payload_age_s=None
- ohlcv_resampler [V2_PLACEHOLDER_BLOCKED] process=False redis_keys=None payload_age_s=None
- technical_analysis [V2_SERVICE_ACTIVE] process=True redis_keys=0 payload_age_s=None
- paralysis_detectors [V2_PLACEHOLDER_BLOCKED] process=False redis_keys=None payload_age_s=None
- validate_symbol_universe_data [V2_PLACEHOLDER_BLOCKED] process=False redis_keys=None payload_age_s=None
- trainer [V2_BRIDGE_READ_ONLY] process=True redis_keys=3 payload_age_s=51.08617305755615
- orchestrator [V2_SERVICE_ACTIVE] process=True redis_keys=1 payload_age_s=None
- signal_router [NOT_REQUIRED_FOR_PAPER_SHADOW] process=False redis_keys=None payload_age_s=None
- trader_primary [V2_SERVICE_ACTIVE] process=True redis_keys=1 payload_age_s=None
- trader_secondary [OPERATOR_DECISION_REQUIRED] process=False redis_keys=None payload_age_s=None
- portfolio_monitor_primary [V2_SERVICE_STARTABLE] process=False redis_keys=0 payload_age_s=None
- portfolio_monitor_secondary [OPERATOR_DECISION_REQUIRED] process=False redis_keys=None payload_age_s=None
- health_probe [V2_SERVICE_ACTIVE] process=False redis_keys=None payload_age_s=489.6041314601898
- critical_health_monitor [V2_PLACEHOLDER_BLOCKED] process=False redis_keys=None payload_age_s=None
- replay_outcome_miner [V2_SERVICE_ACTIVE] process=False redis_keys=None payload_age_s=22.23016667366028
- report_center_indexer [V2_SERVICE_STARTABLE] process=False redis_keys=None payload_age_s=None
- continuous_remediation_governor [V2_SERVICE_STARTABLE] process=False redis_keys=None payload_age_s=None
- self_healing_controller [V2_SERVICE_STARTABLE] process=False redis_keys=None payload_age_s=None

## Phase 3 - API key presence (by env-var name only)
- binance_public_market_data: env=None status=NOT_REQUIRED
- binance_private_or_order: env=BINANCE_API_KEY status=OPERATOR_DECISION_REQUIRED
- coinapi: env=COINAPI_API_KEY status=OPERATOR_DECISION_REQUIRED
- nansen: env=NANSEN_API_KEY status=OPERATOR_DECISION_REQUIRED
- lunarcrush: env=LUNARCRUSH_API_KEY status=OPERATOR_DECISION_REQUIRED
- arkham: env=ARKHAM_API_KEY status=OPERATOR_DECISION_REQUIRED
- kucoin_public: env=None status=NOT_REQUIRED
- coinank: env=COINANK_API_KEY status=OPERATOR_DECISION_REQUIRED

- value_read_or_emitted: False

## Phase 4 - Dynamic 25-symbol paper coverage
- price: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- ohlcv: {'PLACEHOLDER_NOT_READY': 25}
- orderbook: {'PLACEHOLDER_NOT_READY': 25}
- liquidation: {'EVENT_DEPENDENT': 22, 'V2_NATIVE_ACTIVE': 3}
- funding: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- open_interest: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- coinank: {'MISSING_SOURCE': 22, 'V2_BRIDGE_READ_ONLY': 3}
- kucoin: {'OPERATOR_DECISION_REQUIRED': 25}
- coinapi: {'OPERATOR_DECISION_REQUIRED': 25}
- ta: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- features: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- prediction: {'MISSING_SOURCE': 22, 'V2_BRIDGE_READ_ONLY': 3}
- risk: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- orchestrator: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- paper_intent: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- replay_miner: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}
- website_visibility: {'MISSING_SOURCE': 22, 'V2_NATIVE_ACTIVE': 3}

## Phase 5 - Runtime proof
- v2_process_count: 19
- v2_redis_v2_namespace_key_count: 62
- v2_redis_scan_succeeded: True
- report_center_index_age_seconds: None
- replay_miner_status_age_seconds: 22.392069101333618
- old_redis_write_count: 0
- exchange_mutation_call_count: 0
- live_gate: blocked_human_only
- live_symbols: []

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
- did_not_install_systemd_units: True
- did_not_modify_legacy_tree: True
- did_not_mutate_live_symbols_paper_symbols_or_training_symbols: True
- did_not_print_any_raw_credential_value: True
- did_not_run_raw_legacy_script: True
- did_not_start_any_daemon: True
- did_not_start_live_network_feed: True
- did_not_stop_any_daemon: True
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
- Did not install any systemd unit (unit + timer files are written as artifacts only).
- Did not run any raw legacy script.
- Did not start any new network feed.
- Did not load or log any API credential value.
- Did not modify the legacy bot tree.
- Did not stop legacy or V2 runtime.
- Did not write any old Redis key.
- Did not call the exchange.
- Did not enable production trading or canary.
- Did not approve legacy shutdown or Redis trim.
- Did not mutate live_symbols, paper_symbols, or training_symbols.
- Did not adopt any Symbol Universe candidate.
- Did not weaken the paper-fill gate.
- Did not deserialize any legacy checkpoint.
- Did not claim trainer native readiness.
- Did not claim full migration.
