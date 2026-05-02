# Phase 2E1.A — Trainer Subprocess Adapter Implementation Report

## Status

Phase 2E1.A materialized a non-live trainer subprocess adapter foundation
under the approved V2 path:

`v2/backend/app/adapters/trainer/`

The adapter does not import the legacy trainer, Redis clients, or
`subprocess`. Process execution is delegated to an injected runner. The
default runner is isolated in `default_runner.py` and uses
`subprocess.run(..., shell=False)`.

## Files

Adapter source:

- `__init__.py` — public package exports.
- `modes.py` — `TrainerSubprocessMode` enum and `ALLOWED_MODES`.
- `errors.py` — safety, timeout, and config error types.
- `audit_emitter.py` — immutable audit event and `to_dict` helper.
- `subprocess_adapter.py` — injected-runner adapter and safety validation.
- `default_runner.py` — isolated default subprocess runner.

Tests:

- `conftest.py` — fake runner, audit capture, deterministic clock, adapter factory.
- `test_modes.py` — mode enum and argv mode behavior.
- `test_subprocess_adapter_argv_vocabulary.py` — argv contract and unsafe argv/path rejection.
- `test_subprocess_adapter_env_isolation.py` — no `os.environ` passthrough and no env values in audit payloads.
- `test_subprocess_adapter_timeout.py` — timeout exception and audit behavior.
- `test_subprocess_adapter_audit_emission.py` — success/error audit shape, timestamps, digests, capture paths.
- `test_subprocess_adapter_safety_blocks.py` — static safety boundaries, no Redis/legacy imports, `shell=False`.

## Spec Mapping

The implementation maps the Phase 2E1.A spec as follows:

- Exactly three allowed modes: `read_only`, `status`, `export`.
- Adapter `invoke` requires `TrainerSubprocessMode`; raw strings are rejected.
- `extra_argv` is default-deny and non-empty tuples are rejected.
- Subprocess argv is exactly `[legacy_python_path, legacy_script_path, "--mode", mode.value]`.
- Adapter environment is built only from `env_allowlist`; it does not read `os.environ`.
- Capture paths are under `capture_dir/<task_id>/stdout.bin` and `stderr.bin`.
- One audit event is emitted for success, timeout, or runner exception.
- Audit events include deterministic `clock_ms` timestamps and stdout/stderr SHA256 digests.
- The adapter has no Redis import, no legacy trainer import, no network call, and no direct subprocess call.
- `default_runner.py` is the only adapter package module that imports `subprocess`, and it uses `shell=False`.

## Local Validation

Local validation is recorded in `07_2E1A_TEST_INVOCATION_LOG.md`.

Result:

- Python compile passed.
- `pytest -q v2/backend/tests/unit/adapters/trainer` passed with `29 passed`.
- Safety scan completed with matches limited to policy/spec text that forbids legacy path access.

## Safety Result

No live trainer restart, Redis write, legacy mutation, exchange action,
deployment, or live trading enablement was performed.
