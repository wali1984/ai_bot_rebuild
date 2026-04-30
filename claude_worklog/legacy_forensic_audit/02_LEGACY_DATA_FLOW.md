# 02 Legacy Data Flow

## Summary
Observed end-to-end data flow (artifact-backed):
1. Market data ingestion (`ingest/*`).
2. Feature generation (`feature_pipeline`, TA, normalizers).
3. Trainer prediction (`rl/hybrid_trainer.py`, atlas paths).
4. Signal publishing (`signals:trading` evidence in exchange/redis maps).
5. Orchestrator proposal/aggregation (`rl/orchestrator_worker.py`, `rl/tradeplan_orchestrator.py`).
6. Risk/trader execution (`trading/trader.py`, `trading/base_executor.py`).
7. Execution feedback and portfolio/position/PnL update paths.

## Data-flow evidence
- Tier A categories: {'leverage_margin': 25, 'redis_write': 257, 'stops_take_profit': 139, 'exchange_execution': 5332, 'trainer_checkpoint': 500, 'trainer_signal': 723, 'trainer_confidence': 576, 'trainer_reward': 799, 'trainer_feature_state_mass': 611, 'exchange_unresolved_tier_a_review': 1361}
- Exchange map matches: 12439
- Redis map matches: 19401

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
- Medium-High
