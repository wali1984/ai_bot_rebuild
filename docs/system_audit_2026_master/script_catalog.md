# Script Catalog — AI BOT V2

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01

Total CLI scripts: 230 (v2/backend/app/cli/)
Entrypoints with systemd services: ~50
One-shot analysis/audit scripts: ~80
Active paper/trading loops: ~30
Archived/deprecated: ~20

## Category A — Active Trading Pipeline (Critical)

| Script | Service | Role | Status |
|--------|---------|------|--------|
| v2_trade_management_paper_loop.py | ai-bot-v2-trade-management-paper-loop.service | Primary paper trader | ACTIVE |
| v2_risk_gateway_live_loop.py | ai-bot-v2-risk-gateway-live-loop.service | Risk gateway | ACTIVE |
| v2_risk_gateway_runtime_worker.py | (sub-worker) | Risk decisions writer | ACTIVE |
| v2_orchestrator_arbitration_loop.py | (sub-loop) | Prediction arbitration | ACTIVE |
| v2_orchestrator_arbitration_worker.py | (sub-worker) | Orchestrator writer | ACTIVE |
| v2_rl_core_inference_loop.py | ai-bot-v2-rl-core-inference-loop.service | RL core sidecar | ACTIVE |

## Category B — Data Ingestors (Active)

| Script | Service | Provider | Status |
|--------|---------|----------|--------|
| v2_binance_kline_wss_loop.py | ai-bot-v2-binance-kline-wss-loop.service | Binance USDM klines | ACTIVE |
| v2_liquidation_wss_loop.py | ai-bot-v2-liquidation-wss-paper-shadow.service | Binance forceOrder WSS | ACTIVE |
| v2_liquidation_levels_engine.py | ai-bot-v2-liquidation-levels-engine.service | Liq. levels calc | ACTIVE |
| v2_coinapi_wsds_loop.py | ai-bot-v2-coinapi-wsds-loop.service | CoinAPI WSDS | ACTIVE |
| v2_coinapi_rest_ingestor_worker.py | ai-bot-v2-coinapi-rest-fallback-loop.service | CoinAPI REST | ACTIVE |
| v2_kucoin_ingestor_worker.py | ai-bot-v2-kucoin-public-rest-loop.service | KuCoin public REST | ACTIVE |
| v2_coinank_and_liquidation_bridge.py | ai-bot-v2-coinank-live-direct.service | CoinAnk live | ACTIVE |
| v2_coinank_direct_runtime_status_publisher.py | ai-bot-v2-coinank-direct-status-publisher.service | CoinAnk status | ACTIVE |
| v2_lunarcrush_altdata_ingestor.py | ai-bot-v2-lunarcrush-altdata-loop.service | LunarCrush | ACTIVE |
| v2_nansen_altdata_ingestor.py | ai-bot-v2-nansen-altdata-loop.service | Nansen | ACTIVE |
| v2_public_intel_free_tier.py | ai-bot-v2-public-intel-free-tier-loop.service | Public intel | ACTIVE |
| v2_aicoin_whale_intel_free_tier.py | ai-bot-v2-aicoin-whale-intel-loop.service | AICoin + whale walls | ACTIVE |
| v2_arkham_presence_only_worker.py | ai-bot-v2-arkham-presence-loop.service | Arkham presence | ACTIVE |
| v2_dynamic_symbol_discovery_free_tier.py | ai-bot-v2-dynamic-symbol-discovery-loop.service | Symbol discovery | ACTIVE |

## Category C — Feature Pipeline (Active)

| Script | Service | Role | Status |
|--------|---------|------|--------|
| v2_feature_pipeline_native_loop.py | ai-bot-v2-feature-pipeline-native-loop.service | Feature calc loop | ACTIVE |
| v2_feature_pipeline_native.py | (imported) | Feature engine | LIBRARY |
| v2_full_talib_ta_loop.py | ai-bot-v2-full-talib-ta-loop.service | TA-Lib TA calc | ACTIVE |
| v2_feature_snapshot_builder.py | ai-bot-v2-feature-snapshot-builder.service | Feature snapshot | ACTIVE |
| v2_feature_pipeline_and_ta_worker.py | (sub-worker) | Combined worker | ACTIVE |
| v2_market_state_brain_worker.py | (sub-worker) | Market state | ACTIVE |

