# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-10 23:21:09 local

Verdict: BLOCKED

## Scope Inspected

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl`
- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_readonly_audit`

Read-only/live-safety constraints honored: no access to `/home/wali/Desktop/AI BOT`, no Redis writes/deletes, no live service restart, no exchange/order/leverage/margin/live-trading/deploy action, and no secret exposure.

## Findings

1. Prediction output lineage exists in the pure record path, but not at an MVP ingest/read/explain boundary.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:90` defines frozen `TrainerPredictionRecord`.
   - `record.py:92-93` carries `prediction_id` and `feature_snapshot_id`; `record.py:109-110` validates both as non-empty, whitespace-free IDs.
   - `v2/backend/app/services/trainer_prediction_output/service.py:10-54` forwards caller-supplied IDs into the record with injected-clock `prediction_ts_ms`.
   - `v2/backend/app/composition/trainer_prediction_output/runtime.py:23-56` forwards evaluator inputs to the assembler without live I/O.
   - Blocker: `v2/backend/app/api/v1/predictions.py:1-27` remains scaffold-only OPTIONS metadata, and `v2/backend/app/services/prediction_ingest.py:1` is a placeholder. There is no non-live prediction ingest/read/explain service proving lineage is persisted, queryable, or auditable.

2. API lineage schema is present, but prediction-stage coherence is not enforced.
   - `v2/backend/app/api/schemas/prediction.py:16-30` defines `PredictionIngest`/`PredictionRead` with top-level `prediction_id`, `confidence_score`, `raw_output_json`, and `lineage`.
   - `v2/backend/app/api/schemas/lineage.py:26-41` defines nullable chain IDs.
   - Blocker: no inspected handler/service enforces `prediction_id == lineage.prediction_id`, non-null `lineage.feature_snapshot_id`, explicit null downstream IDs, or parent `feature_snapshot_id` existence through a non-live repository.

3. Confidence and basic explainability are captured, but the payload is too thin for the MVP explain/read surface.
   - `record.py:99-100` carries `confidence_raw` and `confidence_calibrated`; `record.py:132-133` validates finite floats in `[0.0, 1.0]`.
   - `record.py:105-106` carries top positive/negative feature code tuples; `record.py:154-158` validates tuple shape, uniqueness, and disjointness.
   - Blocker: prediction output does not preserve contributor weights/values, calibration metadata, source references, previous confidence, confidence delta, or per-feature freshness flags. Later explainability harnesses currently project lineage/action fields only and explicitly exclude richer explainability fields from that layer.

4. Stale/missing/unused feature evidence is computed before prediction output but collapses before the prediction record.
   - `v2/backend/app/services/feature_snapshots/service.py:43-46` computes missing, stale, and unused features.
   - `feature_snapshots/service.py:73-81` stores those lists plus `confidence_input_ready`.
   - `v2/backend/app/domain/features/validation.py:16-23` treats missing/stale/not-ready/source-ungrounded input as trainer input errors.
   - Blocker: `TrainerPredictionRecord` only carries `freshness_flag` and `source_freshness_age_ms` (`record.py:103-104`). The assembler does not accept a validated `FeatureSnapshot`/trainer payload summary, does not enforce `confidence_input_ready`, and does not preserve stale/missing/unused feature lists.

5. Historical PnL evidence remains a requirement driver, not proof of impact.
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:3-11` has `NO_DATA` for winners/losers.
   - `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5-11` requires repeated-loss detection, fee/funding drag, comparing large losers to trainer confidence and feature freshness, and stale/missing default-deny behavior.
   - Blocker: current inputs do not prove that the prediction output MVP supports historical loss attribution or feature-freshness failure analysis from concrete PnL/trainer rows.

6. No live/Redis/legacy/exchange behavior was found in the trainer prediction output implementation slice.
   - The `domain`, `services`, and `composition` trainer prediction output modules are pure Python value/assembler/binder code.
   - Focused tests passed: `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output v2/backend/tests/unit/services/trainer_prediction_output v2/backend/tests/unit/composition/trainer_prediction_output v2/backend/tests/unit/feature_snapshots -q` reported `78 passed`.
   - The blocker is MVP completeness and evidence continuity, not observed live side effects.

## Proposed Non-Live Autofix Tasks

1. Implement a non-live prediction ingest/read/explain path using an in-memory or file-backed test repository abstraction only; do not use Redis, exchange adapters, or live services.
2. Add prediction-stage lineage validation: top-level `prediction_id` must match `lineage.prediction_id`, `lineage.feature_snapshot_id` must be non-null, downstream lineage IDs must be explicit null, and parent snapshot existence must be checked through a non-live repository interface.
3. Extend the prediction output/explainability payload to carry calibration metadata, previous confidence, confidence delta, source references, per-feature freshness flags, and contributor details with values/weights/signs.
4. Change the assembler boundary to accept a validated feature snapshot/trainer payload summary, reject `confidence_input_ready=False`, and preserve stale/missing/unused feature lists in the prediction output or companion explainability record.
5. Add focused tests for feature snapshot -> prediction output -> read/explain projection across fresh, stale, missing, and unused feature cases.
6. Add local-only historical PnL fixtures for representative large winner/loser rows with confidence and feature freshness evidence, then assert the prediction explainability output can support the audit questions without live exchange calls.

## Go / No-Go

NO-GO for Trainer Prediction Output MVP readiness.
