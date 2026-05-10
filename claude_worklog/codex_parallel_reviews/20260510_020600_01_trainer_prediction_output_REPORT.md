BEGIN_FILE claude_worklog/codex_parallel_reviews/20260510_020600_01_trainer_prediction_output_REPORT.md
# Codex Parallel Review: Trainer Prediction Output MVP

Review timestamp: 2026-05-10 02:06:00 America/New_York
Mode: read-only parallel review, except for this requested report artifact and matching go/no-go artifact.

## Scope inspected

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/tests/unit/domain/trainer_prediction_output/`
- `v2/backend/tests/unit/services/trainer_prediction_output/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `v2/backend/app/api/schemas/prediction.py`
- `v2/backend/app/api/v1/predictions.py`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/179_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/190_PHASE_2E3B_PREDICTION_RECORD_ASSEMBLER_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/198_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_SPEC.md`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`
- `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/09_V2_BUILD_IMPACT_MAP.md`

## Findings

No blocking findings.

## Lineage

`TrainerPredictionRecord` carries both required lineage fields: `prediction_id` and `feature_snapshot_id`. The service assembler accepts both fields as keyword-only inputs and copies them into the frozen domain record without generating or mutating them. The composition root forwards the same IDs into the assembler. Downstream orchestrator decision assembly preserves both IDs when deriving an `OrchestratorDecisionRecord`.

The API scaffold for `/predictions` marks the stage as lineage-bearing and lists `feature_snapshot_id` and `prediction_id` as required stage IDs. The API route remains scaffold-only, so the current MVP evidence is domain/service/composition output contract readiness rather than a live HTTP ingest path.

## Confidence And Explainability

The prediction output record includes `confidence_raw`, `confidence_calibrated`, `top_positive_feature_codes`, and `top_negative_feature_codes`. The domain validates confidence as finite floats in `[0.0, 1.0]`, limits explainability feature-code tuples to 8 entries each, enforces non-empty/unique/no-whitespace feature codes, and rejects overlap between positive and negative feature codes.

Earlier trainer parity records retain the fuller `ConfidenceExplainability` bundle with confidence components, calibration metadata, source references, and freshness metadata. The 2E3 output MVP intentionally exposes a compact output record derived from that lineage rather than the entire Stage A parity payload.

## Feature Flags

The output record defines explicit freshness states: `fresh`, `stale`, and `missing`. It enforces `source_freshness_age_ms is None` for `missing`, and requires a nonnegative integer age for `fresh` or `stale`.

The historical PnL and legacy audits require stale/missing feature handling and confidence/freshness comparison for large losers. Current downstream orchestrator logic abstains on `missing` and `stale` freshness before confidence/direction handling, satisfying the non-live default-deny impact for this MVP layer.

No stale, missing, or unused feature flag blocker was found in the trainer prediction output code path.

## Historical PnL Impact

Historical PnL audit impact items map to trainer attribution, confidence/freshness comparison, prediction lineage, and default-deny stale/missing data. The reviewed code supports those impacts through:

- stable `prediction_id` and `feature_snapshot_id` on prediction records;
- raw and calibrated confidence fields;
- positive/negative feature-code attribution fields;
- source freshness flag and age;
- orchestrator abstain behavior for stale/missing trainer inputs.

This review did not inspect or run live historical replay jobs.

## Safety

No live, Redis, legacy, or exchange behavior was observed in the prediction-output domain, service, or composition root. A targeted token scan for Redis/live/exchange/order/leverage/margin/legacy/request/router terms returned zero matches in:

- `v2/backend/app/domain/trainer_prediction_output`
- `v2/backend/app/services/trainer_prediction_output`
- `v2/backend/app/composition/trainer_prediction_output`

The implementation does not call a model, open files, register FastAPI lifespan hooks, read or write Redis, place/cancel orders, change leverage/margin, or enable live trading.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 python - <<'PY' ... import v2.backend.app.domain.trainer_prediction_output ... PY`: import succeeded.
- `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/pytest -q ...`: initial invocation failed because the venv pytest did not include repo root on `PYTHONPATH`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. ./.venv/bin/pytest -q v2/backend/tests/unit/domain/trainer_prediction_output v2/backend/tests/unit/services/trainer_prediction_output v2/backend/tests/unit/composition/trainer_prediction_output`: `73 passed in 0.22s`.

## Proposed Non-Live Autofix Tasks

None required for readiness.

Optional follow-up, not a blocker: add a future non-live mapper from the fuller trainer parity `ConfidenceExplainability` payload into the compact 2E3 positive/negative feature-code output so the derivation is explicit and test-covered when the pipeline integration phase starts.
END_FILE
