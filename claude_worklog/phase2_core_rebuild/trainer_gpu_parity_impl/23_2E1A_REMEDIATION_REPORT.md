# Phase 2E1.A — Subprocess Adapter Codex Remediation Report

## Status

This planner cycle re-emits the trainer subprocess adapter foundation
to address every blocker and the minor finding recorded by Codex in
`09_2E1A_CODEX_REVIEW.md`. No Phase 2E1.A spec, test plan, or safety
boundary document is altered. No Phase 2E1.B surface is opened. No
legacy module is touched. No Redis state is read or written. No live
runtime is restarted.

## Files re-emitted

- `v2/backend/app/adapters/trainer/__init__.py` — package public
  surface trimmed to the five spec-listed names. Submodule re-exports
  for `ALLOWED_MODES`, `DefaultSubprocessRunner`, `SubprocessRunResult`,
  `SubprocessRunner`, `TrainerSubprocessConfigError`, and `to_dict`
  removed. Submodule access remains available (e.g.
  `v2.backend.app.adapters.trainer.subprocess_adapter.SubprocessRunResult`).
- `v2/backend/app/adapters/trainer/subprocess_adapter.py` — the success
  path now calls `self._clock_ms()` once after the runner returns and
  passes the resulting integer as the audit `end_ts_ms`. The success
  path no longer consumes `result.end_ts_ms`. The timeout and
  runner-exception branches are unchanged because they already source
  `end_ts_ms` from `self._clock_ms()`.
- `v2/backend/tests/unit/adapters/trainer/conftest.py` —
  `SubprocessRunResult` is imported from
  `v2.backend.app.adapters.trainer.subprocess_adapter` instead of the
  package root.
- `v2/backend/tests/unit/adapters/trainer/test_modes.py` —
  `ALLOWED_MODES` is imported from
  `v2.backend.app.adapters.trainer.modes` instead of the package root.
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_audit_emission.py`
  — `SubprocessRunResult` is imported from
  `v2.backend.app.adapters.trainer.subprocess_adapter` instead of the
  package root. The test
  `test_invoke_audit_event_carries_start_and_end_ts_from_clock_ms`
  now asserts the success-path audit `end_ts_ms` equals the conftest
  clock fixture's second value (`2000`) and explicitly asserts that
  the runner-supplied `end_ts_ms=222` does NOT leak into the audit
  event.
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_env_isolation.py`
  — `to_dict` is imported from
  `v2.backend.app.adapters.trainer.audit_emitter` instead of the
  package root.

## Files preserved unchanged

- `v2/backend/app/adapters/trainer/modes.py`
- `v2/backend/app/adapters/trainer/errors.py`
- `v2/backend/app/adapters/trainer/audit_emitter.py`
- `v2/backend/app/adapters/trainer/default_runner.py` — its
  `SubprocessRunResult.start_ts_ms`/`end_ts_ms` values remain `0`,
  but those values no longer flow into the audit event on the
  success path because the adapter sources `end_ts_ms` from
  `self._clock_ms()`.
- `v2/backend/tests/unit/adapters/trainer/__init__.py`
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_argv_vocabulary.py`
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_safety_blocks.py`
  — its `from v2.backend.app.adapters.trainer import default_runner,
  subprocess_adapter` form is a Python submodule import; it remains
  valid after the `__init__.py` trim.
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_timeout.py`

## Spec mapping (post-remediation)

- Three-mode allowlist preserved.
- Argv vocabulary preserved.
- `extra_argv` default-deny preserved.
- Env allowlist construction preserved; no `os.environ` passthrough.
- Capture path scheme preserved (`capture_dir/<task_id>/{stdout,stderr}.bin`).
- One audit event per `invoke` preserved (success / timeout / exception).
- Audit `start_ts_ms` is sourced from `self._clock_ms()` (unchanged).
- Audit `end_ts_ms` is sourced from `self._clock_ms()` on the success
  path (newly enforced), and on the timeout and exception paths
  (already enforced).
- No `subprocess` import in `subprocess_adapter.py` (preserved).
- No legacy module import in `subprocess_adapter.py` (preserved).
- No Redis client import anywhere in the adapter package (preserved).
- `default_runner.py` still uses `subprocess.run(..., shell=False)`
  and remains the only module in the adapter package that imports
  `subprocess` (preserved).
- Public package surface is exactly five names per
  `02_PHASE_2E1A_SUBPROCESS_ADAPTER_SPEC.md` Module layout.

## Local validation

The remediation cycle is emit-only. The required local validation
command is recorded in `24_2E1A_REMEDIATION_TEST_LOG.md`. The operator
runs that command after materialization and records the run result in
that file using the canonical wording template. Codex re-review reads
`24_` for the green local validation record.

## Safety result

- No legacy file modified.
- No Redis read or write.
- No live trainer or live trader restarted.
- No exchange order placed or cancelled.
- No leverage or margin mode change.
- No live trading enabled.
- No deployment.
- No production migration.
- No secret value emitted.

PHASE2E1A_TRAINER_PARITY_IMPL_REMEDIATION_REPORT_READY
