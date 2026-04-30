# 05 Legacy Execution Flow

## Summary
Execution flow mapped from exchange action map and Tier A P0/P1 entries:
- Order creation/cancellation paths present.
- Stop loss / take profit flows present.
- `reduceOnly` and `closePosition` usage present in execution paths.
- Leverage/margin change calls mapped and isolated as high-risk paths.
- Position/balance sync and exchange error handling paths present.

## Evidence metrics
- Exchange class counts: {'exchange_unresolved_tier_a_review': 1361, 'docs_exchange_context': 529, 'exchange_state_accounting': 2713, 'exchange_client_init': 409, 'exchange_config': 221, 'comment_exchange_context': 2959, 'account_query': 189, 'position_query': 236, 'exchange_time_sync': 385, 'exchange_error_handling': 1272, 'test_exchange_context': 1165, 'exchange_symbol_metadata': 53, 'stop_loss': 125, 'take_profit': 32, 'websocket_market_data': 354, 'exchange_context_only': 31, 'market_data': 87, 'order_cancel': 16, 'reduce_only': 118, 'balance_query': 82, 'order_create': 65, 'margin_change': 7, 'leverage_change': 30}
- unknown_exchange_use_after: 0
- blocking_unknown_exchange_use_count: 0

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
