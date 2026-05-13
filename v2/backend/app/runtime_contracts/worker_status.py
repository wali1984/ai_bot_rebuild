from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class WorkerMigrationStatus(StrEnum):
    MIGRATED_AND_RUNNING = "MIGRATED_AND_RUNNING"
    MIGRATED_NOT_RUNNING = "MIGRATED_NOT_RUNNING"
    WRAPPED_READONLY_ONLY = "WRAPPED_READONLY_ONLY"
    PAPER_ONLY = "PAPER_ONLY"
    BACKLOG_ONLY = "BACKLOG_ONLY"
    MISSING_IN_V2 = "MISSING_IN_V2"
    LEGACY_ONLY = "LEGACY_ONLY"
    DEPRECATED_WITH_EVIDENCE = "DEPRECATED_WITH_EVIDENCE"
    BLOCKED = "BLOCKED"


STATUS_MEANING: dict[WorkerMigrationStatus, str] = {
    WorkerMigrationStatus.MIGRATED_AND_RUNNING: "independent V2 worker exists and is running",
    WorkerMigrationStatus.MIGRATED_NOT_RUNNING: "independent V2 worker exists but has no current process evidence",
    WorkerMigrationStatus.WRAPPED_READONLY_ONLY: "V2 only observes or wraps legacy output",
    WorkerMigrationStatus.PAPER_ONLY: "paper/shadow runtime only; never live execution",
    WorkerMigrationStatus.BACKLOG_ONLY: "migration backlog item only; not migrated",
    WorkerMigrationStatus.MISSING_IN_V2: "honest gap; no V2 worker found",
    WorkerMigrationStatus.LEGACY_ONLY: "legacy responsibility remains outside V2",
    WorkerMigrationStatus.DEPRECATED_WITH_EVIDENCE: "responsibility retired with evidence",
    WorkerMigrationStatus.BLOCKED: "blocked by missing safety or runtime evidence",
}


READY_REQUIRED_FIELDS = ("runnable_command", "public_payload_path")
REQUIRED_FIELDS = (
    "worker_id",
    "category",
    "purpose",
    "status",
    "generated_at",
    "freshness_seconds",
    "source_paths",
    "evidence_status",
    "legacy_dependency_mode",
    "runtime_pid",
    "runnable_command",
    "public_payload_path",
    "test_status",
    "codex_status",
    "blockers",
    "next_action",
)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass(frozen=True)
class V2WorkerStatus:
    worker_id: str
    category: str
    purpose: str
    status: WorkerMigrationStatus
    generated_at: str
    freshness_seconds: int | None
    source_paths: tuple[str, ...] = field(default_factory=tuple)
    evidence_status: str = "EVIDENCE_MISSING"
    legacy_dependency_mode: str = "unknown"
    runtime_pid: int | None = None
    runnable_command: str | None = None
    public_payload_path: str | None = None
    test_status: str = "missing"
    codex_status: str = "not_reviewed"
    blockers: tuple[str, ...] = field(default_factory=tuple)
    next_action: str = "provide_missing_evidence"

    def __post_init__(self) -> None:
        if self.status not in set(WorkerMigrationStatus):
            raise ValueError(f"unsupported worker status: {self.status}")
        if self.status == WorkerMigrationStatus.BACKLOG_ONLY and not self.blockers:
            raise ValueError("BACKLOG_ONLY must name the migration blocker")
        if self.status == WorkerMigrationStatus.WRAPPED_READONLY_ONLY and self.legacy_dependency_mode != "readonly_wrapper":
            raise ValueError("WRAPPED_READONLY_ONLY must use readonly_wrapper dependency mode")
        ready_errors = ready_blockers(self.to_dict())
        if self.status == WorkerMigrationStatus.MIGRATED_AND_RUNNING and ready_errors:
            raise ValueError("MIGRATED_AND_RUNNING requires " + ", ".join(ready_errors))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["status_meaning"] = STATUS_MEANING[self.status]
        payload["source_paths"] = list(self.source_paths)
        payload["blockers"] = list(self.blockers)
        payload["is_migration"] = self.status in {
            WorkerMigrationStatus.MIGRATED_AND_RUNNING,
            WorkerMigrationStatus.MIGRATED_NOT_RUNNING,
        }
        payload["is_independent_runtime"] = self.status in {
            WorkerMigrationStatus.MIGRATED_AND_RUNNING,
            WorkerMigrationStatus.MIGRATED_NOT_RUNNING,
            WorkerMigrationStatus.PAPER_ONLY,
        }
        return payload


def validate_required_fields(payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field_name in REQUIRED_FIELDS:
        if field_name not in payload:
            missing.append(field_name)
            continue
        value = payload[field_name]
        if field_name in {"worker_id", "category", "purpose", "generated_at", "evidence_status", "legacy_dependency_mode", "test_status", "codex_status", "next_action"}:
            if not isinstance(value, str) or not value.strip():
                missing.append(field_name)
        elif field_name in {"source_paths", "blockers"} and not isinstance(value, list | tuple):
            missing.append(field_name)
    if payload.get("status") not in {status.value for status in WorkerMigrationStatus}:
        missing.append("status")
    return missing


def ready_blockers(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for field_name in READY_REQUIRED_FIELDS:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value.strip():
            blockers.append(field_name)
    if payload.get("test_status") not in {"passed", "present", "configured"}:
        blockers.append("test_status")
    return blockers


def ensure_ready_allowed(status: V2WorkerStatus | dict[str, Any]) -> None:
    payload = status.to_dict() if isinstance(status, V2WorkerStatus) else status
    if payload.get("status") == WorkerMigrationStatus.MIGRATED_AND_RUNNING.value:
        blockers = ready_blockers(payload)
        if blockers:
            raise ValueError("READY status blocked by missing " + ", ".join(blockers))


def example_payload() -> dict[str, Any]:
    return V2WorkerStatus(
        worker_id="paper_execution_worker",
        category="paper_execution_worker",
        purpose="paper/shadow execution evidence only",
        status=WorkerMigrationStatus.PAPER_ONLY,
        generated_at=utc_now(),
        freshness_seconds=0,
        source_paths=("v2/backend/app/cli/paper_online_runtime.py",),
        evidence_status="EVIDENCE_PRESENT",
        legacy_dependency_mode="none",
        runnable_command="python3 -m v2.backend.app.cli.paper_online_runtime --once --write-evidence",
        public_payload_path="v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
        test_status="present",
        codex_status="support_contract_valid",
        next_action="keep paper/shadow evidence current",
    ).to_dict()


def write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    missing = validate_required_fields(payload)
    if missing:
        raise ValueError("worker status payload missing required fields: " + ", ".join(missing))
    ensure_ready_allowed(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


def write_schema(path: Path) -> None:
    schema = {
        "title": "V2WorkerStatus",
        "type": "object",
        "required": list(REQUIRED_FIELDS),
        "properties": {
            "status": {"enum": [status.value for status in WorkerMigrationStatus]},
            "is_migration": {"type": "boolean"},
            "is_independent_runtime": {"type": "boolean"},
        },
        "example": example_payload(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
