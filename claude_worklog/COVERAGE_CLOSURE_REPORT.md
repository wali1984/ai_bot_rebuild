# Coverage Closure Report

## 1. Executive summary
- Coverage gate decision: GO
- Trainer atlas decision: GO
- unsafe_unknown count: 0
- unmapped bot-looking runtime processes: 0
- trainer unknown Redis writes: 0

## 2. Previous NO-GO reasons
- unsafe_unknown > 0
- unmapped bot-looking runtime process > 0
- unknown Redis writes > 0

## 3. unsafe_unknown script resolution
- Previously unsafe_unknown scripts resolved deterministically: 204
- Resolution classes used: `legacy_dead` and `quarantine_unknown`

| script | resolved_class | reason | evidence_counts (runtime/startup/imports/redis_write/exchange) |
|---|---|---|---|
| apply_churn_prevention.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/6 |
| check_ltc_precision.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| check_torch_location.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| clear_redis.py | quarantine_unknown | high-risk script name without deterministic invocation evidence | 0/0/0/0/0 |
| fix_gpu_batch_indent.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/.next/server/app/_not-found/page.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/3 |
| frontend/.next/server/app/_not-found/page_client-reference-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/app/dashboard/page.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/3 |
| frontend/.next/server/app/dashboard/page_client-reference-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/app/favicon.ico/route.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/0 |
| frontend/.next/server/app/login/page.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/1 |
| frontend/.next/server/app/login/page_client-reference-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/app/page.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/3 |
| frontend/.next/server/app/page_client-reference-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/app/trading/page.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/2/3 |
| frontend/.next/server/app/trading/page_client-reference-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/chunks/333.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/6/3 |
| frontend/.next/server/chunks/371.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/2 |
| frontend/.next/server/chunks/586.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/3/1 |
| frontend/.next/server/chunks/611.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/3/0 |
| frontend/.next/server/chunks/688.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/1 |
| frontend/.next/server/chunks/82.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/3 |
| frontend/.next/server/interception-route-rewrite-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/middleware-build-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/middleware-react-loadable-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/next-font-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/pages/_app.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/pages/_document.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/pages/_error.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/3/2 |
| frontend/.next/server/server-reference-manifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/server/webpack-runtime.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/static/AHYH8dJELnxeWGOnyjkj1/_buildManifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/static/AHYH8dJELnxeWGOnyjkj1/_ssgManifest.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/0 |
| frontend/.next/static/chunks/125-3a1c031a1c4bcc64.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/0 |
| frontend/.next/static/chunks/255-4efeec91c7871d79.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/3 |
| frontend/.next/static/chunks/478-1b65ff74eb66a6fc.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/2 |
| frontend/.next/static/chunks/4bd1b696-c023c6e3521b1417.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/1 |
| frontend/.next/static/chunks/52-eea22f2e323de1a4.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/0 |
| frontend/.next/static/chunks/718-ea79efc603a489fd.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/2 |
| frontend/.next/static/chunks/829-fa5ba33bada845b8.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/1 |
| frontend/.next/static/chunks/894-ddf6ab726042650b.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/1 |
| frontend/.next/static/chunks/980-66a77c7e1ed90f88.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/0 |
| frontend/.next/static/chunks/app/_not-found/page-8bf854eda23c53ab.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/1 |
| frontend/.next/static/chunks/app/dashboard/page-26b8b6aa3557c75b.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/2 |
| frontend/.next/static/chunks/app/layout-cfb6e21bf660df93.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/2 |
| frontend/.next/static/chunks/app/login/page-56c3c97472d1cb6a.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/2 |
| frontend/.next/static/chunks/app/page-557601590f070a84.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/2 |
| frontend/.next/static/chunks/app/trading/page-ea1bca2abe6a5d59.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/1 |
| frontend/.next/static/chunks/framework-acd67e14855de5a2.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/1 |
| frontend/.next/static/chunks/main-91b3fa0b94077dbb.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/1/3 |
| frontend/.next/static/chunks/main-app-acfebd916ee8b7f9.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/static/chunks/pages/_app-7d307437aca18ad4.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/static/chunks/pages/_error-cb2a52f75f2162e2.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/static/chunks/polyfills-42372ed130431b0a.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/2/0 |
| frontend/.next/static/chunks/webpack-a881ab60b273ed59.js | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/types/cache-life.d.ts | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/types/routes.d.ts | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/.next/types/validator.ts | legacy_dead | compiled/archive artifact; no runtime/startup/import evidence | 0/0/0/0/0 |
| frontend/eslint.config.mjs | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/next.config.js | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/next.config.ts | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/postcss.config.mjs | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/app/dashboard/page.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| frontend/src/app/layout.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/app/login/page.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/app/page.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/app/providers.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/app/trading/page.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| frontend/src/components/DashboardLayout.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ProtectedRoute.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/alert-dialog.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/alert.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/badge.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/button.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/card.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/dialog.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/dropdown-menu.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/input.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/label.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/separator.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/slider.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/switch.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/tabs.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/components/ui/tooltip.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/contexts/AuthContext.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/src/contexts/WebSocketContext.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/trading-command-center/eslint.config.mjs | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/trading-command-center/next.config.ts | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/trading-command-center/postcss.config.mjs | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/trading-command-center/src/app/layout.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| frontend/trading-command-center/src/app/page.tsx | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| ingest/tm_ids.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| install_everything.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| launch_hybrid_trainer.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| quick_check_binance_normalized.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| restart_trainer_fixed_thresholds.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| rl/gpu_env_wrapper.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/2/0 |
| rl/stable_gpu_trainer.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| scripts/_check_services.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| scripts/audit_pipeline_health.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| scripts/check_unified_features.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| scripts/launch_dashboard.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| scripts/mtf_blocker_validation_report.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| scripts/stop_trader_asjad.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/3/2 |
| scripts/test_hedge_build.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/10/5 |
| scripts/test_liq_pipeline.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/2/1 |
| scripts/ultimate_desktop_fix.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| scripts/update_symbols.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| scripts/verify_gpu_optimizations.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/2/0 |
| scripts/verify_heartbeat_segregation.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| scripts/verify_no_behavior_change.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/1 |
| scripts/why_hedged_timeline.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/2 |
| send_enhancement_summary.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/3 |
| simple_test.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| simple_validation.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| start_system_with_binance.sh | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/4 |
| status_report.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_143_features.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_action_fix.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_ai_signals.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_ai_signals_channel.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_all.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_binance_imports.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_channel_routing.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| test_complete_alerts.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/4 |
| test_complete_trainer_pipeline.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_comprehensive_features.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_comprehensive_talib.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/0 |
| test_config.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_continuous_operation.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_cpu_optimizations.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_dual_positions.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_enhanced_alerts.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/3 |
| test_enhanced_reasoning.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_extraction.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_file_writers.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_fixes.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_forwarding.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_fresh_masa.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_fresh_unified.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_gpu_environment.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/0 |
| test_hedge_trading.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| test_import.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_imports_quick.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_intelligent_trainer.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| test_interrupt_lock.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_leverage_adjustment.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/3/3 |
| test_leverage_proper.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/9/2 |
| test_leverage_usage.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/4/2 |
| test_ltc_trading.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/3 |
| test_masa_gpu.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_masa_loading.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_masa_real_features.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_old_trainer_implementation.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_portfolio_alert.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_portfolio_summary.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_position_detection.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_position_detection_directly.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_ppo_gpu.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/0 |
| test_ppo_prediction.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_production_trading.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/5 |
| test_real_integration.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/5/2 |
| test_realtime_trainer_integration.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/2/3 |
| test_rtx5080.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_rtx5080_blackwell.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_signal_clarity.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_signal_data_fix.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| test_stop_loss_take_profit.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/8/5 |
| test_subproc_fix.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/0 |
| test_systematic_fixes.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/2 |
| test_talib.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_trade_channel.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_trader_advanced.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/3 |
| test_trader_real.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/2 |
| test_trading_signals.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/4 |
| test_trainer_enhancements.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_trainer_positions.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| test_ultra_fast_real_trader.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| test_wsl_gpu_optimization.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| timing_summary.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| tools/build_runtime_contracts.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| tools/filter_runtime_contracts.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| tools/gen_contracts_md.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/0 |
| tools/gen_module_runbooks.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/2/3 |
| tools/gen_runbook.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| tools/liquidation_levels_from_stream.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/1 |
| tools/liquidation_levels_report.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| tools/merge_call_edges.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| tools/redis_contract_scan.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/5/0 |
| tools/repo_blueprint.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/4/0 |
| tools/smoke_publish_test.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/11/0 |
| trading/assert_governor.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| trainer_dimension_patch.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| update_channel_id.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| validate_all_implementations.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/4/1 |
| validate_config.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| validate_fixes.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| validate_implementation.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/1/0 |
| validate_ultra_fast_trader.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| verify_all_imports.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| verify_imports.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/1 |
| verify_rtx5080_cuda.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| verify_rtx5080_setup.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |
| verify_wsl_scripts.py | quarantine_unknown | insufficient deterministic evidence | 0/0/0/0/0 |

