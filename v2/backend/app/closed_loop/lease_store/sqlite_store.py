"""SQLite WAL lease/task/event store for Spark closed-loop runtime."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from v2.backend.app.closed_loop.queue_models import (
    LEASE_STATUS_SET,
    TASK_STATUS_SET,
    WorkerRecord,
    CodexFailMapRecord,
    BurndownCycleRecord,
    LeaseRecord,
    TaskDescriptor,
)
from v2.backend.app.closed_loop.lane_registry import lane_review_dependency, get_lane

REQUIRED_SAFE_FIELDS = (
    "live_gate",
    "live_symbols",
    "approves_live",
    "approves_canary",
    "approves_legacy_shutdown",
    "approves_redis_trim",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _fallback_db_path() -> Path:
    state_directory = os.environ.get("STATE_DIRECTORY")
    if state_directory:
        return Path(state_directory) / "leases.db"
    return (
        _repo_root()
        / "claude_worklog"
        / "final_readiness"
        / "v2_closed_loop_spark"
        / "state"
        / "leases.db"
    )


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()


def _safe_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True)


def _ensure_safe_envelope(descriptor: dict[str, Any]) -> None:
    env = descriptor.get("safe_envelope")
    if not isinstance(env, dict):
        raise ValueError("missing safe_envelope")
    for field in REQUIRED_SAFE_FIELDS:
        if field not in env:
            raise ValueError(f"missing safe_envelope field: {field}")
    if env.get("live_gate") != "blocked_human_only":
        raise ValueError("unsafe live_gate")
    if env.get("live_symbols") != []:
        raise ValueError("unsafe live_symbols")
    if env.get("approves_live") is not False:
        raise ValueError("approves_live must be false")
    if env.get("approves_canary") is not False:
        raise ValueError("approves_canary must be false")
    if env.get("approves_legacy_shutdown") is not False:
        raise ValueError("approves_legacy_shutdown must be false")
    if env.get("approves_redis_trim") is not False:
        raise ValueError("approves_redis_trim must be false")


class SQLiteLeaseStore:
    """Durable queue/lease/work state store."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _fallback_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            check_same_thread=False,
            timeout=5.0,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._bootstrap()
        self._lock = threading.RLock()

    @contextmanager
    def tx(self):
        with self._lock, self._conn:
            yield self._conn

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    def _bootstrap(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    mission_category TEXT NOT NULL,
                    lane_group TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    status TEXT NOT NULL,
                    file_lock_group TEXT,
                    paired_task_id TEXT,
                    depends_on_task_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS leases (
                    lease_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    lane_group TEXT NOT NULL,
                    file_lock_group TEXT,
                    status TEXT NOT NULL,
                    leased_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    worker_kind TEXT NOT NULL,
                    lane_group TEXT NOT NULL,
                    pid INTEGER,
                    status TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS codex_fail_map (
                    fail_id TEXT PRIMARY KEY,
                    codex_task_id TEXT NOT NULL UNIQUE,
                    classification TEXT NOT NULL,
                    remediation_task_id TEXT,
                    operator_required INTEGER NOT NULL DEFAULT 0,
                    unsafe_to_fix INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS burndown_cycles (
                    cycle_id TEXT PRIMARY KEY,
                    blockers_before INTEGER NOT NULL,
                    blockers_after INTEGER NOT NULL,
                    flat_reason TEXT NOT NULL,
                    ready_allowed INTEGER NOT NULL,
                    unresolved_codex_fails INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    task_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_lease_active
                    ON leases(task_id)
                    WHERE status IN ('active', 'running');
                CREATE UNIQUE INDEX IF NOT EXISTS uq_file_lock_lease_active
                    ON leases(file_lock_group)
                    WHERE status IN ('active', 'running') AND file_lock_group IS NOT NULL;
                CREATE INDEX IF NOT EXISTS ix_tasks_status ON tasks(status);
                CREATE INDEX IF NOT EXISTS ix_tasks_lane_agent ON tasks(lane_group, agent);
                CREATE INDEX IF NOT EXISTS ix_leases_status ON leases(status, lane_group);
                CREATE INDEX IF NOT EXISTS ix_workers_status ON workers(status, lane_group);
                """
            )

    def write_event(
        self,
        event_type: str,
        actor: str,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with self.tx():
            self._conn.execute(
                """
                INSERT INTO events(event_id, event_type, actor, task_id, payload_json, created_at)
                VALUES(:event_id, :event_type, :actor, :task_id, :payload_json, :created_at)
                """,
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": event_type,
                    "actor": actor,
                    "task_id": task_id,
                    "payload_json": _safe_json(payload or {}),
                    "created_at": _utc_iso(),
                },
            )

    def create_task(self, descriptor: dict[str, Any], *, status: str = "pending") -> bool:
        if status not in TASK_STATUS_SET:
            raise ValueError(f"invalid task status: {status}")
        if descriptor.get("task_id") is None:
            raise ValueError("task_id required")
        _ensure_safe_envelope(descriptor)
        if not descriptor.get("file_lock_group"):
            raise ValueError("file_lock_group required")
        now = _utc_iso()
        with self.tx():
            self._conn.execute(
                """
                INSERT INTO tasks(
                    task_id, task_type, mission_category, lane_group, owner, agent,
                    status, file_lock_group, paired_task_id, depends_on_task_id, payload_json,
                    created_at, updated_at
                )
                VALUES (:task_id, :task_type, :mission_category, :lane_group, :owner, :agent,
                        :status, :file_lock_group, :paired_task_id, :depends_on_task_id,
                        :payload_json, :created_at, :updated_at)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_type=excluded.task_type,
                    mission_category=excluded.mission_category,
                    lane_group=excluded.lane_group,
                    owner=excluded.owner,
                    agent=excluded.agent,
                    status=excluded.status,
                    file_lock_group=excluded.file_lock_group,
                    paired_task_id=excluded.paired_task_id,
                    depends_on_task_id=excluded.depends_on_task_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                {
                    "task_id": descriptor["task_id"],
                    "task_type": descriptor.get("task_type") or descriptor.get("lane_type"),
                    "mission_category": descriptor["mission_category"],
                    "lane_group": descriptor["lane_group"],
                    "owner": descriptor["owner"],
                    "agent": descriptor["agent"],
                    "status": status,
                    "file_lock_group": descriptor["file_lock_group"],
                    "paired_task_id": descriptor.get("paired_task_id"),
                    "depends_on_task_id": descriptor.get("depends_on_task_id"),
                    "payload_json": _safe_json(descriptor),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return True

    def upsert_worker(self, worker: WorkerRecord | dict[str, Any]) -> None:
        payload = asdict(worker) if hasattr(worker, "payload_json") else dict(worker)
        with self.tx():
            payload_json = _safe_json(payload.get("payload_json") or {})
            now = _utc_iso()
            worker_payload = payload.get("payload_json", {})
            payload_json = _safe_json(worker_payload)
            self._conn.execute(
                """
                INSERT INTO workers(
                    worker_id, worker_kind, lane_group, pid, status, heartbeat_at, payload_json
                ) VALUES (:worker_id, :worker_kind, :lane_group, :pid, :status, :heartbeat_at, :payload_json)
                ON CONFLICT(worker_id) DO UPDATE SET
                    status=excluded.status,
                    heartbeat_at=excluded.heartbeat_at,
                    pid=excluded.pid,
                    payload_json=excluded.payload_json
                """,
                {
                    "worker_id": payload["worker_id"],
                    "worker_kind": payload["worker_kind"],
                    "lane_group": payload["lane_group"],
                    "pid": payload.get("pid"),
                    "status": payload["status"],
                    "heartbeat_at": now,
                    "payload_json": payload_json,
                },
            )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_tasks(self, **where: Any) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tasks"
        values: list[Any] = []
        if where:
            clauses = []
            for key, value in where.items():
                if value is None:
                    continue
                clauses.append(f"{key} = ?")
                values.append(value)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at ASC"
        rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_leases(self, **where: Any) -> list[dict[str, Any]]:
        sql = "SELECT * FROM leases"
        values: list[Any] = []
        if where:
            clauses = []
            for key, value in where.items():
                if value is None:
                    continue
                clauses.append(f"{key} = ?")
                values.append(value)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY leased_at ASC"
        rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_workers(self, **where: Any) -> list[dict[str, Any]]:
        sql = "SELECT * FROM workers"
        values: list[Any] = []
        if where:
            clauses = []
            for key, value in where.items():
                if value is None:
                    continue
                clauses.append(f"{key} = ?")
                values.append(value)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY heartbeat_at DESC"
        rows = self._conn.execute(sql, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def active_lease_count(self, lane_group: str | None = None) -> int:
        if lane_group:
            rows = self._conn.execute(
                """
                SELECT COUNT(*) FROM leases
                WHERE status IN ('active', 'running') AND lane_group=?
                """,
                (lane_group,),
            ).fetchone()[0]
        else:
            rows = self._conn.execute(
                "SELECT COUNT(*) FROM leases WHERE status IN ('active', 'running')"
            ).fetchone()[0]
        return int(rows or 0)

    def active_tasks(self, lane_group: str | None = None) -> list[dict[str, Any]]:
        if lane_group:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status IN ('leased', 'running') AND lane_group=?",
                (lane_group,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status IN ('leased', 'running')"
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def claim_task(self, *, worker_id: str, lane_group: str, worker_kind: str) -> dict[str, Any] | None:
        cfg = get_lane(lane_group)
        if cfg is None:
            raise ValueError(f"unknown lane group: {lane_group}")
        now = _utc_iso()
        now_ts = _parse_iso(now)
        with self.tx():
            active = self.active_lease_count(lane_group=lane_group)
            if active >= cfg.max_parallel:
                return None

            rows = self._conn.execute(
                """
                SELECT * FROM tasks
                WHERE lane_group = ?
                  AND status IN ('pending', 'ready')
                  AND agent = ?
                ORDER BY created_at ASC
                """,
                (lane_group, worker_kind),
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
                _ensure_safe_envelope(payload)
                if not self._depends_complete(row["depends_on_task_id"]):
                    continue
                file_lock_group = row["file_lock_group"] or row["task_id"]
                if self._active_file_lock_conflict(file_lock_group):
                    continue
                lease_id = str(uuid.uuid4())
                expires_at = _utc_iso()
                try:
                    self._conn.execute(
                        """
                        INSERT INTO leases(
                            lease_id, task_id, worker_id, lane_group, file_lock_group,
                            status, leased_at, expires_at, heartbeat_at, payload_json
                        ) VALUES (
                            :lease_id, :task_id, :worker_id, :lane_group, :file_lock_group,
                            :status, :leased_at, :expires_at, :heartbeat_at, :payload_json
                        )
                        """,
                        {
                            "lease_id": lease_id,
                            "task_id": row["task_id"],
                            "worker_id": worker_id,
                            "lane_group": lane_group,
                            "file_lock_group": file_lock_group,
                            "status": "active",
                            "leased_at": now,
                            "expires_at": expires_at,
                            "heartbeat_at": now,
                            "payload_json": _safe_json(
                                {
                                    "lane_group": lane_group,
                                    "worker_kind": worker_kind,
                                    "claimed_from": "sqlite_store",
                                }
                            ),
                        },
                    )
                    self._conn.execute(
                        "UPDATE tasks SET status='leased', updated_at=:updated_at WHERE task_id=:task_id",
                        {"task_id": row["task_id"], "updated_at": now},
                    )
                except sqlite3.IntegrityError:
                    self.write_event(
                        event_type="duplicate_lease_conflict",
                        actor="sqlite_store",
                        task_id=row["task_id"],
                        payload={"lane_group": lane_group, "worker_id": worker_id},
                    )
                    continue
                lease_row = self._conn.execute(
                    "SELECT * FROM leases WHERE lease_id=?", (lease_id,)
                ).fetchone()
                task_row = self._conn.execute(
                    "SELECT * FROM tasks WHERE task_id=?", (row["task_id"],)
                ).fetchone()
                return {"lease": self._row_to_dict(lease_row), "task": self._row_to_dict(task_row)}
        return None

    def heartbeat_lease(self, lease_id: str) -> None:
        now = _utc_iso()
        with self.tx():
            self._conn.execute(
                "UPDATE leases SET heartbeat_at=:hb WHERE lease_id=:lease_id AND status IN ('active', 'running')",
                {"hb": now, "lease_id": lease_id},
            )

    def heartbeat_worker(self, worker_id: str, state: str, *, lane_group: str, worker_kind: str, current_task_id: str | None = None) -> None:
        now = _utc_iso()
        payload = {
            "lane_group": lane_group,
            "worker_kind": worker_kind,
            "state": state,
            "current_task_id": current_task_id,
        }
        with self.tx():
            self._conn.execute(
                """
                UPDATE workers
                SET status=:status, heartbeat_at=:hb, payload_json=:payload_json
                WHERE worker_id=:worker_id
                """,
                {
                    "worker_id": worker_id,
                    "status": "active" if state in {"claiming", "busy", "post_task"} else "idle",
                    "hb": now,
                    "payload_json": _safe_json(payload),
                },
            )
            if self._conn.total_changes == 0:
                self._conn.execute(
                    """
                    INSERT INTO workers(worker_id, worker_kind, lane_group, pid, status, heartbeat_at, payload_json)
                    VALUES (:worker_id, :worker_kind, :lane_group, :pid, :status, :heartbeat_at, :payload_json)
                    """,
                    {
                        "worker_id": worker_id,
                        "worker_kind": worker_kind,
                        "lane_group": lane_group,
                        "pid": os.getpid(),
                        "status": "active" if state in {"claiming", "busy", "post_task"} else "idle",
                        "heartbeat_at": now,
                        "payload_json": _safe_json(payload),
                    },
                )

    def complete_task(self, task_id: str, *, lease_id: str | None = None, status: str = "completed", output_paths: list[str] | None = None, failure_reason: str | None = None) -> None:
        if status not in TASK_STATUS_SET:
            raise ValueError(f"invalid task status: {status}")
        now = _utc_iso()
        task = self.get_task(task_id) or {}
        payload = task.get("payload_json") if isinstance(task.get("payload_json"), dict) else {}
        with self.tx():
            task_payload = {}
            if output_paths:
                task_payload["output_paths"] = output_paths
            if failure_reason:
                task_payload["failure_reason"] = failure_reason
            if task_payload:
                payload.update(task_payload)
            self._conn.execute(
                """
                UPDATE tasks
                SET status=:status, updated_at=:updated_at, payload_json=:payload_json
                WHERE task_id=:task_id
                """,
                {
                    "status": status,
                    "updated_at": now,
                    "task_id": task_id,
                    "payload_json": _safe_json(payload),
                },
            )
            if lease_id:
                self._conn.execute(
                    "UPDATE leases SET status=:status, heartbeat_at=:updated_at WHERE lease_id=:lease_id",
                    {"status": "completed" if status == "completed" else "failed", "updated_at": now, "lease_id": lease_id},
                )
            self._conn.execute(
                """
                INSERT INTO events(event_id, event_type, actor, task_id, payload_json, created_at)
                VALUES(:event_id, :event_type, :actor, :task_id, :payload_json, :created_at)
                """,
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": f"task_{status}",
                    "actor": "worker",
                    "task_id": task_id,
                    "payload_json": _safe_json(
                        {"status": status, "failure_reason": failure_reason, "output_paths": output_paths or []}
                    ),
                    "created_at": now,
                },
            )

    def fail_task(self, task_id: str, *, lease_id: str | None = None, reason: str, safe_to_remediate: bool = True, operator_required: bool = False, unsafe_to_fix: bool = False) -> str | None:
        failed_at = _utc_iso()
        with self.tx():
            self._conn.execute(
                "UPDATE tasks SET status='failed', updated_at=:updated_at WHERE task_id=:task_id",
                {"updated_at": failed_at, "task_id": task_id},
            )
            if lease_id:
                self._conn.execute(
                    "UPDATE leases SET status='failed', heartbeat_at=:updated_at WHERE lease_id=:lease_id",
                    {"updated_at": failed_at, "lease_id": lease_id},
                )
            remediation_id = None
            if safe_to_remediate:
                remediation_id = f"closed_loop_remediation_{task_id}"
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO tasks(
                        task_id, task_type, mission_category, lane_group, owner, agent,
                        status, file_lock_group, paired_task_id, depends_on_task_id, payload_json,
                        created_at, updated_at
                    ) VALUES (
                        :task_id, :task_type, :mission_category, :lane_group, :owner, :agent,
                        :status, :file_lock_group, :paired_task_id, :depends_on_task_id, :payload_json,
                        :created_at, :updated_at
                    )
                    """,
                    {
                        "task_id": remediation_id,
                        "task_type": "CLAUDE_REMEDIATION",
                        "mission_category": "remediation",
                        "lane_group": "runtime-claude",
                        "owner": "CLAUDE",
                        "agent": "claude",
                        "status": "pending",
                        "file_lock_group": f"{task_id}_remediation",
                        "paired_task_id": None,
                        "depends_on_task_id": None,
                        "payload_json": _safe_json(
                            {
                                "task_id": remediation_id,
                                "parent_task_id": task_id,
                                "safe_envelope": {
                                    "live_gate": "blocked_human_only",
                                    "live_symbols": [],
                                    "approves_live": False,
                                    "approves_canary": False,
                                    "approves_legacy_shutdown": False,
                                    "approves_redis_trim": False,
                                },
                                "status": "pending",
                            }
                        ),
                        "created_at": failed_at,
                        "updated_at": failed_at,
                    },
                )
            self._conn.execute(
                """
                INSERT INTO events(event_id, event_type, actor, task_id, payload_json, created_at)
                VALUES(:event_id, :event_type, :actor, :task_id, :payload_json, :created_at)
                """,
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "task_failed",
                    "actor": "worker",
                    "task_id": task_id,
                    "payload_json": _safe_json(
                        {
                            "reason": reason,
                            "operator_required": operator_required,
                            "unsafe_to_fix": unsafe_to_fix,
                            "remediation_task_id": remediation_id,
                        }
                    ),
                    "created_at": failed_at,
                },
            )
            if operator_required or unsafe_to_fix:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO codex_fail_map(
                        fail_id, codex_task_id, classification, remediation_task_id,
                        operator_required, unsafe_to_fix, payload_json, created_at
                    ) VALUES(:fail_id, :codex_task_id, :classification, :remediation_task_id, :operator_required, :unsafe_to_fix, :payload_json, :created_at)
                    """,
                    {
                        "fail_id": str(uuid.uuid4()),
                        "codex_task_id": task_id,
                        "classification": "operator_required" if operator_required else "remediation_available",
                        "remediation_task_id": remediation_id,
                        "operator_required": int(bool(operator_required)),
                        "unsafe_to_fix": int(bool(unsafe_to_fix)),
                        "payload_json": _safe_json({"reason": reason}),
                        "created_at": failed_at,
                    },
                )
            return remediation_id

    def stale_lease_reclaim(self, *, stale_seconds: int = 120, second_stale_seconds: int = 300) -> dict[str, int]:
        now_ts = datetime.now(timezone.utc).timestamp()
        now_iso = _utc_iso()
        stale = self._conn.execute(
            "SELECT * FROM leases WHERE status IN ('active','running')"
        ).fetchall()
        first_count = 0
        second_count = 0
        for lease in stale:
            heartbeat_ts = _parse_iso(lease["heartbeat_at"])
            age = now_ts - heartbeat_ts
            payload = json.loads(lease["payload_json"] or "{}")
            reclaim_stage = int(payload.get("reclaim_stage", 0))
            if age < stale_seconds:
                continue
            task_id = lease["task_id"]
            if reclaim_stage >= 1 and age >= second_stale_seconds:
                second_count += 1
                remediation_id = f"closed_loop_remediation_{task_id}"
                self._conn.execute(
                    "UPDATE leases SET status='second_stale', heartbeat_at=:hb WHERE lease_id=:lease_id",
                    {"hb": now_iso, "lease_id": lease["lease_id"]},
                )
                self._conn.execute(
                    "UPDATE tasks SET status='failed', updated_at=:updated_at WHERE task_id=:task_id",
                    {"updated_at": now_iso, "task_id": task_id},
                )
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO tasks(
                        task_id, task_type, mission_category, lane_group, owner, agent,
                        status, file_lock_group, paired_task_id, depends_on_task_id, payload_json,
                        created_at, updated_at
                    ) VALUES (
                        :task_id, :task_type, :mission_category, :lane_group, :owner, :agent,
                        :status, :file_lock_group, :paired_task_id, :depends_on_task_id, :payload_json,
                        :created_at, :updated_at
                    )
                    """,
                    {
                        "task_id": remediation_id,
                        "task_type": "CLAUDE_REMEDIATION",
                        "mission_category": "remediation",
                        "lane_group": "runtime-claude",
                        "owner": "CLAUDE",
                        "agent": "claude",
                        "status": "pending",
                        "file_lock_group": f"{task_id}_second_stale_remediation",
                        "paired_task_id": None,
                        "depends_on_task_id": None,
                        "payload_json": _safe_json(
                            {
                                "task_id": remediation_id,
                                "parent_task_id": task_id,
                                "classification": "SECOND_STALE_REMEDIATION_REQUIRED",
                                "safe_envelope": {
                                    "live_gate": "blocked_human_only",
                                    "live_symbols": [],
                                    "approves_live": False,
                                    "approves_canary": False,
                                    "approves_legacy_shutdown": False,
                                    "approves_redis_trim": False,
                                },
                                "status": "pending",
                            }
                        ),
                        "created_at": now_iso,
                        "updated_at": now_iso,
                    },
                )
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO codex_fail_map(
                        fail_id, codex_task_id, classification, remediation_task_id,
                        operator_required, unsafe_to_fix, payload_json, created_at
                    ) VALUES(:fail_id, :codex_task_id, :classification, :remediation_task_id,
                             :operator_required, :unsafe_to_fix, :payload_json, :created_at)
                    """,
                    {
                        "fail_id": str(uuid.uuid4()),
                        "codex_task_id": task_id,
                        "classification": "second_stale_remediation_required",
                        "remediation_task_id": remediation_id,
                        "operator_required": 0,
                        "unsafe_to_fix": 0,
                        "payload_json": _safe_json(
                            {
                                "age_seconds": age,
                                "reason": "second stale lease requires remediation",
                            }
                        ),
                        "created_at": now_iso,
                    },
                )
                self.write_event(
                    "second_stale_escalation",
                    "sqlite_store",
                    task_id=task_id,
                    payload={"age_seconds": age, "remediation_task_id": remediation_id},
                )
                continue
            first_count += 1
            payload["reclaim_stage"] = reclaim_stage + 1
            self._conn.execute(
                "UPDATE leases SET status='stale', heartbeat_at=:hb, payload_json=:payload_json WHERE lease_id=:lease_id",
                {
                    "hb": now_iso,
                    "payload_json": _safe_json(payload),
                    "lease_id": lease["lease_id"],
                },
            )
            self._conn.execute(
                "UPDATE tasks SET status='pending', updated_at=:updated_at WHERE task_id=:task_id",
                {"updated_at": now_iso, "task_id": task_id},
            )
            self.write_event("stale_reclaim", "sqlite_store", task_id=task_id, payload={"age_seconds": age})
        return {"stale_reclaims": first_count, "second_stale_escalations": second_count}

    def add_codex_fail_map(self, *, codex_task_id: str, classification: str, remediation_task_id: str | None = None, operator_required: bool = False, unsafe_to_fix: bool = False, payload: dict[str, Any] | None = None) -> bool:
        try:
            with self.tx():
                self._conn.execute(
                    """
                    INSERT INTO codex_fail_map(
                        fail_id, codex_task_id, classification, remediation_task_id, operator_required,
                        unsafe_to_fix, payload_json, created_at
                    ) VALUES (:fail_id, :codex_task_id, :classification, :remediation_task_id, :operator_required, :unsafe_to_fix, :payload_json, :created_at)
                    """,
                    {
                        "fail_id": str(uuid.uuid4()),
                        "codex_task_id": codex_task_id,
                        "classification": classification,
                        "remediation_task_id": remediation_task_id,
                        "operator_required": int(bool(operator_required)),
                        "unsafe_to_fix": int(bool(unsafe_to_fix)),
                        "payload_json": _safe_json(payload or {}),
                        "created_at": _utc_iso(),
                    },
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def add_burndown_cycle(self, *, blockers_before: int, blockers_after: int, flat_reason: str, ready_allowed: bool, unresolved_codex_fails: int, payload: dict[str, Any]) -> str:
        cycle_id = str(uuid.uuid4())
        now = _utc_iso()
        self._conn.execute(
            """
            INSERT INTO burndown_cycles(
                cycle_id, blockers_before, blockers_after, flat_reason, ready_allowed,
                unresolved_codex_fails, payload_json, started_at, finished_at
            ) VALUES(
                :cycle_id, :blockers_before, :blockers_after, :flat_reason, :ready_allowed,
                :unresolved_codex_fails, :payload_json, :started_at, :finished_at
            )
            """,
            {
                "cycle_id": cycle_id,
                "blockers_before": blockers_before,
                "blockers_after": blockers_after,
                "flat_reason": flat_reason,
                "ready_allowed": int(bool(ready_allowed)),
                "unresolved_codex_fails": unresolved_codex_fails,
                "payload_json": _safe_json(payload),
                "started_at": now,
                "finished_at": now,
            },
        )
        return cycle_id

    def metrics_snapshot(self) -> dict[str, Any]:
        now_ts = datetime.now(timezone.utc).timestamp()
        active_leases = self._conn.execute(
            "SELECT COUNT(*) FROM leases WHERE status IN ('active','running')"
        ).fetchone()[0]
        busy_workers = self._conn.execute(
            "SELECT COUNT(*) FROM workers WHERE json_extract(payload_json, '$.state')='busy' AND status='active'"
        ).fetchone()[0]
        idle_workers = self._conn.execute(
            "SELECT COUNT(*) FROM workers WHERE json_extract(payload_json, '$.state')='idle_ready' AND status='active'"
        ).fetchone()[0]
        oldest_task = self._conn.execute(
            "SELECT created_at FROM tasks WHERE status IN ('pending','ready') ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        oldest_age = None
        if oldest_task:
            oldest_age = max(0.0, now_ts - _parse_iso(oldest_task[0]))
        oldest_worker_heartbeat = self._conn.execute(
            "SELECT heartbeat_at FROM workers ORDER BY heartbeat_at DESC LIMIT 1"
        ).fetchone()
        worker_heartbeat_age = None
        if oldest_worker_heartbeat:
            worker_heartbeat_age = max(0.0, now_ts - _parse_iso(oldest_worker_heartbeat[0]))
        oldest_lease_heartbeat = self._conn.execute(
            "SELECT heartbeat_at FROM leases ORDER BY heartbeat_at DESC LIMIT 1"
        ).fetchone()
        lease_heartbeat_age = None
        if oldest_lease_heartbeat:
            lease_heartbeat_age = max(0.0, now_ts - _parse_iso(oldest_lease_heartbeat[0]))
        eligible_tasks = self._count_eligible_tasks()
        completed_total = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='task_completed'"
        ).fetchone()[0]
        duplicate_conflicts = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='duplicate_lease_conflict'"
        ).fetchone()[0]
        payload_age = self._conn.execute(
            "SELECT created_at FROM events ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        payload_age_seconds = None
        if payload_age:
            payload_age_seconds = max(0.0, now_ts - _parse_iso(payload_age[0]))
        codex_fail_map_total = self._conn.execute(
            "SELECT COUNT(*) FROM codex_fail_map"
        ).fetchone()[0]
        return {
            "v2_closed_loop_active_leases": float(active_leases or 0),
            "v2_closed_loop_busy_workers": float(busy_workers or 0),
            "v2_closed_loop_idle_workers": float(idle_workers or 0),
            "v2_closed_loop_worker_heartbeat_age_seconds": worker_heartbeat_age,
            "v2_closed_loop_lease_heartbeat_age_seconds": lease_heartbeat_age,
            "v2_closed_loop_queue_eligible_tasks": float(eligible_tasks or 0),
            "v2_closed_loop_queue_oldest_task_age_seconds": oldest_age,
            "v2_closed_loop_task_completions_total": float(completed_total or 0),
            "v2_closed_loop_codex_fail_map_total": float(codex_fail_map_total or 0),
            "v2_closed_loop_executor_unavailable": 0.0
            if (busy_workers or 0) > 0 or (active_leases or 0) > 0
            else 1.0,
            "v2_closed_loop_duplicate_lease_conflicts_total": float(duplicate_conflicts or 0),
            "v2_closed_loop_burndown_blockers": float(
                self._conn.execute(
                    "SELECT COUNT(*) FROM codex_fail_map WHERE operator_required=0 AND unsafe_to_fix=0"
                ).fetchone()[0]
            ),
            "v2_closed_loop_payload_age_seconds": payload_age_seconds,
        }

    def report_status(self) -> dict[str, Any]:
        with self.tx():
            tasks = self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            leases = self._conn.execute("SELECT COUNT(*) FROM leases").fetchone()[0]
            workers = self._conn.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
            fails = self._conn.execute("SELECT COUNT(*) FROM codex_fail_map").fetchone()[0]
            events = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            return {
                "status": "ok",
                "db_path": str(self.db_path),
                "journal_mode": self._conn.execute("PRAGMA journal_mode").fetchone()[0],
                "busy": bool(int(self._conn.execute("PRAGMA busy_timeout").fetchone()[0])),
                "tasks": tasks,
                "leases": leases,
                "workers": workers,
                "codex_fail_map": fails,
                "events": events,
            }

    def reconcile(self) -> dict[str, Any]:
        duplicates = self._conn.execute(
            """
            SELECT task_id, COUNT(*) AS c FROM leases
            WHERE status IN ('active','running')
            GROUP BY task_id HAVING c > 1
            """
        ).fetchall()
        file_conflicts = self._conn.execute(
            """
            SELECT file_lock_group, COUNT(*) AS c FROM leases
            WHERE status IN ('active','running') AND file_lock_group IS NOT NULL
            GROUP BY file_lock_group HAVING c > 1
            """
        ).fetchall()
        missing_safe = self._conn.execute(
            """
            SELECT task_id FROM tasks
            WHERE json_extract(payload_json, '$.safe_envelope.live_gate') IS NULL
            """
        ).fetchall()
        return {
            "duplicate_active_task_leases": len(duplicates),
            "duplicate_file_lock_active_leases": len(file_conflicts),
            "tasks_missing_safe_envelope": len(missing_safe),
            "duplicate_active_task_leases_detail": [r["task_id"] for r in duplicates],
            "duplicate_file_lock_active_leases_detail": [r["file_lock_group"] for r in file_conflicts],
            "tasks_missing_safe_envelope_detail": [r["task_id"] for r in missing_safe],
        }

    def _depends_complete(self, depends_on_task_id: str | None) -> bool:
        if not depends_on_task_id:
            return True
        parent = self._conn.execute(
            "SELECT status FROM tasks WHERE task_id = ?", (depends_on_task_id,)
        ).fetchone()
        if parent is None:
            return False
        return parent["status"] == "completed"

    def _active_file_lock_conflict(self, file_lock_group: str | None) -> bool:
        if not file_lock_group:
            return False
        row = self._conn.execute(
            "SELECT lease_id FROM leases WHERE status IN ('active', 'running') AND file_lock_group = ? LIMIT 1",
            (file_lock_group,),
        ).fetchone()
        return row is not None

    def _count_eligible_tasks(self) -> int:
        rows = self._conn.execute(
            """
            SELECT COUNT(*) FROM tasks
            WHERE status IN ('pending','ready')
            """
        ).fetchone()[0]
        return int(rows or 0)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for field in ("payload_json",):
            if field in result and isinstance(result[field], str):
                try:
                    result[field] = json.loads(result[field])
                except Exception:
                    result[field] = {}
        return result
