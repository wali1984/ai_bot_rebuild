# Runtime Truth Freshness Fix

Generated at: 2026-05-12T05:07:18.942Z

Fixes applied:

- Expanded read-only process detection to include live market ingestors and feature_pipeline.
- Removed the false fallback that displayed the last completed task as the current running task.
- Added last_completed_task and last_task_status as separate fields.
- Added market_ingestor_status and feature_pipeline_status to runtime_monitor_status.
- Preserved TRAINER_RUNTIME_EVIDENCE_MISSING when no realtime trainer process or trainer monitor stream is observed.
