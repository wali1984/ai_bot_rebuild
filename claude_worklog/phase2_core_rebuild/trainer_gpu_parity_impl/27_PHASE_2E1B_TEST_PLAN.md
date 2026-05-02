# Phase 2E1.B — Test Plan

Tests live in `v2/backend/tests/unit/domain/trainer_parity/`.

All tests are unit tests, fully synchronous, no I/O, no subprocess,
no network, no Redis, no legacy import.

This file was revised in the same planner turn that revised the
spec (`26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`). The revisions add a
`FreshnessMetadata` test module and update fixtures and the public
surface test for the nine-name surface.

## Files to author

- `__init__.py` (empty)
- `conftest.py` — small fixture factory for valid Stage A and Stage B
  records and helper builders for valid `FeatureStatusFlags`,
  `FeatureFreshnessEnvelope`, `FreshnessMetadata`, and
  `ConfidenceExplainability`.
- `test_stage_a_record_invariants.py`
- `test_stage_b_record_invariants.py`
- `test_feature_status_flags.py`
- `test_feature_freshness_envelope.py`
- `test_freshness_metadata.py`
- `test_lineage_validator_stage_a.py`
- `test_lineage_validator_stage_b.py`
- `test_explainability_validator.py`
- `test_public_surface.py`

## conftest.py fixture set

- `valid_feature_status_flags()` returns a `FeatureStatusFlags` with
  one entry per category and disjoint feature names.
- `valid_feature_freshness_envelope()` returns an envelope with two
  source entries; `oldest_source_*` matches the maximum-age entry.
- `valid_freshness_metadata()` returns a `FreshnessMetadata` with
  two feature entries (e.g., `"feat_a"` and `"feat_b"`), all three
  tuples covering the same feature set, distinct ages, and statuses
  drawn from `{"fresh", "warning"}`.
- `valid_confidence_explainability()` returns an explainability
  record with at least one component, distinct names, finite
  contributions, non-empty `calibration_model_version` and
  `calibration_method`.
- `valid_stage_a_record()` returns a Stage A record using the above
  fixtures and stable IDs (`prediction_id="pred-1"`,
  `feature_snapshot_id="snap-1"`, `symbol="BTCUSDT"`).
- `valid_stage_b_record(stage_a)` returns a Stage B record whose
  lineage matches the provided Stage A record.

Fixtures are pure builders. No filesystem access. No environment
reads.

## test_stage_a_record_invariants.py

- valid record constructs.
- empty `prediction_id` raises `TrainerParityLineageError`.
- empty `feature_snapshot_id` raises.
- empty `symbol` raises.
- empty `model_version` raises.
- empty `checkpoint_id` raises.
- empty `worker_id` raises.
- empty `worker_health_status` raises.
- negative `prediction_ts_ms` raises.
- `confidence_raw` of -0.0001 raises.
- `confidence_raw` of 1.0001 raises.
- `confidence_calibrated` of -0.0001 raises.
- `confidence_calibrated` of 1.0001 raises.
- duplicate entries in `top_positive_features` raises.
- duplicate entries in `top_negative_features` raises.
- duplicate entries in `source_key_references` raises.
- record is frozen: assigning to a field raises
  `dataclasses.FrozenInstanceError`.
- record carries the `freshness_metadata` field with the value
  passed in (smoke check that the new field is wired correctly).

## test_stage_b_record_invariants.py

- valid record constructs.
- empty `signal_id` raises.
- empty `prediction_id` raises.
- empty `feature_snapshot_id` raises.
- empty `symbol` raises.
- empty `action` raises.
- empty `action_type` raises.
- `confidence` of -0.0001 raises.
- `confidence` of 1.0001 raises.
- negative `signal_ts_ms` raises.
- `action` outside the allowed set raises.
- `action_type` outside the allowed set raises.
- record is frozen.

## test_feature_status_flags.py

- valid flags construct.
- duplicate inside `stale` raises.
- duplicate inside `missing` raises.
- duplicate inside `unused` raises.
- a feature name appearing in `stale` and `missing` raises.
- a feature name appearing in `stale` and `unused` raises.
- a feature name appearing in `missing` and `unused` raises.
- frozen instance check.

## test_feature_freshness_envelope.py

- valid envelope constructs.
- negative `oldest_source_age_ms` raises.
- empty `oldest_source_name` raises.
- duplicate source name raises.
- negative freshness_ms raises.
- mismatch between `oldest_source_age_ms` and the actual maximum-age
  entry raises.
- mismatch between `oldest_source_name` and the actual maximum-age
  entry raises.
- frozen instance check.

## test_freshness_metadata.py

- valid metadata constructs.
- duplicate feature name in `per_feature_last_update_ms` raises.
- duplicate feature name in `per_feature_age_ms` raises.
- duplicate feature name in `per_feature_status` raises.
- mismatched feature-name set across the three tuples raises (a
  feature appearing in two tuples but missing from the third).
- empty feature name raises.
- negative `last_update_ts_ms` raises.
- negative `age_ms` raises.
- status outside `{"fresh", "warning", "stale", "missing"}` raises.
- all three tuples empty raises (must reference at least one
  feature).
- frozen instance check.

## test_lineage_validator_stage_a.py

- valid record passes.
- a record manually constructed via `object.__new__` with a blanked
  `prediction_id` raises (defense-in-depth path).
- a record with blanked `feature_snapshot_id` raises.
- a record with blanked `symbol` raises.

## test_lineage_validator_stage_b.py

- matching Stage A and Stage B passes.
- mismatched `prediction_id` raises with a reason naming the failing
  edge.
- mismatched `feature_snapshot_id` raises with a reason naming the
  failing edge.
- mismatched `symbol` raises with a reason naming the failing edge.
- `signal_ts_ms` strictly less than `prediction_ts_ms` raises with a
  reason naming the failing edge.
- `signal_ts_ms` equal to `prediction_ts_ms` is accepted.

## test_explainability_validator.py

- valid record passes.
- empty `confidence_components` raises (constructed via
  `object.__new__` since `ConfidenceExplainability.__post_init__`
  rejects malformed components at construction).
- duplicate component name raises.
- non-finite contribution raises (NaN and +inf both checked, via
  `object.__new__` path because the dataclass constructor rejects
  non-finite contributions at build time).
- empty `calibration_model_version` raises.
- empty `calibration_method` raises.
- both `top_positive_features` and `top_negative_features` empty
  raises.
- empty `source_key_references` raises.
- valid `freshness_metadata` smoke-check (the validator should not
  raise for a properly populated metadata field).

## test_public_surface.py

- `from v2.backend.app.domain.trainer_parity import *` exposes
  exactly the nine names in the spec:
    - `StageATrainerRecord`
    - `StageBTrainerRecord`
    - `FeatureStatusFlags`
    - `FeatureFreshnessEnvelope`
    - `FreshnessMetadata`
    - `validate_stage_a_lineage`
    - `validate_stage_b_lineage`
    - `validate_stage_a_explainability`
    - `TrainerParityLineageError`
- No additional names are exported. No `errors`, no internal
  helpers, no `_ALLOWED_*` constants exposed, no
  `ConfidenceExplainability` re-export from `__init__`.
- Each exported name is callable or a class as expected.

## Validation invocation

Run: `pytest v2/backend/tests/unit/domain/trainer_parity/ -q`

Expected: all tests pass, zero warnings, zero errors, zero failures.

The implementation report must record the exact pytest summary line
and confirm zero warnings.

PHASE2E1B_TRAINER_PARITY_IMPL_TEST_PLAN_READY
PHASE2E1B_TRAINER_PARITY_IMPL_TEST_PLAN_REVISED

