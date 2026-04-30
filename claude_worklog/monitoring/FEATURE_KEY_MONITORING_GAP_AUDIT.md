# Feature Key Monitoring Gap Audit

## Assessment Q&A
- **Are ingestor Redis keys explicitly monitored?** Partially. Current monitor tracks heartbeats/selected streams but not broad ingestor key inventory.
- **Are feature_pipeline output keys explicitly monitored?** Partially. `heartbeat:FeaturePipeline` is monitored, but full feature output key set is not inventoried.
- **Are feature freshness timestamps captured?** Partially. Heartbeats and stale counters exist; per-key freshness is not comprehensively captured.
- **Are trainer input feature snapshots captured?** No. Current monitor does not store full trainer input snapshot payloads keyed by feature_snapshot_id.
- **Are prediction/confidence changes linked to specific feature keys?** No. Confidence stats are present but not causally linked to exact feature keys/values.
- **Are signal records linked to feature snapshot IDs?** No explicit linkage captured in monitor output.
- **Are orchestrator decisions linked to feature snapshot IDs?** No explicit linkage captured in monitor output.
- **Are trader actions linked back to prediction/signal/feature snapshot IDs?** Partially for signal_id checks; prediction/feature snapshot chain is missing.

## What is missing
- Read-only inventory of ingestor/feature key namespaces and per-key freshness.
- Feature snapshot-level attribution (`feature_snapshot_id`) across trainer→signal→orchestrator→risk→execution.
- Confidence driver capture tied to exact source keys and feature values.
- Explicit unused/stale/missing source flags at prediction time.
- End-to-end ID link matrix: prediction_id, signal_id, decision_id, risk_decision_id, execution_intent_id.

## Classification
FEATURE_KEY_MONITORING_PARTIAL
