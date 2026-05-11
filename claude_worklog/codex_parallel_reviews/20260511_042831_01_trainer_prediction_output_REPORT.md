# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-11 04:28:31 local

Verdict: BLOCKED

## Scope Inspected

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl`
- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_readonly_audit`

Read-only/live-safety constraints honored: no access to `/home/wali/Desktop/AI BOT`, no Redis writes/deletes, no live service restart, no exchange/order/leverage/margin/live-trading/deploy action, and no secret exposure.

## Findings

1. Prediction output lineage exists in the pure domain/service/composition path, but not at an MVP ingest/read/explain boundary.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:90-106` defines frozen `TrainerPredictionRecord` with `prediction_id` and `feature_snapshot_id`.
   - `record.py:108-110` validates both IDs as non-empty, whitespace-free IDs.
   - `v2/backend/app/services/trainer_prediction_output/service.py:10-54` forwards caller-supplied IDs into the record and stamps `prediction_ts_ms` from an injected clock.
   - `v2/backend/app/composition/trainer_prediction_output/runtime.py:23-56` forwards evaluator inputs to the assembler without live I/O.
   - Blocker: `v2/backend/app/api/v1/predictions.py:1-27` remains scaffold-only OPTIONS metadata, `v2/backend/app/services/prediction_ingest.py:1` is a placeholder, and `v2/backend/app/adapters/db/repositories/predictions.py:1` is a placeholder. There is no non-live prediction ingest/read/explain service proving lineage is persisted, queryable, or auditable.

2. API lineage schema is present, but prediction-stage coherence is not enforced.
   - `v2/backend/app/api/schemas/prediction.py:16-30` defines `PredictionIngest`/`PredictionRead` with top-level `prediction_id`, `confidence_score`, `raw_output_json`, and `lineage`.
   - `v2/backend/app/api/schemas/lineage.py:26-41` defines nullable chain IDs, including `feature_snapshot_id` and `prediction_id`.
   - Blocker: no inspected handler/service enforces `prediction_id == lineage.prediction_id`, non-null `lineage.feature_snapshot_id`, explicit null downstream IDs, or parent `feature_snapshot_id` existence through a non-live repository.

3. Confidence values and minimal top-feature codes are captured, but the explainability payload is too thin for the MVP explain/read surface.
   - `record.py:99-100` carries `confidence_raw` and `confidence_calibrated`; `record.py:132-133` validates finite floats in `[0.0, 1.0]`.
   - `record.py:105-106` carries top positive/negative feature code tuples; `record.py:154-158` validates tuple shape and disjointness.
   - Existing Stage A parity has richer evidence: `v2/backend/app/domain/trainer_parity/stage_a_record.py:13-27` defines `ConfidenceExplainability`, and `stage_a_record.py:50-66` carries confidence explainability, source keys, feature status flags, freshness metadata, and feature freshness envelope.
   - `v2/backend/app/domain/trainer_parity/explainability_validator.py:16-78` requires non-empty confidence components, calibration metadata, top features, source key references, and freshness metadata.
   - Blocker: `TrainerPredictionRecord`, `assemble_prediction_record()`, and the composition evaluator do not preserve confidence components, contributor weights/values, calibration method/model metadata, source references, previous confidence, confidence delta, per-feature freshness flags, or freshness envelope evidence.

4. Stale/missing/unused feature flags exist before prediction output but collapse before the prediction record.
   - `v2/backend/app/domain/features/models.py:44-62` defines `FeatureSnapshot` with `stale_features`, `missing_features`, `unused_features`, and `confidence_input_ready`.
   - `v2/backend/app/domain/features/models.py:64-81` includes those lists in `trainer_payload()`.
   - `v2/backend/app/services/feature_snapshots/service.py:43-46` computes missing, stale, and unused features, and `service.py:73-81` stores those lists plus trainer readiness.
   - `v2/backend/app/domain/features/validation.py:16-23` rejects missing/stale/not-ready/source-ungrounded trainer inputs.
   - Blocker: `TrainerPredictionRecord` only carries `freshness_flag` and `source_freshness_age_ms` (`record.py:103-104`). The assembler does not accept a validated `FeatureSnapshot`/trainer payload summary, does not enforce `confidence_input_ready`, and does not preserve stale/missing/unused feature lists.

5. Historical PnL evidence remains a requirement driver, not proof of impact.
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md:7-14` reports zero income/trade/order rows and `BINANCE_PULL_NOT_REQUESTED`.
   - `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:3-11` has `NO_DATA` for winners/losers.
   - `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5-11` requires repeated-loss detection, fee/funding drag, comparing large losers to trainer confidence and feature freshness, and stale/missing default-deny behavior.
   - `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md:12-17` requires V2 to emit `prediction_id`/`feature_snapshot_id`, expose confidence attribution, and block stale/missing feature input.
   - `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md:24-36` requires current trainer confidence, confidence delta, feature freshness, and market-context evidence for the LAB hedge-unwind failure review.
   - Blocker: current inputs do not prove that the prediction output MVP supports historical loss attribution or feature-freshness failure analysis from concrete PnL/trainer rows.

