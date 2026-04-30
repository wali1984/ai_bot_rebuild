# 09 Continuous Monitoring and Attribution Review

## Scope
Verify continuous monitoring, evidence packets, trainer liveness, and feature/signal attribution are represented and aligned with post-monitor and continuous_monitoring inputs.

## Inputs
- Architecture: 02, 03, 11, 14
- Requirements: 01, 02, 03, 04, 06, 07, 09
- Continuous monitoring: `claude_worklog/continuous_monitoring/01..11`
- Continuous monitoring impl: `claude_worklog/continuous_monitoring_impl/01..07` plus trainer liveness reports
- Post-monitor: `claude_worklog/post_monitor/01..11`

## Packet model
Architecture file 14 defines six packet types:
- hourly
- daily
- alert
- Claude review
- Codex review
- Ollama summarization

These match `claude_worklog/continuous_monitoring/02_CLAUDE_EVIDENCE_PACKET_FORMAT.md`, `03_CODEX_REVIEW_PACKET_FORMAT.md`, and the Ollama summarization packet plan.

## Monitoring domains
Architecture 14 lists:
- trainer liveness (corrected logic)
- feature flow monitoring
- signal attribution monitoring
- Redis memory monitoring
- readiness/dashboard monitoring

Each domain maps to a continuous_monitoring document (01–08, 10, 11) and is tied to post-monitor findings (01–11).

## Trainer liveness
- Requirement 09 mandates detection of `TRAINER_PREDICTION_WORKER_DEAD_PROCESS_ALIVE` and emission of `TRAINER_INTERNAL_LIVENESS_CRITICAL`.
- continuous_monitoring/11 codifies the trainer-internal liveness requirement.
- continuous_monitoring_impl includes the post-fix 10-minute validation report and false-positive-fix reports, demonstrating the corrected logic referenced in architecture 14.
- Architecture 14 explicitly notes "trainer liveness (corrected logic)", showing the fix is reflected in the architecture.

## Feature attribution and signal explainability
- Requirement 02: feature snapshot schema with full source freshness envelope.
- Requirement 04: confidence explainability with top +/- contributors and freshness flags.
- Architecture 11 mandates the explainability payload (source keys, values, freshness, stale/missing/unused flags, model version, checkpoint, confidence before/after, top +/- drivers, orchestrator reason, risk decision, execution/block reason).
- Database schema 03 persists `feature_snapshots`, `feature_values` (with stale/missing/unused flags), `confidence_events` (with `top_positive_json`, `top_negative_json`).

## Lineage chain alignment
Required (requirement 01 + 03):
`feature_snapshot_id → prediction_id → signal_id → decision_id → risk_decision_id → execution_intent_id`

Architecture 02 lists the chain as the "Mandatory lineage chain". Architecture 03 enforces it via FK constraints across `feature_snapshots`, `prediction_events`, `confidence_events`, `signal_events`, `orchestrator_decisions`, `risk_decisions`, `execution_intents`. Architecture 11 mandates the IDs as the lineage payload.

## Heartbeat schema and Redis safety
- Requirement 06 (heartbeat schema) → `heartbeat_events` table (03).
- Requirement 05 (Redis memory bands 85/90/95) → architecture 04 retention plan; aligns with continuous_monitoring/07 Redis memory plan.
- Post-monitor finding 07 (Redis ~96.8%) → architecture 04 cites the same critical-band finding.

## Evidence storage and dashboard
- Architecture 14 defines packet metadata in `evidence_packets`, raw payload retention with lifecycle policy, cross-reference by `monitor_snapshot_id` and `change_id`.
- Database schema 03 implements both tables.
- Dashboard requirements (continuous_monitoring/08) align with architecture 14 dashboard readiness items (real-time ingestion, confidence/quality indicators, alert classification + ack workflows).

## Risks and notes
- Architecture 14 is concise (26 lines). Build-phase must lock packet JSON shapes by version, retention windows per packet type, and ack workflow semantics.
- Continuous_monitoring/04 alert thresholds should be encoded as configurable policy rather than hard-coded values; architecture allows this via `config_versions`.

## Verdict
Continuous monitoring, evidence packets, trainer liveness, and feature/signal attribution are fully represented and traceable to corrected post-monitor findings.
