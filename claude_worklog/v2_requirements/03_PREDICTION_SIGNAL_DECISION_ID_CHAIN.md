# 03 Prediction Signal Decision ID Chain

## Objective
Define exact stage-by-stage ID propagation across trainer, signal, orchestrator, risk gateway, and execution.

## Stage contracts

### A) Trainer inference
Output must include:
- `prediction_id`
- `feature_snapshot_id`
- `model_version`
- `checkpoint_id`
- `prediction_ts_ms`
- `confidence_raw`
- `confidence_calibrated`

### B) Trainer signal publication
Output must include:
- `signal_id`
- `prediction_id`
- `feature_snapshot_id`
- `action`
- `action_type`
- `confidence`
- `signal_ts_ms`

### C) Orchestrator decision
Output must include:
- `decision_id`
- `signal_id`
- `prediction_id`
- `feature_snapshot_id`
- `decision_ts_ms`
- `decision_result` (allow/block/defer)
- `decision_reason_codes[]`

### D) Risk gateway
Output must include:
- `risk_decision_id`
- `decision_id`
- `signal_id`
- `risk_ts_ms`
- `risk_result` (allow/size_reduce/block)
- `risk_reason_codes[]`

### E) Execution intent
Output must include:
- `execution_intent_id`
- `risk_decision_id`
- `decision_id`
- `signal_id`
- `execution_intent_ts_ms`
- `intent_type`
- `intent_status`

## Mandatory lineage tuple
Every downstream record must carry:
- `feature_snapshot_id`
- `prediction_id`
- `signal_id`
- `decision_id`
- `risk_decision_id`
- `execution_intent_id` (if already created)

## Integrity rules
- No stage may emit child ID without parent ID.
- Parent IDs are immutable.
- Cross-symbol linkage is invalid.
- Missing lineage fields are hard validation failures for observability compliance.
