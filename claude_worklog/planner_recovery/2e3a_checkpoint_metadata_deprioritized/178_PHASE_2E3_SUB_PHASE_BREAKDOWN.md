# Phase 2E3 Sub-Phase Breakdown — Trainer GPU and Checkpoint Runner

This document is the canonical sub-phase plan for Phase 2E3 of
REQ_0006. Phase 2E3 builds the V2-side checkpoint and GPU telemetry
observation surface that REQ_0006 calls for in addition to the
liveness alert (Phase 2E1) and the prediction-worker health model
(Phase 2E2). It is the third milestone group inside the trainer
parity service implementation. Every sub-phase is dispatched only
after its predecessor's Codex review PASS marker is materialized.
Sub-phases land sequentially. No sub-phase opens until its
predecessor is Codex-passed.

## Predecessor gates for Phase 2E3 entry

- Phase 2E1.E composition root Codex re-review PASS
  (`PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`,
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/139_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`).
- Phase 2E2.A worker health domain Codex PASS
  (`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS`,
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/148_2E2A_WORKER_HEALTH_DOMAIN_CODEX_GO_NO_GO.md`).
- Phase 2E2.B worker health service Codex re-review PASS
  (`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS`,
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/169_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`).
- Phase 2E2.C worker health composition Codex PASS
  (`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS`,
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`).

## Source-of-truth contracts driving Phase 2E3

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/02_GPU_AND_BATCHING_PARITY_REQUIREMENTS.md`
  binds the V2-side GPU telemetry contract: `gpu_device_id`,
  per-process GPU memory high-water mark, and `last_gpu_batch_ts_ms`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/03_CHECKPOINT_AND_MODEL_LOADING_PARITY.md`
  binds the V2-side checkpoint observation contract: `checkpoint_id`,
  `model_version`, `created_ts_ms`, `promoted_flag`,
  `legacy_checkpoint_path`, `legacy_metadata_hash`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md`
  binds the subprocess boundary that delivers checkpoint and GPU
  telemetry observations from the legacy runtime to V2.
- `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`
  binds Stage A lineage fields that consume `checkpoint_id` and
  `model_version`.
- `claude_worklog/legacy_preservation/03_TRAINER_TRADER_PARITY_REQUIREMENTS.md`
  binds parity preservation of legacy checkpoint and GPU behavior.
- `claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`
  binds the executable surface authority for Phase 2E.

## Sub-phase order

### 2E3.A — Checkpoint metadata domain (this turn)

- Surface: `v2/backend/app/domain/checkpoint_metadata/`.
- Files written: `__init__.py`, `errors.py`, `promotion_status.py`,
  `checkpoint_metadata.py`, `checkpoint_validators.py`.
- Tests written: `v2/backend/tests/unit/domain/checkpoint_metadata/`
  package marker plus 20 test files (see `180`).
- Inputs consumed (read-only, no modification): standard library
  only. The checkpoint metadata domain is import-isolated and does
  not depend on any prior 2E1 or 2E2 V2 module.
- Public surface (six names): `CheckpointMetadataDomainError`,
  `CheckpointMetadata`, `validate_checkpoint_metadata`,
  `PROMOTION_STATUS_NOT_PROMOTED`, `PROMOTION_STATUS_PROMOTED`,
  `PROMOTION_STATUS_UNKNOWN`.
- Codex gate: `111` reviews `110` outputs.

### 2E3.B — GPU telemetry domain (next milestone)

- Surface (planned): `v2/backend/app/domain/gpu_telemetry/`.
- Files (planned): `__init__.py`, `errors.py`, `gpu_telemetry_record.py`,
  `gpu_telemetry_validators.py`.
- Responsibility: encode the three GPU telemetry fields per
  `02_GPU_AND_BATCHING_PARITY_REQUIREMENTS.md` as a frozen
  dataclass with full invariant coverage. No subprocess. No Redis.
- Codex gate: future task pair.

### 2E3.C — Checkpoint observation service (later milestone)

- Surface (planned): `v2/backend/app/services/checkpoint_observation/`.
- Responsibility: orchestrate read-only checkpoint metadata
  observation through the existing Phase 2E1.A subprocess adapter
  in `read_only|status` mode. Returns a `CheckpointMetadata`
  instance per call. No Redis. No legacy mutation.
- Codex gate: future task pair.

### 2E3.D — GPU telemetry observation service (later milestone)

- Surface (planned): `v2/backend/app/services/gpu_telemetry_observation/`.
- Responsibility: orchestrate read-only GPU telemetry observation
  through the existing Phase 2E1.A subprocess adapter. Returns a
  GPU telemetry record per call. No Redis. No legacy mutation.
- Codex gate: future task pair.

### 2E3.E — Checkpoint composition root (later milestone)

- Surface (planned): `v2/backend/app/composition/checkpoint_observation/`.
- Responsibility: compose the 2E3.C service with the gamma.real
  factory chain inherited from 2E1.E for any subprocess-adapter
  dependency it must build at process start.
- Codex gate: future task pair.

### 2E3.F — GPU telemetry composition root (later milestone)

- Surface (planned): `v2/backend/app/composition/gpu_telemetry_observation/`.
- Responsibility: composition-root pattern identical to 2E3.E for
  the GPU telemetry observation service.
- Codex gate: future task pair.

## Sequencing rule

If `111` (Codex review of 2E3.A) returns FAIL with concrete
blockers and zero safety violations, planner enqueues a narrow
REQ_0007 / REQ_0014 autofix task scoped to the five authored
source files plus the 20 new test files only and does not advance
to 2E3.B. If `111` returns PASS, planner opens a new cycle to
author the 2E3.B scope.

## Hard-stop reminders for every 2E3 sub-phase

- No legacy mutation under `/home/wali/Desktop/AI BOT`.
- No Redis read or write at the domain layer.
- No live service restart.
- No exchange action.
- No leverage or margin change.
- No live trading enabled.
- No deploy intent.
- No production migration.
- No secret exposure.
- No real legacy checkpoint file is read in tests.
- No real subprocess is spawned in tests.

PHASE2E3_TRAINER_GPU_CHECKPOINT_SUB_PHASE_BREAKDOWN_READY
