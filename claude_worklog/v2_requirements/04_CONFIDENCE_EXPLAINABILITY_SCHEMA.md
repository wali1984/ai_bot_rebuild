# 04 Confidence Explainability Schema

## Goal
Make confidence outputs explainable using source-grounded feature contributions.

## Required explainability block
Each prediction/signal record must include `confidence_explainability` with:

- `top_positive_features[]` (ordered by positive contribution)
- `top_negative_features[]` (ordered by negative contribution)

Each feature contribution item must include:
- `feature_name`
- `contribution_score`
- `source_redis_key`
- `source_redis_pattern`
- `source_ts_ms`
- `freshness_age_ms`
- `stale_flag`
- `missing_flag`
- `unused_flag`

Record-level required fields:
- `model_version`
- `checkpoint_id`
- `calibration_version`
- `confidence_raw`
- `confidence_calibrated`
- `explainability_method`
- `explainability_schema_version`

## Minimum cardinality
- Minimum 3 entries in `top_positive_features[]`.
- Minimum 3 entries in `top_negative_features[]`.
- If fewer exist, emit explicit placeholder with `missing_flag=true`.

## Compliance rule
A signal lacking `confidence_explainability` is not explainability-complete and cannot qualify for pre-V2 GO criteria.
