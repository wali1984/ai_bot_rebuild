# 06 Feature Data Flow Gaps

## Current state
- Ingestor/feature key namespaces are documented in `INGESTOR_FEATURE_KEY_MAP.md`.
- Redis key inventory snapshot confirms broad keyspace presence.
- Gap audit classifies monitoring as `FEATURE_KEY_MONITORING_PARTIAL`.

## Missing runtime visibility for enterprise-grade explainability
1. Per-key freshness SLA snapshots across ingestor and feature namespaces.
2. Captured trainer input snapshots with durable `feature_snapshot_id`.
3. Deterministic binding of prediction/confidence outputs to exact source feature keys and values.
4. End-to-end event graph across trainer→signal→orchestrator→risk→execution.
5. Explicit stale/missing/unused source annotations at prediction time.

## Operational implication
- Existing monitor is valid for health/status checks.
- Existing monitor is not sufficient for full explainability and forensic attribution requirements.