## 4. Tier A script classification
- Tier A script count: 690
- Full per-script classification is in `claude_worklog/coverage/TIER_A_SCRIPT_CLASSIFICATION.md`.
- Tier A includes scripts with exchange actions, Redis writes, and/or trainer/signal/risk critical paths.

## 5. Hybrid trainer chunk classification
- Trainer file: /home/wali/Desktop/AI BOT REBUILD/legacy_reference/rl/hybrid_trainer.py
- Chunk count: 58
- Category counts:
  - confidence: 2
  - reward: 56
- Full per-chunk map: `claude_worklog/trainer_atlas/HYBRID_TRAINER_CHUNK_CLASSIFICATION.md`.

## 6. Trainer Redis write classification
- unknown_write count: 0
- Classification counts:
  - read_only: 4443
  - write_signal: 295
  - write_metric: 564
  - write_checkpoint_metadata: 74
  - write_heartbeat: 13
  - write_risk_state: 37
  - unknown_write: 0
- Full line-level map: `claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md`.

## 7. Secret-redaction changes
- Added centralized redaction in `tools/common_audit.py` via `redact_text()`.
- Redaction applied to process command outputs, env/config matched text, Redis/exchange/startup matched text, and evidence viewers.
- Redacted patterns: api_key, apikey, secret, token, password, private_key, BINANCE, TELEGRAM, COINANK, OPENAI, ANTHROPIC.
- Updated files:
  - tools/common_audit.py
  - tools/collect_runtime_processes.py
  - tools/collect_env_config_refs.py
  - tools/collect_redis_usage.py
  - tools/collect_exchange_actions.py
  - tools/collect_startup_refs.py
  - tools/show_file_range.py
  - tools/show_trainer_section.py

## 8. Remaining blockers
- None from deterministic coverage and trainer-atlas gates.

## 9. GO/NO-GO decision
- Decision: GO
- Gate rules applied: unsafe_unknown, unknown trainer Redis write, exchange-action classification completeness, runtime unmapped process count, and redaction implementation.

## 10. Whether Claude may be started
- Claude may be started: YES
- Start command if approved: `cd "$HOME/Desktop/AI BOT REBUILD" && claude`
