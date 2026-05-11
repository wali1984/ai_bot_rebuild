# Codex Parallel Review: Trainer Prediction Output MVP

Review timestamp: 2026-05-11 09:38:46 America/New_York

Verdict: READY

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/tests/unit/domain/trainer_prediction_output/`
- `v2/backend/tests/unit/services/trainer_prediction_output/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `v2/backend/app/services/feature_snapshots/service.py`
- selected orchestrator-decision propagation tests
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/178`, `179`, `190`, `198`, `199`, `204`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`
- selected legacy read-only audit references for Redis/live/exchange boundaries

## Lineage

PASS. `TrainerPredictionRecord` carries both lineage roots: `prediction_id` and `feature_snapshot_id` are required fields with non-empty, no-whitespace, max-length validation in `v2/backend/app/domain/trainer_prediction_output/record.py:90-110`.

PASS. The assembler preserves caller-provided lineage and records the injected clock as `prediction_ts_ms` without deriving IDs or touching external state in `v2/backend/app/services/trainer_prediction_output/service.py:10-54`.

PASS. The composition binder forwards `prediction_id` and `feature_snapshot_id` unchanged to the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:23-56`.

PASS. Downstream orchestrator-decision service propagates `prediction_id` and `feature_snapshot_id` into `OrchestratorDecisionRecord` with `live_blocked=True`, preserving the lineage chain for the next MVP stage.

## Confidence And Explainability Payload

PASS for Trainer Prediction Output MVP scope. The prediction output record carries `confidence_raw`, `confidence_calibrated`, `freshness_flag`, `source_freshness_age_ms`, `top_positive_feature_codes`, and `top_negative_feature_codes` with range/type/disjointness invariants in `record.py:98-106` and `record.py:132-168`.

Residual note, not a blocker: the richer Stage A parity explainability bundle remains in `v2/backend/app/domain/trainer_parity/stage_a_record.py:13-66` and validator expectations remain in `v2/backend/app/domain/trainer_parity/explainability_validator.py:16-78`. The 2E3 MVP intentionally narrowed output to confidence values plus top feature code attribution per `179_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_SPEC.md`; no full `confidence_components`, calibration method, source-key references, or per-feature freshness metadata object is emitted by this MVP record.

## Stale, Missing, And Unused Feature Flags

PASS. `FeatureSnapshotService` computes `stale_features`, `missing_features`, `unused_features`, and `confidence_input_ready` before trainer consumption in `v2/backend/app/services/feature_snapshots/service.py`. Unit coverage confirms missing `spread_bps`, stale `close`, and unused `debug_unused_feature` are detected and mark trainer readiness false.

PASS. The trainer prediction output record has coarse `freshness_flag` values `fresh`, `stale`, and `missing`; missing requires `source_freshness_age_ms=None`, while fresh/stale require an integer age.

Residual note, not a blocker: unused features are retained at feature snapshot level and are not repeated inside `TrainerPredictionRecord`. That matches the MVP shape because the record links back to `feature_snapshot_id`.

## Historical PnL Evidence Impact

PASS. Historical audit requirements explicitly call for comparing large losers to trainer confidence and feature freshness, default-denying stale/missing data, and replay/backtest scenarios. The reviewed MVP provides the needed prediction lineage, confidence fields, and freshness flag for those downstream consumers.

PASS. The selected orchestrator-decision tests confirm stale and missing prediction freshness abstain rather than proceed, preserving the historical PnL audit requirement that stale/missing data default-deny before any later paper/live lane.

Residual note, not a blocker: this MVP does not itself implement PnL replay, fee/funding accounting, or large-loser scenario generation. Those are mapped to paper/backtest lanes in `historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`.

## Safety And Isolation

PASS. No trainer prediction output domain/service/composition source contains direct Redis, HTTP, FastAPI, exchange, live-order, leverage, margin, subprocess, socket, or environment access tokens in the reviewed source scan.

PASS. The reviewed trainer prediction output code is pure value/domain/service/composition code. It does not import legacy bot modules, does not read or write Redis, does not restart services, does not place/cancel orders, does not change leverage/margin, does not enable live trading, and does not deploy.

PASS. Targeted tests were run with bytecode writes and pytest cache disabled:

- `73 passed` for domain/service/composition trainer prediction output suites.
- `4 passed` for feature stale/missing/unused and orchestrator freshness/lineage propagation checks.

## Concrete Blockers

None.

## Proposed Non-Live Follow-Up Tasks

1. Add a non-live projection adapter from the richer `StageATrainerRecord` explainability bundle into the MVP `TrainerPredictionRecord` fields, with explicit documentation of omitted fields and a link back to `feature_snapshot_id`.
2. Add a read-only evidence test that reconstructs confidence/freshness for one historical large-loser fixture through `feature_snapshot_id -> prediction_id -> decision_id`.
3. Add a non-live report projection that displays unused feature names from `FeatureSnapshot.trainer_payload()` beside the linked prediction record, without duplicating unused flags into the prediction record.

CODEX_PARALLEL_REVIEW_READY
