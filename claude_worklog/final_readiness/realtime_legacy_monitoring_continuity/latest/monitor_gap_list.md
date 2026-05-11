# Monitor Gap List

Generated: 2026-05-11T07:45:58.228145+00:00

The monitor lane is continuous/read-only, but not clean. It is READY as a continuity lane because evidence exists and is carried forward; it is not a live-readiness pass.

Blocking gaps carried from Phase 3C:

- `redis_memory_pressure_critical_95`
- `executed_rows_missing_prediction_id`
- `executed_rows_missing_feature_snapshot_id`
- `executed_rows_incomplete_lineage_tuple`
- `duplicate_exchange_order_id_rows_observed`
- `stale_executed_timestamps_gt_5m`
- `trainer_internal_liveness_critical_seen`
- `prior_post_monitor_no_go`

Next safe work: keep read-only monitor continuity active, add V2-owned monitor ingestion/storage, and make these gaps visible in Mission Control without writing legacy Redis or restarting legacy services.
