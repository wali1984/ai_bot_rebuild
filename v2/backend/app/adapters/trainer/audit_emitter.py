"""Audit event value object for trainer subprocess invocations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .modes import TrainerSubprocessMode


@dataclass(frozen=True)
class TrainerSubprocessAuditEvent:
    task_id: str
    mode: TrainerSubprocessMode
    legacy_python_path: str
    legacy_script_path: str
    pid: int | None
    start_ts_ms: int
    end_ts_ms: int | None
    returncode: int | None
    stdout_digest_sha256: str | None
    stderr_digest_sha256: str | None
    stdout_path: str | None
    stderr_path: str | None
    safety_violation: str | None


def to_dict(event: TrainerSubprocessAuditEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload["mode"] = event.mode.value
    return payload
