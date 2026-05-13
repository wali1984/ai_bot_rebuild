# Script Migration Truth Report

Generated: 2026-05-13T04:43:38.228869Z

Backlog readiness is not migration completion.

Summary:
- Total script rows: 4195
- Migrated to V2 rows: 1592
- Backlog/not-migrated rows: 2603
- Unsafe unknown rows from backlog: 2093
- Exchange-action script references: 344
- Redis-writer script references: 445
- Active runtime script count: 7

Classification counts:

```json
{
  "unknown_needs_evidence": 1895,
  "v2_namespace_wrapper_exists": 223,
  "monitor_only": 79,
  "backlog_not_migrated": 401,
  "paper_shadow_only": 4,
  "wrapped_readonly_in_v2": 1,
  "migrated_to_v2": 1592
}
```

If most scripts are only `backlog_not_migrated`, `monitor_only`, or `unknown_needs_evidence`, that means migration is incomplete. The backlog is useful evidence, not a production replacement.

First 80 rows are shown below. Full matrix is in `script_migration_truth_matrix.json`.

| Path | Class | Priority | V2 action | Blocker |
| --- | --- | --- | --- | --- |
| .claude/hooks/block_dangerous.sh | unknown_needs_evidence | P0 execution/risk/live safety | rewrite_clean | unknown_requires_evidence |
| claude_worklog/tools/agent_supervisor.py | v2_namespace_wrapper_exists | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/agent_supervisor_dashboard.py | v2_namespace_wrapper_exists | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/autonomous_non_live_rebuild_controller.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/build_automation_liveness_payload.py | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/build_autonomous_live_readiness_builder.py | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/build_legacy_ingestor_inventory.py | monitor_only | P2 ingestors/market data | monitor | none |
| claude_worklog/tools/build_operator_gui_explainability_payload.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/build_phase2_legacy_service_map.py | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/build_system_atlas_runtime_coverage.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/check_autonomous_rebuild_status.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/check_claude_code_quota_status.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/claude_code_quota_guard.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/claude_master_rebuild_planner.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/codex_non_live_watchdog.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/collect_non_live_operational_proof.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/create_codex_parallel_review_batch.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/finalize_claude_design_output.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/historical_pnl_trade_audit.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/launch_agent_supervisor_dashboard.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/launch_runtime_monitor_dashboard.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/legacy_readonly_audit_sentinel.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/migrate_legacy_secrets_local.sh | v2_namespace_wrapper_exists | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/parallel_capacity_scheduler.py | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/phase2_ingestor_copy_hash_inventory.py | monitor_only | P2 ingestors/market data | monitor | none |
| claude_worklog/tools/read_only_monitor.py | monitor_only | P0 execution/risk/live safety | monitor | none |
| claude_worklog/tools/reconcile_evidence_status.py | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/run_autonomous_planner_once.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/run_historical_pnl_trade_audit_once.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/run_legacy_readonly_audit_once.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/run_phase_017_with_watchdog.py | v2_namespace_wrapper_exists | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/runtime_monitor_dashboard.py | v2_namespace_wrapper_exists | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_agent_supervisor_daemon.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_autonomous_agent_supervisor.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_claude_code_quota_guard.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_claude_design_handoff.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_claude_master_rebuild_planner.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_codex_non_live_watchdog.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_historical_pnl_trade_audit_sentinel.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_legacy_readonly_audit_sentinel.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/start_parallel_capacity_scheduler.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_agent_supervisor.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_autonomous_agent_supervisor.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_claude_code_quota_guard.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_claude_master_rebuild_planner.sh | v2_namespace_wrapper_exists | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_codex_non_live_watchdog.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_historical_pnl_trade_audit_sentinel.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_legacy_readonly_audit_sentinel.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/status_parallel_capacity_scheduler.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_agent_supervisor_daemon.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_autonomous_agent_supervisor.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_claude_code_quota_guard.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_claude_master_rebuild_planner.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_codex_non_live_watchdog.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_historical_pnl_trade_audit_sentinel.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_legacy_readonly_audit_sentinel.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| claude_worklog/tools/stop_parallel_capacity_scheduler.sh | monitor_only | P3 monitor/audit/logging | monitor | none |
| legacy_reference/.backups/fix_signals_20251012_191010/hybrid_trainer.py | backlog_not_migrated | P0 execution/risk/live safety | wrap_or_reference_readonly | none |
| legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py | paper_shadow_only | P0 execution/risk/live safety | wrap_or_reference_readonly | none |
| legacy_reference/.backups/fix_signals_20251012_191010/trader.py | backlog_not_migrated | P0 execution/risk/live safety | wrap_or_reference_readonly | none |
| legacy_reference/.backups/fix_signals_20251012_191330/hybrid_trainer.py | backlog_not_migrated | P0 execution/risk/live safety | wrap_or_reference_readonly | none |
| legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py | paper_shadow_only | P0 execution/risk/live safety | wrap_or_reference_readonly | none |
| legacy_reference/.backups/fix_signals_20251012_191330/trader.py | backlog_not_migrated | P0 execution/risk/live safety | wrap_or_reference_readonly | none |
| legacy_reference/.data/live/ADAUSDT_15m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/ADAUSDT_1h.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/ADAUSDT_1m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/ADAUSDT_4h.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/ADAUSDT_5m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/AVAXUSDT_15m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/AVAXUSDT_1h.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/AVAXUSDT_1m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/AVAXUSDT_4h.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/AVAXUSDT_5m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/BTCUSDT_15m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/BTCUSDT_1h.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/BTCUSDT_1m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/BTCUSDT_4h.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/BTCUSDT_5m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/DOGEUSDT_15m.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
| legacy_reference/.data/live/DOGEUSDT_1h.jsonl | unknown_needs_evidence | P5 cleanup/deprecated | review_before_use | unknown_requires_evidence |
