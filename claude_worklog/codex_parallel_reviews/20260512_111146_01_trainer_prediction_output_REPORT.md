# Codex Parallel Review: Trainer Prediction Output MVP

Review timestamp: 2026-05-12 11:11:46 America/New_York

Verdict: READY

## Scope Reviewed

- `v2/backend/app/domain/trainer_prediction_output/`
- `v2/backend/app/services/trainer_prediction_output/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/tests/unit/domain/trainer_prediction_output/`
- `v2/backend/tests/unit/services/trainer_prediction_output/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `v2/backend/app/services/feature_snapshots/service.py`
- `v2/backend/app/domain/features/models.py`
- selected orchestrator-decision and risk-gateway lineage/freshness propagation tests
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/182`, `191`, `198`, `199`, `200`, `204`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`
- `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`

## Lineage

PASS. `TrainerPredictionRecord` requires both lineage roots: `prediction_id` and `feature_snapshot_id` are first-class fields and are validated as non-empty, no-whitespace identifiers in `v2/backend/app/domain/trainer_prediction_output/record.py:90` and `v2/backend/app/domain/trainer_prediction_output/record.py:108`.

PASS. `assemble_prediction_record(...)` preserves caller-provided `prediction_id` and `feature_snapshot_id`, records the injected clock into `prediction_ts_ms`, and does not derive lineage from external state in `v2/backend/app/services/trainer_prediction_output/service.py:10`.

PASS. `build_trainer_prediction_output_evaluator(...)` forwards `prediction_id` and `feature_snapshot_id` unchanged to the assembler in `v2/backend/app/composition/trainer_prediction_output/runtime.py:23`.

PASS. Downstream decision lineage is covered: `assemble_orchestrator_decision_record(...)` derives `decision_id` from `prediction_id`, propagates `prediction_id` and `feature_snapshot_id`, and emits `live_blocked=True` in `v2/backend/app/services/orchestrator_decision/service.py:76`.

## Confidence And Explainability Payload

PASS. The MVP record carries the confidence and compact explainability payload required at this layer: `confidence_raw`, `confidence_calibrated`, `freshness_flag`, `source_freshness_age_ms`, `top_positive_feature_codes`, and `top_negative_feature_codes` in `v2/backend/app/domain/trainer_prediction_output/record.py:98`.

PASS. Confidence fields are finite floats in `[0.0, 1.0]`, feature-code lists are tuples capped at 8 entries, and positive/negative feature codes must be disjoint in `v2/backend/app/domain/trainer_prediction_output/record.py:132` and `v2/backend/app/domain/trainer_prediction_output/record.py:154`.

Residual note, not a blocker: this MVP emits compact top-feature attribution codes, not the richer Stage A explainability object. Full source refs, ingestor refs, stale/missing/unused feature names, and lineage gap details remain anchored on the linked `feature_snapshot_id`.

## Stale, Missing, And Unused Feature Flags

PASS. Feature snapshot construction computes `stale_features`, `missing_features`, `unused_features`, and `confidence_input_ready` before trainer output assembly in `v2/backend/app/services/feature_snapshots/service.py:45` and `v2/backend/app/services/feature_snapshots/service.py:61`.

PASS. `FeatureSnapshot.trainer_payload()` preserves those flags for downstream read-only evidence via `feature_snapshot_id` in `v2/backend/app/domain/features/models.py:64`.

PASS. The prediction output record enforces coarse freshness semantics: `missing` requires `source_freshness_age_ms is None`, while `fresh` and `stale` require an integer age in `v2/backend/app/domain/trainer_prediction_output/record.py:159`.

Residual note, not a blocker: unused feature names are not duplicated into `TrainerPredictionRecord`; consumers must join through `feature_snapshot_id`.

## Historical PnL Evidence Impact

PASS. Historical PnL audit requirements call for comparing large losers to trainer confidence and feature freshness, default-denying stale/missing data, and replay/backtest scenarios. The MVP supplies the required `prediction_id`, `feature_snapshot_id`, calibrated confidence, freshness flag, worker status, and top feature codes for those downstream lanes.

PASS. Legacy read-only trainer evidence explicitly requires `prediction_id`, `feature_snapshot_id`, confidence attribution, and stale/missing feature blocking. The reviewed implementation satisfies those output-contract pieces without touching legacy runtime.

PASS. Downstream decision behavior preserves the historical requirement to abstain on stale or missing prediction freshness before any paper/live lane: missing and stale freshness map to `DECISION_ACTION_ABSTAIN` in `v2/backend/app/services/orchestrator_decision/service.py:77`.

Residual note, not a blocker: this MVP does not itself implement PnL replay, fee/funding accounting, or large-loser scenario generation. Those remain mapped to paper/backtest lanes by the historical audit impact map.

## Safety And Isolation

PASS. Source scan over `domain/trainer_prediction_output`, `services/trainer_prediction_output`, and `composition/trainer_prediction_output` found no Redis, URL env, HTTP, FastAPI, exchange, order, leverage, margin, subprocess, socket, environment, dynamic import, logging, or live-enable tokens.

PASS. The implementation is pure value/domain/service/composition code. It does not import legacy bot modules, read or write Redis, restart services, place or cancel orders, change leverage or margin, enable live trading, deploy, or expose credentials.

PASS. Review commands were local and non-live. Tests were run with bytecode writes and pytest cache disabled.

## Validation Commands Run

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/trainer_prediction_output v2/backend/tests/unit/services/trainer_prediction_output v2/backend/tests/unit/composition/trainer_prediction_output` — exit 0, `73 passed`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/services/risk_gateway/test_assemble_deny_orchestrator_abstained_for_abstain_freshness_stale.py v2/backend/tests/unit/services/risk_gateway/test_assemble_deny_orchestrator_abstained_for_abstain_freshness_missing.py v2/backend/tests/unit/services/risk_gateway/test_assemble_propagates_input_lineage_fields.py v2/backend/tests/unit/services/risk_gateway/test_assemble_returned_record_is_live_blocked_true.py` — exit 0, `4 passed`
- `rg -n "<forbidden/live/exchange token pattern>" v2/backend/app/domain/trainer_prediction_output v2/backend/app/services/trainer_prediction_output v2/backend/app/composition/trainer_prediction_output` — exit 1, zero matches

## Concrete Blockers

None.

## Proposed Non-Live Follow-Up Tasks

1. Add a non-live projection test that joins `feature_snapshot_id -> prediction_id -> decision_id` for a historical large-loser fixture and asserts confidence/freshness evidence is reconstructable.
2. Add a read-only report projection that displays feature snapshot stale/missing/unused names beside the linked prediction record without duplicating those lists into `TrainerPredictionRecord`.
3. Add a compact contract note documenting which richer Stage A explainability fields are intentionally represented only by top feature codes plus `feature_snapshot_id` in this MVP.

CODEX_PARALLEL_REVIEW_READY
