"""Shared lifecycle helpers for the V2 closed-loop Claude/Codex execution engine.

The runners and coordinator all need the same lifecycle envelope, lock
semantics, duplicate-suppression rules and pid/heartbeat utilities. They
live here so the three executables stay consistent with the schema
declared in ``claude_worklog/final_readiness/v2_closed_loop_execution/latest/task_lifecycle_schema.json``.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
STATE_TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "state" / "tasks"
LIFECYCLE_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_execution"
    / "latest"
)
LOG_DIR = LIFECYCLE_DIR / "logs"
LOCK_DIR = LIFECYCLE_DIR / "locks"
HEARTBEAT_DIR = LIFECYCLE_DIR / "heartbeats"
WORKER_LEASES_PATH = LIFECYCLE_DIR / "worker_leases.json"
PUBLIC_DIR = (
    REPO_ROOT / "v2" / "frontend" / "public" / "v2_closed_loop_execution" / "latest"
)

TASK_TYPES = (
    "CLAUDE_IMPLEMENTATION",
    "CODEX_REVIEW",
    "CODEX_TAKEOVER",
    "REMEDIATION",
)
STATUSES = (
    "pending",
    "running",
    "completed",
    "failed",
    "stale",
    "blocked_operator_required",
    "duplicate_suppressed",
)

DEFAULT_STALL_SECONDS = 10 * 60
DEFAULT_MAX_STALL_RELAUNCHES = 1


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def ensure_dirs() -> None:
    for d in (LIFECYCLE_DIR, LOG_DIR, LOCK_DIR, HEARTBEAT_DIR, PUBLIC_DIR):
        d.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


@contextmanager
def file_lock(group: str, timeout: float = 0.0):
    """Non-blocking flock on ``LOCK_DIR/<group>.lock``.

    Yields True if the lock was acquired, False otherwise. The lock
    serializes edits across the three closed-loop runners so two
    processes never simultaneously edit tasks sharing a
    ``file_lock_group``.
    """
    ensure_dirs()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", group or "default")
    lock_path = LOCK_DIR / f"{safe}.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    acquired = False
    deadline = time.time() + max(0.0, timeout)
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                    if time.time() >= deadline:
                        break
                    time.sleep(0.05)
                    continue
                raise
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            parts = proc_stat.read_text(encoding="utf-8", errors="ignore").split()
            if len(parts) >= 3 and parts[2] == "Z":
                return False
        except OSError:
            pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def normalize_descriptor(raw: dict[str, Any], path: Path) -> dict[str, Any]:
    """Return a copy of ``raw`` upgraded to the lifecycle envelope.

    Existing legacy descriptors miss the lifecycle fields; we fill them
    with safe defaults so the runners can operate without rewriting the
    historical task corpus.
    """
    now = utc_iso()
    d = dict(raw) if isinstance(raw, dict) else {}
    d.setdefault("task_id", path.stem)
    if not d.get("task_type"):
        d["task_type"] = infer_task_type(d, path)
    if not d.get("owner"):
        d["owner"] = infer_owner(d)
    d.setdefault("status", d.get("status") or "pending")
    if not d.get("file_lock_group"):
        d["file_lock_group"] = infer_lock_group(d, path)
    d.setdefault("created_at", now)
    d["updated_at"] = now
    d.setdefault("stall_count", int(d.get("stall_count") or 0))
    d.setdefault("max_stall_relaunches", DEFAULT_MAX_STALL_RELAUNCHES)
    d.setdefault("stall_threshold_seconds", DEFAULT_STALL_SECONDS)
    d.setdefault("expected_output_paths", d.get("expected_output_paths") or [])
    d.setdefault("fail_blockers", d.get("fail_blockers") or [])
    d.setdefault("duplicate_suppression_key", d.get("duplicate_suppression_key"))
    return d


def infer_task_type(d: dict[str, Any], path: Path) -> str:
    name = path.name.lower()
    agent = (d.get("agent") or "").lower()
    if "codex_review" in name or "codex_review" in agent:
        return "CODEX_REVIEW"
    if "codex_takeover" in name or "takeover" in name:
        return "CODEX_TAKEOVER"
    if "remediation" in name:
        return "REMEDIATION"
    if "claude" in name or agent.startswith("claude"):
        return "CLAUDE_IMPLEMENTATION"
    if agent.startswith("codex"):
        return "CODEX_REVIEW"
    return "CLAUDE_IMPLEMENTATION"


def infer_owner(d: dict[str, Any]) -> str:
    agent = (d.get("agent") or "").lower()
    if agent.startswith("codex"):
        return "CODEX"
    if agent.startswith("claude"):
        return "CLAUDE"
    if d.get("operator_required_reason"):
        return "OPERATOR"
    return "CLAUDE"


def infer_lock_group(d: dict[str, Any], path: Path) -> str:
    explicit = d.get("file_lock_group")
    if explicit:
        return str(explicit)
    # Group by the bare task slug (strip leading numeric prefixes and
    # paired claude_fix_/codex_review_ markers) so Claude implementation
    # and its paired Codex review serialise edits over the same area.
    stem = path.stem
    stem = re.sub(r"^\d+_", "", stem)
    stem = re.sub(r"^(claude_fix_|codex_review_|codex_takeover_)", "", stem)
    return stem or path.stem


def iter_task_files() -> Iterable[Path]:
    if not TASKS_DIR.exists():
        return []
    return sorted(p for p in TASKS_DIR.iterdir() if p.suffix == ".json")


def heartbeat_path(task_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", task_id)
    return HEARTBEAT_DIR / f"{safe}.json"


def write_heartbeat(task_id: str, pid: int, extra: dict[str, Any] | None = None) -> None:
    ensure_dirs()
    payload = {
        "task_id": task_id,
        "pid": pid,
        "alive": pid_alive(pid),
        "updated_at": utc_iso(),
    }
    if extra:
        payload.update(extra)
    write_json_atomic(heartbeat_path(task_id), payload)


def read_heartbeat(task_id: str) -> dict[str, Any] | None:
    p = heartbeat_path(task_id)
    if not p.exists():
        return None
    val = read_json(p)
    return val if isinstance(val, dict) else None


def newest_mtime(paths: Iterable[Path]) -> float | None:
    best: float | None = None
    for p in paths:
        if not p.exists():
            continue
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if best is None or m > best:
            best = m
    return best


def expected_outputs_present(d: dict[str, Any]) -> bool:
    paths = d.get("expected_output_paths") or []
    if not paths:
        return False
    for rel in paths:
        if not (REPO_ROOT / rel).exists():
            return False
    return True


def source_truth_status_path(task_id: str) -> Path:
    return STATE_TASKS_DIR / f"{task_id}.json"


def read_source_truth(task_id: str) -> dict[str, Any] | None:
    path = source_truth_status_path(task_id)
    if not path.exists():
        return None
    val = read_json(path)
    return val if isinstance(val, dict) else None


def source_truth_completion_suppresses_dispatch(raw: dict[str, Any]) -> bool:
    """Return True when this descriptor must not be re-queued by source truth.

    A descriptor may still be re-opened by operator intent if they
    explicitly clear the suppression by setting ``source_truth_reopened``
    or ``reopen_from_source_truth``.
    """
    if not bool(raw.get("resolved_from_source_truth")):
        return False
    if str(raw.get("source_truth_status") or "").lower().strip() != "completed":
        return False
    if not bool(raw.get("source_truth_superseded")):
        return False
    if raw.get("source_truth_reopened") or raw.get("reopen_from_source_truth"):
        return False
    return True


def _source_truth_completed_at(state: dict[str, Any]) -> str | None:
    last_run = state.get("last_run")
    if isinstance(last_run, dict):
        end_time = last_run.get("end")
        if isinstance(end_time, str) and end_time:
            return end_time
    ts = state.get("last_status_change_ts")
    return ts if isinstance(ts, str) else None


def reconcile_source_truth_completions(
    *,
    task_paths: Iterable[Path] | None = None,
    apply_updates: bool = True,
) -> dict[str, Any]:
    """Reconcile descriptor completion state against authoritative agent state files.

    Agent Supervisor keeps completion truth in
    ``agent_supervisor/state/tasks/<id>.json``. When a descriptor is marked
    completed there but not in the working descriptor, the descriptor becomes
    terminally completed and is marked as source-of-truth-resolved so it can
    never be redispatched unless state is reopened.
    """
    now = utc_iso()
    paths = [
        p for p in (task_paths if task_paths is not None else iter_task_files())
    ]
    reconciled: list[dict[str, Any]] = []
    completed_task_reconciliations: list[dict[str, Any]] = []
    already_completed_source_truth: list[dict[str, Any]] = []
    redispatch_suppressed: list[dict[str, Any]] = []
    reopened_from_source_truth: list[dict[str, Any]] = []
    leases_to_clear: list[str] = []
    errors: list[dict[str, Any]] = []

    for path in paths:
        raw = read_json(path)
        if not isinstance(raw, dict):
            continue
        d = normalize_descriptor(raw, path)
        task_id = d.get("task_id")
        if not task_id:
            continue
        state = read_source_truth(str(task_id))
        if not state:
            continue
        source_status = str(state.get("status") or "").lower().strip()
        current_status = str(d.get("status") or "").lower().strip()
        if source_status != "completed":
            continue
        if current_status == "completed":
            if source_truth_completion_suppresses_dispatch(raw):
                entry = {
                    "task_id": task_id,
                    "descriptor_path": str(path.relative_to(REPO_ROOT)),
                    "descriptor_status_before": current_status,
                    "source_truth_status": source_status,
                    "reconciled_status": "completed",
                    "source_truth_completed_at": _source_truth_completed_at(state),
                    "reconciled_at": now,
                }
                already_completed_source_truth.append(entry)
                leases_to_clear.append(str(task_id))
            continue

        previous_status = current_status
        completed_at = _source_truth_completed_at(state)
        normalized_completed_at = completed_at if completed_at else now

        if apply_updates:
            raw = dict(raw)
            raw["status"] = "completed"
            raw["next_action"] = (
                "Source-of-truth completed this task in state/tasks; redispatch is suppressed."
            )
            raw["resolved_from_source_truth"] = True
            raw["source_truth_superseded"] = True
            raw["completed_at"] = normalized_completed_at
            raw["source_truth_status"] = source_status
            raw["source_truth_completed_at"] = completed_at or normalized_completed_at
            raw["source_truth_record"] = str(
                source_truth_status_path(str(task_id)).relative_to(REPO_ROOT)
            )
            raw["reconciled_from_source_truth_at"] = now
            raw["updated_at"] = now
            raw["source_truth_superseded"] = True
            raw["resolved_from_source_truth"] = True
            # Preserve historical execution logs / artifacts and stop any in-flight
            # redispatch path from continuing.
            raw.pop("pid_or_job_id", None)
            raw.pop("worker_id", None)
            raw.pop("lease_id", None)
            write_json_atomic(path, raw)

        entry = {
            "task_id": task_id,
            "descriptor_path": str(path.relative_to(REPO_ROOT)),
            "descriptor_status_before": previous_status,
            "source_truth_status": source_status,
            "reconciled_status": "completed",
            "source_truth_completed_at": completed_at,
            "reconciled_at": now,
        }
        completed_task_reconciliations.append(entry)
        reconciled.append(entry)
        redispatch_suppressed.append(entry)
        if previous_status in {"running", "pending", "pending_redispatch", "stale", "completed"}:
            leases_to_clear.append(str(task_id))

    return {
        "schema_version": "v2_closed_loop_source_truth_reconciliation_v1",
        "generated_utc": now,
        "apply_updates": apply_updates,
        "safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
            "modifies_legacy_repo": False,
            "writes_old_redis": False,
            "calls_exchange_mutation": False,
        },
        "completed_from_source_truth_count": len(completed_task_reconciliations),
        "already_completed_source_truth_count": len(already_completed_source_truth),
        "already_completed_source_truth": already_completed_source_truth,
        "redispatch_suppressed_count": len(redispatch_suppressed),
        "reconciled": reconciled,
        "redispatch_suppression": redispatch_suppressed,
        "reopened_from_source_truth": reopened_from_source_truth,
        "stale_completed_reconciliations": completed_task_reconciliations,
        "leases_to_clear": sorted(set(leases_to_clear)),
        "errors": errors,
    }


def clear_active_worker_leases(task_ids: Iterable[str]) -> dict[str, Any]:
    now = utc_iso()
    targets = sorted({str(task_id) for task_id in task_ids if str(task_id)})
    if not targets:
        return {
            "schema_version": "v2_closed_loop_worker_lease_clear_status_v1",
            "generated_utc": now,
            "cleared_count": 0,
            "cleared_lease_ids": [],
            "targeted_task_ids": [],
            "updated": False,
            "errors": [],
        }

    if not WORKER_LEASES_PATH.exists():
        return {
            "schema_version": "v2_closed_loop_worker_lease_clear_status_v1",
            "generated_utc": now,
            "cleared_count": 0,
            "cleared_lease_ids": [],
            "targeted_task_ids": targets,
            "updated": False,
            "errors": [f"worker lease registry missing: {WORKER_LEASES_PATH}"],
        }

    registry = read_json(WORKER_LEASES_PATH)
    if not isinstance(registry, dict):
        return {
            "schema_version": "v2_closed_loop_worker_lease_clear_status_v1",
            "generated_utc": now,
            "cleared_count": 0,
            "cleared_lease_ids": [],
            "targeted_task_ids": targets,
            "updated": False,
            "errors": ["worker lease registry unreadable"],
        }

    leases = registry.get("leases")
    if not isinstance(leases, list):
        return {
            "schema_version": "v2_closed_loop_worker_lease_clear_status_v1",
            "generated_utc": now,
            "cleared_count": 0,
            "cleared_lease_ids": [],
            "targeted_task_ids": targets,
            "updated": False,
            "errors": ["worker lease registry missing leases list"],
        }

    active_statuses = {"active", "running", "leased"}
    cleared_count = 0
    cleared_lease_ids: list[str] = []
    changed = False

    for lease in leases:
        if not isinstance(lease, dict):
            continue
        if str(lease.get("task_id") or "") not in targets:
            continue
        status = str(lease.get("status") or "").lower()
        if status not in active_statuses:
            continue
        lease["status"] = "completed"
        lease["failure_reason"] = lease.get("failure_reason") or "source_truth_completed"
        lease["heartbeat_at"] = now
        cleared_count += 1
        lease_id = lease.get("lease_id")
        if isinstance(lease_id, str):
            cleared_lease_ids.append(lease_id)
        changed = True

    if changed:
        registry["generated_utc"] = now
        write_json_atomic(WORKER_LEASES_PATH, registry)

    return {
        "schema_version": "v2_closed_loop_worker_lease_clear_status_v1",
        "generated_utc": now,
        "cleared_count": cleared_count,
        "cleared_lease_ids": cleared_lease_ids,
        "targeted_task_ids": targets,
        "updated": changed,
        "errors": [],
    }
def is_complete_marker(d: dict[str, Any]) -> bool:
    """Best-effort: a task whose precheck file exists and contains the
    success marker is treated as already complete by the runners. This
    matches how the legacy agent_supervisor tasks signal completion.
    """
    pre = d.get("precheck_file")
    needle = d.get("precheck_contains")
    if not pre or not needle:
        return False
    p = REPO_ROOT / pre
    if not p.exists():
        return False
    try:
        return needle in p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
