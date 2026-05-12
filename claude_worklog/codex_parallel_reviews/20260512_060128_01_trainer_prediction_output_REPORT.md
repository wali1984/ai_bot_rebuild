# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-12
Mode: read-only parallel review; no live services, Redis keys, exchange state, leverage/margin, orders, deployment, or legacy runtime were touched.

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/services/feature_snapshots/`
- focused tests under `v2/backend/tests/unit/domain/trainer_prediction_output/`, `v2/backend/tests/unit/services/trainer_prediction_output/`, `v2/backend/tests/unit/composition/trainer_prediction_output/`, and `v2/backend/tests/unit/feature_snapshots/`
- trainer GPU parity implementation notes for 2E3.A/B/C
- historical PnL and legacy read-only audit impact maps

## Findings

GO: Trainer Prediction Output MVP is ready for the reviewed non-live scope.

Lineage is present and validated. `TrainerPredictionRecord` carries both `prediction_id` and `feature_snapshot_id` as first-class required fields, validates non-empty/no-whitespace/length-capped identifiers, and the assembler and composition root pass both IDs through unchanged. Downstream orchestrator/risk/paper services reference the same lineage fields in their own tests and service boundaries.

Confidence and explainability MVP payload are present. The record includes `confidence_raw`, `confidence_calibrated`, `freshness_flag`, `source_freshness_age_ms`, `worker_health_status`, and bounded disjoint `top_positive_feature_codes` / `top_negative_feature_codes`. This satisfies the Phase 2E3 MVP shape described by the implementation worklogs: confidence plus top-K attribution codes, without expanding into a model runner or API surface.

Stale/missing/unused feature flags are represented before prediction output. `FeatureSnapshotService` emits `stale_features`, `missing_features`, `unused_features`, `confidence_input_ready`, and `trainer_input_schema_version`; freshness requires stale/missing data to be explicit. The trainer prediction record separately constrains prediction freshness to `fresh`, `stale`, or `missing`, with cross-field validation for age presence.

Historical PnL evidence impact is covered at MVP handoff level. The audit requires comparing large losers to trainer confidence and feature freshness, plus preserving trainer/orchestrator lineage. This MVP provides the required confidence, feature freshness linkage via `feature_snapshot_id`, and prediction lineage. Full realized-PnL attribution and replay scoring remain in paper backtest / risk / ledger lanes, not in this trainer output MVP.

No live, Redis, legacy, or exchange behavior was found in the trainer prediction output domain/service/composition packages. The reviewed source is pure dataclass validation and pure assembly/binder code. Existing app-wide Redis adapters and exchange/live scaffolds are not imported by this MVP surface. The focused forbidden-token and import-clean tests cover Redis, URL env, FastAPI, HTTP, threading, subprocess, and related unsafe imports for the trainer prediction output packages.

## Non-Blocking Notes

- `v2/backend/app/api/schemas/prediction.py` is still scaffold-style and uses `confidence_score` / `raw_output_json`; the Phase 2E3 worklogs explicitly exclude FastAPI/API expansion from this milestone, so this is not a Trainer Prediction Output MVP blocker.
- Richer explainability with numeric contribution weights is not present. The scoped MVP uses top positive/negative feature code tuples; weighted attribution can be a later non-live enhancement if required by a future explainability contract.

## Validation

Command run with pytest cache disabled:

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/trainer_prediction_output/ v2/backend/tests/unit/services/trainer_prediction_output/ v2/backend/tests/unit/composition/trainer_prediction_output/ v2/backend/tests/unit/feature_snapshots/ -q`

Result: `78 passed in 0.20s`

## Proposed Non-Live Follow-Up Tasks

- Add a future non-live API/schema alignment task that maps `TrainerPredictionRecord` to read-side prediction payloads only after the API milestone opens.
- Add a future non-live explainability enhancement task only if weighted feature contribution payloads become required beyond current top-K feature-code MVP.

