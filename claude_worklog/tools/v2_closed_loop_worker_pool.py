"""Compatibility wrapper for legacy entrypoint: closed-loop worker pool CLI.

The CLI delegates to Spark by default, but this module also keeps the
file-backed helper API used by the existing worker-pool tests, queue
remediation tools, and rollback mode.  ``LEASE_BACKEND=file`` uses these
helpers directly so rollback is real, not just a documented systemd drop-in.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT_FOR_IMPORT))

from v2.backend.app.closed_loop.cli.worker_pool import (
    main as _spark_main,
    run_once as _spark_run_once,
)
from v2_closed_loop_lifecycle import (
    HEARTBEAT_DIR,
    LIFECYCLE_DIR,
    LOG_DIR,
    REPO_ROOT,
    TASKS_DIR,
    iter_task_files,
    normalize_descriptor,
    pid_alive,
    read_json,
    source_truth_completion_suppresses_dispatch,
    utc_iso,
    write_json_atomic,
)

__all__ = [
    "DEFAULT_MAX_CLAUDE_WORKERS",
    "DEFAULT_MAX_CODEX_WORKERS",
    "LANE_TYPE_CLAUDE",
    "LANE_TYPE_CODEX",
    "LANE_TYPE_REMEDIATION",
    "LANE_TYPE_TAKEOVER",
    "LIVE_BLOCKED_ENVELOPE",
    "WORKER_HEARTBEAT_DIR",
    "claim_next_task",
    "compute_pool_status",
    "current_alive_workers_by_lane",
    "ensure_worker_dirs",
    "main",
    "maintain_pool",
    "read_lease_registry",
    "read_worker_heartbeats",
    "reclaim_stale_leases",
    "run_once",
    "run_pool_once",
    "update_lease",
    "worker_is_active",
    "write_lease_registry",
    "write_worker_heartbeat",
    "is_unsafe_descriptor",
]


LANE_TYPE_CLAUDE = "CLAUDE_IMPLEMENTATION"
LANE_TYPE_CODEX = "CODEX_REVIEW"
LANE_TYPE_TAKEOVER = "CODEX_TAKEOVER"
LANE_TYPE_REMEDIATION = "REMEDIATION"

DEFAULT_MAX_CLAUDE_WORKERS = 3
DEFAULT_MAX_CODEX_WORKERS = 3
LEASE_STALE_SECONDS = 120
WORKER_STALE_SECONDS = 300

WORKER_HEARTBEAT_DIR = LIFECYCLE_DIR / "worker_heartbeats"
LEASE_REGISTRY_PATH = LIFECYCLE_DIR / "worker_leases.json"
STATUS_PATH = LIFECYCLE_DIR / "worker_pool_status.json"

LIVE_BLOCKED_ENVELOPE = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
}

_LEGACY_SUBCOMMANDS = {"run-once"}


def ensure_worker_dirs() -> None:
    WORKER_HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
    LIFECYCLE_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)


def _parse_ts(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _active_status(value: str | None) -> bool:
    return value in {"leased", "running", "active"}


def _lane_matches(task: dict[str, Any], lane_types: Iterable[str]) -> bool:
    lanes = set(lane_types)
    task_type = task.get("task_type") or task.get("lane_type")
    if task_type in lanes:
        return True
    agent = str(task.get("agent") or "").lower()
    if agent.startswith("claude") and LANE_TYPE_CLAUDE in lanes:
        return True
    if agent.startswith("codex") and LANE_TYPE_CODEX in lanes:
        return True
    return False


def _safe_task(task: dict[str, Any]) -> bool:
    return is_unsafe_descriptor(task) is None


def is_unsafe_descriptor(task: dict[str, Any]) -> str | None:
    """Return an exact safety rejection reason, or None when claimable."""

    env = task.get("safe_envelope") or LIVE_BLOCKED_ENVELOPE
    if env.get("live_gate", "blocked_human_only") != "blocked_human_only":
        return "UNSAFE_LIVE_GATE"
    if env.get("live_symbols", []) != []:
        return "UNSAFE_LIVE_SYMBOLS"
    if env.get("approves_live") or env.get("approves_canary"):
        return "UNSAFE_LIVE_OR_CANARY_APPROVAL"
    if env.get("approves_legacy_shutdown") or env.get("approves_redis_trim"):
        return "UNSAFE_SHUTDOWN_OR_REDIS_TRIM_APPROVAL"
    text = json.dumps(task, sort_keys=True).lower()
    forbidden = (
        "enable live",
        "live_trading",
        "live_canary",
        "enable canary",
        "start canary",
        "approve canary",
        "approve_live",
        "approves_live\": true",
        "approves_canary\": true",
        "shutdown legacy",
        "exchange mutation",
        "create_order",
        "cancel_order",
        "old redis write",
    )
    for token in forbidden:
        if token in text:
            return f"UNSAFE_DESCRIPTOR_TOKEN:{token}"
    return None


def write_worker_heartbeat(
    worker_id: str,
    lane_type: str,
    *,
    state: str,
    current_task_id: str | None = None,
    extra: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    ensure_worker_dirs()
    payload = {
        "worker_id": worker_id,
        "lane_type": lane_type,
        "state": state,
        "current_task_id": current_task_id,
        "pid": os.getpid(),
        "updated_at": utc_iso(),
        "last_heartbeat": utc_iso(),
        "alive": True,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    if extra:
        payload.update(extra)
    if fields:
        payload.update(fields)
    write_json_atomic(WORKER_HEARTBEAT_DIR / f"{worker_id}.json", payload)
    return payload


def read_worker_heartbeats() -> list[dict[str, Any]]:
    ensure_worker_dirs()
    out: list[dict[str, Any]] = []
    for path in sorted(WORKER_HEARTBEAT_DIR.glob("*.json")):
        val = read_json(path)
        if isinstance(val, dict):
            out.append(val)
    return out


def worker_is_active(hb: dict[str, Any], *, max_age_seconds: int = WORKER_STALE_SECONDS) -> bool:
    if not isinstance(hb, dict):
        return False
    age = time.time() - _parse_ts(hb.get("updated_at") or hb.get("last_heartbeat"))
    if age > max_age_seconds:
        return False
    pid = hb.get("pid")
    return True if pid is None else pid_alive(pid)


def current_alive_workers_by_lane() -> dict[str, list[dict[str, Any]]]:
    by_lane: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for hb in read_worker_heartbeats():
        if worker_is_active(hb):
            by_lane[str(hb.get("lane_type"))].append(hb)
    return by_lane


def read_lease_registry() -> dict[str, Any]:
    ensure_worker_dirs()
    val = read_json(LEASE_REGISTRY_PATH)
    if not isinstance(val, dict):
        return {
            "schema_version": "v2_closed_loop_file_lease_registry_v1",
            "generated_utc": utc_iso(),
            "leases": [],
            "safety": dict(LIVE_BLOCKED_ENVELOPE),
        }
    val.setdefault("leases", [])
    val.setdefault("safety", dict(LIVE_BLOCKED_ENVELOPE))
    return val


def write_lease_registry(registry: dict[str, Any]) -> None:
    registry = dict(registry)
    registry["generated_utc"] = utc_iso()
    registry.setdefault("schema_version", "v2_closed_loop_file_lease_registry_v1")
    registry.setdefault("safety", dict(LIVE_BLOCKED_ENVELOPE))
    write_json_atomic(LEASE_REGISTRY_PATH, registry)


def _active_leases(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return [l for l in registry.get("leases", []) if _active_status(l.get("status"))]


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def _write_task(task: dict[str, Any]) -> None:
    write_json_atomic(_task_path(task["task_id"]), task)


def _iter_current_tasks() -> list[tuple[Path, dict[str, Any]]]:
    tasks: list[tuple[Path, dict[str, Any]]] = []
    for path in iter_task_files():
        raw = read_json(path)
        if not isinstance(raw, dict):
            continue
        if source_truth_completion_suppresses_dispatch(raw):
            continue
        raw_updated_at = raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None
        try:
            descriptor_mtime = path.stat().st_mtime
        except OSError:
            descriptor_mtime = 0.0
        task = normalize_descriptor(raw, path)
        if task.get("status") not in {"pending", "ready"}:
            continue
        freshness_ts = max(_parse_ts(raw_updated_at), descriptor_mtime)
        if not task.get("current_active") and freshness_ts < time.time() - 24 * 3600:
            continue
        tasks.append((path, task))
    return tasks


def claim_next_task(worker_id: str, lane_types: str | tuple[str, ...]) -> dict[str, Any] | None:
    ensure_worker_dirs()
    lanes = (lane_types,) if isinstance(lane_types, str) else tuple(lane_types)
    registry = read_lease_registry()
    active = _active_leases(registry)
    active_task_ids = {l.get("task_id") for l in active}
    active_locks = {l.get("file_lock_group") for l in active if l.get("file_lock_group")}
    for path, task in _iter_current_tasks():
        if not _lane_matches(task, lanes):
            continue
        if not _safe_task(task):
            continue
        task_id = task["task_id"]
        file_lock_group = str(task.get("file_lock_group") or task_id)
        if task_id in active_task_ids or file_lock_group in active_locks:
            continue
        now = utc_iso()
        task_lane_type = str(task.get("task_type") or task.get("lane_type") or lanes[0])
        lease = {
            "lease_id": str(uuid.uuid4()),
            "task_id": task_id,
            "worker_id": worker_id,
            "lane_type": task_lane_type,
            "status": "leased",
            "file_lock_group": file_lock_group,
            "leased_at": now,
            "heartbeat_at": now,
            "safety": dict(LIVE_BLOCKED_ENVELOPE),
        }
        registry["leases"].append(lease)
        write_lease_registry(registry)
        task["status"] = "running"
        task["worker_id"] = worker_id
        task["lease_id"] = lease["lease_id"]
        task["updated_at"] = now
        _write_task(task)
        return {"lease": lease, "task": task, "task_path": str(path)}
    return None


def update_lease(lease_id: str, *, status: str | None = None, heartbeat: bool = False, **fields: Any) -> dict[str, Any] | None:
    registry = read_lease_registry()
    found = None
    for lease in registry.get("leases", []):
        if lease.get("lease_id") != lease_id:
            continue
        if status:
            lease["status"] = status
        if heartbeat:
            lease["heartbeat_at"] = utc_iso()
        lease.update(fields)
        found = lease
        break
    write_lease_registry(registry)
    return found


def reclaim_stale_leases(*, stale_seconds: int = LEASE_STALE_SECONDS) -> dict[str, Any]:
    registry = read_lease_registry()
    reclaimed: list[str] = []
    second_time: list[str] = []
    terminal_synced: list[str] = []
    now = time.time()
    for lease in registry.get("leases", []):
        if not _active_status(lease.get("status")):
            continue
        task = read_json(_task_path(str(lease.get("task_id"))))
        if isinstance(task, dict) and task.get("status") in {"completed", "failed", "blocked_operator_required"}:
            lease["status"] = task["status"]
            terminal_synced.append(str(lease.get("task_id")))
            continue
        age = now - _parse_ts(lease.get("heartbeat_at"))
        if age < stale_seconds:
            continue
        if lease.get("was_stale"):
            lease["status"] = "second_stale"
            second_time.append(str(lease.get("task_id")))
            if isinstance(task, dict):
                task["status"] = "failed"
                task["fail_blockers"] = ["SECOND_STALE_LEASE_REQUIRES_TAKEOVER_OR_OPERATOR_REMEDIATION"]
                task["updated_at"] = utc_iso()
                _write_task(task)
        else:
            lease["status"] = "released"
            lease["was_stale"] = True
            reclaimed.append(str(lease.get("task_id")))
            if isinstance(task, dict):
                task["status"] = "pending"
                task["updated_at"] = utc_iso()
                _write_task(task)
    write_lease_registry(registry)
    return {
        "reclaimed": reclaimed,
        "second_time": second_time,
        "terminal_synced": terminal_synced,
    }


def _current_counts_by_lane() -> dict[str, int]:
    counts = {
        LANE_TYPE_CLAUDE: 0,
        LANE_TYPE_CODEX: 0,
        LANE_TYPE_TAKEOVER: 0,
        LANE_TYPE_REMEDIATION: 0,
    }
    for _path, task in _iter_current_tasks():
        task_type = str(task.get("task_type") or task.get("lane_type") or "")
        if task_type in counts:
            counts[task_type] += 1
        elif str(task.get("agent") or "").lower().startswith("codex"):
            counts[LANE_TYPE_CODEX] += 1
        else:
            counts[LANE_TYPE_CLAUDE] += 1
    return counts


def compute_pool_status(
    *,
    target_claude: int = DEFAULT_MAX_CLAUDE_WORKERS,
    target_codex: int = DEFAULT_MAX_CODEX_WORKERS,
    reclaim: dict[str, Any] | None = None,
) -> dict[str, Any]:
    heartbeats = read_worker_heartbeats()
    active_hbs = [hb for hb in heartbeats if worker_is_active(hb)]
    by_lane = current_alive_workers_by_lane()
    registry = read_lease_registry()
    active_leases = _active_leases(registry)
    counts_by_lane = _current_counts_by_lane()
    current_total = sum(counts_by_lane.values())
    active_lane_count = len(active_hbs)
    worker_count_busy = sum(1 for hb in active_hbs if hb.get("state") == "busy")
    worker_count_idle = sum(1 for hb in active_hbs if hb.get("state") == "idle_ready")
    task_ids = [l.get("task_id") for l in active_leases]
    locks = [l.get("file_lock_group") for l in active_leases if l.get("file_lock_group")]
    duplicate_task_leases = len(task_ids) - len(set(task_ids))
    duplicate_file_locks = len(locks) - len(set(locks))
    duplicate_worker_leases = len([l.get("worker_id") for l in active_leases]) - len(set(l.get("worker_id") for l in active_leases))
    target_lanes = min(3, max(current_total, 0)) if current_total else 0
    blocker = None
    shortfall_reason = None
    if current_total > 0 and active_lane_count < target_lanes:
        blocker = "ACTIVE_LANES_BELOW_MINIMUM"
        shortfall_reason = f"active_lane_count={active_lane_count}<target={target_lanes}"
    return {
        "schema_version": "v2_closed_loop_worker_pool_status_v1",
        "generated_utc": utc_iso(),
        "go_no_go": "V2_CLOSED_LOOP_WORKER_POOL_READY" if blocker is None else "V2_CLOSED_LOOP_WORKER_POOL_BLOCKED",
        "ready": blocker is None,
        "blocker": blocker,
        "worker_count_total": len(heartbeats),
        "worker_count_active": len(active_hbs),
        "worker_count_busy": worker_count_busy,
        "worker_count_idle_ready": worker_count_idle,
        "active_lane_count": active_lane_count,
        "active_claude_workers": len(by_lane.get(LANE_TYPE_CLAUDE, [])),
        "active_codex_workers": len(by_lane.get(LANE_TYPE_CODEX, [])),
        "target_claude_workers": target_claude,
        "target_codex_workers": target_codex,
        "current_automatable_count": current_total,
        "current_automatable_count_by_lane": counts_by_lane,
        "active_leases_count": len(active_leases),
        "active_lane_shortfall_reason": shortfall_reason,
        "current_task_assignments": [
            {
                "task_id": lease.get("task_id"),
                "worker_id": lease.get("worker_id"),
                "lane_type": lease.get("lane_type"),
                "file_lock_group": lease.get("file_lock_group"),
            }
            for lease in active_leases
        ],
        "heartbeats": heartbeats,
        "leases": registry.get("leases", []),
        "duplicate_task_leases": duplicate_task_leases,
        "duplicate_file_locks": duplicate_file_locks,
        "duplicate_worker_leases": duplicate_worker_leases,
        "reclaim": reclaim or {},
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }


def maintain_pool(
    *,
    target_claude: int = DEFAULT_MAX_CLAUDE_WORKERS,
    target_codex: int = DEFAULT_MAX_CODEX_WORKERS,
    spawn: bool = False,
) -> dict[str, Any]:
    ensure_worker_dirs()
    by_lane = current_alive_workers_by_lane()
    claude_needed = max(0, target_claude - len(by_lane.get(LANE_TYPE_CLAUDE, [])))
    codex_needed = max(0, target_codex - len(by_lane.get(LANE_TYPE_CODEX, [])))
    actions: list[dict[str, Any]] = []
    if spawn:
        for idx in range(claude_needed):
            worker_id = f"claude-spawn-{int(time.time())}-{idx}"
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(REPO_ROOT / "claude_worklog/tools/v2_closed_loop_claude_worker.py"),
                    "--worker-id",
                    worker_id,
                ],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            actions.append({"worker_id": worker_id, "pid": proc.pid, "kind": "claude"})
        for idx in range(codex_needed):
            worker_id = f"codex-spawn-{int(time.time())}-{idx}"
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(REPO_ROOT / "claude_worklog/tools/v2_closed_loop_codex_worker.py"),
                    "--worker-id",
                    worker_id,
                ],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            actions.append({"worker_id": worker_id, "pid": proc.pid, "kind": "codex"})
    return {"actions": actions, "claude_needed": claude_needed, "codex_needed": codex_needed}


def run_pool_once(
    *,
    target_claude: int = DEFAULT_MAX_CLAUDE_WORKERS,
    target_codex: int = DEFAULT_MAX_CODEX_WORKERS,
    spawn: bool = False,
    reclaim: bool = True,
) -> dict[str, Any]:
    if spawn:
        maintain_pool(target_claude=target_claude, target_codex=target_codex, spawn=True)
    reclaim_status = reclaim_stale_leases() if reclaim else {}
    status = compute_pool_status(
        target_claude=target_claude,
        target_codex=target_codex,
        reclaim=reclaim_status,
    )
    write_json_atomic(STATUS_PATH, status)
    return status


def run_once(
    *,
    db_path: str | None = None,
    max_iterations: int | None = None,
    only_workers: str | None = None,
    lane_group: str | None = None,
) -> dict[str, Any]:
    if os.environ.get("LEASE_BACKEND") == "file":
        return run_pool_once()
    return _spark_run_once(
        db_path=db_path,
        max_iterations=max_iterations,
        only_workers=only_workers,
        lane_group=lane_group,
    )


def main(argv: list[str] | None = None) -> int:  # noqa: D401
    """Entry point: strip legacy positional/flag args then delegate to Spark or file backend."""
    if argv is None:
        argv = sys.argv[1:]

    filtered: list[str] = [a for a in argv if a not in _LEGACY_SUBCOMMANDS]
    legacy = argparse.ArgumentParser(add_help=False)
    legacy.add_argument("--spawn", action="store_true", default=False)
    legacy.add_argument("--target-claude", type=int, default=DEFAULT_MAX_CLAUDE_WORKERS)
    legacy.add_argument("--target-codex", type=int, default=DEFAULT_MAX_CODEX_WORKERS)
    legacy.add_argument("--json", action="store_true", default=False)
    legacy_ns, remaining = legacy.parse_known_args(filtered)
    if os.environ.get("LEASE_BACKEND") == "file":
        status = run_pool_once(
            target_claude=legacy_ns.target_claude,
            target_codex=legacy_ns.target_codex,
            spawn=legacy_ns.spawn,
        )
        if legacy_ns.json:
            print(json.dumps(status, indent=2, sort_keys=True))
        return 0 if status.get("ready") else 2
    if legacy_ns.json:
        status = compute_pool_status(
            target_claude=legacy_ns.target_claude,
            target_codex=legacy_ns.target_codex,
        )
        print(json.dumps(status, indent=2, sort_keys=True))
        return 0
    return _spark_main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
