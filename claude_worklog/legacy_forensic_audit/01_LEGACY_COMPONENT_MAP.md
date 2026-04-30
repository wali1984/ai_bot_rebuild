# 01 Legacy Component Map

## Summary
- Script registry entries: 957.
- Runtime mapped processes: 48.
- Startup references: 34925.
- Core components mapped from script/path evidence (counts):
  - ingestors: 26
  - feature pipeline: 16
  - trainer: 69
  - orchestrator: 7
  - signal router: 5
  - trader(s): 5
  - portfolio monitors: 3
  - watchdogs: 3
  - exchange wrappers: 20
  - dashboard/monitor scripts: 52
  - startup/control scripts: 200

## Component evidence samples
- Ingestors: ingest/alphavantage_client.py, ingest/alphavantage_normalizer.py, ingest/base_ingestor.py, ingest/ccxt_backfill.py, ingest/ccxt_historical.py, ingest/cdd_enhanced_slow.py, ingest/cdd_historical.py, ingest/cdd_to_jsonl.py
- Trainer: .backups/fix_signals_20251012_191010/hybrid_trainer.py, .backups/fix_signals_20251012_191330/hybrid_trainer.py, analyze_eth_trainer_data.py, check_trainer_status.py, debug_and_restart_trainer.py, debug_trainer_positions.py
- Orchestrator: Documentation/Audits/scripts/monitor_orchestrator.py, rl/orchestrator_worker.py, rl/tradeplan_orchestrator.py, scripts/audit_orchestrator_last30m.py, scripts/monitor_orchestrator_shadow.py, tests/test_orchestrator_hedge_stress.py
- Traders: trading/base_executor.py, trading/stealth_stops.py, trading/trader-asjad.py, trading/trader.py, trading/trader_websocket_helper.py
- Startup/control: Documentation/Audits/scripts/audit_012426_session_changes.py, Documentation/Audits/scripts/comprehensive_system_audit.py, Documentation/Audits/scripts/critical_health_monitor.py, Documentation/Audits/scripts/drift_guard_monitor.py, Documentation/Audits/scripts/monitor_orchestrator.py, Documentation/Audits/scripts/run_full_e2e_validation.py

## Raw evidence pointers
- claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md

## Source artifacts used
- claude_worklog/coverage/FILE_MANIFEST.json
- claude_worklog/coverage/SCRIPT_REGISTRY.json
- claude_worklog/coverage/SCRIPT_DEPENDENCY_GRAPH.json
- claude_worklog/coverage/STARTUP_PATH_MAP.json
- claude_worklog/coverage/RUNTIME_PROCESS_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/CONFIG_ENV_MAP.json

## Verification commands
- python3 tools/show_file_range.py --file "./legacy_reference/rl/hybrid_trainer.py" --start 1 --end 80
- python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 30000 --end 30120
- python3 tools/codex_adversarial_coverage_check.py

## Unresolved questions
- Which Tier A unresolved items need code-owner adjudication before production deprecation mapping?
- Which legacy scripts are wrappers only and can be archived in V2 migration phase?

## Confidence level
- High