## Category D — Trainer (Active)

| Script | Service | Role | Status |
|--------|---------|------|--------|
| v2_native_cuda_trainer_persistent_loop.py | ai-bot-v2-trainer-training-loop.service | Main trainer loop | ACTIVE |
| v2_native_rl_masa_ppo_cuda_trainer_loop.py | (sub-loop) | PPO/MASA training | ACTIVE |
| v2_native_trainer_prediction_publisher.py | (publisher) | Prediction publish | ACTIVE |
| v2_native_trainer_dataset_builder.py | (builder) | Dataset construction | ACTIVE |
| v2_trainer_training_live_loop.py | (outer loop) | Training outer loop | ACTIVE |
| v2_trainer_bridge.py | (bridge) | Legacy bridge stub | DISABLED |
| v2_trainer_checkpoint_evidence_publisher.py | ai-bot-v2-trainer-checkpoint-evidence.service | Checkpoint metadata | ACTIVE |
| v2_checkpoint_promotion_status.py | (status) | Checkpoint status | ONE_SHOT |

## Category E — Publishers (Active)

| Script | Service/Timer | Role | Status |
|--------|--------------|------|--------|
| v2_all_timeframe_prediction_signal_price_target_publisher.py | ai-bot-v2-all-timeframe-...service | Prediction publisher | ACTIVE |
| v2_market_chart_payload_publisher.py | ai-bot-v2-market-chart-payload-publisher.service | Chart payloads | ACTIVE |
| v2_professional_market_chart_payload_publisher.py | ai-bot-v2-professional-market-chart...service | OHLCV/TA chart | ACTIVE |
| v2_derivatives_runtime_payload_publisher.py | ai-bot-v2-derivatives-runtime-publisher.timer | Derivatives data | TIMER_30s |
| v2_portfolio_state_publisher.py | (sub-publisher) | Portfolio state | ACTIVE |
| v2_operator_runtime_truth_publisher.py | (sub-publisher) | Runtime truth | ACTIVE |
| v2_realtime_runtime_truth_publisher.py | (sub-publisher) | Realtime truth | ACTIVE |
| v2_ingestors_status_publisher.py | ai-bot-v2-ingestors-status-publisher.service | Ingestor status | ACTIVE |
| v2_log_errors_status_publisher.py | ai-bot-v2-log-errors-status-publisher.service | Log errors status | ACTIVE |
| v2_technical_analysis_status_publisher.py | ai-bot-v2-technical-analysis-status-publisher.service | TA status | ACTIVE |
| symbol_universe_public_payload.py | ai-bot-v2-symbol-universe-publisher.service | Symbol universe | ACTIVE |
| v2_liquidation_runtime_status_publisher.py | ai-bot-v2-liquidation-runtime-status-publisher.service | Liq status | ACTIVE |
| v2_liquidation_bridge_status_publisher.py | (sub-publisher) | Liq bridge status | ACTIVE |
| v2_signal_publisher.py | (orchestrator) | Signal write | ACTIVE |
| v2_signal_lineage_worker.py | (worker) | Signal lineage | ACTIVE |
| v2_misc_state_keys_publisher.py | (misc) | State keys | ACTIVE |
| v2_pipeline_control_status_publisher.py | (status) | Pipeline control | ACTIVE |
| v2_trade_terminal_runtime_payload_publisher.py | ai-bot-v2-trade-terminal-runtime-publisher.timer | Trade terminal | TIMER_30s |
| v2_website_contracts_status.py | (status) | Website contract status | ONE_SHOT |

## Category F — Monitoring & Observability (Active)

| Script | Role | Status |
|--------|------|--------|
| v2_continuous_edge_guardian.py | A-grade execution gate | ACTIVE |
| v2_continuous_hourly_monitor.py | Hourly monitor | ACTIVE |
| v2_script_monitor.py | Script monitoring | ACTIVE |
| v2_one_hour_trainer_risk_orchestrator_data_website_monitor.py | Full 1h monitor | ONE_SHOT |
| v2_paper_shadow_outcome_observer.py | Paper outcome observer | ACTIVE_TIMER |
| paper_shadow_outcome_observer.py | Legacy paper observer | ACTIVE_TIMER |
| v2_paper_equity_ledger_reconciliation_and_website_truth_repair.py | PnL reconciliation | TIMER |

