# Planner Turn 2V — Open Trainer Lineage Parity Fields Extension

## Date
2026-05-09

## HEAD
a473106 Add autonomous live readiness builder proof

## Context — what is closed and what is still BLOCKED

Closed (PASS markers verified):
- `V2_BACKTEST_AND_PAPER_MVP_READY` and `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`
- `NON_LIVE_OPERATOR_PROOF_HARNESS_READY_FOR_CODEX_REVIEW` and `NON_LIVE_OPERATOR_PROOF_HARNESS_CODEX_PASS`
- `AUTOMATION_LIVENESS_AND_LEGACY_TRADER_DOWN_TOLERANCE_READY`
- `AUTONOMOUS_LIVE_READINESS_BUILDER_READY`
- `CONTINUOUS_PAPER_SHADOW_RUNTIME_READY`
- `HISTORICAL_30D_REPLAY_AND_PAPER_PROOF_READY`
- `PROFESSIONAL_OPERATOR_GUI_AND_DECISION_EXPLAINABILITY_READY`
- `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`

Still BLOCKED:
- `TRAINER_LINEAGE_AND_READINESS_BLOCKED` per
  `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/trainer_lineage_coverage.json`
  with five missing trainer parity lineage fields:
  - `model_version`
  - `checkpoint_id`
  - `confidence_raw`
  - `confidence_calibrated`
  - `trainer_worker_liveness`

## Why this is the next safe non-live milestone

`TRAINER_LINEAGE_AND_READINESS_BLOCKED` is the only remaining `BLOCKED` final-readiness marker. The five missing fields are the exact prediction-output lineage fields that REQ_0006 trainer parity service requires (per `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md` Stage A: `model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `worker_health_status`). They are also explicitly required by REQ_0009 confidence-explanation surface (model/checkpoint version) and REQ_0017/REQ_0020 paper-backtest lane A (trainer prediction lineage).

The gap is mechanical:
1. `v2/backend/app/proof/non_live_operational_proof.py` `_base_lineage` does not emit those five fields per scenario row.
2. `claude_worklog/tools/build_autonomous_live_readiness_builder.py` `build_trainer_gate` hardcodes the five coverage entries to `False` instead of reading them from `decision_explainability_result.json`.

Closing the gap is a single non-live, deterministic, fixture-only edit. It does not enable live trading, does not write Redis, does not restart live services, does not place/cancel orders, does not change leverage/margin, does not deploy, does not expose secrets, and does not modify `/home/wali/Desktop/AI BOT`.

## Decision

Open Phase 2V — Trainer Lineage Parity Fields Extension as a single consolidated Lane A (`paper_backtest_mvp`) milestone authored under `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/` with planning artifacts 00-05 and implementation/codex artifacts 06-09. Implementation task `185_phase2v_trainer_lineage_parity_fields_extension_implementation` dispatches the consolidated edit. Codex review follows on PASS.

## Authorized scope summary

- Edit `v2/backend/app/proof/non_live_operational_proof.py` to emit `model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness` per scenario row on every projection.
- Edit `claude_worklog/tools/build_autonomous_live_readiness_builder.py` `build_trainer_gate` to read those five fields from the proof artifact and flip the marker to `TRAINER_LINEAGE_AND_READINESS_READY` when all five are populated.
- Extend `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py` `test_required_lineage_fields_are_present` to require the five new fields on every scenario row.
- Author `v2/backend/tests/unit/proof/test_trainer_lineage_parity_fields_coverage.py` to verify the autonomous builder reports `TRAINER_LINEAGE_AND_READINESS_READY` and zero gaps when the proof artifact is regenerated.
- Author implementation report `06_IMPLEMENTATION_REPORT.md` and milestone gate `07_GO_NO_GO.md` containing exactly `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_READY_FOR_CODEX_REVIEW`.
- Regenerate `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/` and `v2/frontend/public/trainer_lineage_and_readiness/latest/` via the builder so the marker flip is visible in the operator surface; commit those regenerated artifacts as part of the implementation milestone.

## Lane / MVP fields

- `lane`: `paper_backtest_mvp`
- `mvp_relevance`: closes REQ_0006 trainer parity service prediction-output lineage gaps and flips `TRAINER_LINEAGE_AND_READINESS` from `BLOCKED` to `READY` for the live-gate review.
- `blocked_by`: `TRAINER_LINEAGE_AND_READINESS_BLOCKED` with the five named gaps.
- `next_gate`: `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_READY_FOR_CODEX_REVIEW`.

## Hard non-live boundaries reaffirmed

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write Redis.
- Do not restart live services.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy.
- Do not run production migrations.
- Do not expose or commit secrets.
- Final live approval remains human-only.

PHASE_2V_OPEN
