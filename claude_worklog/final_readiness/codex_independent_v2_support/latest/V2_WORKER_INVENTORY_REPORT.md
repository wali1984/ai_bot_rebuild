# V2 Worker Inventory Report

Generated: 2026-05-13T21:18:19Z

Codex classified worker migration coverage without mutating legacy, old Redis, or exchange state.

Live gate: `blocked_human_only`
Workers: 15
Migrated count: 1
Next recommended Claude worker: `market_ingestor`

| Category | Status | Blocker | Next action |
| --- | --- | --- | --- |
| market_ingestor | BLOCKED | missing_runnable_command_test | resolve missing_runnable_command_test |
| coinank_bridge | WRAPPED_READONLY_ONLY | readonly_wrapper_not_independent_runtime | Claude should port coinank_bridge into independent V2 runtime |
| feature_snapshot_builder | BLOCKED | missing_runnable_command | resolve missing_runnable_command |
| trainer_bridge | WRAPPED_READONLY_ONLY | readonly_wrapper_not_independent_runtime | Claude should port trainer_bridge into independent V2 runtime |
| orchestrator_adapter | BLOCKED | missing_runnable_command | resolve missing_runnable_command |
| signal_publisher | BLOCKED | missing_runnable_command | resolve missing_runnable_command |
| risk_gateway_worker | BLOCKED | missing_runnable_command | resolve missing_runnable_command |
| paper_execution_worker | PAPER_ONLY | none | keep paper/shadow evidence fresh; do not promote to live |
| execution_ledger_worker | BLOCKED | missing_runnable_command | resolve missing_runnable_command |
| account_position_monitor | MIGRATED_NOT_RUNNING | none | start or supervise the V2 worker after Claude migration owner confirms |
| replay_worker | BLOCKED | missing_runnable_command | resolve missing_runnable_command |
| script_monitor_worker | BLOCKED | missing_runnable_command | resolve missing_runnable_command |
| config_manager | BLOCKED | missing_runnable_command_test | resolve missing_runnable_command_test |
| admin_ai_backend | BLOCKED | missing_runnable_command_test | resolve missing_runnable_command_test |
| live_execution_stub | BLOCKED | missing_runnable_command | resolve missing_runnable_command |

Backlog-only entries are not counted as migrated. Read-only wrappers are not counted as independent V2 runtime.
