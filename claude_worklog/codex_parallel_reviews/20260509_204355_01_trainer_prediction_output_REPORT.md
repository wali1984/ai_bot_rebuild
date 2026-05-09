BEGIN_FILE claude_worklog/codex_parallel_reviews/20260509_204355_01_trainer_prediction_output_REPORT.md
# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-09 20:43:55 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- focused trainer prediction output, trainer parity, and proof tests under `v2/backend/tests/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
- `claude_worklog/historical_pnl_audit/`
- `claude_worklog/legacy_readonly_audit/`

## Validation Performed

- Static source and worklog inspection only.
- No live services were restarted.
- No Redis command was issued.
- No exchange, order, leverage, margin, deployment, or live-trading action was taken.

## Findings

### PASS - prediction_id and feature_snapshot_id lineage fields are present

`TrainerPredictionRecord` carries `prediction_id` and `feature_snapshot_id` as frozen dataclass fields in `v2/backend/app/domain/trainer_prediction_output/record.py:90-106` and validates both IDs as non-empty, whitespace-free strings in `record.py:108-110`.

`assemble_prediction_record` accepts both IDs and forwards them into the domain record in `v2/backend/app/services/trainer_prediction_output/service.py:10-54`. The composition evaluator forwards caller-supplied IDs into that assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:23-56`.

Residual lineage risk remains: this path accepts independent primitive values. It does not bind the IDs to a concrete `StageATrainerRecord`, feature snapshot object, or source-key/freshness payload, so a syntactically valid record can still mix unrelated IDs, confidence values, top features, and freshness evidence.

### BLOCKER - confidence/explainability payload is not preserved in the prediction output record

The MVP prediction output record carries `confidence_raw`, `confidence_calibrated`, `top_positive_feature_codes`, and `top_negative_feature_codes` only in `v2/backend/app/domain/trainer_prediction_output/record.py:99-106`.

The richer trainer parity Stage A contract already exists: `ConfidenceExplainability` carries confidence components, floor/ceiling flags, calibration model version, and calibration method in `v2/backend/app/domain/trainer_parity/stage_a_record.py:13-27`. `StageATrainerRecord` also carries source key references, freshness metadata, feature freshness envelope, and worker health status in `stage_a_record.py:50-66`.

`validate_stage_a_explainability` requires non-empty confidence components, calibration metadata, top features, source key references, and freshness metadata in `v2/backend/app/domain/trainer_parity/explainability_validator.py:16-60`. Those fields are not accepted or emitted by `TrainerPredictionRecord`, `assemble_prediction_record`, or `build_trainer_prediction_output_evaluator`.

This blocks the review topic because downstream paper/replay/risk consumers can see confidence numbers, but cannot audit why confidence was assigned, how it was calibrated, whether floor/ceiling logic applied, or which source keys supported the attribution.

### BLOCKER - stale/missing/unused feature flags are reduced to a lossy freshness summary

The prediction output record compresses feature state into `freshness_flag` and `source_freshness_age_ms` in `v2/backend/app/domain/trainer_prediction_output/record.py:103-104`, with only cross-field consistency checks in `record.py:159-168`.

The trainer parity model already has explicit per-feature categories for `stale`, `missing`, and `unused` in `v2/backend/app/domain/trainer_parity/feature_status_flags.py:10-45`, plus a per-source freshness envelope in `feature_status_flags.py:48-110`.

The MVP output therefore cannot identify which feature was stale, missing, or unused; cannot preserve source-level freshness; and cannot carry source-key references. A single enum is useful for coarse gating, but not sufficient for explainability, replay labeling, or root-cause review.

### BLOCKER - historical PnL evidence needs richer trainer output evidence than this MVP emits

The historical PnL audit requires comparing large losers to trainer confidence and feature freshness, default-denying stale/missing data, and replaying large-loser patterns in `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5-11`.

The legacy LAB hedge unwind failure requires current trainer confidence, confidence delta, feature freshness, liquidation/OI/orderbook/funding/volatility/liquidity context, and sufficient explanation/audit evidence in `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md:23-36`.

The legacy trainer runtime evidence explicitly requires V2 to emit `prediction_id` and `feature_snapshot_id`, expose confidence attribution, and block stale/missing feature input in `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md:12-17`.

The current prediction output MVP satisfies the ID emission part, but under-supports confidence attribution and stale/missing feature evidence for the historical PnL and LAB failure-review lanes.

### PASS - no live, Redis, legacy, exchange, leverage, margin, deployment, or live-trading behavior observed

The reviewed trainer prediction output domain/service/composition packages are pure value/binder code. The implementation does not import Redis clients, HTTP clients, FastAPI routers/lifespan hooks, exchange adapters, legacy runtime modules, or environment URL readers. `v2/backend/app/services/prediction_ingest.py` remains a no-behavior placeholder.

No reviewed code path writes Redis, deletes Redis keys, restarts live services, places/cancels orders, changes leverage/margin, enables live trading, deploys, or exposes secrets.

## Concrete Blockers

1. `TrainerPredictionRecord` lacks a structured confidence explainability payload.
   - Missing evidence includes confidence components, confidence floor/ceiling flags, calibration model version, calibration method, source key references, and freshness metadata linkage.

2. `TrainerPredictionRecord` lacks per-feature stale/missing/unused flag payloads.
   - Existing trainer parity objects preserve this information, but the prediction output MVP compresses it into `freshness_flag` and `source_freshness_age_ms`.

3. The assembler/composition path is not bound to a concrete Stage A trainer record or feature snapshot lineage source.
   - The record can be internally valid while mixing unrelated lineage IDs, top feature codes, confidence values, worker health, and freshness evidence.

4. Historical PnL/LAB failure evidence cannot be fully explained from the typed prediction output.
   - The output preserves IDs and confidence values, but not enough attribution, confidence delta inputs, source-key references, or per-feature stale/missing evidence for audit-grade replay review.

## Proposed Non-Live Autofix Tasks

1. Add pure trainer prediction output value objects for confidence explainability, source key references, per-feature stale/missing/unused flags, freshness metadata, and source freshness envelope.

2. Extend `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator` to accept and preserve those payloads without I/O, Redis, FastAPI, model loading, exchange access, or live behavior.

3. Add a pure mapper from `StageATrainerRecord` into `TrainerPredictionRecord`, validating that `prediction_id`, `feature_snapshot_id`, `symbol`, model/checkpoint IDs, confidence values, calibration metadata, top features, source keys, freshness metadata, and worker health cannot drift.

4. Add focused unit tests for explainability immutability, non-empty confidence components, finite contribution values, duplicate component rejection, calibration method/version preservation, floor/ceiling flag preservation, stale/missing/unused preservation, source reference preservation, and missing/stale consistency.

5. Add a non-live LAB hedge-unwind fixture assertion proving downstream replay/risk/audit code can inspect confidence attribution, confidence delta inputs, feature freshness, and stale/missing/unused evidence from the typed prediction output without live side effects.

## Safety Statement

This review did not modify `/home/wali/Desktop/AI BOT`, write Redis, delete Redis keys, restart live services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose secrets. Only the requested review artifacts under `claude_worklog/codex_parallel_reviews/` were authored.
END_FILE
