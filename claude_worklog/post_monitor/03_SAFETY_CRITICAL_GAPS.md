# 03 Safety-Critical Gaps

## Gap A — Feature-to-action attribution is incomplete
- Evidence: `FEATURE_KEY_MONITORING_PARTIAL` classification.
- Missing links explicitly documented:
  - no full `feature_snapshot_id` chain,
  - no prediction-to-feature key/value causal map,
  - no full end-to-end ID matrix across trainer→signal→orchestrator→risk→execution.
- Safety impact: root-cause and rollback confidence are limited for live failures.

## Gap B — Redis memory pressure is high
- Evidence: dashboard recorded ~96.80% memory ratio.
- Safety impact: elevated risk of eviction/latency/instability during additional telemetry growth.

## Gap C — Heartbeat key type mismatch observed continuously
- Evidence in snapshots: `signals:trainer:heartbeat` value repeatedly includes `WRONGTYPE`.
- Safety impact: heartbeat interpretation ambiguity can hide genuine liveness issues.

## Gap D — Attribution fields in executed sample are incomplete
- Evidence in snapshots (`executed_analysis` range):
  - `missing_signal_id`: 74–81 in sampled executed rows,
  - `missing_confidence`: 58–63 in sampled executed rows,
  - `stale_executed_ts_ms_gt_5m`: 398–400 of 400 sampled rows.
- Safety impact: weak forensic confidence and timing-quality visibility.

## Risk posture
- Current runtime evidence supports continued hardening and read-only validation work.
- Current runtime evidence does not support a V2 build go decision.
