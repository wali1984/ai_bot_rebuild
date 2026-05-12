# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-12 00:54:38 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- focused tests under `v2/backend/tests/unit/domain/trainer_prediction_output/`, `v2/backend/tests/unit/services/trainer_prediction_output/`, `v2/backend/tests/unit/composition/trainer_prediction_output/`, and `v2/backend/tests/unit/feature_snapshots/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
- `claude_worklog/historical_pnl_audit/`
- `claude_worklog/legacy_readonly_audit/`

## Validation Performed

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q v2/backend/tests/unit/domain/trainer_prediction_output v2/backend/tests/unit/services/trainer_prediction_output v2/backend/tests/unit/composition/trainer_prediction_output v2/backend/tests/unit/feature_snapshots`
  - result: `78 passed in 0.20s`
- Static live/exchange/Redis mutation scan over the trainer prediction output domain, service, composition, and focused tests.
  - result: no production-source matches; the only match was a test string asserting Redis import cleanliness.
- Prior 2E3 implementation/review artifacts report passing domain, assembler, and composition gates, with no Redis/live behavior observed.

## Findings

### PASS - prediction_id and feature_snapshot_id lineage exists and is forwarded

`TrainerPredictionRecord` defines `prediction_id` and `feature_snapshot_id` as frozen dataclass fields and validates both as non-empty, whitespace-free identifiers up to 128 characters in `v2/backend/app/domain/trainer_prediction_output/record.py:92`.

`assemble_prediction_record` accepts both IDs and forwards them unchanged into the record in `v2/backend/app/services/trainer_prediction_output/service.py:12`. `build_trainer_prediction_output_evaluator` forwards both IDs into the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:25`.

Residual risk: the assembler accepts independent primitive arguments, so valid-looking IDs can still be combined with unrelated confidence, freshness, or top-feature data.

### BLOCKER - confidence/explainability payload is not preserved

The prediction-output MVP carries `confidence_raw`, `confidence_calibrated`, `top_positive_feature_codes`, and `top_negative_feature_codes`, but it does not carry the structured `confidence_explainability` payload required by `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`.

The richer trainer parity contract requires confidence components, calibration metadata, floor/ceiling flags, source references, freshness metadata, and feature status flags. The current 2E3 surface intentionally narrows this to scalars and code tuples, which is not enough to audit why confidence was assigned or how it was calibrated.

### BLOCKER - stale/missing/unused feature flags are lossy at prediction output

`FeatureSnapshotService` can compute `stale_features`, `missing_features`, `unused_features`, and `confidence_input_ready`, and the focused feature snapshot test proves those flags work. However, `TrainerPredictionRecord` only stores `freshness_flag` and `source_freshness_age_ms`.

That loses per-feature stale/missing/unused evidence at the prediction-output boundary. Historical PnL review asks to compare large losers to trainer confidence and feature freshness; the typed prediction output cannot identify which features were stale, missing, or unused.

### BLOCKER - historical PnL evidence needs richer attribution than this MVP exposes

`claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` requires comparing large losers to trainer confidence and feature freshness and default-denying stale/missing data. `09_V2_BUILD_IMPACT_MAP.md` maps trainer/orchestrator evidence to `prediction_id`, `decision_id`, lineage, and trainer attribution.

The current MVP provides IDs and confidence scalars, but not enough explainability or per-feature freshness evidence to satisfy that historical-PnL attribution requirement.

### PASS - no live, Redis, legacy mutation, exchange, leverage, margin, or deployment behavior observed

The reviewed trainer prediction output packages are pure value/service/composition code. I observed no Redis reads or writes, Redis key deletion, live service restart, order placement/cancelation, leverage or margin changes, live trading enablement, deployment behavior, legacy mutation, exchange client usage, or secret exposure in the reviewed production surface.

## Concrete Blockers

1. `TrainerPredictionRecord` lacks a structured confidence explainability payload.
2. `TrainerPredictionRecord` lacks per-feature stale/missing/unused feature flag payloads.
3. The assembler/composition path is not bound to a concrete `StageATrainerRecord` or `FeatureSnapshot`, allowing lineage IDs and evidence payloads to drift.

## Proposed Non-Live Autofix Tasks

1. Add pure trainer prediction output value objects for confidence explainability, source references, feature status flags, and freshness metadata summaries.
2. Extend `TrainerPredictionRecord`, `assemble_prediction_record`, and `build_trainer_prediction_output_evaluator` to preserve those payloads without Redis, I/O, FastAPI, model loading, exchange access, or live behavior.
3. Add a pure mapper from `StageATrainerRecord` or `FeatureSnapshot` into `TrainerPredictionRecord`, validating that `prediction_id`, `feature_snapshot_id`, symbol, confidence, calibration metadata, freshness flags, and top features cannot drift.
4. Add focused unit tests for explainability immutability, non-empty confidence components, finite contribution values, calibration metadata preservation, stale/missing/unused preservation, source reference preservation, and missing/stale consistency.
5. Add a non-live historical/LAB replay assertion proving downstream risk/replay can inspect confidence attribution and per-feature freshness evidence from the typed prediction output.

## Safety Statement

This review performed read-only inspection and local non-live tests/static checks only. It did not modify `/home/wali/Desktop/AI BOT`, write Redis, delete Redis keys, restart live services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose secrets. Only the two requested review artifacts under `claude_worklog/codex_parallel_reviews/` were authored.
