# 01 Observability and Attribution Spec

## Purpose
Define mandatory observability and attribution requirements derived from post-monitor findings, with fail-safe defaults and backward compatibility.

## Runtime constraints from findings
- Current state is `V2_BUILD_NO_GO`.
- Feature attribution status is partial.
- Redis memory operated near critical band (~96.8%).
- Heartbeat key-type ambiguity (`WRONGTYPE`) exists and must be removed.

## Canonical ID definitions
All IDs are required for every actionable decision path:

- `feature_snapshot_id`: Immutable ID for one trainer input snapshot assembled from Redis features for one symbol/time bucket.
- `prediction_id`: Immutable ID for one model inference result produced from one `feature_snapshot_id`.
- `signal_id`: Immutable ID for one published trainer signal associated to one `prediction_id`.
- `decision_id`: Immutable ID for one orchestrator decision on a `signal_id`.
- `risk_decision_id`: Immutable ID for one risk gateway evaluation on a `decision_id`.
- `execution_intent_id`: Immutable ID for one executable order intent produced from one `risk_decision_id`.

## Required linkage model
Single-parent deterministic linkage is required:

1. `feature_snapshot_id` -> parent of `prediction_id`
2. `prediction_id` -> parent of `signal_id`
3. `signal_id` -> parent of `decision_id`
4. `decision_id` -> parent of `risk_decision_id`
5. `risk_decision_id` -> parent of `execution_intent_id`

Additionally, each child record must carry:
- direct parent ID,
- full upstream lineage tuple,
- producer component name,
- monotonic event timestamp.

## Required record envelope for every stage
Mandatory fields:
- `event_type`
- `event_ts_ms`
- `symbol`
- `timeframe`
- all six IDs (directly or via lineage tuple)
- `producer`
- `schema_version`
- `model_version`
- `checkpoint_id` (where applicable)

## Backward compatibility rules
- Existing legacy keys/streams remain readable.
- V2 telemetry must be additive.
- No mutation/deletion of legacy Redis namespaces as part of attribution rollout.
