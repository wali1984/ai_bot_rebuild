# Phase 2E1.A — Subprocess Adapter Codex Remediation Task

This task remediates the two blockers and one minor finding recorded
in `09_2E1A_CODEX_REVIEW.md` and `10_2E1A_CODEX_GO_NO_GO.md` for the
trainer subprocess adapter foundation. The remediation re-emits a
narrow set of files that already exist under
`v2/backend/app/adapters/trainer/` and the corresponding test package.
No new Phase 2E1 sub-phase is opened by this task; per the sequencing
rule in `01_PHASE_BREAKDOWN.md`, planner does not advance to Phase
2E1.B until Codex re-reviews this remediation and PASSes.

## Inputs (frozen)

- `02_PHASE_2E1A_SUBPROCESS_ADAPTER_SPEC.md` — Phase 2E1.A binding contract.
- `03_PHASE_2E1A_TEST_PLAN.md` — Phase 2E1.A test plan.
- `04_PHASE_2E1A_SAFETY_BOUNDARIES.md` — Phase 2E1.A safety envelope.
- `09_2E1A_CODEX_REVIEW.md` — Codex review verdict and findings.
- `10_2E1A_CODEX_GO_NO_GO.md` — Codex FAIL marker.

## Findings to remediate

### Blocker 1 — Success-path audit `end_ts_ms` is runner-controlled

- Codex evidence:
  `v2/backend/app/adapters/trainer/subprocess_adapter.py` records
  `start_ts_ms = int(self._clock_ms())` but emits
  `end_ts_ms=result.end_ts_ms` on success. The default runner returns
  `start_ts_ms=0` and `end_ts_ms=0`, so a default-runner success audit
  would record an end timestamp of `0` instead of an adapter-clock
  value.
- Spec violation:
  `02_PHASE_2E1A_SUBPROCESS_ADAPTER_SPEC.md` Hard rules:
  "The audit event includes `start_ts_ms` and `end_ts_ms` from
  `clock_ms`, never from `time.time()` or `time.monotonic()` directly."
- Remediation: in
  `v2/backend/app/adapters/trainer/subprocess_adapter.py`, after the
  runner returns successfully, call `self._clock_ms()` once and use
  the resulting integer as the audit `end_ts_ms`. The success path
  must NOT consume `result.end_ts_ms`. The timeout and
  runner-exception branches already source `end_ts_ms` from
  `self._clock_ms()` and remain unchanged.
- Test reinforcement: in
  `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_audit_emission.py`,
  rewrite `test_invoke_audit_event_carries_start_and_end_ts_from_clock_ms`
  so it asserts the success-path audit `end_ts_ms` equals the second
  value emitted by the conftest clock fixture (`2000`) and
  additionally asserts that the runner-supplied `end_ts_ms=222` does
  NOT leak into the audit event. This catches the regression Codex
  flagged.

### Blocker 2 — Validation log lacks explicit zero-failure record

- Codex evidence: `07_2E1A_TEST_INVOCATION_LOG.md` reports
  "passed with `29 passed`" but does not explicitly record zero
  failures, zero errors, and zero warnings, and Codex could not
  verify the green local validation record independently.
- Remediation: emit a fresh remediation test log
  `24_2E1A_REMEDIATION_TEST_LOG.md` that names the exact validation
  command for the remediated files, requires the operator to record
  pytest exit code `0`, and requires the operator-run-result section
  to state explicitly: `0 failed`, `0 errors`, `0 warnings`. The
  historical `07_2E1A_TEST_INVOCATION_LOG.md` is preserved unchanged
  for audit trail; Codex re-review reads `24_` for the green record.

### Minor — Public package surface broader than spec

- Codex evidence:
  `v2/backend/app/adapters/trainer/__init__.py` re-exports
  `ALLOWED_MODES`, `DefaultSubprocessRunner`, `SubprocessRunResult`,
  `SubprocessRunner`, `TrainerSubprocessConfigError`, and `to_dict`,
  and imports `default_runner` at package import time. This broadens
  the public surface beyond the five names listed in
  `02_PHASE_2E1A_SUBPROCESS_ADAPTER_SPEC.md` Module layout.
- Remediation: re-emit
  `v2/backend/app/adapters/trainer/__init__.py` so the package
  imports and `__all__` contain exactly five names —
  `SubprocessTrainerAdapter`, `TrainerSubprocessMode`,
  `TrainerSubprocessAuditEvent`, `TrainerSubprocessSafetyError`,
  `TrainerSubprocessTimeoutError`. Re-emit four test files that
  imported non-spec symbols from the package root so they import
  those symbols from their submodules instead:
  - `tests/unit/adapters/trainer/conftest.py` —
    `SubprocessRunResult` from `subprocess_adapter` submodule.
  - `tests/unit/adapters/trainer/test_modes.py` —
    `ALLOWED_MODES` from `modes` submodule.
  - `tests/unit/adapters/trainer/test_subprocess_adapter_audit_emission.py`
    — `SubprocessRunResult` from `subprocess_adapter` submodule.
  - `tests/unit/adapters/trainer/test_subprocess_adapter_env_isolation.py`
    — `to_dict` from `audit_emitter` submodule.
  The submodule import in
  `tests/unit/adapters/trainer/test_subprocess_adapter_safety_blocks.py`
  (`from v2.backend.app.adapters.trainer import default_runner,
  subprocess_adapter`) is preserved unchanged; Python's submodule
  resolution remains valid without an explicit package-level
  re-export.

## Out-of-scope for this task

- No change to Phase 2E1.A spec, test plan, or safety boundaries.
- No introduction of Phase 2E1.B surface
  (`v2/backend/app/domain/trainer_parity/`).
- No legacy trainer modification.
- No Redis or live runtime change.
- No exchange action.
- No new public symbols.

## Required output files

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/22_2E1A_REMEDIATION_TASK.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/23_2E1A_REMEDIATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/24_2E1A_REMEDIATION_TEST_LOG.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/25_2E1A_REMEDIATION_GO_NO_GO.md`
- `v2/backend/app/adapters/trainer/__init__.py`
- `v2/backend/app/adapters/trainer/subprocess_adapter.py`
- `v2/backend/tests/unit/adapters/trainer/conftest.py`
- `v2/backend/tests/unit/adapters/trainer/test_modes.py`
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_audit_emission.py`
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_env_isolation.py`

## Safety boundaries

- Output prefix allowlist:
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`,
  `v2/backend/app/adapters/trainer/`,
  `v2/backend/tests/unit/adapters/trainer/`.
- No `legacy_reference/**` modification.
- No `/home/wali/Desktop/AI BOT` access.
- No Redis read or write.
- No live-service restart.
- No exchange-side action.
- No leverage/margin change.
- No live trading enablement.
- No deployment.
- No production migration.
- No secret value emitted.

PHASE2E1A_TRAINER_PARITY_IMPL_REMEDIATION_TASK_READY
