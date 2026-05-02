# Phase 2E1.A Subprocess Adapter Specification

Binding contract for supervisor task `053`. Codex (task `054`) verifies
each requirement against the materialized files.

## Module layout

- `v2/backend/app/adapters/trainer/__init__.py`
  - Public re-exports: `SubprocessTrainerAdapter`, `TrainerSubprocessMode`,
    `TrainerSubprocessAuditEvent`, `TrainerSubprocessSafetyError`,
    `TrainerSubprocessTimeoutError`.
- `v2/backend/app/adapters/trainer/modes.py`
  - `class TrainerSubprocessMode(str, Enum)` with exactly three members:
    `READ_ONLY = "read_only"`, `STATUS = "status"`, `EXPORT = "export"`.
  - Module-level frozenset `ALLOWED_MODES` mirroring the enum values.
  - No other constants. No I/O at import.
- `v2/backend/app/adapters/trainer/errors.py`
  - `class TrainerSubprocessSafetyError(RuntimeError)`.
  - `class TrainerSubprocessTimeoutError(RuntimeError)`.
  - `class TrainerSubprocessConfigError(RuntimeError)`.
  - No other types.
- `v2/backend/app/adapters/trainer/audit_emitter.py`
  - `@dataclass(frozen=True) class TrainerSubprocessAuditEvent` with
    fields: `task_id: str`, `mode: TrainerSubprocessMode`,
    `legacy_python_path: str`, `legacy_script_path: str`,
    `pid: int | None`, `start_ts_ms: int`, `end_ts_ms: int | None`,
    `returncode: int | None`, `stdout_digest_sha256: str | None`,
    `stderr_digest_sha256: str | None`, `stdout_path: str | None`,
    `stderr_path: str | None`, `safety_violation: str | None`.
  - `def to_dict(event: TrainerSubprocessAuditEvent) -> dict[str, Any]`.
  - No actual emission; emission is the caller's job (this keeps the
    audit ledger writer decoupled and lets Phase 2E1.D wire it).
- `v2/backend/app/adapters/trainer/subprocess_adapter.py`
  - `@dataclass(frozen=True) class SubprocessRunResult` with fields
    `returncode: int`, `stdout: bytes`, `stderr: bytes`,
    `pid: int | None`, `start_ts_ms: int`, `end_ts_ms: int`.
  - `class SubprocessRunner(Protocol)` with one method
    `run(argv: list[str], *, env: dict[str, str], cwd: str, timeout_s: float, stdout_path: str, stderr_path: str) -> SubprocessRunResult`.
  - `class SubprocessTrainerAdapter`:
    - Constructor parameters (all required, no defaults that would
      reach the legacy filesystem):
      `legacy_python_path: str`, `legacy_script_path: str`,
      `legacy_bot_root: str`, `capture_dir: str`, `timeout_s: float`,
      `runner: SubprocessRunner`, `clock_ms: Callable[[], int]`,
      `env_allowlist: frozenset[str]`,
      `audit_sink: Callable[[TrainerSubprocessAuditEvent], None]`.
    - Method `invoke(self, *, task_id: str, mode: TrainerSubprocessMode, extra_argv: tuple[str, ...] = ()) -> SubprocessRunResult`.
      - Validates `mode in ALLOWED_MODES`.
      - Validates that every entry in `extra_argv` is in a hard-coded
        positive allowlist of safe flag forms (none required for
        Phase 2E1.A; the parameter exists but the allowlist is empty,
        so any non-empty `extra_argv` raises
        `TrainerSubprocessSafetyError`).
      - Builds `argv = [legacy_python_path, legacy_script_path, "--mode", mode.value]`.
      - Builds env from `env_allowlist` only — no `os.environ` passthrough.
      - Builds capture paths under `capture_dir/<task_id>/`.
      - Calls `runner.run(...)` with `timeout_s`.
      - On `subprocess.TimeoutExpired` (mapped by the runner), raises
        `TrainerSubprocessTimeoutError` and emits an audit event with
        `safety_violation = "timeout"`.
      - On any other exception, emits an audit event with
        `safety_violation = "runner_exception:<class>"` and re-raises.
      - On success, emits an audit event with `safety_violation = None`.
      - Returns the `SubprocessRunResult`.
    - The adapter never calls `subprocess.*` directly. The default
      production runner is provided in a separate file —
      `v2/backend/app/adapters/trainer/default_runner.py` — but
      Phase 2E1.A does NOT instantiate the default runner against the
      real legacy filesystem; the production wiring is gated to
      Phase 2E1.D.

## Hard rules (Codex must verify)

- The argv list contains exactly four elements:
  `[legacy_python_path, legacy_script_path, "--mode", mode.value]`.
- The argv list contains no shell metacharacters; the runner uses
  `subprocess.run(..., shell=False)` (verified by inspection of
  `default_runner.py` plus a unit test).
- The env dict passed to the runner contains only keys present in
  `env_allowlist`. No `os.environ` lookup is performed by the
  adapter (verified by a unit test that injects a poisoned
  `os.environ` and asserts it does not leak into the runner call).
- No legacy module is imported. The adapter file does not contain
  any `import` statement that targets `legacy_reference`,
  `/home/wali/Desktop/AI BOT`, `rl.hybrid_trainer`,
  `rl.orchestrator_worker`, `trading.trader`, or `trading.trader_asjad`.
- The adapter does not import `redis`, `redis.asyncio`, or any other
  Redis client.
- The adapter raises `TrainerSubprocessSafetyError` if `mode` is not
  one of `read_only`, `status`, `export`.
- The adapter raises `TrainerSubprocessSafetyError` if `extra_argv`
  is non-empty (Phase 2E1.A allowlist is empty).
- The adapter raises `TrainerSubprocessSafetyError` if
  `legacy_python_path` or `legacy_script_path` is empty or contains
  any of the literal substrings: `;`, `|`, `&&`, `\`\``, `$(`.
- The adapter emits exactly one audit event per `invoke` call —
  success, timeout, or error.
- The audit event includes `start_ts_ms` and `end_ts_ms` from
  `clock_ms`, never from `time.time()` or `time.monotonic()` directly.

## Forbidden behaviors (Codex must verify absent)

- No call to `os.system`, `os.popen`, `subprocess.call`,
  `subprocess.check_call`, `subprocess.check_output`,
  `subprocess.Popen`, or `pty.spawn` anywhere in the adapter file.
  These are confined to `default_runner.py` only.
- No filesystem write outside `capture_dir`.
- No network call.
- No legacy Redis observation.
- No env passthrough by default.
- No swallowing of exceptions.
- No log line that includes a secret value (env values are not logged;
  only env keys may appear in audit metadata).

PHASE2E1A_TRAINER_PARITY_SUBPROCESS_ADAPTER_SPEC_READY
