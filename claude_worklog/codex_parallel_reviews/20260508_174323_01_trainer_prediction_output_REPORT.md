# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-08 17:43:23 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- related downstream lineage consumers in `v2/backend/app/domain/orchestrator_decision/`, `v2/backend/app/services/orchestrator_decision/`, and `v2/backend/app/domain/risk_gateway/`
- related feature/parity sources in `v2/backend/app/domain/features/`, `v2/backend/app/services/feature_snapshots/`, and `v2/backend/app/domain/trainer_parity/`
- focused tests under `v2/backend/tests/unit/domain/trainer_prediction_output/`, `v2/backend/tests/unit/services/trainer_prediction_output/`, `v2/backend/tests/unit/composition/trainer_prediction_output/`, plus related feature/parity references
- historical and legacy audit notes under `claude_worklog/historical_pnl_audit/` and `claude_worklog/legacy_readonly_audit/`
- prior 2E3A/2E3B/2E3C specs and Codex reviews under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

## Validation Performed

- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output v2/backend/tests/unit/services/trainer_prediction_output v2/backend/tests/unit/composition/trainer_prediction_output -q`
  - result: `73 passed in 0.25s`
- `rg -n "redis|Redis|aioredis|hiredis|requests|httpx|FastAPI|APIRouter|lifespan|ccxt|binance|kucoin|order|leverage|margin|live" v2/backend/app/domain/trainer_prediction_output v2/backend/app/services/trainer_prediction_output v2/backend/app/composition/trainer_prediction_output`
  - result: no matches

## Findings

### PASS - prediction_id and feature_snapshot_id are present and propagated

`TrainerPredictionRecord` carries both `prediction_id` and `feature_snapshot_id` as required fields and validates each as a non-empty, whitespace-free string with max length 128 in `v2/backend/app/domain/trainer_prediction_output/record.py`.

The assembler service forwards both IDs into the record unchanged, and the composition evaluator forwards the caller-provided values into the assembler. Downstream orchestrator and risk records also include both IDs, preserving the basic lineage chain.

Residual gap: the prediction-output MVP accepts raw keyword arguments and does not bind a `TrainerPredictionRecord` to a concrete `FeatureSnapshot` or `StageATrainerRecord` object. Existing trainer parity validators can compare Stage A to Stage B lineage, but the MVP output path does not currently validate that `feature_snapshot_id`, top feature codes, freshness, and confidence explainability came from the same source snapshot.

### BLOCKER - confidence/explainability payload is not preserved in TrainerPredictionRecord

The output record contains only:

- `confidence_raw`
- `confidence_calibrated`
- `top_positive_feature_codes`
- `top_negative_feature_codes`

The richer explainability payload exists in trainer parity Stage A as `ConfidenceExplainability`, including `confidence_components`, floor/ceiling flags, `calibration_model_version`, and `calibration_method`, and is validated by `validate_stage_a_explainability`.

That payload is not present in `TrainerPredictionRecord`, `assemble_prediction_record`, or `build_trainer_prediction_output_evaluator`. As a result, consumers of the trainer prediction output MVP cannot audit why confidence was assigned, what calibration method/version was used, whether confidence was floored/ceiled, or which source keys backed the attribution.

Audit impact: `legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md` requires V2 to expose confidence attribution. `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` requires explanation/audit sufficient to inspect trainer confidence and confidence delta around hedge unwind failures. The current MVP output loses that evidence at the prediction-output boundary.

### BLOCKER - stale/missing/unused feature flags are reduced to a lossy freshness flag

Feature snapshot construction tracks `stale_features`, `missing_features`, `unused_features`, `confidence_input_ready`, and source freshness. Trainer parity also has `FeatureStatusFlags(stale, missing, unused)` and `FeatureFreshnessEnvelope`.

The trainer prediction output MVP only carries:

- `freshness_flag`
- `source_freshness_age_ms`

It does not carry the per-feature stale/missing/unused lists or source-key references. This prevents downstream explainability and replay from determining which features were stale, missing, or unused at prediction time.

Audit impact: `historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` requires comparing large losers to trainer confidence and feature freshness, and requires risk gateway default-deny on stale/missing data. A single freshness enum is enough for a coarse abstain decision, but not enough for historical PnL evidence review, replay labeling, or root-cause attribution.

### PASS - coarse stale/missing gating exists downstream

The orchestrator decision service abstains on `freshness_flag == "missing"` before `stale`, then worker health, then low confidence. This gives a non-live coarse default-abstain path for missing/stale feature input.

Residual gap: because the MVP output lacks the actual stale/missing feature names and unused feature list, the downstream decision can explain only the coarse reason code, not the evidence payload.

### PASS - no live, Redis, legacy mutation, exchange, leverage, margin, or deployment behavior observed in prediction-output MVP

The reviewed prediction-output domain/service/composition packages are pure Python value/binder code. The targeted forbidden-token scan found no Redis, live, HTTP, exchange, order, leverage, or margin tokens in those packages. The implementation does not import legacy code, does not read or write Redis, does not register FastAPI, does not place orders, does not restart services, and does not enable live trading.

Historical and legacy audit files were read only. No Redis commands were run. No live services were restarted. No exchange actions were taken.

## Concrete Blockers

1. `TrainerPredictionRecord` does not include a structured confidence explainability payload.
   - Missing fields include confidence components, confidence floor/ceiling flags, calibration model version, calibration method, source key references, and freshness metadata linkage.

2. `TrainerPredictionRecord` does not include stale/missing/unused feature flag payloads.
   - Existing feature snapshot and trainer parity modules preserve these details, but the prediction output MVP compresses them into `freshness_flag` and `source_freshness_age_ms`.

3. The assembler/composition path does not validate the prediction output against a concrete `FeatureSnapshot` or `StageATrainerRecord`.
   - The record can carry matching-looking IDs and top feature codes without proving they came from the same snapshot or validated Stage A output.

## Proposed Non-Live Autofix Tasks

1. Add pure domain value objects under `v2/backend/app/domain/trainer_prediction_output/` for:
   - `PredictionConfidenceExplainability`
   - `PredictionFeatureStatusFlags`
   - optional source/freshness summary fields needed for replay and audit

2. Extend `TrainerPredictionRecord` with the above payloads while preserving `prediction_id`, `feature_snapshot_id`, raw/calibrated confidence, direction, worker health, freshness flag, and top feature codes.

3. Extend `assemble_prediction_record` and `build_trainer_prediction_output_evaluator` to accept and forward the new payloads without I/O, Redis, FastAPI, model loading, or live behavior.

4. Add unit tests covering:
   - explainability payload required and immutable
   - confidence component duplicate/empty/non-finite rejection
   - calibration method/version required
   - stale/missing/unused feature flag preservation
   - source key references preserved
   - missing/stale freshness remains consistent with feature flag payloads
   - no Redis/live/import regressions

5. Add a pure mapper from existing `StageATrainerRecord` or `FeatureSnapshot` plus trainer output primitives into `TrainerPredictionRecord`, with tests proving `prediction_id` and `feature_snapshot_id` lineage cannot drift.

6. Add a replay/audit fixture based on the LAB hedge unwind requirements that asserts the prediction output exposes enough confidence, freshness, and feature status evidence for downstream risk/replay explanation without any live side effects.

## Safety Statement

This review performed read-only inspection and targeted local unit tests only. It did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart live services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets.