## Category G — Live Gate (Blocked/DRY_RUN)

| Script | Role | Status |
|--------|------|--------|
| v2_live_canary_executor.py | Live canary executor | DRY_RUN_ONLY |
| v2_live_canary_kill_switch.py | Emergency kill switch | MANUAL_ONLY |
| v2_live_canary_one_order_enablement.py | Canary enablement | BLOCKED |
| v2_live_canary_permission_probe.py | Permission probe | ONE_SHOT |
| v2_binance_live_order_transport_binding_and_first_hour_monitoring.py | Live transport | BLOCKED |
| v2_live_submit_disarm.py | Live disarm | EMERGENCY |
| v2_default_blocked_execution_adapter_stub.py | Blocked stub | ALWAYS_BLOCKED |
| v2_final_live_gate_blocker_burndown_and_operator_enable_packet.py | Gate blocker analysis | ONE_SHOT |
| v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass.py | Live gate single pass | BLOCKED |

## Category H — Analysis & Audit Scripts (One-shot)

| Script | Purpose | Status |
|--------|---------|--------|
| v2_adaptive_capital_productivity_status.py (13,098 lines) | Full capital/leverage/margin audit | ONE_SHOT |
| v2_prediction_signal_quality_audit.py | Signal quality audit | ONE_SHOT |
| v2_expected_move_model_review.py | Expected move review | ONE_SHOT |
| v2_paper_timeframe_churn_governance_audit.py | Churn governance | ONE_SHOT |
| v2_audit_2026_06_19_runtime_validator.py | Runtime validator | ONE_SHOT |
| run_paper_shadow_edge_report.py (1,692 lines) | Paper edge report | ONE_SHOT |
| v2_out_of_sample_reverify_evidence_producer.py | OOS evidence | ONE_SHOT |
| v2_post_hoc_replay_outcome_miner.py | Replay outcome mining | TIMER |
| v2_model_edge_recovery_champion_challenger.py | Champion/challenger | ONE_SHOT |
| v2_production_equivalence_comparator.py | Prod equivalence | ONE_SHOT |
| v2_backtest_runner.py | Backtest run | ONE_SHOT |
| v2_replay_worker.py | Replay run | ONE_SHOT |
| v2_native_edge_proof_evaluator.py | Edge proof | ONE_SHOT |
| zero_miss_atlas_builder.py | Atlas builder | ONE_SHOT |
| export_pipeline_trust_evidence.py | Pipeline trust export | ONE_SHOT |
| verify_pipeline_trust.py | Trust verification | ONE_SHOT |

## Category I — Recovery & Repair Scripts

| Script | Purpose | Status |
|--------|---------|--------|
| v2_market_state_integrity_paper_equity_and_website_realtime_full_repair.py | State repair | ONE_SHOT |
| v2_paper_fill_position_mark_to_market_equity_repair.py | MTM repair | ONE_SHOT |
| v2_paper_equity_ledger_reconciliation_and_website_truth_repair.py | Ledger repair | ONE_SHOT |
| v2_model_state_ai_predictions_signals_runtime_truth_semantic_repair.py | Model state repair | ONE_SHOT |
| run_runtime_alpha_decision_chain_remediation.py | Decision chain fix | ONE_SHOT |
| v2_production_payload_freshness_refresher.py | Payload refresh | ONE_SHOT |
| v2_paper_outcome_memory_rebuild.py | Outcome memory rebuild | ONE_SHOT |

## Category J — Legacy Bridge (Disabled/Stub)

| Script | Purpose | Status |
|--------|---------|--------|
| v2_trainer_bridge.py | Legacy trainer bridge | DISABLED (bridge_exit complete) |
| v2_legacy_ingestor_adapter.py | Legacy ingestor adapter | DISABLED |
| v2_legacy_startup_manifest_parity_and_bridge_exit.py | Bridge exit | COMPLETE |
| v2_native_runtime_bridge_exit_and_dynamic_symbol_migration.py | Runtime bridge exit | COMPLETE |

## Category K — paper_online_runtime.py (Disabled)

| Script | Status | Note |
|--------|--------|------|
| paper_online_runtime.py (3,286 lines) | DISABLED 2026-06-27 | Replaced by v2_trade_management_paper_loop.py |
