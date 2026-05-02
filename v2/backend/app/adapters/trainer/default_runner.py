"""Default subprocess runner for the trainer adapter.

Production wiring remains gated to later Phase 2E tasks. This runner exists so
Codex can verify the subprocess boundary and ``shell=False`` behavior.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import TrainerSubprocessTimeoutError
from .subprocess_adapter import SubprocessRunResult


class DefaultSubprocessRunner:
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
        try:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                capture_output=True,
                shell=False,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            raise TrainerSubprocessTimeoutError("trainer subprocess timed out") from exc

        Path(stdout_path).parent.mkdir(parents=True, exist_ok=True)
        Path(stdout_path).write_bytes(completed.stdout or b"")
        Path(stderr_path).write_bytes(completed.stderr or b"")

        return SubprocessRunResult(
            returncode=completed.returncode,
            stdout=completed.stdout or b"",
            stderr=completed.stderr or b"",
            pid=None,
            start_ts_ms=0,
            end_ts_ms=0,
        )
