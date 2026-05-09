# Phase 2V — Trainer Lineage Parity Fields Spec

## Five fields added to the deterministic non-live proof contract

| Field | Type | Per-scenario fixture values |
| --- | --- | --- |
| `model_version` | `str` | `hybrid_trainer_v2026_05` for all five scenarios |
| `checkpoint_id` | `str` | `ckpt_<scenario_id>_2026_05` (deterministic per row) |
| `confidence_raw` | `float` | scenario-specific value, generally `confidence + 0.04` clamped to `[0.0, 1.0]` |
| `confidence_calibrated` | `float` | equal to existing `confidence` |
| `trainer_worker_liveness` | `str` | one of `alive`, `degraded`, `worker_dead` per scenario |

## Per-scenario assignments

| `scenario_id` | `model_version` | `checkpoint_id` | `confidence_raw` | `confidence_calibrated` | `trainer_worker_liveness` |
| --- | --- | --- | --- | --- | --- |
| `safe_long_paper_intent` | `hybrid_trainer_v2026_05` | `ckpt_safe_long_paper_intent_2026_05` | `0.86` | `0.82` | `alive` |
| `stale_data_blocked` | `hybrid_trainer_v2026_05` | `ckpt_stale_data_blocked_2026_05` | `0.81` | `0.78` | `degraded` |
| `duplicate_signal_blocked` | `hybrid_trainer_v2026_05` | `ckpt_duplicate_signal_blocked_2026_05` | `0.77` | `0.74` | `alive` |
| `hedge_close_residual_exposure_blocked` | `hybrid_trainer_v2026_05` | `ckpt_hedge_close_residual_exposure_blocked_2026_05` | `0.72` | `0.69` | `alive` |
| `lab_hedge_unwind_short_squeeze` | `hybrid_trainer_v2026_05` | `ckpt_lab_hedge_unwind_short_squeeze_2026_05` | `0.69` | `0.66` | `worker_dead` |

The `worker_dead` value on the LAB scenario expresses the legacy "process alive but prediction worker dead" failure literal, so the proof projection demonstrates the operator-visible detection path.

## Emission sites

The values are emitted by `_base_lineage` so that every projection row that already carries lineage (replay/backtest scenarios, paper ledger events, risk gateway decisions, decision explainability explanations, shadow comparisons) gains the five fields automatically. No new emission site is added; the existing `_base_lineage` consumers all participate.

The five fields are also placed on `ledger_event` rows because `_ledger_event` consumes the `_base_lineage` row.

`confidence` is preserved equal to `confidence_calibrated` so the existing `test_required_lineage_fields_are_present` and `test_risk_gateway_blocks_stale_data` assertions remain green.

## Trainer gate coverage logic

`build_trainer_gate` in `claude_worklog/tools/build_autonomous_live_readiness_builder.py` reads `decision_explainability_result.json` from the proof output directory and computes:

- `model_version`: every explanation row has a non-empty, non-`evidence_missing` `model_version`.
- `checkpoint_id`: every explanation row has a non-empty, non-`evidence_missing` `checkpoint_id`.
- `confidence_raw`: every explanation row has a numeric `confidence_raw` field.
- `confidence_calibrated`: every explanation row has a numeric `confidence_calibrated` field.
- `trainer_worker_liveness`: every explanation row has a non-empty, non-`evidence_missing` `trainer_worker_liveness` value (`alive`, `degraded`, `worker_dead` are all valid coverage signals — including `worker_dead`, since the legacy failure literal is itself observability evidence).

Marker logic:
- If all five fields plus the existing fields (`feature_snapshot_id`, `prediction_id`, `confidence`, `risk_decision_id`, `execution_intent_id`, `top_positive_negative_contributors`, `stale_missing_unused_flags`, `dashboard_prediction_reasoning`) are covered, emit `TRAINER_LINEAGE_AND_READINESS_READY`.
- Otherwise emit `TRAINER_LINEAGE_AND_READINESS_BLOCKED` and list the gap names exactly as today.

The `_trainer_report` text is updated so that when the marker is `TRAINER_LINEAGE_AND_READINESS_READY`:
- `trainer live-ready: false` is preserved (final live readiness is still gated by human approval and the live-gate review).
- The reason line reads: `"fixture/proof lineage now includes model/checkpoint identity, raw/calibrated confidence, and trainer worker liveness; live trading remains blocked_human_only."`
- The trailing literal becomes `TRAINER_LINEAGE_AND_READINESS_READY`.

## Public mirror

The same payloads are written to both `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/` and `v2/frontend/public/trainer_lineage_and_readiness/latest/`, matching today's mirror behavior.

## Determinism rules

- `GENERATED_AT` in the proof module remains `"2026-05-08T00:00:00Z"`.
- The trainer gate `generated_at` field continues to use the wall clock at runtime, matching today's behavior.
- All five new field values are pure literals derived from `ProofScenario`. No environment variable, no network call, no file read other than the existing JSON read of the proof artifact.

## Hard non-live boundaries

- No model file, no checkpoint file, and no GPU runtime are loaded.
- No Redis read/write occurs.
- No exchange or live API call occurs.
- The five values are deterministic identifiers/numbers that do not encode any secret.

PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC_READY
