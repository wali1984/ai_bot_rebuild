# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-09 14:09:37 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/services/feature_snapshots/`
- focused trainer prediction output and feature snapshot tests under `v2/backend/tests/unit/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
- `claude_worklog/historical_pnl_audit/`
- `claude_worklog/legacy_readonly_audit/`

## Validation Performed

- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output v2/backend/tests/unit/services/trainer_prediction_output v2/backend/tests/unit/composition/trainer_prediction_output v2/backend/tests/unit/feature_snapshots -q`
  - result: `78 passed in 0.23s`
- Static source scan over trainer prediction output domain/service/composition packages and focused tests for Redis, Redis mutation/admin operations, HTTP clients, FastAPI startup, exchange/order/leverage/margin/live-trading tokens, and the live legacy path.
  - result: no production source matches; matches were limited to test names and forbidden-token assertions.

## Findings

### PASS - prediction_id and feature_snapshot_id lineage fields are present

`TrainerPredictionRecord` carries `prediction_id` and `feature_snapshot_id` as required frozen dataclass fields and validates both as non-empty, whitespace-free IDs in `v2/backend/app/domain/trainer_prediction_output/record.py:90`.

`assemble_prediction_record` accepts both IDs and forwards them unchanged into the record in `v2/backend/app/services/trainer_prediction_output/service.py:10`. The composition evaluator forwards caller-supplied IDs into the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:23`.

Residual lineage risk remains: the MVP path accepts independent primitives. It does not assemble from, or validate against, a concrete `StageATrainerRecord` or `FeatureSnapshot`, so internally valid IDs can still be paired with unrelated confidence, freshness, or top-feature evidence.

### BLOCKER - confidence/explainability payload is not preserved

The prediction output record carries only `confidence_raw`, `confidence_calibrated`, `top_positive_feature_codes`, and `top_negative_feature_codes` in `v2/backend/app/domain/trainer_prediction_output/record.py:99`.

The richer trainer parity Stage A contract already exists: `ConfidenceExplainability` carries confidence components, floor/ceiling flags, calibration model version, and calibration method in `v2/backend/app/domain/trainer_parity/stage_a_record.py:13`. `validate_stage_a_explainability` requires non-empty components, calibration metadata, top features, source key references, and freshness metadata in `v2/backend/app/domain/trainer_parity/explainability_validator.py:16`.

That structured explainability payload is absent from `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator`. Downstream consumers can see the confidence numbers but cannot audit why confidence was assigned, how it was calibrated, whether floor/ceiling logic applied, or which source keys supported the attribution.

Historical/audit impact: `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md` requires prediction lineage and confidence attribution. `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` requires current trainer confidence, confidence delta, feature freshness, and market-context evidence for the LAB hedge-unwind failure review.

### BLOCKER - stale/missing/unused feature flags are reduced to a lossy enum

The feature snapshot model carries `stale_features`, `missing_features`, `unused_features`, source snapshot IDs, source key refs, ingestor refs, and `confidence_input_ready` in `v2/backend/app/domain/features/models.py:43`.

The prediction output record compresses feature state into only `freshness_flag` and `source_freshness_age_ms` in `v2/backend/app/domain/trainer_prediction_output/record.py:103`. It does not carry per-feature stale, missing, or unused lists; source-key refs; per-feature freshness metadata; or the source freshness envelope already present in trainer parity.

Historical/audit impact: `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` requires comparing large losers to trainer confidence and feature freshness and requires default-deny on stale/missing data. A single freshness enum is enough for coarse abstain behavior, but not enough for replay labeling, historical PnL attribution, or root-cause review.

### PASS - historical PnL evidence impact is correctly non-live but under-supported by this MVP output

The historical PnL audit maps large winners/losers, trainer/orchestrator evidence, and LAB hedge unwind into the paper/backtest MVP lane in `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`. The legacy audit maps trainer worker health gaps and LAB hedge unwind explainability into the same MVP lane in `claude_worklog/legacy_readonly_audit/09_V2_BUILD_IMPACT_MAP.md`.

The current prediction output MVP preserves basic lineage IDs that later paper/replay records can carry, but it does not preserve enough confidence attribution or feature-status evidence to satisfy those historical PnL and failure-case review needs.

### PASS - no live, Redis, legacy mutation, exchange, leverage, margin, or deployment behavior observed

The reviewed trainer prediction output domain/service/composition packages are pure value/binder code. They do not import Redis clients, HTTP clients, FastAPI routers/lifespan hooks, exchange adapters, legacy runtime modules, or environment URL readers. No reviewed code writes Redis, deletes keys, restarts services, places/cancels orders, changes leverage/margin, enables live trading, deploys, or exposes secrets.

## Concrete Blockers

1. `TrainerPredictionRecord` lacks a structured confidence explainability payload.
   - Missing evidence includes confidence components, confidence floor/ceiling flags, calibration model version, calibration method, source key references, and freshness metadata linkage.

2. `TrainerPredictionRecord` lacks per-feature stale/missing/unused flag payloads.
   - Existing feature snapshot and trainer parity modules preserve these details, but the prediction output MVP compresses them into `freshness_flag` and `source_freshness_age_ms`.

3. The assembler/composition path is not bound to a concrete `StageATrainerRecord` or `FeatureSnapshot`.
   - The record can be internally valid while mixing unrelated lineage IDs, top feature codes, confidence values, and freshness evidence.

## Proposed Non-Live Autofix Tasks

1. Add pure domain value objects under `v2/backend/app/domain/trainer_prediction_output/` for confidence explainability, prediction feature status flags, source key references, and freshness metadata summaries.

2. Extend `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator` to accept and preserve those payloads without I/O, Redis, FastAPI, model loading, exchange access, or live behavior.

3. Add a pure mapper from `StageATrainerRecord` or `FeatureSnapshot` plus direction/output primitives into `TrainerPredictionRecord`, validating that `prediction_id`, `feature_snapshot_id`, `symbol`, source keys, freshness, confidence, calibration metadata, and top features cannot drift.

4. Add focused unit tests for explainability immutability, non-empty confidence components, finite contribution values, duplicate component rejection, calibration method/version preservation, floor/ceiling flags, stale/missing/unused preservation, source reference preservation, and missing/stale consistency.

5. Add a non-live LAB hedge-unwind replay/audit fixture assertion proving downstream risk/replay can inspect confidence attribution, confidence delta inputs, feature freshness, and stale/missing/unused evidence from the typed prediction output without live side effects.

## Safety Statement

This review performed read-only inspection and focused local non-live tests only. It did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart live services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets. Only the two requested review artifacts under `claude_worklog/codex_parallel_reviews/` were authored.
