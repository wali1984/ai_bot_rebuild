"""Structured models for Spark queue artifacts."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


TASK_STATUS_SET = {
    "pending",
    "leased",
    "running",
    "completed",
    "failed",
    "released",
    "stale",
    "duplicate_suppressed",
    "operator_required",
}

LEASE_STATUS_SET = {
    "active",
    "running",
    "completed",
    "failed",
    "released",
    "stale",
    "second_stale",
    "duplicate_conflict",
}

WORKER_STATUS_SET = {
    "active",
    "idle",
    "stopped",
}


@dataclass(frozen=True)
class TaskDescriptor:
    task_id: str
    task_type: str
    mission_category: str
    lane_group: str
    owner: str
    agent: str
    status: str
    file_lock_group: str
    paired_task_id: str | None
    depends_on_task_id: str | None
    payload_json: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeaseRecord:
    lease_id: str
    task_id: str
    worker_id: str
    lane_group: str
    file_lock_group: str | None
    status: str
    leased_at: str
    expires_at: str
    heartbeat_at: str
    payload_json: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkerRecord:
    worker_id: str
    worker_kind: str
    lane_group: str
    pid: int | None
    status: str
    heartbeat_at: str
    payload_json: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodexFailMapRecord:
    fail_id: str
    codex_task_id: str
    classification: str
    remediation_task_id: str | None
    operator_required: bool
    unsafe_to_fix: bool
    payload_json: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BurndownCycleRecord:
    cycle_id: str
    blockers_before: int
    blockers_after: int
    flat_reason: str
    ready_allowed: bool
    unresolved_codex_fails: int
    payload_json: dict[str, Any]
    started_at: str
    finished_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
