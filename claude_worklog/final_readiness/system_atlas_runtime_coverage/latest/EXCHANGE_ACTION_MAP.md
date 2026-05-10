# Exchange Action Map

| file | action_type | risk_class | callable_in_v2 | blocked_or_fail_closed |
| --- | --- | --- | --- | --- |
| .claude/hooks/block_dangerous.sh | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| .claude/hooks/block_dangerous.sh | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| .claude/hooks/block_dangerous.sh | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| .claude/hooks/block_dangerous.sh | change_margin | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| .claude/hooks/block_dangerous.sh | change_margin_type | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| .claude/hooks/block_dangerous.sh | change_position_mode | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/autonomous_non_live_rebuild_controller.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/autonomous_non_live_rebuild_controller.py | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/autonomous_non_live_rebuild_controller.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/autonomous_non_live_rebuild_controller.py | change_margin | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_operator_gui_explainability_payload.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_operator_gui_explainability_payload.py | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | change_margin | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | change_margin_type | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | change_position_mode | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | close_position | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | reduce_only | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | stop_market | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | rebalance | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | ADJUST_LEVERAGE | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | ADJUST_LEVERAGE_AND_POSITION | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/claude_master_rebuild_planner.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/claude_master_rebuild_planner.py | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/claude_master_rebuild_planner.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/claude_master_rebuild_planner.py | change_margin | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/codex_non_live_watchdog.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/codex_non_live_watchdog.py | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/codex_non_live_watchdog.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/codex_non_live_watchdog.py | change_margin | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/collect_non_live_operational_proof.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/collect_non_live_operational_proof.py | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/collect_non_live_operational_proof.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/collect_non_live_operational_proof.py | change_margin | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/create_codex_parallel_review_batch.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/historical_pnl_trade_audit.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/legacy_readonly_audit_sentinel.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| claude_worklog/tools/read_only_monitor.py | ADJUST_LEVERAGE | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/hybrid_trainer.py | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py | ADJUST_LEVERAGE | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | change_position_mode | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | stop_market | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/hybrid_trainer.py | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py | ADJUST_LEVERAGE | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | change_position_mode | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | stop_market | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.logs/dashboard.log | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.ta-lib/src/tools/ta_regtest/ta_regtest.c | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.ta-lib/src/tools/ta_regtest/test_abstract.c | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/.ta-lib/src/tools/ta_regtest/test_util.c | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/ADAPTIVE_TRADING_COMPLETE.md | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/ADD_REMAINING_FEATURES.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/BINANCE_IMPLEMENTATION_COMPLETE.md | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/BINANCE_IMPLEMENTATION_COMPLETE.md | change_margin | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/BINANCE_IMPLEMENTATION_COMPLETE.md | change_margin_type | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/BINANCE_IMPLEMENTATION_COMPLETE.md | stop_market | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/BINANCE_IMPLEMENTATION_COMPLETE.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/BINANCE_IMPLEMENTATION_COMPLETE.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Audits/scripts/audit_012426_session_changes.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Audits/scripts/comprehensive_system_audit.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Audits/scripts/comprehensive_system_audit.py | rebalance | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Audits/scripts/critical_health_monitor.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Audits/scripts/drift_guard_monitor.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Audits/scripts/monitor_orchestrator.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Final Enhancements completion.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/GPT DEEP Implementation guide.md | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Hybrid Trainer Discovery.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Implementation2.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/OPERATOR_RUNBOOK.md | close_position | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/OPERATOR_RUNBOOK.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Runbook Fixing System Issues and Preparing for Live Deployment.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Trainer Enahancement Plan2.md | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Trainer Enhancement Plan.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Trainer Enhancement Plan1.md | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/Trainer audit.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live2.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live2.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live2.md | rebalance | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live3.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live3.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/live5.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/runbook3.md | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/trainer-log.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/wma ai bot 1.md | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/wma ai bot 1.md | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Documentation/wma ai bot 1.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/INTEGRATION_COMPLETE_SCRIPT.sh | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/LATENCY_OPTIMIZATIONS.md | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Public Dashboard/api.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/Public Dashboard/api.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/QUICK_START_INTEGRATION.sh | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/System Runbook.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/api/routes/config_routes.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/api/routes/frontend_routes.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/api/routes/trading_routes.py | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/api/routes/trading_routes.py | cancel_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/api/routes/trading_routes.py | change_leverage | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/api/routes/trading_routes.py | close_position | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/api/routes/trading_routes.py | stop_market | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/apply_churn_prevention.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/apply_churn_prevention.py | rebalance | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/apply_immediate_fixes.sh | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/apply_qa_fixes.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/archive/hybrid_trainer.bkp | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/archive/hybrid_trainer.py.backup.20251015_001011 | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/archive/hybrid_trainer.py.backup.20251015_001535 | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/archive/hybrid_trainer.py.backup_20251012_233111 | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/comprehensive_validation_analysis.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/comprehensive_validation_analysis.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/comprehensive_validation_analysis.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/config.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/config.py | dca | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/config.py | rebalance | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/config_accounts.py | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/config_accounts.py | trailing_stop | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/dashboard/api.py | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/Final Enhancements completion.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/GPT DEEP Implementation guide.md | create_order | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/Hybrid Trainer Discovery.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/Implementation2.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Discovery.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Final Trainer Prompts.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Final Trainer guide 13.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Final Trainer guide 7.md | change_position_mode | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Final Trainer guide 7.md | reduce_only | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Final Trainer guide 7.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Final enhancements.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Final trainer guide.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/GUARD.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/PRODUCTION_DEPLOYMENT_GUIDE.md | take_profit | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/PRODUCTION_DEPLOYMENT_GUIDE.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/Trainer Guide.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/copilot-instructions.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/dash 3.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/dash 5.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |
| legacy_reference/docs/OLD/trainer-log.md | hedge | TIER_A_EXCHANGE_ACTION | False | forbidden_by_policy_or_requires_raw_review |

Showing 160 of 583 rows. Full data is in JSON.
