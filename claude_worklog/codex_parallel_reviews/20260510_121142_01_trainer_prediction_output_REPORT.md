# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-10 12:11:42 local

Verdict: BLOCKED

## Scope inspected

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl`
- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_readonly_audit`

No live services were restarted. No Redis writes/deletes were performed. No exchange/order/leverage/margin/live-trading/deploy actions were performed.

## Findings

1. Prediction lineage exists as a pure value object, but the live API/storage ingestion path is still scaffold-only.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:90` defines `TrainerPredictionRecord` with `prediction_id` and `feature_snapshot_id`.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:108` validates both IDs as non-empty, whitespace-free strings.
   - `v2/backend/app/services/trainer_prediction_output/service.py:10` assembles the record and stamps `prediction_ts_ms` from an injected clock.
   - Blocker: `v2/backend/app/api/v1/predictions.py:3` says the route is scaffold-only; `v2/backend/app/api/v1/predictions.py:25` exposes only an OPTIONS metadata shim.
   - Blocker: `v2/backend/app/services/prediction_ingest.py:1` is a placeholder with no behavior, and `v2/backend/app/adapters/db/repositories/predictions.py` is a placeholder.
   - Impact: prediction output cannot yet be ingested, persisted, fetched, or audited through the MVP API path, so `prediction_id`/`feature_snapshot_id` lineage is not end-to-end.

2. API schema lineage does not enforce the required non-null prediction-stage IDs.
   - `v2/backend/app/api/schemas/prediction.py:21` carries top-level `prediction_id`, but the schema only embeds a generic `LineageBlock` at `v2/backend/app/api/schemas/prediction.py:26`.
   - `v2/backend/app/api/middleware/lineage_validator.py:1` documents the intended pre-handler validators.
   - Blocker: `v2/backend/app/api/middleware/lineage_validator.py:19` is passthrough only; shape, stage-required, parent-existence, chain-coherence, immutability, and uniqueness checks are not implemented.
   - Impact: malformed API payloads can claim lineage-bearing shape without enforcing `lineage.feature_snapshot_id` and `lineage.prediction_id` consistency with the record.

3. Confidence and explainability payload is incomplete for the MVP prediction output contract.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:99` and `v2/backend/app/domain/trainer_prediction_output/record.py:100` carry `confidence_raw` and `confidence_calibrated`.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:105` and `v2/backend/app/domain/trainer_prediction_output/record.py:106` carry top positive/negative feature code tuples.
   - Existing Stage A parity has a richer required explainability contract: `v2/backend/app/domain/trainer_parity/stage_a_record.py:13` defines `ConfidenceExplainability`, and `v2/backend/app/domain/trainer_parity/stage_a_record.py:58` attaches it to `StageATrainerRecord`.
   - `v2/backend/app/domain/trainer_parity/explainability_validator.py:16` requires confidence components, calibration metadata, top features, source references, and freshness metadata.
   - Blocker: the MVP `TrainerPredictionRecord` does not carry `confidence_explainability`, confidence components, calibration method/model metadata, source key references, per-feature freshness metadata, or feature freshness envelope. It also allows both top feature tuples to be empty when freshness is missing.
   - Impact: downstream `/predictions/{id}/explain` and audit consumers cannot reconstruct why confidence was produced, only the scalar scores and limited top feature codes.

4. Stale/missing/unused feature flags exist at feature-snapshot level but are not bound into prediction output assembly.
   - `v2/backend/app/domain/features/models.py:56` through `v2/backend/app/domain/features/models.py:58` define `stale_features`, `missing_features`, and `unused_features`.
   - `v2/backend/app/domain/features/models.py:64` includes those lists in `trainer_payload()`.
   - `v2/backend/app/domain/features/validation.py:16` through `v2/backend/app/domain/features/validation.py:23` reject missing, stale, not-ready, or source-ungrounded trainer inputs.
   - `v2/backend/app/services/feature_snapshots/service.py:43` through `v2/backend/app/services/feature_snapshots/service.py:81` compute and expose these flags.
   - Blocker: `assemble_prediction_record()` accepts only a collapsed `freshness_flag` and `source_freshness_age_ms`; it does not require the `FeatureSnapshot`, does not check `confidence_input_ready`, and does not preserve stale/missing/unused feature lists on the prediction record.
   - Impact: stale/missing/unused evidence can be lost between feature snapshot creation and trainer prediction output.

5. Historical PnL evidence is not available enough to validate impact.
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md:7` through `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md:9` report zero income, trade, and order rows.
   - `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md:14` records `BINANCE_PULL_NOT_REQUESTED`.
   - The requirements still call for comparing large losers to trainer confidence and feature freshness at `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:7`.
   - Blocker: there is no concrete historical PnL/trade/trainer row evidence to prove the prediction output MVP covers loss attribution or feature-freshness-driven failure analysis.

6. No live/Redis/legacy/exchange behavior was found in the trainer prediction output domain/service/composition slice.
   - A restricted token scan over `v2/backend/app/domain/trainer_prediction_output`, `v2/backend/app/services/trainer_prediction_output`, `v2/backend/app/composition/trainer_prediction_output`, `v2/backend/app/services/prediction_ingest.py`, `v2/backend/app/api/v1/predictions.py`, and `v2/backend/app/api/schemas/prediction.py` found no `redis`, exchange adapter, order, leverage, margin, subprocess, HTTP, or websocket references.
   - Unit tests also include forbidden-token guards for domain, service, and composition modules.
   - This is a pass for the reviewed prediction-output implementation slice, with the caveat that API and repository behavior are still placeholders.

## Proposed non-live autofix tasks

1. Add a pure `PredictionOutputEnvelope` or extend `TrainerPredictionRecord` to carry the full Stage A explainability payload: confidence components, calibration model/version/method, source key references, per-feature freshness metadata, feature freshness envelope, stale/missing/unused feature lists, and `confidence_input_ready`.
2. Change `assemble_prediction_record()` to accept a feature snapshot/trainer payload object or validated feature snapshot summary, reject `confidence_input_ready=False`, and preserve stale/missing/unused flags in the prediction output.
3. Implement non-live prediction ingest/read/explain handlers backed by an in-memory or test repository first, with no Redis/exchange/live dependencies.
4. Implement API-level lineage validation for prediction-stage payloads: top-level `prediction_id` must match `lineage.prediction_id`, `lineage.feature_snapshot_id` must be non-null, downstream IDs must be explicit null, and parent snapshot existence should be checked against a non-live repository abstraction.
5. Add focused unit tests proving stale, missing, and unused feature flags survive feature snapshot -> prediction output -> explain/read projection.
6. Add a local-only historical PnL fixture with large winner/loser rows and trainer confidence/freshness fields, then assert the prediction output explainability envelope can support the historical failure-pattern requirements without live exchange calls.

## Go / No-Go

NO-GO for Trainer Prediction Output MVP readiness.

