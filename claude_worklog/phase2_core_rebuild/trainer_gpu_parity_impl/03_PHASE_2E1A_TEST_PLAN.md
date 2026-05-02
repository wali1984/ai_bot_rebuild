# Phase 2E1.A Test Plan

All tests run under `pytest` against `v2/backend/`. No test spawns the
legacy trainer. No test reads from the legacy filesystem. No test
touches Redis. No test makes a network call.

## Test files

- `v2/backend/tests/unit/adapters/trainer/__init__.py` — empty init.
- `v2/backend/tests/unit/adapters/trainer/conftest.py`
  - Provides `FakeRunner`, a `SubprocessRunner` implementation that
    records every call and returns a programmable `SubprocessRunResult`
    or raises a programmable exception.
  - Provides `make_adapter(runner=...)` factory with safe defaults that
    point at fake paths under `tmp_path` — never at the real legacy
    filesystem.
  - Provides `audit_capture` fixture — a list-backed sink that the
    test reads to assert audit shape.
- `v2/backend/tests/unit/adapters/trainer/test_modes.py`
  - `test_modes_enum_membership_is_exactly_three`.
  - `test_modes_enum_values_match_subprocess_argv`.
  - `test_modes_allowed_modes_frozenset_matches_enum`.
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_argv_vocabulary.py`
  - `test_invoke_read_only_builds_expected_argv`.
  - `test_invoke_status_builds_expected_argv`.
  - `test_invoke_export_builds_expected_argv`.
  - `test_invoke_rejects_string_mode_value`.
  - `test_invoke_rejects_non_enum_mode`.
  - `test_invoke_rejects_non_empty_extra_argv`.
  - `test_invoke_rejects_path_with_shell_metacharacters` (parametrized
    over `;`, `|`, `&&`, backtick, `$(` — but the spec strings are
    referenced via repr to keep the test file free of literal command
    constructs).
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_env_isolation.py`
  - `test_invoke_does_not_pass_through_os_environ` — sets a poison key
    on `os.environ` via monkeypatch, asserts the runner-received env
    does not contain it.
  - `test_invoke_passes_only_allowlisted_env_keys` — supplies an
    allowlist `{"PYTHONUNBUFFERED"}` plus a poisoned `os.environ`,
    asserts the runner-received env contains only the allowlist key.
  - `test_invoke_env_values_are_not_audit_logged` — supplies a sentinel
    env value, asserts the audit event payload (via `to_dict`) does
    not contain the sentinel value as a substring of any field.
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_timeout.py`
  - `test_invoke_raises_timeout_error_when_runner_times_out`.
  - `test_invoke_emits_audit_event_with_timeout_violation`.
  - `test_invoke_returncode_none_on_timeout`.
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_audit_emission.py`
  - `test_invoke_emits_exactly_one_audit_event_on_success`.
  - `test_invoke_emits_exactly_one_audit_event_on_runner_exception`.
  - `test_invoke_audit_event_carries_start_and_end_ts_from_clock_ms`.
  - `test_invoke_audit_event_carries_stdout_and_stderr_digests`.
  - `test_invoke_audit_event_carries_stdout_and_stderr_paths_under_capture_dir`.
- `v2/backend/tests/unit/adapters/trainer/test_subprocess_adapter_safety_blocks.py`
  - `test_adapter_module_does_not_import_subprocess_directly` — opens
    the adapter source, asserts no `import subprocess` line.
  - `test_adapter_module_does_not_import_legacy_modules` — opens the
    adapter source, asserts no import line targets `legacy_reference`,
    `rl.hybrid_trainer`, `rl.orchestrator_worker`, `trading.trader`,
    or `trading.trader_asjad`.
  - `test_adapter_module_does_not_import_redis` — opens the adapter
    source, asserts no `import redis` line.
  - `test_default_runner_uses_shell_false` — opens
    `default_runner.py`, asserts `shell=False` is present in every
    `subprocess.run` call.

## Determinism

- Tests use a fixed `clock_ms = lambda: <counter>` so timestamps are
  reproducible.
- Tests do not call `time.sleep`.
- Tests do not write outside `tmp_path`.

## Coverage gate

Phase 2E1.A is acceptable when every test in this plan passes locally
under `pytest -q v2/backend/tests/unit/adapters/trainer/` with zero
failures, zero errors, and zero warnings. The supervisor task `053`
records the test invocation log under
`claude_worklog/agent_supervisor/runs/053_trainer_parity_2e1a_implementation/<ts>/`.

PHASE2E1A_TRAINER_PARITY_TEST_PLAN_READY
