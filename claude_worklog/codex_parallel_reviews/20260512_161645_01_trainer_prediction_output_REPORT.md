# Codex Parallel Review: Trainer Prediction Output MVP

Review timestamp: 2026-05-12 16:16:45 America/New_York

Verdict: READY

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/services/feature_snapshots/service.py`
- `v2/backend/app/domain/features/models.py`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/tests/unit/domain/trainer_prediction_output/`
- `v2/backend/tests/unit/services/trainer_prediction_output/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/191_PHASE_2E3B_PREDICTION_RECORD_ASSEMBLER_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/199_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/200_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`
- `claude_worklog/legacy_readonly_audit/09_V2_BUILD_IMPACT_MAP.md`

## Lineage

PASS. `TrainerPredictionRecord` carries `prediction_id` and `feature_snapshot_id` as required first-class fields and validates them as non-empty, no-whitespace, length-capped identifiers in `v2/backend/app/domain/trainer_prediction_output/record.py:91` and `v2/backend/app/domain/trainer_prediction_output/record.py:108`.

PASS. `assemble_prediction_record(...)` accepts both IDs as keyword-only inputs, injects only `prediction_ts_ms` from the supplied clock, and forwards `prediction_id` plus `feature_snapshot_id` unchanged into the record in `v2/backend/app/services/trainer_prediction_output/service.py:10` and `v2/backend/app/services/trainer_prediction_output/service.py:38`.

PASS. `build_trainer_prediction_output_evaluator(...)` preserves the same input contract and forwards both lineage IDs unchanged to the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:23` and `v2/backend/app/composition/trainer_prediction_output/runtime.py:40`.

PASS. Downstream orchestrator evidence remains linked: `decision_id` is derived from `prediction_id`, while `prediction_id` and `feature_snapshot_id` are propagated into `OrchestratorDecisionRecord` in `v2/backend/app/services/orchestrator_decision/service.py:76` and `v2/backend/app/services/orchestrator_decision/service.py:105`.

## Confidence And Explainability Payload

PASS. The MVP record includes `confidence_raw`, `confidence_calibrated`, `freshness_flag`, `source_freshness_age_ms`, `worker_health_status`, `top_positive_feature_codes`, and `top_negative_feature_codes` in `v2/backend/app/domain/trainer_prediction_output/record.py:99`.

PASS. Confidence values are finite floats in `[0.0, 1.0]`; top positive and negative feature code tuples are validated and must be disjoint in `v2/backend/app/domain/trainer_prediction_output/record.py:132` and `v2/backend/app/domain/trainer_prediction_output/record.py:154`.

Residual note, not a blocker: this MVP exposes compact top-K attribution codes, not weighted feature contribution objects. Rich source refs, ingestor refs, lineage-gap notes, and stale/missing/unused feature names remain joined through `feature_snapshot_id`.

## Stale, Missing, And Unused Feature Flags

PASS. Feature snapshot construction computes stale, missing, and unused feature lists before trainer output assembly in `v2/backend/app/services/feature_snapshots/service.py:43` and stores them on `FeatureSnapshot` in `v2/backend/app/services/feature_snapshots/service.py:61`.

PASS. `FeatureSnapshot.trainer_payload()` preserves `stale_features`, `missing_features`, `unused_features`, `confidence_input_ready`, source snapshot IDs, source key refs, ingestor refs, and lineage gap reason for non-live evidence joins via `feature_snapshot_id` in `v2/backend/app/domain/features/models.py:64`.

PASS. The prediction output itself enforces coarse freshness semantics: `missing` requires `source_freshness_age_ms is None`, while `fresh` and `stale` require an integer age in `v2/backend/app/domain/trainer_prediction_output/record.py:159`.

Residual note, not a blocker: unused feature names are not duplicated onto `TrainerPredictionRecord`; consumers must use `feature_snapshot_id` to inspect the full feature snapshot.

## Historical PnL Evidence Impact

PASS. Historical PnL requirements call for comparing large losers to trainer confidence and feature freshness, default-denying stale/missing data, and preserving trainer/orchestrator lineage in `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5` and `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md:7`.

PASS. The MVP supplies the handoff evidence required for that lane: `prediction_id`, `feature_snapshot_id`, calibrated confidence, freshness flag, worker health, and top feature codes. The legacy impact map also ties trainer worker health, source freshness, feature snapshots, no-live Redis handling, and downstream decision IDs to V2 requirements in `claude_worklog/legacy_readonly_audit/09_V2_BUILD_IMPACT_MAP.md:7`.

PASS. Stale and missing prediction freshness map to orchestrator abstain before any execution lane in `v2/backend/app/services/orchestrator_decision/service.py:77`, satisfying the historical requirement that stale/missing data default-deny downstream behavior.

Residual note, not a blocker: this trainer output MVP does not implement realized-PnL replay, fee/funding accounting, or large-loser scenario generation; those remain paper/backtest, risk, and ledger responsibilities.

## Safety And Isolation

PASS. A source scan over `v2/backend/app/domain/trainer_prediction_output`, `v2/backend/app/services/trainer_prediction_output`, and `v2/backend/app/composition/trainer_prediction_output` found no Redis, URL env, FastAPI, HTTP, exchange, order, leverage, margin, live-enable, subprocess, socket, environment, dynamic import, logging, or print tokens.

PASS. The reviewed trainer prediction output code is pure domain/service/composition code. It does not import legacy bot modules, read or write Redis, restart services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose credentials.

PASS. Review validation commands were local and non-live, with bytecode writes and pytest cache disabled.

## Validation Commands Run

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/trainer_prediction_output/ -q` - exit 0, `31 passed`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/services/trainer_prediction_output/ -q` - exit 0, `22 passed`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/composition/trainer_prediction_output/ -q` - exit 0, `20 passed`
- `rg -n "<forbidden/live/exchange token pattern>" v2/backend/app/domain/trainer_prediction_output v2/backend/app/services/trainer_prediction_output v2/backend/app/composition/trainer_prediction_output` - exit 1, zero matches

## Concrete Blockers

None.

## Proposed Non-Live Follow-Up Tasks

1. Add a read-only projection test that joins `feature_snapshot_id -> prediction_id -> decision_id` for a historical large-loser fixture and asserts confidence plus freshness evidence is reconstructable.
2. Add a non-live report projection that displays feature snapshot stale/missing/unused names beside the linked prediction record without duplicating those lists into `TrainerPredictionRecord`.
3. Add a compact contract note documenting that weighted explainability fields are intentionally outside this MVP, which uses top feature codes plus `feature_snapshot_id`.

CODEX_PARALLEL_REVIEW_READY
