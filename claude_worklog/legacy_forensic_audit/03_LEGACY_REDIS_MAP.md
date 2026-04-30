# 03 Legacy Redis Map

## Summary
- Redis writer files: 131
- Redis reader files (derived): 273
- Redis unknown usage matches: 16560
- Tier A redis_write entries: 257

## Redis writers/readers
- Top writer files (sample): .backups/fix_signals_20251012_191010/hybrid_trainer.py, .backups/fix_signals_20251012_191010/paper_trader.py, .backups/fix_signals_20251012_191010/trader.py, .backups/fix_signals_20251012_191330/hybrid_trainer.py, .backups/fix_signals_20251012_191330/paper_trader.py, .backups/fix_signals_20251012_191330/trader.py, COINANK_FIX_COMPLETE.md, COINAPI_INTEGRATION.md, COMPLETE_TRAINING_PIPELINE_DOCS.md, COMPREHENSIVE_AUDIT_COMPARISON_REPORT.md, COMPREHENSIVE_DATA_FIX.md, CRITICAL_ARCHITECTURE_DISCOVERY.md, Docs/cursor/Session summary.md, Documentation/02/02/2nd_feb.md, Documentation/AUDIT_PUBLISH_CONTRACT.md, Documentation/COMPREHENSIVE_SYSTEM_AUDIT_REPORT.md, Documentation/DATA_FLOW_ANALYSIS.md, Documentation/FASTLANE_FINAL_IMPLEMENTATION.md, Documentation/FASTLANE_INTEGRATION_PATCH.md, Documentation/Final Enhancements completion.md
- Top reader files (sample): .backups/fix_signals_20251012_191010/hybrid_trainer.py, .backups/fix_signals_20251012_191330/hybrid_trainer.py, AUDIT_FIXES_RED_AMBER.md, Audit-Jan21.md, BINANCE_IMPORT_FIX.md, CIRCUIT_BREAKER_TRIPPED_ANALYSIS.md, COINANK_DATA_FLOW_AUDIT.md, COMPLETE_DATA_ARCHITECTURE.md, COMPLETE_SYSTEM_DOCUMENTATION.md, COMPLETE_SYSTEM_STATUS_REPORT.md, COMPLETE_TRAINING_PIPELINE_DOCS.md, DASHBOARD_METRICS_COMPLETE.md, DUAL_LANE_STRATEGY.md, Docs/cursor/2026-03-01_session_1_6c54c929.md, Docs/cursor/2026-03-01_session_2_ab7afe9d.md, Docs/cursor/2026-03-04_session_5_acaea88c.md, Documentation/AUDIT_INSTRUCTIONS_PHASE_2_7.md, Documentation/AUDIT_REDIS_IO_KEYS.md, Documentation/Audits/scripts/03042026.md, Documentation/Audits/scripts/audit_012426_session_changes.py

## Legacy keys/streams V2 must never write
- `signals:trading` and account-scoped trading streams
- `positions:*` namespaces
- `portfolio:*` namespaces
- `wma:trainer:*` and `wma:trader:*` namespaces
- Heartbeat/status keys owned by legacy services

## Unknown Redis usage requiring Tier A review
- Count from redis map `redis_unknown`: 16560
- Action: retain in Tier A adjudication queue; no automatic assumptions.

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
- Medium
