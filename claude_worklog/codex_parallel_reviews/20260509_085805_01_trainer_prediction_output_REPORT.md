# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-09 08:58:05 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- focused unit tests under `v2/backend/tests/unit/domain/trainer_prediction_output/`, `v2/backend/tests/unit/services/trainer_prediction_output/`, and `v2/backend/tests/unit/composition/trainer_prediction_output/`
- related trainer parity/explainability sources under `v2/backend/app/domain/trainer_parity/`
- non-live proof surfaces under `v2/backend/app/proof/`
- audit inputs under `claude_worklog/historical_pnl_audit/` and `claude_worklog/legacy_readonly_audit/`
- prior 2E3A/2E3B/2E3C specs and Codex review artifacts under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`

## Validation Performed

- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ v2/backend/tests/unit/services/trainer_prediction_output/ v2/backend/tests/unit/composition/trainer_prediction_output/ -q`
  - result: `73 passed in 0.23s`
- `python3 -m py_compile` over the trainer prediction output domain, service, and composition source files
  - result: passed
- forbidden-token scan over the trainer prediction output domain, service, and composition packages for Redis, FastAPI, HTTP clients, environment readers, subprocess/socket/threading/asyncio, wall-clock helpers, logging/print, and dynamic import tokens
  - result: no matches
- live/exchange behavior scan over the trainer prediction output packages and focused tests for order placement/cancelation, leverage, margin, live enablement, Redis mutation, exchange clients, and legacy mutation tokens
  - result: no matches

## Findings

### PASS - prediction_id and feature_snapshot_id lineage fields exist and are forwarded

`TrainerPredictionRecord` defines `prediction_id` and `feature_snapshot_id` as required frozen dataclass fields and validates each as a non-empty, whitespace-free identifier up to 128 characters in `v2/backend/app/domain/trainer_prediction_output/record.py:90-110`.

`assemble_prediction_record` accepts both IDs and forwards them unchanged into the record in `v2/backend/app/services/trainer_prediction_output/service.py:10-54`. `build_trainer_prediction_output_evaluator` forwards both IDs unchanged into the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:23-56`.

Residual lineage risk: the output path accepts independent primitive keyword arguments. It does not derive the record from a concrete `StageATrainerRecord` or `FeatureSnapshot`, so valid-looking IDs can still be combined with unrelated confidence, freshness, or top-feature data.

### BLOCKER - confidence/explainability payload is not preserved at the prediction-output boundary

The current prediction output record carries only `confidence_raw`, `confidence_calibrated`, `top_positive_feature_codes`, and `top_negative_feature_codes` in `v2/backend/app/domain/trainer_prediction_output/record.py:99-106`.

The richer trainer parity Stage A contract already defines `ConfidenceExplainability` with `confidence_components`, floor/ceiling flags, `calibration_model_version`, and `calibration_method` in `v2/backend/app/domain/trainer_parity/stage_a_record.py:13-28`. `validate_stage_a_explainability` also requires non-empty confidence components, calibration metadata, source key references, and freshness metadata in `v2/backend/app/domain/trainer_parity/explainability_validator.py:16-77`.

That structured payload is absent from `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator`. Downstream consumers can see the confidence numbers but cannot audit why confidence was assigned, how it was calibrated, whether floor/ceiling logic was applied, or which source keys supported the attribution.

Audit impact: `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md:12-17` requires V2 to emit prediction lineage, expose confidence attribution, and block stale/missing feature input. `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md:24-36` requires current trainer confidence, confidence delta, feature freshness, and market-context features for hedge-unwind review.

### BLOCKER - stale/missing/unused feature flags are reduced to a lossy freshness enum

The current output record carries only `freshness_flag` and `source_freshness_age_ms` in `v2/backend/app/domain/trainer_prediction_output/record.py:103-104`, with coarse consistency checks at `record.py:141-168`.

Trainer parity preserves richer feature evidence through `FeatureStatusFlags`, `FreshnessMetadata`, and `FeatureFreshnessEnvelope`. The non-live proof harnesses also demonstrate the expected evidence shape by emitting `feature_flags.stale`, `feature_flags.missing`, and `feature_flags.unused` in `v2/backend/app/proof/non_live_operational_proof.py:159-183` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:334-362`.

Because the prediction-output MVP does not carry stale feature names, missing feature names, unused feature names, source references, or per-feature freshness metadata, replay and historical-PnL review cannot determine which input feature caused a stale/missing state.

Audit impact: `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5-11` requires comparing large losers to trainer confidence and feature freshness and default-denying stale/missing data. `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md:5-11` maps large winners/losers and trainer/orchestrator evidence to trainer attribution and lineage.

### PASS - coarse non-live stale/missing behavior is represented elsewhere

The non-live proof fixtures include stale data and LAB hedge-unwind scenarios, preserve `prediction_id` and `feature_snapshot_id`, and emit coarse feature flags in proof outputs. This is useful evidence for operator workflow validation, but it is fixture-side evidence rather than a typed prediction-output contract.

The historical proof explicitly labels stale feature snapshots and unused live/exchange adapters in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:356-360`, with live gate status fixed to `blocked_human_only`.

### PASS - no live, Redis, legacy mutation, exchange, leverage, margin, or deployment behavior observed

The reviewed trainer prediction output domain/service/composition packages are pure value and binder code. They do not import Redis, FastAPI, HTTP clients, exchange adapters, legacy runtime paths, live trading modules, environment URL loaders, service startup code, or model-loading code. They do not read or write Redis, delete keys, restart services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose secrets.

## Concrete Blockers

1. `TrainerPredictionRecord` lacks a structured confidence explainability payload.
   - Missing evidence includes confidence components, confidence floor/ceiling flags, calibration model version, calibration method, source key references, and freshness metadata linkage.

2. `TrainerPredictionRecord` lacks per-feature stale/missing/unused flag payloads.
   - The implementation compresses feature state into `freshness_flag` and `source_freshness_age_ms`, which is not enough for historical PnL attribution, replay labeling, or root-cause review.

3. The assembler/composition path is not bound to a concrete `StageATrainerRecord` or `FeatureSnapshot`.
   - The record can be internally valid while mixing unrelated lineage IDs, top feature codes, confidence values, and freshness evidence.

## Proposed Non-Live Autofix Tasks

1. Add pure domain value objects under `v2/backend/app/domain/trainer_prediction_output/` for prediction confidence explainability, prediction feature status flags, source key references, and freshness metadata summaries.

2. Extend `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator` to accept and preserve those payloads without I/O, Redis, FastAPI, model loading, exchange access, or live behavior.

3. Add a pure mapper from `StageATrainerRecord` or `FeatureSnapshot` plus direction/output primitives into `TrainerPredictionRecord`, validating that `prediction_id`, `feature_snapshot_id`, `symbol`, source keys, freshness, confidence, calibration metadata, and top features cannot drift.

4. Add focused unit tests for explainability immutability, non-empty confidence components, finite contribution values, duplicate component rejection, calibration method/version preservation, floor/ceiling flags, stale/missing/unused preservation, source reference preservation, and missing/stale consistency.

5. Add a non-live LAB hedge-unwind replay/audit fixture assertion proving downstream risk/replay can inspect confidence attribution, confidence delta inputs, feature freshness, and stale/missing/unused evidence from the typed prediction output without live side effects.

## Safety Statement

This review performed read-only inspection and local non-live unit/compile/static checks only. It did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart live services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets. Only the two requested review artifacts under `claude_worklog/codex_parallel_reviews/` were authored.
