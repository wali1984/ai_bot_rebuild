# Redis Writer Path Resolution

Generated: 2026-05-10T03:28:53.332163+00:00

| path | phase3b_classification | redis_writes | unresolved |
| --- | --- | --- | --- |
| .claude/hooks/block_dangerous.sh | fail_closed_forbidden_path | ['xdel', 'xtrim', 'flushall', 'flushdb'] | False |
| claude_worklog/tools/agent_supervisor.py | docs_test_comment_only | ['xadd', 'xdel', 'flushall', 'flushdb'] | False |
| claude_worklog/tools/agent_supervisor_dashboard.py | docs_test_comment_only | ['set('] | False |
| claude_worklog/tools/autonomous_non_live_rebuild_controller.py | docs_test_comment_only | ['xadd', 'set(', 'xdel', 'flushall', 'flushdb'] | False |
| claude_worklog/tools/build_operator_gui_explainability_payload.py | docs_test_comment_only | ['set('] | False |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | docs_test_comment_only | ['xadd', 'set(', 'hset', 'delete(', 'xdel', 'xtrim', 'flushall', 'flushdb', 'redis-cli set', 'redis-cli xadd'] | False |
| claude_worklog/tools/claude_master_rebuild_planner.py | docs_test_comment_only | ['xadd', 'xdel', 'flushall', 'flushdb'] | False |
| claude_worklog/tools/codex_non_live_watchdog.py | docs_test_comment_only | ['xadd', 'xdel', 'flushall', 'flushdb'] | False |
| claude_worklog/tools/collect_non_live_operational_proof.py | docs_test_comment_only | ['xadd', 'xdel', 'flushall', 'flushdb'] | False |
| claude_worklog/tools/historical_pnl_trade_audit.py | docs_test_comment_only | ['set('] | False |
| claude_worklog/tools/migrate_legacy_secrets_local.sh | docs_test_comment_only | ['set('] | False |
| claude_worklog/tools/read_only_monitor.py | docs_test_comment_only | ['set('] | False |
| claude_worklog/tools/run_phase_017_with_watchdog.py | docs_test_comment_only | ['set('] | False |
| claude_worklog/tools/runtime_monitor_dashboard.py | docs_test_comment_only | ['xadd', 'hset'] | False |
| claude_worklog/tools/status_claude_master_rebuild_planner.sh | docs_test_comment_only | ['set('] | False |
| legacy_reference/.backups/fix_signals_20251012_191010/hybrid_trainer.py | legacy_writer | ['set('] | False |
| legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py | legacy_writer | ['set(', 'hset', 'delete('] | False |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | legacy_writer | ['set(', 'hset', 'delete('] | False |
| legacy_reference/.backups/fix_signals_20251012_191330/hybrid_trainer.py | legacy_writer | ['set('] | False |
| legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py | legacy_writer | ['set(', 'hset', 'delete('] | False |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | legacy_writer | ['set(', 'hset', 'delete('] | False |
| legacy_reference/.ta-lib/autom4te.cache/traces.1 | legacy_writer | ['set('] | False |
| legacy_reference/.ta-lib/include/ta_defs.h | legacy_writer | ['set('] | False |
| legacy_reference/.ta-lib/src/ta_abstract/ta_abstract.c | legacy_writer | ['set('] | False |
| legacy_reference/.ta-lib/src/ta_common/ta_global.c | legacy_writer | ['set('] | False |
| legacy_reference/.ta-lib/src/tools/gen_code/gen_code.c | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/.ta-lib/src/tools/ta_regtest/test_internals.c | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/Audits/scripts/audit_012426_session_changes.py | legacy_writer | ['set('] | False |
| legacy_reference/Documentation/Audits/scripts/critical_health_monitor.py | legacy_writer | ['set('] | False |
| legacy_reference/Documentation/Final Enhancements completion.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/GPT DEEP Implementation guide.md | docs_test_comment_only | ['redis-cli set'] | False |
| legacy_reference/Documentation/Implementation_Plan.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/OPERATOR_RUNBOOK.md | docs_test_comment_only | ['redis-cli set'] | False |
| legacy_reference/Documentation/Runbook1.md | docs_test_comment_only | ['xadd', 'hset'] | False |
| legacy_reference/Documentation/Runkbook0.md | docs_test_comment_only | ['xadd', 'set(', 'hset'] | False |
| legacy_reference/Documentation/Trainer audit.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/live1.md | docs_test_comment_only | ['set(', 'hset'] | False |
| legacy_reference/Documentation/live2.md | docs_test_comment_only | ['set(', 'hset', 'delete('] | False |
| legacy_reference/Documentation/live4.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/live5.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/trainer enh.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/trainer-log.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/Documentation/wma ai bot 1.md | docs_test_comment_only | ['xadd'] | False |
| legacy_reference/IMPLEMENT_ALL_FEATURES.py | legacy_writer | ['set('] | False |
| legacy_reference/MONITORING_GUIDE.md | docs_test_comment_only | ['flushdb'] | False |
| legacy_reference/README.md | docs_test_comment_only | ['set(', 'hset'] | False |
| legacy_reference/System Runbook.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/all_data_extractor.py | legacy_writer | ['set('] | False |
| legacy_reference/analyze_comprehensive_features.py | legacy_writer | ['set('] | False |
| legacy_reference/analyze_current_signals.py | legacy_writer | ['set('] | False |
| legacy_reference/api/auth.py | legacy_writer | ['set('] | False |
| legacy_reference/api/routes/config_routes.py | legacy_writer | ['set('] | False |
| legacy_reference/api/routes/redis_routes.py | legacy_writer | ['xadd', 'delete('] | False |
| legacy_reference/archive/hybrid_trainer.bkp | legacy_writer | ['set('] | False |
| legacy_reference/archive/hybrid_trainer.py.backup.20251015_001011 | legacy_writer | ['set('] | False |
| legacy_reference/archive/hybrid_trainer.py.backup.20251015_001535 | legacy_writer | ['set('] | False |
| legacy_reference/archive/hybrid_trainer.py.backup_20251012_233111 | legacy_writer | ['set('] | False |
| legacy_reference/audit_binance_last_48h.py | legacy_writer | ['set('] | False |
| legacy_reference/binance_websocket.py | legacy_writer | ['set('] | False |
| legacy_reference/check_unified_features.py | legacy_writer | ['set('] | False |
| legacy_reference/circuit_breaker.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/cleanup_coinank_keys.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/clear_redis.py | legacy_writer | ['flushall'] | False |
| legacy_reference/comprehensive_feature_extractor.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/comprehensive_system_validation.py | legacy_writer | ['set('] | False |
| legacy_reference/config.py | legacy_writer | ['redis-cli set'] | False |
| legacy_reference/debug_current_positions.py | legacy_writer | ['set('] | False |
| legacy_reference/debug_ppo_pipeline.py | legacy_writer | ['set('] | False |
| legacy_reference/deploy_qa_fixed.sh | legacy_writer | ['flushdb'] | False |
| legacy_reference/diagnose_high_confidence_no_trades.py | legacy_writer | ['set('] | False |
| legacy_reference/diagnose_redis.py | legacy_writer | ['delete('] | False |
| legacy_reference/docs/Final Enhancements completion.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/GPT DEEP Implementation guide.md | docs_test_comment_only | ['redis-cli set'] | False |
| legacy_reference/docs/Implementation_Plan.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/Final Trainer Guide 8.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/Final Trainer guide 13.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/Final trainer guide 1.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/Final trainer guide 2.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/Final trainer pytest fix.md | docs_test_comment_only | ['redis-cli set'] | False |
| legacy_reference/docs/OLD/PRODUCTION_DEPLOYMENT_GUIDE.md | docs_test_comment_only | ['set(', 'flushdb', 'redis-cli set'] | False |
| legacy_reference/docs/OLD/Phase-11.md | docs_test_comment_only | ['delete('] | False |
| legacy_reference/docs/OLD/copilot 12.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/copilot 13.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/copilot 14.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/copilot 8.md | docs_test_comment_only | ['delete('] | False |
| legacy_reference/docs/OLD/copilot 9.md | docs_test_comment_only | ['set(', 'delete('] | False |
| legacy_reference/docs/OLD/copilot-instructions.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/dash 4.md | docs_test_comment_only | ['set(', 'delete('] | False |
| legacy_reference/docs/OLD/phase11.1.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/OLD/unit test.md | docs_test_comment_only | ['hset', 'redis-cli set'] | False |
| legacy_reference/docs/OPERATOR_RUNBOOK.md | docs_test_comment_only | ['redis-cli set'] | False |
| legacy_reference/docs/Runbook1.md | docs_test_comment_only | ['xadd', 'hset'] | False |
| legacy_reference/docs/Runkbook0.md | docs_test_comment_only | ['xadd', 'set(', 'hset'] | False |
| legacy_reference/docs/Trainer audit.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/live1.md | docs_test_comment_only | ['set(', 'hset'] | False |
| legacy_reference/docs/live2.md | docs_test_comment_only | ['set(', 'hset', 'delete('] | False |
| legacy_reference/docs/live4.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/live5.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/trainer enh.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/trainer-log.md | docs_test_comment_only | ['set('] | False |
| legacy_reference/docs/wma ai bot 1.md | docs_test_comment_only | ['xadd'] | False |
| legacy_reference/emergency_brake.py | legacy_writer | ['flushdb'] | False |
| legacy_reference/enhanced_startup.py | legacy_writer | ['set('] | False |
| legacy_reference/extract_all_feature_keys.py | legacy_writer | ['set('] | False |
| legacy_reference/feature_pipeline.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/final_system_validation.py | legacy_writer | ['xadd', 'delete('] | False |
| legacy_reference/final_test_signal.py | docs_test_comment_only | ['xadd'] | False |
| legacy_reference/final_validation.py | legacy_writer | ['set('] | False |
| legacy_reference/fix_feature_pipeline_performance.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/fix_trainer_comprehensive.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/ingest/base_ingestor.py | legacy_writer | ['set('] | False |
| legacy_reference/ingest/ccxt_backfill.py | legacy_writer | ['set('] | False |
| legacy_reference/ingest/ccxt_historical.py | legacy_writer | ['set('] | False |
| legacy_reference/ingest/cdd_historical.py | legacy_writer | ['set('] | False |
| legacy_reference/ingest/liquidation_bridge.py | legacy_writer | ['xadd', 'set('] | False |
| legacy_reference/ingest/liquidation_levels_engine.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/liquidation_levels_engine.py.bak.v1 | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/live_alphavantage_news.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/live_binance.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/live_binance_liquidations.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/ingest/live_ccxt.py | legacy_writer | ['set(', 'hset', 'delete('] | False |
| legacy_reference/ingest/live_coinank.py | legacy_writer | ['xadd', 'set(', 'hset'] | False |
| legacy_reference/ingest/live_coinank_global_aggregator.py | legacy_writer | ['set('] | False |
| legacy_reference/ingest/live_coinapi_rest.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/live_coinapi_v1.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/live_coinapi_wsds.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/live_kucoin.py | legacy_writer | ['set('] | False |
| legacy_reference/ingest/live_tokenmetrics.py | legacy_writer | ['set(', 'hset', 'delete('] | False |
| legacy_reference/ingest/load_historical.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/realtime_price_provider.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/ingest/technical_analysis.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/investigate_telegram_alerts.py | legacy_writer | ['xadd'] | False |
| legacy_reference/ltc_trading_test.py | legacy_writer | ['xadd'] | False |
| legacy_reference/monitor_portfolio_asjad.py | legacy_writer | ['set('] | False |
| legacy_reference/monitor_portfolio_primary.py | legacy_writer | ['set('] | False |
| legacy_reference/monitor_system_memory.py | legacy_writer | ['set('] | False |
| legacy_reference/monitor_trainer_signals.py | legacy_writer | ['set('] | False |
| legacy_reference/monitoring/live_system_auditor.py | legacy_writer | ['set('] | False |
| legacy_reference/ohlcv_resampler_hotfix.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/open_test_position.py | docs_test_comment_only | ['xadd'] | False |
| legacy_reference/optimization_quickstart.sh | legacy_writer | ['hset'] | False |
| legacy_reference/quick_validate.py | legacy_writer | ['xadd'] | False |
| legacy_reference/reset_circuit_breaker.py | legacy_writer | ['delete('] | False |
| legacy_reference/risk/assertions.py | legacy_writer | ['set('] | False |
| legacy_reference/risk/auto_deleverager.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/risk/global_breadth.py | legacy_writer | ['set('] | False |
| legacy_reference/risk/halt_manager.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/risk/hedge_cage_manager.py | legacy_writer | ['delete('] | False |
| legacy_reference/risk/kill_switch.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/risk/margin_governor.py | legacy_writer | ['set('] | False |
| legacy_reference/risk/phase_controller.py | legacy_writer | ['set('] | False |
| legacy_reference/risk/reduce_only_latch.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/risk/risk_state_machine.py | legacy_writer | ['set('] | False |
| legacy_reference/risk/shared_risk_gate.py | legacy_writer | ['set('] | False |
| legacy_reference/risk/trainer_intent.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/batch_utils.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/calibrated_confidence.py | legacy_writer | ['xadd', 'set(', 'hset'] | False |
| legacy_reference/rl/coinapi_symbol_map.py | legacy_writer | ['set(', 'hset', 'delete('] | False |
| legacy_reference/rl/confidence_logger.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/cpu_env.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/decision_trace.py | legacy_writer | ['xadd'] | False |
| legacy_reference/rl/drift_monitor.py | legacy_writer | ['xadd'] | False |
| legacy_reference/rl/dynamic_runner_hedge.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/enhanced_architectures.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/environment.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/execution_overlay.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/gpu_batch_env.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/gpu_env_wrapper.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/gpu_environment.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/gymnasium_wrapper.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/hedge_manager_v3.py | legacy_writer | ['set(', 'delete('] | False |
| legacy_reference/rl/hedge_position_manager.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/hedge_rule_engine.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/historical_csv_loader.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/historical_data_loader.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/historical_data_manager.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/hybrid_trainer.py.backup_indent_fix | legacy_writer | ['xadd'] | False |
| legacy_reference/rl/ingestor_quality_router.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/light_vec_env.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/light_worker.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/liquidation_prevention.py | legacy_writer | ['xadd', 'delete('] | False |
| legacy_reference/rl/market_context.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/masa_supervised_pretrainer.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/metrics_tracker.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/microstructure_aggregator.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/microstructure_features.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/microstructure_overlay.py | legacy_writer | ['xadd', 'set('] | False |
| legacy_reference/rl/old-trainer.md | docs_test_comment_only | ['xadd', 'set(', 'hset'] | False |
| legacy_reference/rl/orchestrator_worker.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/portfolio_policy_manager.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/portfolio_recovery_allocator.py | legacy_writer | ['xadd'] | False |
| legacy_reference/rl/position_monitor.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/profit_bank.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/promotion_controller.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/proposal_bus.py | legacy_writer | ['xadd', 'set('] | False |
| legacy_reference/rl/proposal_hedge_preflight.py | legacy_writer | ['xadd'] | False |
| legacy_reference/rl/proposal_schema.py | legacy_writer | ['xadd'] | False |
| legacy_reference/rl/scripts/backfill_predictions_stub.py | legacy_writer | ['set(', 'hset'] | False |
| legacy_reference/rl/supervised_trainer.py | legacy_writer | ['set('] | False |
| legacy_reference/rl/target_exposure_controller.py | legacy_writer | ['xadd', 'set('] | False |

Showing 200 of 445 rows. Full data is in JSON.
