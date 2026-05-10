# Safety Critical Gaps

- blocker: redis_memory_pressure_critical_95 (latest snapshot redis_memory.memory_ratio_pct)
- blocker: executed_rows_missing_prediction_id (latest snapshot executed_analysis.missing_prediction_id)
- blocker: executed_rows_missing_feature_snapshot_id (latest snapshot executed_analysis.missing_feature_snapshot_id)
- blocker: executed_rows_incomplete_lineage_tuple (latest snapshot executed_analysis.lineage_tuple_incomplete_rows)
- blocker: duplicate_exchange_order_id_rows_observed (latest snapshot executed_analysis.duplicate_exchange_order_id_rows)
- blocker: stale_executed_timestamps_gt_5m (latest snapshot executed_analysis.stale_executed_ts_ms_gt_5m)
- blocker: trainer_internal_liveness_critical_seen (trainer_metrics.jsonl trainer_internal_liveness_status)
- blocker: prior_post_monitor_no_go (claude_worklog/post_monitor/09_V2_BUILD_GO_NO_GO.md)
- non_blocking_context: phase3a_runtime_monitor_placeholder_not_run (system_atlas_runtime_coverage/latest/runtime_monitor/runtime_monitor_status.json)