6. No live/Redis/legacy/exchange behavior was found in the trainer prediction output implementation slice.
   - The `domain`, `services`, and `composition` trainer prediction output modules are pure Python value/assembler/binder code.
   - Restricted safety scan over the trainer prediction output slice, scaffold prediction API/schema, prediction ingest placeholder, and predictions repository placeholder found zero hits for Redis mutation/access, exchange/order/leverage/margin, HTTP/websocket, subprocess, service restart, or live-trading tokens.
   - Focused tests passed: `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output v2/backend/tests/unit/services/trainer_prediction_output v2/backend/tests/unit/composition/trainer_prediction_output v2/backend/tests/unit/feature_snapshots -q` reported `78 passed`.
   - The blocker is MVP completeness and evidence continuity, not observed live side effects.

## Concrete Blockers

1. No non-live prediction ingest/read/explain implementation or repository proves `prediction_id` and `feature_snapshot_id` lineage survives beyond in-memory record construction.
2. No prediction-stage lineage validator enforces top-level/lineage ID coherence, required upstream `feature_snapshot_id`, explicit downstream null IDs, or parent snapshot existence.
3. The prediction output record lacks the structured confidence/explainability payload already required by Stage A parity and downstream audit needs.
4. Stale/missing/unused feature evidence and `confidence_input_ready` are computed on feature snapshots but are not bound into prediction assembly or preserved on prediction output.
5. Historical PnL/LAB failure evidence cannot be fully explained from the typed prediction output because concrete PnL rows are absent and the output lacks enough attribution/freshness detail.

## Proposed Non-Live Autofix Tasks

1. Implement a non-live prediction ingest/read/explain path backed by an in-memory or file-backed test repository abstraction only; do not use Redis, exchange adapters, or live services.
2. Add prediction-stage lineage validation: top-level `prediction_id` must match `lineage.prediction_id`, `lineage.feature_snapshot_id` must be non-null, downstream lineage IDs must be explicit null, and parent snapshot existence must be checked through a non-live repository interface.
3. Extend `TrainerPredictionRecord` or add a companion prediction output envelope carrying confidence components, contributor values/weights/signs, calibration method/model/version, source references, feature freshness flags, previous confidence, and confidence delta.
4. Change the assembler boundary to accept a validated feature snapshot/trainer payload summary, reject `confidence_input_ready=False`, and preserve stale/missing/unused feature lists in the prediction output or companion explainability record.
5. Add focused tests for feature snapshot -> prediction output -> read/explain projection across fresh, stale, missing, and unused feature cases.
6. Add local-only historical PnL/LAB fixtures with representative large winner/loser rows, confidence values, confidence deltas, and feature freshness evidence, then assert the prediction explainability output can support the audit questions without live exchange calls.

## Go / No-Go

NO-GO for Trainer Prediction Output MVP readiness.
