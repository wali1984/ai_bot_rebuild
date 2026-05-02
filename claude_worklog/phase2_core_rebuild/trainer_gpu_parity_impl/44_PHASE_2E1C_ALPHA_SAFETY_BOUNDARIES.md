# Phase 2E1.C.α — Safety Boundaries

The 2E1.C.α domain layer is the first authored fragment of the trainer
internal liveness monitor. It does NOT observe live state, does NOT
write Redis, does NOT spawn subprocesses, does NOT touch the legacy
trainer venv, and does NOT call the network. The boundaries below
govern both the implementation task (060) and the local validation
task (061).

## Read scope

Implementer may read:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`
- `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/42_PHASE_2E1C_ALPHA_LIVENESS_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/43_PHASE_2E1C_ALPHA_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`
  (for shape parallels only)
- existing files under `v2/backend/app/domain/trainer_parity/` and
  `v2/backend/tests/unit/domain/trainer_parity/` (for code style
  parallels only — MUST NOT be edited)

Implementer MUST NOT read:

- any file under `/home/wali/Desktop/AI BOT/`
- any `.env` or secrets file
- any Redis key
- any network resource

## Write scope

Implementer may write only:

- `v2/backend/app/domain/trainer_liveness/__init__.py`
- `v2/backend/app/domain/trainer_liveness/errors.py`
- `v2/backend/app/domain/trainer_liveness/signal_snapshot.py`
- `v2/backend/app/domain/trainer_liveness/sla_config.py`
- `v2/backend/app/domain/trainer_liveness/alert.py`
- `v2/backend/app/domain/trainer_liveness/evaluator.py`
- `v2/backend/tests/unit/domain/trainer_liveness/__init__.py`
- `v2/backend/tests/unit/domain/trainer_liveness/conftest.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_signal_snapshot_invariants.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_sla_config_invariants.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_alert_invariants.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_no_alert.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_age_exceeds.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_zero_stream_growth.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_fatal_log_signature.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_evaluator_multi_reason.py`
- `v2/backend/tests/unit/domain/trainer_liveness/test_public_surface.py`
- worklog reports listed in the implementation task's
  `required_output_files`.

## Forbidden actions

- Modify any file under `legacy_reference/`.
- Modify any file under `/home/wali/Desktop/AI BOT/`.
- Modify any file under `v2/backend/app/domain/trainer_parity/` or
  `v2/backend/tests/unit/domain/trainer_parity/`.
- Modify any `.env` or secrets file.
- Run any subprocess other than `python -m py_compile`,
  `pytest`, `python -c <safe expression>`, and `grep` / `rg`.
- Start the legacy trainer venv.
- Import any legacy module.
- Connect to Redis.
- Connect to the network.
- Place exchange orders.
- Cancel exchange orders.
- Change leverage or margin.
- Restart any running service.
- Enable live trading.
- Deploy.
- Run production migrations.
- Expose or commit secrets.

## Authoring tool discipline

- Implementer MUST use the `Write` tool to author each Python source
  file and test file.
- Implementer MUST NOT use `BEGIN_FILE` / `END_FILE` blocks for any
  Python file. The harness has a known materialization defect that
  emits the trailing `END_FILE: <path>` marker as bare top-level text
  inside the materialized file, producing a `SyntaxError` at compile
  time. The 2E1.B END_FILE marker incident is documented in
  `claude_worklog/autonomous_control_plane/PLANNER_PHASE2E1B_END_FILE_MARKER_DISCOVERY.md`.
- Implementer MAY use `BEGIN_FILE` / `END_FILE` blocks for Markdown
  worklog reports (the harness defect is harmless in Markdown).
- Implementer MUST verify after authoring that
  `rg "^END_FILE:" v2/backend/app/domain/trainer_liveness/` and
  `rg "^END_FILE:" v2/backend/tests/unit/domain/trainer_liveness/`
  both return zero hits before declaring the implementation ready.

## Stop conditions

The implementer halts and emits
`PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_BLOCKED` to the GO_NO_GO marker
file under any of:

- a forbidden token leak detected during self-grep;
- a `python -m py_compile` failure on any of the 16 authored files;
- a forbidden-import detection in `test_public_surface.py`;
- any directive that would require Redis, subprocess, network, GPU,
  legacy import, or live behavior.

PHASE2E1C_ALPHA_TRAINER_LIVENESS_SAFETY_BOUNDARIES_READY
