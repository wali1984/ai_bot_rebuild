# 08 V2 Requirements From Runtime

Derived from completed monitor evidence (not design-only assumptions).

## Required before V2 build GO

1. Feature snapshot lineage
- Introduce durable `feature_snapshot_id` emitted at trainer input boundary.
- Persist read-only lineage references through signal and execution telemetry.

2. End-to-end ID chain completeness
- Enforce linkage fields across runtime path:
  - `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id`.

3. Confidence explainability envelope
- Record top feature contributors and source key references for each prediction/signal decision.
- Include stale/missing/unused source indicators per decision.

4. Redis safety margin guard
- Define operational memory guardrails with alert classes below critical band.
- Demonstrate stable run with acceptable memory headroom (well below current ~96.8%).

5. Heartbeat schema correctness
- Remove/resolve heartbeat WRONGTYPE ambiguity to ensure reliable liveness semantics.

## Validation requirement
- Re-run read-only monitor cycle after implementing observability improvements and compare against this baseline.
