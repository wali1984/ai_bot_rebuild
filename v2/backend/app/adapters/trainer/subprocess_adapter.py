"""Subprocess-bounded trainer adapter for Phase 2E1.A.

This module is deliberately narrow: it validates a read-only subprocess
invocation contract and delegates execution to an injected runner. It does not
import legacy trainer modules, Redis clients, or subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Callable, Protocol

from .audit_emitter import TrainerSubprocessAuditEvent
from .errors import (
    TrainerSubprocessConfigError,
    TrainerSubprocessSafetyError,
    TrainerSubprocessTimeoutError,
)
from .modes import ALLOWED_MODES, TrainerSubprocessMode


@dataclass(frozen=True)
class SubprocessRunResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    pid: int | None
    start_ts_ms: int
    end_ts_ms: int


class SubprocessRunner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        env: dict[str, str],
        cwd: str,
        timeout_s: float,
        stdout_path: str,
        stderr_path: str,
    ) -> SubprocessRunResult:
        ...


_FORBIDDEN_PATH_FRAGMENTS = (";", "|", "&&", "``", "$(")
_SAFE_TASK_ID_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


class SubprocessTrainerAdapter:
    def __init__(
        self,
        *,
        legacy_python_path: str,
        legacy_script_path: str,
        legacy_bot_root: str,
        capture_dir: str,
        timeout_s: float,
        runner: SubprocessRunner,
        clock_ms: Callable[[], int],
        env_allowlist: frozenset[str],
        audit_sink: Callable[[TrainerSubprocessAuditEvent], None],
    ) -> None:
        self._legacy_python_path = self._validate_path_text(
            "legacy_python_path", legacy_python_path
        )
        self._legacy_script_path = self._validate_path_text(
            "legacy_script_path", legacy_script_path
        )
        self._legacy_bot_root = self._validate_path_text("legacy_bot_root", legacy_bot_root)
        self._capture_dir = self._validate_path_text("capture_dir", capture_dir)
        if timeout_s <= 0:
            raise TrainerSubprocessConfigError("timeout_s must be positive")
        if runner is None or not hasattr(runner, "run"):
            raise TrainerSubprocessConfigError("runner must implement SubprocessRunner")
        if not callable(clock_ms):
            raise TrainerSubprocessConfigError("clock_ms must be callable")
        if not isinstance(env_allowlist, frozenset):
            raise TrainerSubprocessConfigError("env_allowlist must be a frozenset")
        if not callable(audit_sink):
            raise TrainerSubprocessConfigError("audit_sink must be callable")

        self._timeout_s = float(timeout_s)
        self._runner = runner
        self._clock_ms = clock_ms
        self._env_allowlist = env_allowlist
        self._audit_sink = audit_sink

    def invoke(
        self,
        *,
        task_id: str,
        mode: TrainerSubprocessMode,
        extra_argv: tuple[str, ...] = (),
    ) -> SubprocessRunResult:
        self._validate_task_id(task_id)
        self._validate_mode(mode)
        if extra_argv:
            raise TrainerSubprocessSafetyError("extra_argv is not allowed in Phase 2E1.A")

        start_ts_ms = int(self._clock_ms())
        stdout_path, stderr_path = self._capture_paths(task_id)
        argv = [
            self._legacy_python_path,
            self._legacy_script_path,
            "--mode",
            mode.value,
        ]
        env = self._build_env()

        try:
            result = self._runner.run(
                argv,
                env=env,
                cwd=self._legacy_bot_root,
                timeout_s=self._timeout_s,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        except TrainerSubprocessTimeoutError:
            end_ts_ms = int(self._clock_ms())
            self._emit_audit(
                task_id=task_id,
                mode=mode,
                pid=None,
                start_ts_ms=start_ts_ms,
                end_ts_ms=end_ts_ms,
                returncode=None,
                stdout=b"",
                stderr=b"",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                safety_violation="timeout",
            )
            raise
        except Exception as exc:
            end_ts_ms = int(self._clock_ms())
            self._emit_audit(
                task_id=task_id,
                mode=mode,
                pid=None,
                start_ts_ms=start_ts_ms,
                end_ts_ms=end_ts_ms,
                returncode=None,
                stdout=b"",
                stderr=b"",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                safety_violation=f"runner_exception:{exc.__class__.__name__}",
            )
            raise

        end_ts_ms = int(self._clock_ms())
        self._emit_audit(
            task_id=task_id,
            mode=mode,
            pid=result.pid,
            start_ts_ms=start_ts_ms,
            end_ts_ms=end_ts_ms,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            safety_violation=None,
        )
        return result

    def _build_env(self) -> dict[str, str]:
        return {key: "" for key in sorted(self._env_allowlist)}

    def _capture_paths(self, task_id: str) -> tuple[str, str]:
        task_dir = Path(self._capture_dir) / task_id
        return str(task_dir / "stdout.bin"), str(task_dir / "stderr.bin")

    def _emit_audit(
        self,
        *,
        task_id: str,
        mode: TrainerSubprocessMode,
        pid: int | None,
        start_ts_ms: int,
        end_ts_ms: int | None,
        returncode: int | None,
        stdout: bytes,
        stderr: bytes,
        stdout_path: str | None,
        stderr_path: str | None,
        safety_violation: str | None,
    ) -> None:
        event = TrainerSubprocessAuditEvent(
            task_id=task_id,
            mode=mode,
            legacy_python_path=self._legacy_python_path,
            legacy_script_path=self._legacy_script_path,
            pid=pid,
            start_ts_ms=start_ts_ms,
            end_ts_ms=end_ts_ms,
            returncode=returncode,
            stdout_digest_sha256=sha256(stdout).hexdigest() if stdout else None,
            stderr_digest_sha256=sha256(stderr).hexdigest() if stderr else None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            safety_violation=safety_violation,
        )
        self._audit_sink(event)

    def _validate_mode(self, mode: TrainerSubprocessMode) -> None:
        if not isinstance(mode, TrainerSubprocessMode):
            raise TrainerSubprocessSafetyError("mode must be a TrainerSubprocessMode")
        if mode.value not in ALLOWED_MODES:
            raise TrainerSubprocessSafetyError("mode is not allowed")

    def _validate_task_id(self, task_id: str) -> None:
        if not task_id or any(ch not in _SAFE_TASK_ID_CHARS for ch in task_id):
            raise TrainerSubprocessSafetyError("task_id contains unsafe characters")

    def _validate_path_text(self, name: str, value: str) -> str:
        if not isinstance(value, str) or not value:
            raise TrainerSubprocessConfigError(f"{name} must be a non-empty string")
        if any(fragment in value for fragment in _FORBIDDEN_PATH_FRAGMENTS):
            raise TrainerSubprocessSafetyError(f"{name} contains a shell metacharacter")
        return value
