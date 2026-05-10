# Runtime Truth Table

| Check | Pass | Evidence |
| --- | --- | --- |
| monitor_artifacts_present | True | claude_worklog/monitoring/snapshots.jsonl; claude_worklog/monitoring/trainer_metrics.jsonl |
| runtime_duration_ge_12h | True | first/last ts_utc in snapshots.jsonl |
| redis_memory_pressure_non_blocking | False | redis_memory.memory_ratio_pct in snapshots.jsonl |
| trainer_liveness_clean | False | trainer_metrics.jsonl trainer_internal_liveness_status |
| execution_lineage_complete | False | snapshots.jsonl executed_analysis |
| duplicate_exchange_order_id_absent | False | snapshots.jsonl executed_analysis |
| live_gate_blocked | True | Phase 3C generated payload |
