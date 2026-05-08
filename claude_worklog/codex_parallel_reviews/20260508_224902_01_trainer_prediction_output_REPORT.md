# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-08 22:49:02 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- focused trainer prediction output tests under `v2/backend/tests/unit/domain`, `v2/backend/tests/unit/services`, and `v2/backend/tests/unit/composition`
- related lineage/evidence sources under `v2/backend/app/domain/trainer_parity/`, `v2/backend/app/domain/features/`, `v2/backend/app/services/feature_snapshots/`, and `v2/backend/app/services/orchestrator_decision/`
- prior phase artifacts under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
- audit inputs under `claude_worklog/historical_pnl_audit/` and `claude_worklog/legacy_readonly_audit/`

## Validation Performed

- Static source inspection only, plus targeted `rg`, `sed`, and `nl` reads.
- No pytest invocation was run in this pass to preserve read-only review mode beyond the two requested report artifacts.
- Forbidden-token scan over `v2/backend/app/domain/trainer_prediction_output`, `v2/backend/app/services/trainer_prediction_output`, and `v2/backend/app/composition/trainer_prediction_output` found no Redis, FastAPI, HTTP, exchange, order, leverage, margin, live, legacy, subprocess, socket, or environment-loading tokens.

## Findings

### PASS - prediction_id and feature_snapshot_id lineage fields exist

`TrainerPredictionRecord` defines `prediction_id` and `feature_snapshot_id` as required frozen dataclass fields and validates both as non-empty, whitespace-free identifiers up to 128 characters in `v2/backend/app/domain/trainer_prediction_output/record.py:90`.

`assemble_prediction_record` forwards caller-supplied `prediction_id` and `feature_snapshot_id` unchanged into the record in `v2/backend/app/services/trainer_prediction_output/service.py:38`.

`build_trainer_prediction_output_evaluator` forwards both IDs unchanged into the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:40`.

Downstream orchestrator assembly copies `prediction.prediction_id` and `prediction.feature_snapshot_id` into the decision record in `v2/backend/app/services/orchestrator_decision/service.py:105`, preserving coarse prediction-to-decision lineage.

### BLOCKER - confidence/explainability payload is not preserved

The prediction output record currently carries only `confidence_raw`, `confidence_calibrated`, and two top-feature-code tuples in `v2/backend/app/domain/trainer_prediction_output/record.py:99`.

The richer trainer parity Stage A contract already has `ConfidenceExplainability`, including `confidence_components`, floor/ceiling flags, `calibration_model_version`, and `calibration_method` in `v2/backend/app/domain/trainer_parity/stage_a_record.py:13`. That payload is not present on `TrainerPredictionRecord`, not accepted by `assemble_prediction_record`, and not forwarded by the composition evaluator.

Impact: `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md:15` requires V2 to expose confidence attribution, and `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md:24` requires current trainer confidence, confidence delta, and feature freshness for hedge-unwind safety review. The current MVP drops the evidence needed to audit why a confidence was assigned and how it was calibrated.

### BLOCKER - stale/missing/unused feature flags are reduced to a lossy freshness flag

Feature snapshot construction preserves `stale_features`, `missing_features`, `unused_features`, source key refs, source ingestor refs, and `confidence_input_ready` in `v2/backend/app/services/feature_snapshots/service.py:61`.

Trainer parity Stage A also has structured `FeatureStatusFlags(stale, missing, unused)` and `FeatureFreshnessEnvelope` in `v2/backend/app/domain/trainer_parity/feature_status_flags.py:10`.

The trainer prediction output MVP reduces this evidence to `freshness_flag` and `source_freshness_age_ms` in `v2/backend/app/domain/trainer_prediction_output/record.py:103`. That is enough for coarse abstain routing, but not enough to identify which inputs were stale, missing, or unused when reviewing historical PnL, replay cases, or failure root cause.

Impact: `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5` requires comparing large losers to trainer confidence and feature freshness, and requires default-deny on stale/missing data. A single enum loses the per-feature evidence needed for that audit.

### BLOCKER - output assembly is not bound to a concrete feature snapshot or Stage A record

Trainer parity has validators that bind Stage B back to Stage A by comparing `prediction_id`, `feature_snapshot_id`, and `symbol` in `v2/backend/app/domain/trainer_parity/lineage_validator.py:27`.

The prediction output MVP accepts independent primitive keyword arguments. There is no mapper from `StageATrainerRecord` or `FeatureSnapshot` into `TrainerPredictionRecord`, and no validation that the top feature codes, freshness fields, confidence values, and lineage IDs came from the same source snapshot.

Impact: the record can be internally valid while still combining a real `feature_snapshot_id` with mismatched confidence/explainability/freshness evidence. That is a lineage gap for replay and historical PnL attribution.

### PASS - coarse stale/missing gating exists downstream

The orchestrator decision service abstains for `freshness_flag == "missing"` before `stale`, then worker health, then low confidence in `v2/backend/app/services/orchestrator_decision/service.py:77`. This provides a non-live coarse gate for stale/missing feature states.

Residual gap: the decision path can explain only the coarse enum, not the stale/missing/unused feature names or source freshness breakdown that caused the enum.

### PASS - no live, Redis, legacy mutation, exchange, leverage, margin, or deployment behavior observed

The reviewed trainer prediction output domain/service/composition packages are pure Python value and binder code. They do not import Redis, FastAPI, HTTP clients, exchange adapters, legacy paths, or live trading modules. They do not read or write Redis, delete keys, restart services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose secrets.

## Concrete Blockers

1. `TrainerPredictionRecord` lacks a structured confidence explainability payload.
2. `TrainerPredictionRecord` lacks per-feature stale/missing/unused flag payloads and source key references.
3. The assembler/composition path does not validate or derive the output from a concrete `StageATrainerRecord` or `FeatureSnapshot`.

## Proposed Non-Live Autofix Tasks

1. Add pure domain value objects for prediction confidence explainability and prediction feature status flags under `v2/backend/app/domain/trainer_prediction_output/`.
2. Extend `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator` to accept and preserve those payloads without I/O, Redis, FastAPI, model loading, or live behavior.
3. Add a pure mapper from `StageATrainerRecord` or `FeatureSnapshot` plus trainer direction primitives into `TrainerPredictionRecord`, with validation that `prediction_id`, `feature_snapshot_id`, `symbol`, source keys, freshness, confidence, and top features cannot drift.
4. Add unit tests for explainability immutability, non-empty confidence components, finite contributions, duplicate rejection, calibration method/version preservation, floor/ceiling flags, stale/missing/unused preservation, and source reference preservation.
5. Add replay/audit fixture coverage based on the LAB hedge-unwind requirements proving downstream risk/replay can inspect confidence attribution, confidence delta inputs, feature freshness, and stale/missing/unused evidence without live side effects.

## Safety Statement

This review did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart live services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets. Only the two requested review artifacts under `claude_worklog/codex_parallel_reviews/` were authored.
