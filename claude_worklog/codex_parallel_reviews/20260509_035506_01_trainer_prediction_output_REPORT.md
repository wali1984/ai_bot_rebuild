# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-09 03:55:06 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- focused trainer prediction output tests under `v2/backend/tests/unit/domain`, `v2/backend/tests/unit/services`, and `v2/backend/tests/unit/composition`
- related feature/parity/orchestrator surfaces under `v2/backend/app/domain/features/`, `v2/backend/app/domain/trainer_parity/`, and `v2/backend/app/services/orchestrator_decision/`
- phase artifacts under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
- audit evidence under `claude_worklog/historical_pnl_audit/` and `claude_worklog/legacy_readonly_audit/`

## Validation Performed

- Static source inspection only using `rg`, `find`, `sed`, `nl`, and `git status`.
- No pytest invocation was run in this pass to preserve read-only review mode beyond the two requested report artifacts.
- Forbidden-token scan over `v2/backend/app/domain/trainer_prediction_output`, `v2/backend/app/services/trainer_prediction_output`, and `v2/backend/app/composition/trainer_prediction_output` found no Redis, FastAPI, HTTP, exchange, order, leverage, margin, live, legacy mutation, subprocess, socket, deployment, or secret-handling tokens.

## Findings

### PASS - prediction_id and feature_snapshot_id lineage fields exist

`TrainerPredictionRecord` defines `prediction_id` and `feature_snapshot_id` as required frozen dataclass fields and validates both as non-empty, whitespace-free identifiers up to 128 characters in `v2/backend/app/domain/trainer_prediction_output/record.py:90-110`.

`assemble_prediction_record` accepts both IDs and forwards them unchanged into the domain record in `v2/backend/app/services/trainer_prediction_output/service.py:10-54`.

`build_trainer_prediction_output_evaluator` forwards both IDs unchanged into the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:23-56`.

### BLOCKER - confidence/explainability payload is not preserved

The prediction output record currently carries only `confidence_raw`, `confidence_calibrated`, and two top-feature-code tuples in `v2/backend/app/domain/trainer_prediction_output/record.py:99-106`.

The richer trainer parity Stage A contract already has `ConfidenceExplainability`, including `confidence_components`, floor/ceiling flags, `calibration_model_version`, and `calibration_method` in `v2/backend/app/domain/trainer_parity/stage_a_record.py:13-28`. `validate_stage_a_explainability` additionally requires non-empty components, calibration metadata, source key references, and freshness metadata in `v2/backend/app/domain/trainer_parity/explainability_validator.py:16-77`.

That structured payload is not present on `TrainerPredictionRecord`, not accepted by `assemble_prediction_record`, and not forwarded by the composition evaluator. Consumers of the MVP cannot audit why confidence was assigned, how it was calibrated, or whether confidence floor/ceiling logic affected the result.

Audit impact: `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md:15-20` requires V2 to emit prediction lineage, expose confidence attribution, and block stale/missing feature input. `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md:44-56` requires current trainer confidence, confidence delta, and feature freshness for hedge-unwind review.

### BLOCKER - stale/missing/unused feature flags are reduced to a lossy freshness flag

Feature snapshots preserve `stale_features`, `missing_features`, `unused_features`, `confidence_input_ready`, and source references in `v2/backend/app/domain/features/models.py:43-81`. Trainer input validation blocks missing/stale/not-ready inputs in `v2/backend/app/domain/features/validation.py:90-106`.

Trainer parity also has structured `FeatureStatusFlags(stale, missing, unused)` and `FeatureFreshnessEnvelope` in `v2/backend/app/domain/trainer_parity/feature_status_flags.py:120-220`.

The trainer prediction output MVP reduces this evidence to `freshness_flag` and `source_freshness_age_ms` in `v2/backend/app/domain/trainer_prediction_output/record.py:103-104` and `record.py:141-168`. That is enough for a coarse stale/missing enum, but not enough to identify which features were stale, missing, or unused at prediction time.

Audit impact: `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:61-67` requires comparing large losers to trainer confidence and feature freshness, plus default-deny on stale/missing data. `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md:72-78` maps large winners/losers and trainer/orchestrator evidence to trainer attribution and lineage. The current output drops the per-feature evidence needed for replay labels and root-cause review.

### BLOCKER - output assembly is not bound to a concrete feature snapshot or Stage A record

Trainer parity includes a pure lineage validator that compares Stage B back to Stage A by `prediction_id`, `feature_snapshot_id`, and `symbol` in `v2/backend/app/domain/trainer_parity/lineage_validator.py:247-260`.

The prediction output MVP accepts independent primitive keyword arguments. There is no mapper from `StageATrainerRecord` or `FeatureSnapshot` into `TrainerPredictionRecord`, and no validation that top feature codes, freshness fields, confidence values, source references, and lineage IDs came from the same source snapshot.

Impact: a `TrainerPredictionRecord` can be internally valid while combining a real `feature_snapshot_id` with mismatched confidence/explainability/freshness evidence. That is a lineage gap for replay, historical PnL attribution, and failure-case audit.

### PASS - no live, Redis, legacy mutation, exchange, leverage, margin, or deployment behavior observed

The reviewed trainer prediction output domain/service/composition packages are pure value/binder code. They do not import Redis, FastAPI, HTTP clients, exchange adapters, legacy runtime paths, live trading modules, environment URL loaders, or service startup code. They do not read or write Redis, delete keys, restart services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose secrets.

## Concrete Blockers

1. `TrainerPredictionRecord` lacks a structured confidence explainability payload.
2. `TrainerPredictionRecord` lacks per-feature stale/missing/unused flag payloads, source key references, and freshness metadata linkage.
3. The assembler/composition path does not validate or derive the output from a concrete `StageATrainerRecord` or `FeatureSnapshot`.

## Proposed Non-Live Autofix Tasks

1. Add pure domain value objects under `v2/backend/app/domain/trainer_prediction_output/` for prediction confidence explainability, prediction feature status flags, source key references, and freshness metadata summaries.
2. Extend `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator` to accept and preserve those payloads without I/O, Redis, FastAPI, model loading, exchange access, or live behavior.
3. Add a pure mapper from `StageATrainerRecord` or `FeatureSnapshot` plus trainer direction primitives into `TrainerPredictionRecord`, with validation that `prediction_id`, `feature_snapshot_id`, `symbol`, source keys, freshness, confidence, and top features cannot drift.
4. Add unit tests for explainability immutability, non-empty confidence components, finite contributions, duplicate rejection, calibration method/version preservation, floor/ceiling flags, stale/missing/unused preservation, source reference preservation, and missing/stale consistency.
5. Add replay/audit fixture coverage based on the LAB hedge-unwind requirements proving downstream risk/replay can inspect confidence attribution, confidence delta inputs, feature freshness, and stale/missing/unused evidence without live side effects.

## Safety Statement

This review did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart live services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets. Only the two requested review artifacts under `claude_worklog/codex_parallel_reviews/` were authored.
