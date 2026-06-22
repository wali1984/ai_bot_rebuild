# V2 Legacy Startup Manifest Parity and Bridge-Exit Report

GO/NO-GO: V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT_READY

live_gate=blocked_human_only. live_symbols=[]. approves_live=false. approves_canary=false. approves_legacy_shutdown=false. approves_redis_trim=false.

## Phase 1 - Manifest source
- local_path: /home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh
- snapshot_path: /home/wali/Desktop/AI BOT REBUILD/legacy_reference/scripts/start_all_services_production.sh
- local_sha256: 2b5a9a63fc76487b3a6f46cdbb8060044aeab69c5f8117bbf30e7efdb8a10ca9
- snapshot_sha256: aeed39be4840c2204752c4a3937edbd38df349897c20b316950883d91acbf0b9
- diff_classification: LOCAL_AND_SNAPSHOT_DIFFER_LOCAL_RUNTIME_SCRIPT_USED_FOR_PARSING
- parsing_source_used: local
- env_flags_extracted_count: 14
- python_invocations_extracted_count: 27
- item_count: 38

## Phase 2 - Parity matrix
- row_count: 38
- parity_score_v2_native_over_total: 0.263
  - LEGACY_REFERENCE_ONLY: 4
  - NOT_REQUIRED_FOR_V2_PAPER_SHADOW: 3
  - OPERATOR_DECISION_REQUIRED: 4
  - V2_BRIDGE_FROM_LEGACY_REDIS: 4
  - V2_MISSING: 13
  - V2_NATIVE: 10

## Phase 3 - Redis contract map
- row_count: 24

## Phase 4 - Dynamic symbol coverage
- universe_size: 25
- currently_active_symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
- service_families: 17

## Phase 5 - V2 startup-order parity
- 0_5_monitoring: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 0_preflight: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 1_ingestors: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 2_5_ta: V2_NATIVE_PARITY (gap=NONE)
- 2_5_validation: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 2_features: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 3B_orchestrator: V2_NATIVE_PARITY (gap=NONE)
- 3_trainer: V2_BRIDGE_PARITY (gap=BRIDGE_ONLY_FOR_SOME_SERVICES)
- 4A_signal_router: V2_NATIVE_PARITY (gap=NONE)
- 4B_traders: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 4C_portfolio: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 5_health: V2_GAP_PRESENT (gap=MISSING_SERVICES_OR_BRIDGE_ONLY)
- 6_final_status: OPERATOR_DECISION_PENDING (gap=OPERATOR_DECISION_REQUIRED)

## Phase 6 - First-batch tasks
- v2_native_binance_ohlcv_dynamic_symbol_ingestor -> V2_NATIVE_BINANCE_OHLCV_DYNAMIC_SYMBOL_INGESTOR_READY
- v2_native_binance_orderbook_dynamic_symbol_ingestor -> V2_NATIVE_BINANCE_ORDERBOOK_DYNAMIC_SYMBOL_INGESTOR_READY
- v2_native_coinank_dynamic_symbol_ingestor -> V2_NATIVE_COINANK_DYNAMIC_SYMBOL_INGESTOR_READY
- v2_native_kucoin_dynamic_symbol_ingestor -> V2_NATIVE_KUCOIN_DYNAMIC_SYMBOL_INGESTOR_READY
- v2_native_coinapi_wsds_dynamic_symbol_ingestor -> V2_NATIVE_COINAPI_WSDS_DYNAMIC_SYMBOL_INGESTOR_READY
- v2_native_feature_pipeline_dynamic_symbol_expansion -> V2_NATIVE_FEATURE_PIPELINE_DYNAMIC_SYMBOL_EXPANSION_READY
- v2_native_technical_analysis_dynamic_symbol_service -> V2_NATIVE_TECHNICAL_ANALYSIS_DYNAMIC_SYMBOL_SERVICE_READY
- v2_trainer_bridge_exit_native_prediction_publisher_contract -> V2_TRAINER_BRIDGE_EXIT_NATIVE_PREDICTION_PUBLISHER_CONTRACT_READY
- v2_trainer_dataset_builder_from_v2_replay_features -> V2_TRAINER_DATASET_BUILDER_FROM_V2_REPLAY_FEATURES_READY
- v2_startup_order_parity_control_plane -> V2_STARTUP_ORDER_PARITY_CONTROL_PLANE_READY

## Phase 7 - Automation integration
- primary_p0_mission: V2_LEGACY_STARTUP_MANIFEST_PARITY_AND_BRIDGE_EXIT
- startup_manifest_coverage_total: 38
- missing_startup_services_count: 17
- bridge_only_services_count: 4
- v2_native_services_count: 10
- operator_decision_required_count: 4
- not_required_for_v2_paper_shadow_count: 3
- dynamic_symbol_coverage_total: 25
- v2_native_active_symbol_count: 3
- service_parity_score: 0.263
- bridge_exit_progress_pct: 26.3

## Phase 8 - Operator dashboard (public mirror)
- public_path: v2/frontend/public/v2_legacy_startup_manifest_parity_and_bridge_exit/latest/operator_dashboard_payload.json
- live_blocked: True | shutdown_blocked: True | controls_present: False | fake_readiness: False

## Safety scoreboard
- approves_canary: False
- approves_legacy_shutdown: False
- approves_live: False
- approves_redis_trim: False
- did_not_adopt_any_symbol_universe_candidate: True
- did_not_call_exchange_mutation: True
- did_not_change_leverage_or_margin_mode: True
- did_not_create_paper_only_shutdown_acceptance_file: True
- did_not_deserialize_legacy_checkpoint: True
- did_not_expose_raw_api_keys: True
- did_not_install_systemd_units_or_scheduler_daemons: True
- did_not_modify_legacy_tree: True
- did_not_mutate_live_symbols_paper_symbols_or_training_symbols: True
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
- Did not modify the legacy bot tree.
- Did not stop legacy or V2 runtime.
- Did not stop the report center, replay miner, or Codex governors.
- Did not write any old Redis key.
- Did not call the exchange.
- Did not change leverage or margin mode.
- Did not enable production trading.
- Did not approve legacy shutdown or Redis trim.
- Did not install systemd units or scheduler daemons.
- Did not mutate live_symbols, paper_symbols, or training_symbols.
- Did not adopt any Symbol Universe candidate.
- Did not weaken the paper-fill gate.
- Did not deserialize any legacy checkpoint.
- Did not expose any raw API key.
