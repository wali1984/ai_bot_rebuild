```
# Trainer Output Contract and Lineage IDs

V2 must enforce the lineage tuple defined in
`claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`.
This document binds those requirements to the trainer output surface.

## Stage A: trainer inference (must emit)

- `prediction_id`
- `feature_snapshot_id`
- `model_version`
- `checkpoint_id`
- `prediction_ts_ms`
- `confidence_raw`
- `confidence_calibrated`
- `confidence_explainability`
- `top_positive_features[]`
- `top_negative_features[]`
- `source_key_references[]`
- `freshness_metadata`
- `feature_status_flags` (`stale[]`, `missing[]`, `unused[]`)
- `feature_freshness_envelope` (per-source freshness flags)
- `worker_id`
- `worker_health_status`

The full explainability set is bound by
`04_REWARD_AND_CONFIDENCE_PARITY_MAP.md` and is mandatory on every Stage A
record.

## Stage B: trainer signal publication (must emit)

- `signal_id`
- `prediction_id`
- `feature_snapshot_id`
- `action`
- `action_type`
- `confidence`
- `signal_ts_ms`

## Integrity rules

- No `prediction_id` may exist without a valid `feature_snapshot_id` from
  `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`.
- No `signal_id` may exist without a valid `prediction_id`.
- Cross-symbol linkage is invalid.
- Parent IDs are immutable once written.
- A missing lineage field is a hard observability validation failure.
- A missing legacy-preservation explainability field (per
  `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`) is a hard observability
  validation failure.

## Mapping to V2 storage (planning only)

- The trainer output records will land in the V2 Postgres tables described
  by `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` in a later
  phase. This phase only fixes the contract; it does not write code.

PHASE2_TRAINER_GPU_PARITY_OUTPUT_CONTRACT_READY
```
