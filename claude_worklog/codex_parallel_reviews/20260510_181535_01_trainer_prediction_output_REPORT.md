# Codex Parallel Review - Trainer Prediction Output MVP

Review timestamp: 2026-05-10 18:15:35 local

Verdict: BLOCKED

## Scope inspected

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl`
- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_readonly_audit`

Read-only constraints honored for live systems: no Redis writes/deletes, no live service restart, no exchange/order/leverage/margin/live-trading/deploy action, and no access to `/home/wali/Desktop/AI BOT`.

## Findings

1. Prediction output lineage exists in the pure record path, but is not end-to-end for the MVP API/storage path.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:90` defines frozen `TrainerPredictionRecord`.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:92` and `v2/backend/app/domain/trainer_prediction_output/record.py:93` carry `prediction_id` and `feature_snapshot_id`.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:109` and `v2/backend/app/domain/trainer_prediction_output/record.py:110` validate both IDs as non-empty, whitespace-free identifiers.
   - `v2/backend/app/services/trainer_prediction_output/service.py:10` accepts both IDs and `v2/backend/app/services/trainer_prediction_output/service.py:38` copies them into the record with an injected-clock `prediction_ts_ms`.
   - `v2/backend/app/composition/trainer_prediction_output/runtime.py:40` forwards evaluator inputs unchanged into the service.
   - Blocker: `v2/backend/app/api/v1/predictions.py:3` declares the route scaffold-only, and `v2/backend/app/api/v1/predictions.py:25` only exposes an OPTIONS metadata shim. `v2/backend/app/services/prediction_ingest.py:1` is also a placeholder.
   - Impact: `prediction_id` and `feature_snapshot_id` lineage is strong inside domain/service/composition, but not yet ingestible, persisted, readable, or auditable through a prediction-output MVP boundary.

2. API lineage schema is present, but prediction-stage non-null/coherence enforcement is incomplete.
   - `v2/backend/app/api/schemas/prediction.py:21` defines top-level `prediction_id`.
   - `v2/backend/app/api/schemas/prediction.py:26` embeds the generic `LineageBlock`.
   - `v2/backend/app/api/v1/predictions.py:20` declares stage-required IDs as `feature_snapshot_id` and `prediction_id`.
   - Blocker: no inspected prediction ingest handler enforces that top-level `prediction_id` matches `lineage.prediction_id`, that `lineage.feature_snapshot_id` is non-null, or that downstream lineage IDs remain explicit null for the prediction stage.
   - Impact: lineage contract readiness is not yet proven at the API payload boundary.

3. Confidence and explainability are compact, but not sufficient for the broader MVP explainability payload.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:99` and `v2/backend/app/domain/trainer_prediction_output/record.py:100` carry `confidence_raw` and `confidence_calibrated`.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:132` and `v2/backend/app/domain/trainer_prediction_output/record.py:133` validate both scores as finite floats in `[0.0, 1.0]`.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:105` and `v2/backend/app/domain/trainer_prediction_output/record.py:106` carry top positive/negative feature code tuples, with disjointness enforced at `v2/backend/app/domain/trainer_prediction_output/record.py:157`.
   - Existing decision-explainability tests expect richer fields such as `top_positive_feature_contributors`, `top_negative_feature_contributors`, `feature_freshness_flags`, `previous_confidence`, `confidence_delta`, and `confidence_calibration`.
   - Blocker: the prediction output record does not preserve confidence components, calibration metadata, source references, per-feature freshness flags, previous confidence/delta, or contributor-level payloads needed by explain/read consumers.
   - Impact: `/predictions/{id}/explain` cannot be implemented from this record alone without rehydrating external context.

4. Stale/missing/unused feature flags exist in feature snapshots but are collapsed before prediction output.
   - `v2/backend/app/services/feature_snapshots/service.py:43` through `v2/backend/app/services/feature_snapshots/service.py:46` compute missing, stale, and unused features.
   - `v2/backend/app/services/feature_snapshots/service.py:73` through `v2/backend/app/services/feature_snapshots/service.py:76` stores those flags plus `confidence_input_ready`.
   - `v2/backend/app/domain/features/validation.py:16` through `v2/backend/app/domain/features/validation.py:23` treats missing/stale/not-ready/source-ungrounded inputs as trainer input errors.
   - `v2/backend/app/domain/trainer_prediction_output/record.py:103` and `v2/backend/app/domain/trainer_prediction_output/record.py:104` only carry `freshness_flag` and `source_freshness_age_ms`.
   - Blocker: `assemble_prediction_record()` does not accept a `FeatureSnapshot` or validated trainer payload summary, does not enforce `confidence_input_ready`, and does not preserve stale/missing/unused feature lists.
   - Impact: feature quality evidence can be lost between feature snapshot generation and prediction output.

5. Historical PnL evidence still limits impact validation.
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:7` requires comparing large losers to trainer confidence and feature freshness.
   - `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md:9` maps trainer/orchestrator evidence to `prediction_id`, `decision_id`, and lineage.
   - Blocker: the inspected audit inputs do not provide enough concrete PnL/trade/trainer rows to prove the prediction output MVP supports loss attribution and feature-freshness failure analysis.
   - Impact: historical PnL impact remains a requirements driver, not proven evidence for this MVP.

6. No live/Redis/legacy/exchange side effects were found in the trainer prediction output slice.
   - `v2/backend/app/domain/trainer_prediction_output`, `v2/backend/app/services/trainer_prediction_output`, and `v2/backend/app/composition/trainer_prediction_output` are pure value/assembler/composition modules.
   - Restricted scans over that slice did not find Redis command usage, exchange adapters, order placement/cancel behavior, leverage/margin changes, subprocess/network behavior, or live-trading enablement.
   - Prior 2E3A, 2E3B, and 2E3C worklog reviews record passing isolated forbidden-token, import-clean, py_compile, and focused unit-test gates.

## Proposed non-live autofix tasks

1. Implement a non-live prediction ingest/read/explain path backed by an in-memory or test repository abstraction first; do not use Redis, exchange adapters, or live services.
2. Add prediction-stage lineage validation: top-level `prediction_id` must match `lineage.prediction_id`, `lineage.feature_snapshot_id` must be non-null, downstream lineage IDs must be explicit null, and parent snapshot existence must be checked through a non-live repository interface.
3. Extend the prediction output envelope or add a companion explainability payload carrying confidence components, calibration method/model/version, source references, feature freshness flags, previous confidence, confidence delta, and top contributor details.
4. Change the assembler boundary to accept a validated feature snapshot/trainer payload summary, reject `confidence_input_ready=False`, and preserve stale/missing/unused feature lists.
5. Add tests for feature snapshot -> prediction output -> read/explain projection, covering fresh, stale, missing, and unused feature cases.
6. Add local-only historical PnL fixtures with representative large winner/loser rows, confidence values, and feature freshness evidence, then assert the explainability payload supports the audit requirements without live exchange calls.

## Go / No-Go

NO-GO for Trainer Prediction Output MVP readiness.

