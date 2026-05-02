# Phase 2E1 Sub-Phase Breakdown

Each sub-phase is dispatched only after its predecessor's Codex review
PASS marker is materialized. Sub-phases land sequentially. No sub-phase
opens Phase 2E1.B until 2E1.A is Codex-passed.

## 2E1.A — Subprocess adapter foundation

- Surface: `v2/backend/app/adapters/trainer/`.
- Files written: `subprocess_adapter.py`, `modes.py`, `audit_emitter.py`,
  `errors.py`, `__init__.py` (re-export public symbols).
- Tests written: `v2/backend/tests/unit/adapters/trainer/test_modes.py`,
  `test_subprocess_adapter_argv_vocabulary.py`,
  `test_subprocess_adapter_env_isolation.py`,
  `test_subprocess_adapter_timeout.py`,
  `test_subprocess_adapter_audit_emission.py`,
  `test_subprocess_adapter_safety_blocks.py`.
- Codex gate: `054` — review `053` outputs.

## 2E1.B — Trainer output contract dataclasses and validators

- Surface: `v2/backend/app/domain/trainer_parity/`.
- Files written: `stage_a_record.py`, `stage_b_record.py`,
  `lineage_validator.py`, `explainability_validator.py`,
  `feature_status_flags.py`, `__init__.py`.
- Tests: `v2/backend/tests/unit/domain/trainer_parity/`.
- Codex gate: future `055`.

## 2E1.C — Prediction worker liveness monitor (read-only contract only)

- Surface: `v2/backend/app/services/trainer_parity_liveness/`.
- Files written: `liveness_signals.py`, `liveness_alert.py`,
  `liveness_sink.py` (in-process abstract sink), `__init__.py`.
- Tests: `v2/backend/tests/unit/services/trainer_parity_liveness/`.
- Codex gate: future `056`.

## 2E1.D — Trainer parity service composition

- Surface: `v2/backend/app/services/trainer_parity/`.
- Files written: `service.py`, `non_live_mode.py`, `__init__.py`.
- Tests: `v2/backend/tests/unit/services/trainer_parity/` plus a
  contract test under `v2/backend/tests/contract/`.
- Codex gate: future `057`.

## Sequencing rule

If `054` (Codex review of 2E1.A) returns FAIL, planner enqueues
remediation under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
and does not advance to 2E1.B. If `054` returns PASS, planner opens a
new cycle to author the 2E1.B scope and dispatch `055`.

PHASE2E1_TRAINER_PARITY_IMPL_PHASE_BREAKDOWN_READY
