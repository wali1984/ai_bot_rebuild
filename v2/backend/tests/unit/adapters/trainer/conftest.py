"""Fixtures for trainer subprocess adapter unit tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable

import pytest

for parent in Path(__file__).resolve().parents:
    if (parent / "v2").is_dir():
        sys.path.insert(0, str(parent))
        break

from v2.backend.app.adapters.trainer import (
    SubprocessRunResult,
    SubprocessTrainerAdapter,
    TrainerSubprocessAuditEvent,
)


@dataclass
class FakeRunCall:
    argv: list[str]
    env: dict[str, str]
    cwd: str
    timeout_s: float
    stdout_path: str
    stderr_path: str


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[FakeRunCall] = []
        self.result: SubprocessRunResult | None = None
        self.side_effect: Exception | None = None

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
        call = FakeRunCall(
            argv=list(argv),
            env=dict(env),
            cwd=cwd,
            timeout_s=timeout_s,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
        self.calls.append(call)
        if self.side_effect is not None:
            raise self.side_effect
        if self.result is not None:
            return self.result
        return SubprocessRunResult(
            returncode=0,
            stdout=b"ok",
            stderr=b"",
            pid=123,
            start_ts_ms=10,
            end_ts_ms=20,
        )


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def audit_capture() -> list[TrainerSubprocessAuditEvent]:
    return []


@pytest.fixture
def clock_ms() -> Callable[[], int]:
    values = iter([1000, 2000, 3000, 4000, 5000])
    return lambda: next(values)


@pytest.fixture
def make_adapter(tmp_path: Path, fake_runner: FakeRunner, audit_capture, clock_ms):
    def _factory(
        *,
        runner: FakeRunner | None = None,
        env_allowlist: frozenset[str] = frozenset({"PYTHONUNBUFFERED"}),
    ) -> SubprocessTrainerAdapter:
        return SubprocessTrainerAdapter(
            legacy_python_path=str(tmp_path / "legacy-python"),
            legacy_script_path=str(tmp_path / "trainer_entrypoint.py"),
            legacy_bot_root=str(tmp_path / "legacy-root"),
            capture_dir=str(tmp_path / "captures"),
            timeout_s=5.0,
            runner=runner or fake_runner,
            clock_ms=clock_ms,
            env_allowlist=env_allowlist,
            audit_sink=audit_capture.append,
        )

    return _factory


@pytest.fixture
def adapter(make_adapter) -> SubprocessTrainerAdapter:
    return make_adapter()
