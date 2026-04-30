# 02 Feature Snapshot Schema

## Goal
Standardize trainer input feature snapshots to make predictions auditable and reproducible.

## `feature_snapshot_id` definition
`feature_snapshot_id` is a deterministic, immutable identifier for one assembled feature snapshot.

Recommended composition:
- `symbol`
- `trigger_timeframe`
- `bucket_start_ts_ms`
- `snapshot_sequence`
- hash of normalized key/value payload

## Required snapshot fields
- `feature_snapshot_id`
- `snapshot_ts_ms`
- `symbol`
- `trigger_timeframe`
- `htf_context` (e.g., 1h/4h bias payload refs)
- `feature_sources[]` array with entries containing:
  - `source_key`
  - `source_pattern`
  - `source_ts_ms`
  - `freshness_age_ms`
  - `stale_flag`
  - `missing_flag`
  - `unused_flag`
- `feature_values` (normalized numeric/categorical payload)
- `schema_version`

## Freshness policy fields
Per source key, include:
- `freshness_sla_ms`
- `freshness_age_ms`
- `freshness_status` in `{fresh, warning, stale, missing}`

## Trainer contract
No `prediction_id` may be generated without a valid `feature_snapshot_id` and a complete `feature_sources[]` freshness envelope.
