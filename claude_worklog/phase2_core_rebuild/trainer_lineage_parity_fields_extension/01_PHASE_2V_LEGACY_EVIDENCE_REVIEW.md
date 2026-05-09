# Phase 2V — Legacy Evidence Review

## Legacy contract evidence (already authored)

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md` — Stage A trainer-inference output contract mandates `model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `worker_health_status` on every prediction record.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md` — confidence raw vs calibrated separation.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md` — `worker_health_status` requirement and the legacy "process alive but prediction worker dead" failure pattern.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/03_CHECKPOINT_AND_MODEL_LOADING_PARITY.md` — model/checkpoint identity preservation.
- `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` — lineage chain.

## Legacy hybrid trainer atlas evidence

- `claude_worklog/trainer_atlas/HYBRID_TRAINER_ATLAS.md`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_CHECKPOINT_PATHS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIDENCE_PATHS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_FEATURE_PATHS.json`

These confirm that the legacy hybrid trainer (`rl.hybrid_trainer`) produced predictions tied to a model name and checkpoint path, and emitted both raw and calibrated confidence internally, but did not surface a stable typed `worker_health_status` on the wire — making the "alive but worker dead" failure invisible to monitors.

## Legacy runtime / read-only audit evidence

- `claude_worklog/legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`
- `claude_worklog/legacy_readonly_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` (where present)

These document the operational gap that REQ_0006 was authored to close: predictions that did not carry trainer worker liveness, model identity, or distinct raw vs calibrated confidence, leaving operators and the risk gateway blind during silent worker failures.

## Active-gap evidence

- `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/trainer_lineage_coverage.json` — explicitly lists the five missing fields.
- `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/trainer_evidence_gaps.md` — same five fields.
- `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md` — `TRAINER_LINEAGE_AND_READINESS_BLOCKED`.

## Requirement evidence

- `claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md` — adds confidence attribution, prediction worker health, and lineage on every record.
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md` — confidence-change surface must show model/checkpoint version.
- `claude_worklog/requirements_inbox/REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md` — Lane A scope includes trainer prediction output, `prediction_id` / `feature_snapshot_id` emission, confidence attribution.
- `claude_worklog/requirements_inbox/REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md` — Lane A approved categories include trainer prediction output and confidence attribution.
- `claude_worklog/requirements_inbox/REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md` — V2 must fix missing model/checkpoint lineage and worker liveness.

## Legacy failure addressed by Phase 2V

1. Legacy "process alive but prediction worker dead" — V2 emits `trainer_worker_liveness` per scenario; the LAB hedge-unwind fixture explicitly carries the `worker_dead` value to demonstrate operator-visible detection.
2. Legacy predictions could not be traced to a specific model or checkpoint — V2 emits `model_version` and `checkpoint_id` on every projection row.
3. Legacy ambiguity between raw and calibrated confidence — V2 emits `confidence_raw` and `confidence_calibrated` distinctly on every row, while keeping the existing `confidence` field as the calibrated convenience alias.

PHASE_2V_LEGACY_EVIDENCE_REVIEW_READY
