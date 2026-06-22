"""V2 Closed-Loop Queue-Consumption Remediation orchestrator.

Codex passed the persistent worker pool, but the mission progress
status shows workers idle_ready while the current-work queue still
has items. This orchestrator answers, item by item, the question
"why isn't this safe automatable task being leased and executed?"
and fixes the consumption path where the answer is one of the
LEASE_CREATION_BUG / QUEUE_FILTER_BUG / STALE_HISTORICAL classes.

Phases mirror the spec:

1. Walk every current queue item, classify it into the canonical
   blocker codes, emit ``queue_consumption_diagnosis.json``.
2. Reset zombie running descriptors and force a bounded lease cycle
   (max 3 Claude leases + 3 Codex leases) using the existing lease
   layer.
3. Wait briefly so workers (polling every 15s) pick the new leases.
4. Collect execution proof: worker_id, worker_pid, lease_id, child
   pid, log path, log bytes, started_at, updated_at.
5. Compute completion/failure accounting for the cycle.
6. Emit canonical outputs + GO_NO_GO marker.

The orchestrator never approves live/canary/legacy shutdown/Redis
trim/exchange mutation. ``live_gate=blocked_human_only`` and
``live_symbols=[]`` are stamped on every payload.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import v2_claude_task_runner as claude_runner
import v2_closed_loop_worker_pool as pool
import v2_codex_review_runner as codex_runner
import v2_current_work_filter as current_filter
from v2_closed_loop_lifecycle import (
    REPO_ROOT,
    TASKS_DIR,
    ensure_dirs,
    normalize_descriptor,
    pid_alive,
    read_json,
    utc_iso,
    write_json_atomic,
)

REMEDIATION_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_worker_pool_queue_consumption_remediation"
    / "latest"
)
REMEDIATION_PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_worker_pool_queue_consumption_remediation"
    / "latest"
)

LIVE_BLOCKED_ENVELOPE = dict(pool.LIVE_BLOCKED_ENVELOPE)

CANONICAL_BLOCKERS = (
    "MALFORMED_DESCRIPTOR",
    "MISSING_OWNER",
    "MISSING_TASK_TYPE",
    "UNSAFE_TASK_TYPE",
    "OPERATOR_REQUIRED",
    "FILE_LOCK_CONFLICT",
    "DUPLICATE_SUPPRESSED",
    "SUPERSEDED",
    "STALE_HISTORICAL",
    "WORKER_AUTH_MISSING",
    "EXECUTOR_BINARY_MISSING",
    "QUEUE_FILTER_BUG",
    "LEASE_CREATION_BUG",
    "NO_BLOCKER_LEASE_SHOULD_HAVE_OCCURRED",
)


def ensure_remediation_dirs() -> None:
    REMEDIATION_DIR.mkdir(parents=True, exist_ok=True)
    REMEDIATION_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------- Phase 1: diagnosis ----------------------------- #


def _active_lease_index() -> tuple[set[str], set[str | None]]:
    registry = pool.read_lease_registry()
    active = [l for l in registry["leases"] if l.get("status") in ("leased", "running")]
    task_ids = {l.get("task_id") for l in active if l.get("task_id")}
    groups = {l.get("file_lock_group") for l in active if l.get("file_lock_group")}
    return task_ids, groups


def diagnose_queue() -> dict[str, Any]:
    queue_result = current_filter.build_current_work_queue(active_window_hours=24)
    queue = queue_result["queue"]
    leased_task_ids, leased_groups = _active_lease_index()
    rows: list[dict[str, Any]] = []
    claude_exec = claude_runner.discover_claude_executor()
    codex_exec = codex_runner.discover_codex_executor()
    by_lane: dict[str, list[dict[str, Any]]] = pool.current_alive_workers_by_lane()
    # Pass 1: every row in the current-work queue.
    current_paths = {REPO_ROOT / row["path"] for row in queue["current"]}
    # Pass 2: include descriptors that are flagged ``current_active=true``
    # but the current-work filter rejected (typically for safety /
    # operator-required reasons). The diagnostic must still answer
    # "why isn't this being executed?" for those.
    extra_paths: list[Path] = []
    if TASKS_DIR.exists():
        for f in sorted(TASKS_DIR.iterdir()):
            if f.suffix != ".json" or f in current_paths:
                continue
            raw = read_json(f)
            if not isinstance(raw, dict):
                continue
            if raw.get("current_active") is True:
                extra_paths.append(f)
    for row in queue["current"]:
        path = REPO_ROOT / row["path"]
        raw = read_json(path)
        if not isinstance(raw, dict):
            rows.append({
                "task_id": row.get("task_id"),
                "descriptor_path": row.get("path"),
                "task_type": None,
                "owner": None,
                "file_lock_group": None,
                "eligible_for_claude_worker": False,
                "eligible_for_codex_worker": False,
                "selected_by_filter": True,
                "rejected_by_filter": False,
                "rejection_reason": None,
                "lease_attempted": False,
                "lease_created": False,
                "worker_assigned": None,
                "blocker_if_not_leased": "MALFORMED_DESCRIPTOR",
            })
            continue
        d = normalize_descriptor(raw, path)
        verdict = classify_queue_item(
            d, path, leased_task_ids, leased_groups, claude_exec, codex_exec,
            by_lane,
        )
        rows.append(verdict)
    for path in extra_paths:
        raw = read_json(path)
        if not isinstance(raw, dict):
            continue
        d = normalize_descriptor(raw, path)
        verdict = classify_queue_item(
            d, path, leased_task_ids, leased_groups, claude_exec, codex_exec,
            by_lane,
        )
        # Mark as filter-rejected so the operator sees this came from
        # the broader scan, not the current-work filter.
        verdict["selected_by_filter"] = False
        verdict["rejected_by_filter"] = True
        rows.append(verdict)
    return {
        "schema_version": "v2_closed_loop_queue_consumption_diagnosis_v1",
        "generated_utc": utc_iso(),
        "current_automatable_count": queue["current_automatable_count"],
        "historical_excluded_count": queue["historical_excluded_count"],
        "rows": rows,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }


def classify_queue_item(
    d: dict[str, Any],
    path: Path,
    leased_task_ids: set[str],
    leased_groups: set,
    claude_exec: dict[str, Any],
    codex_exec: dict[str, Any],
    by_lane: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    task_id = d.get("task_id") or path.stem
    ttype = d.get("task_type")
    status = d.get("status")
    owner = d.get("owner")
    grp = d.get("file_lock_group")

    eligible_for_claude = ttype in (pool.LANE_TYPE_CLAUDE, pool.LANE_TYPE_REMEDIATION)
    eligible_for_codex = ttype in (pool.LANE_TYPE_CODEX, pool.LANE_TYPE_TAKEOVER)

    selected = True
    rejected = False
    rejection_reason: str | None = None
    blocker: str | None = None

    if not ttype:
        rejected = True
        rejection_reason = "missing_task_type"
        blocker = "MISSING_TASK_TYPE"
    elif not owner:
        rejected = True
        rejection_reason = "missing_owner"
        blocker = "MISSING_OWNER"
    elif d.get("operator_required_reason") or status == "blocked_operator_required":
        rejected = True
        rejection_reason = f"operator_required:{d.get('operator_required_reason')}"
        blocker = "OPERATOR_REQUIRED"
    elif d.get("superseded_by"):
        rejected = True
        rejection_reason = f"superseded_by:{d.get('superseded_by')}"
        blocker = "SUPERSEDED"
    elif pool.is_unsafe_descriptor(d) is not None:
        rejected = True
        rejection_reason = f"unsafe:{pool.is_unsafe_descriptor(d)}"
        blocker = "UNSAFE_TASK_TYPE"
    elif status == "duplicate_suppressed":
        rejected = True
        rejection_reason = "duplicate"
        blocker = "DUPLICATE_SUPPRESSED"
    elif status in ("completed",):
        rejected = True
        rejection_reason = "already_completed"
        blocker = None
    elif task_id in leased_task_ids:
        rejected = False
        rejection_reason = None
        blocker = None
    elif grp and grp in leased_groups:
        rejected = True
        rejection_reason = f"file_lock_group_held:{grp}"
        blocker = "FILE_LOCK_CONFLICT"
    elif status == "running" and not _running_descriptor_has_live_pid(d):
        rejected = True
        rejection_reason = "running_status_but_dead_pid"
        blocker = "STALE_HISTORICAL"  # zombie — should be reset
    elif eligible_for_claude and not claude_exec.get("available"):
        rejected = True
        rejection_reason = "claude_executor_missing"
        blocker = "EXECUTOR_BINARY_MISSING"
    elif eligible_for_codex and not codex_exec.get("available"):
        rejected = True
        rejection_reason = "codex_executor_missing"
        blocker = "EXECUTOR_BINARY_MISSING"
    elif status not in ("pending", "pending_redispatch"):
        # status=running with live pid means it IS being executed — fine.
        rejected = False
        rejection_reason = f"status={status}"
        blocker = None
    else:
        # No reason to refuse — if there is also a fresh Claude or Codex
        # worker, this is a lease-creation bug.
        if (eligible_for_claude and by_lane.get(pool.LANE_TYPE_CLAUDE)) or (
            eligible_for_codex and by_lane.get(pool.LANE_TYPE_CODEX)
        ):
            blocker = "NO_BLOCKER_LEASE_SHOULD_HAVE_OCCURRED"

    return {
        "task_id": task_id,
        "task_type": ttype,
        "owner": owner,
        "descriptor_path": str(path.relative_to(REPO_ROOT)),
        "file_lock_group": grp,
        "status": status,
        "eligible_for_claude_worker": eligible_for_claude,
        "eligible_for_codex_worker": eligible_for_codex,
        "selected_by_filter": selected,
        "rejected_by_filter": rejected,
        "rejection_reason": rejection_reason,
        "lease_attempted": False,
        "lease_created": task_id in leased_task_ids,
        "worker_assigned": _find_worker_assigned(task_id),
        "blocker_if_not_leased": blocker,
    }


def _running_descriptor_has_live_pid(d: dict[str, Any]) -> bool:
    pid = d.get("pid_or_job_id")
    return pid_alive(pid)


def _find_worker_assigned(task_id: str) -> str | None:
    registry = pool.read_lease_registry()
    for l in registry["leases"]:
        if l.get("task_id") == task_id and l.get("status") in ("leased", "running"):
            return l.get("worker_id")
    return None


# ----------------------------- Phase 2: force lease cycle ----------------------------- #


def reset_zombie_running_descriptors(diagnosis: dict[str, Any]) -> list[dict[str, Any]]:
    """Reset descriptors whose status==running but whose pid is dead.

    Returning them to ``pending`` allows the worker pool to claim them
    in the next cycle. This is the documented STALE_HISTORICAL path.
    """
    reset: list[dict[str, Any]] = []
    for row in diagnosis["rows"]:
        if row.get("blocker_if_not_leased") != "STALE_HISTORICAL":
            continue
        path = REPO_ROOT / row["descriptor_path"]
        raw = read_json(path) or {}
        if not isinstance(raw, dict):
            continue
        raw["status"] = "pending"
        raw["updated_at"] = utc_iso()
        raw.pop("pid_or_job_id", None)
        raw.pop("started_at", None)
        write_json_atomic(path, raw)
        reset.append({
            "task_id": row["task_id"],
            "from_status": "running_zombie",
            "to_status": "pending",
        })
    return reset


def materialize_current_descriptor_envelope(
    diagnosis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Persist inferred lifecycle fields for current descriptors.

    Older descriptors sometimes carry explicit nulls for task_type,
    owner, or file_lock_group. Normalization can infer them in memory,
    but already-running worker daemons only see the JSON on disk. This
    materializes the safe inferred envelope so real workers can claim
    the task themselves; no lease is created here.
    """
    materialized: list[dict[str, Any]] = []
    for row in diagnosis.get("rows") or []:
        if not row.get("selected_by_filter"):
            continue
        path = REPO_ROOT / str(row.get("descriptor_path") or "")
        raw = read_json(path)
        if not isinstance(raw, dict):
            continue
        normalized = normalize_descriptor(raw, path)
        updates: dict[str, Any] = {}
        for key in ("task_type", "owner", "file_lock_group"):
            if not raw.get(key) and normalized.get(key):
                updates[key] = normalized[key]
        if "expected_output_paths" not in raw:
            updates["expected_output_paths"] = normalized.get("expected_output_paths") or []
        if not updates:
            continue
        raw.update(updates)
        raw["updated_at"] = utc_iso()
        write_json_atomic(path, raw)
        materialized.append({
            "task_id": normalized.get("task_id"),
            "descriptor_path": str(path.relative_to(REPO_ROOT)),
            "fields": sorted(updates),
        })
    return materialized


def force_lease_cycle(
    *,
    max_claude_leases: int,
    max_codex_leases: int,
) -> dict[str, Any]:
    """Run the maintainer and let real worker daemons claim work.

    Earlier versions of this remediation created leases from the
    orchestrator process. That proves only descriptor mutation, not
    worker execution. Queue consumption now remains worker-claim based:
    the remediation refreshes the pool and waits for daemon workers to
    claim tasks through their normal loop.
    """
    pool_status_before = pool.run_pool_once(
        target_claude=pool.DEFAULT_MAX_CLAUDE_WORKERS,
        target_codex=pool.DEFAULT_MAX_CODEX_WORKERS,
        spawn=True,
        reclaim=True,
    )
    alive = pool.current_alive_workers_by_lane()
    claude_attempts = [{
        "worker_claim_model": True,
        "external_lease_created": False,
        "idle_worker_count": sum(
            1 for hb in alive.get(pool.LANE_TYPE_CLAUDE, [])
            if hb.get("state") == "idle_ready"
        ),
        "max_lease_target": max_claude_leases,
    }]
    codex_attempts = [{
        "worker_claim_model": True,
        "external_lease_created": False,
        "idle_worker_count": sum(
            1 for hb in alive.get(pool.LANE_TYPE_CODEX, [])
            if hb.get("state") == "idle_ready"
        ),
        "max_lease_target": max_codex_leases,
    }]

    return {
        "claude_attempts": claude_attempts,
        "codex_attempts": codex_attempts,
        "claude_leases_created": 0,
        "codex_leases_created": 0,
        "external_lease_creation_disabled": True,
        "worker_claim_model": True,
        "pool_status_before_wait": pool_status_before,
    }


# ----------------------------- Phase 3: execution proof ----------------------------- #


def collect_execution_proof() -> list[dict[str, Any]]:
    registry = pool.read_lease_registry()
    heartbeats = {hb.get("worker_id"): hb for hb in pool.read_worker_heartbeats()}
    proof: list[dict[str, Any]] = []
    for lease in registry["leases"]:
        if lease.get("status") not in ("leased", "running"):
            continue
        descriptor_path = REPO_ROOT / lease.get("descriptor_path", "")
        d = read_json(descriptor_path) if descriptor_path.exists() else None
        log_path = d.get("log_path") if isinstance(d, dict) else None
        if not log_path and lease.get("task_id"):
            log_path = str(pool.LOG_DIR / f"{lease['task_id']}.log")
        log_bytes: int | None = None
        if log_path:
            lp = REPO_ROOT / log_path if not Path(log_path).is_absolute() else Path(log_path)
            if lp.exists():
                try:
                    log_bytes = lp.stat().st_size
                except OSError:
                    log_bytes = None
        worker_hb = heartbeats.get(lease.get("worker_id")) or {}
        proof.append({
            "worker_id": lease.get("worker_id"),
            "worker_pid": worker_hb.get("pid"),
            "worker_heartbeat": worker_hb.get("last_heartbeat"),
            "worker_state": worker_hb.get("state"),
            "worker_current_lease_id": worker_hb.get("current_lease_id"),
            "lease_id": lease.get("lease_id"),
            "lease_status": lease.get("status"),
            "task_id": lease.get("task_id"),
            "task_status": d.get("status") if isinstance(d, dict) else None,
            "child_process_pid": worker_hb.get("child_pid"),
            "log_path": log_path,
            "log_bytes": log_bytes,
            "expected_outputs": lease.get("output_paths"),
            "started_at": d.get("started_at") if isinstance(d, dict) else None,
            "updated_at": d.get("updated_at") if isinstance(d, dict) else None,
        })
    return proof


# ----------------------------- Phase 4: accounting ----------------------------- #


def compute_accounting(diagnosis_before: dict[str, Any]) -> dict[str, Any]:
    diagnosis_now = diagnose_queue()
    before_status_by_task = {r["task_id"]: r.get("status") for r in diagnosis_before["rows"]}

    completed = 0
    failed = 0
    blocked = 0
    still_running = 0
    remediations_created = 0
    idle_workers_with_work = 0

    for row in diagnosis_now["rows"]:
        prior_status = before_status_by_task.get(row["task_id"])
        now_status = row.get("status")
        if now_status == "completed" and prior_status != "completed":
            completed += 1
        elif now_status == "failed" and prior_status != "failed":
            failed += 1
        elif now_status == "blocked_operator_required" and prior_status != "blocked_operator_required":
            blocked += 1
        elif now_status == "running":
            still_running += 1

    # Detect any new remediation descriptors created since baseline.
    if TASKS_DIR.exists():
        for f in TASKS_DIR.iterdir():
            if f.suffix != ".json":
                continue
            try:
                if f.stat().st_mtime < time.time() - 600:
                    continue
            except OSError:
                continue
            if f.name.startswith("closed_loop_remediation_"):
                remediations_created += 1

    # Idle workers with eligible work.
    alive = pool.current_alive_workers_by_lane()
    idle_claude = [hb for hb in alive.get(pool.LANE_TYPE_CLAUDE, []) if hb.get("state") == "idle_ready"]
    idle_codex = [hb for hb in alive.get(pool.LANE_TYPE_CODEX, []) if hb.get("state") == "idle_ready"]
    eligible_claude = [
        r for r in diagnosis_now["rows"]
        if r["eligible_for_claude_worker"]
        and r.get("status") in ("pending", "pending_redispatch")
        and not r.get("lease_created")
        and r.get("blocker_if_not_leased") in (None, "NO_BLOCKER_LEASE_SHOULD_HAVE_OCCURRED")
    ]
    eligible_codex = [
        r for r in diagnosis_now["rows"]
        if r["eligible_for_codex_worker"]
        and r.get("status") in ("pending", "pending_redispatch")
        and not r.get("lease_created")
        and r.get("blocker_if_not_leased") in (None, "NO_BLOCKER_LEASE_SHOULD_HAVE_OCCURRED")
    ]
    if idle_claude and eligible_claude:
        idle_workers_with_work += min(len(idle_claude), len(eligible_claude))
    if idle_codex and eligible_codex:
        idle_workers_with_work += min(len(idle_codex), len(eligible_codex))

    return {
        "completed_task_count_this_cycle": completed,
        "failed_task_count_this_cycle": failed,
        "remediation_created_count_this_cycle": remediations_created,
        "blocked_task_count_this_cycle": blocked,
        "still_running_task_count": still_running,
        "idle_workers_with_eligible_work_count": idle_workers_with_work,
        "diagnosis_after": diagnosis_now,
    }


# ----------------------------- Phase 5+6: state + outputs ----------------------------- #


def compute_state(
    diagnosis_before: dict[str, Any],
    zombies_reset: list[dict[str, Any]],
    lease_cycle: dict[str, Any],
    execution_proof: list[dict[str, Any]],
    accounting: dict[str, Any],
) -> dict[str, Any]:
    diagnosis_after = accounting["diagnosis_after"]
    pool_status = pool.compute_pool_status(
        target_claude=pool.DEFAULT_MAX_CLAUDE_WORKERS,
        target_codex=pool.DEFAULT_MAX_CODEX_WORKERS,
    )

    blockers: list[str] = []
    if accounting["idle_workers_with_eligible_work_count"] > 0:
        blockers.append("IDLE_WORKERS_WHILE_ELIGIBLE_WORK_EXISTS")
    if pool_status.get("duplicate_task_leases"):
        blockers.append("DUPLICATE_TASK_LEASE")
    if pool_status.get("duplicate_file_locks"):
        blockers.append("DUPLICATE_FILE_LOCK_LEASE")
    if pool_status.get("duplicate_worker_leases"):
        blockers.append("DUPLICATE_WORKER_ACTIVE_LEASE")

    eligible_safe_pending = [
        r for r in diagnosis_after["rows"]
        if r.get("status") in ("pending", "pending_redispatch")
        and (r.get("blocker_if_not_leased") is None
             or r.get("blocker_if_not_leased") == "NO_BLOCKER_LEASE_SHOULD_HAVE_OCCURRED")
        and not r.get("lease_created")
    ]
    eligible_total = (
        sum(1 for r in diagnosis_after["rows"]
            if (r.get("status") in ("pending", "pending_redispatch", "running")
                or r.get("lease_created"))
            and r.get("blocker_if_not_leased") is None)
    )
    active_leases = pool_status["active_leases_count"]
    if active_leases < min(3, eligible_total) and len(eligible_safe_pending) > 0:
        blockers.append("ACTIVE_LEASE_COUNT_BELOW_MINIMUM")
    missing_proof = [
        p for p in execution_proof
        if not p.get("task_id")
        or not p.get("worker_id")
        or not p.get("worker_pid")
        or not p.get("worker_heartbeat")
        or not p.get("log_path")
    ]
    if missing_proof:
        blockers.append("ACTIVE_LEASE_PROOF_MISSING")
    non_executing_leases = [
        p for p in execution_proof
        if p.get("lease_status") == "leased"
        and p.get("worker_current_lease_id") != p.get("lease_id")
    ]
    if non_executing_leases:
        blockers.append("ACTIVE_LEASE_NOT_EXECUTING")

    ready = not blockers
    marker = (
        "V2_WORKER_POOL_QUEUE_CONSUMPTION_REMEDIATION_READY"
        if ready else
        "V2_WORKER_POOL_QUEUE_CONSUMPTION_REMEDIATION_BLOCKED"
    )

    return {
        "schema_version": "v2_worker_pool_queue_consumption_remediation_status_v1",
        "generated_utc": utc_iso(),
        "go_no_go": marker,
        "marker": marker,
        "ready": ready,
        "blockers": blockers,
        "diagnosis_before": diagnosis_before,
        "diagnosis_after": diagnosis_after,
        "zombies_reset": zombies_reset,
        "lease_cycle": lease_cycle,
        "execution_proof": execution_proof,
        "accounting": {k: v for k, v in accounting.items() if k != "diagnosis_after"},
        "pool_status": pool_status,
        "active_leases_count": active_leases,
        "eligible_safe_pending_count": len(eligible_safe_pending),
        "eligible_total_count": eligible_total,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }


def emit_outputs(state: dict[str, Any]) -> None:
    ensure_remediation_dirs()
    write_json_atomic(
        REMEDIATION_DIR / "queue_consumption_diagnosis.json",
        state["diagnosis_after"],
    )
    write_json_atomic(
        REMEDIATION_PUBLIC_DIR / "queue_consumption_diagnosis.json",
        state["diagnosis_after"],
    )
    write_json_atomic(
        REMEDIATION_DIR / "queue_lease_assignment_status.json",
        {
            "schema_version": "v2_worker_pool_queue_lease_assignment_status_v1",
            "generated_utc": state["generated_utc"],
            "lease_cycle": state["lease_cycle"],
            "active_leases_count": state["active_leases_count"],
            "eligible_safe_pending_count": state["eligible_safe_pending_count"],
            "current_task_assignments": state["pool_status"]["current_task_assignments"],
            "active_leases": state["execution_proof"],
            "safety": dict(LIVE_BLOCKED_ENVELOPE),
        },
    )
    write_json_atomic(
        REMEDIATION_DIR / "worker_execution_proof.json",
        {
            "schema_version": "v2_worker_pool_worker_execution_proof_v1",
            "generated_utc": state["generated_utc"],
            "execution_proof": state["execution_proof"],
            "safety": dict(LIVE_BLOCKED_ENVELOPE),
        },
    )
    write_json_atomic(
        REMEDIATION_PUBLIC_DIR / "worker_execution_proof.json",
        {
            "schema_version": "v2_worker_pool_worker_execution_proof_v1",
            "generated_utc": state["generated_utc"],
            "execution_proof": state["execution_proof"],
            "safety": dict(LIVE_BLOCKED_ENVELOPE),
        },
    )
    write_json_atomic(REMEDIATION_DIR / "queue_consumption_remediation_status.json", state)
    write_json_atomic(REMEDIATION_PUBLIC_DIR / "queue_consumption_remediation_status.json", state)
    write_json_atomic(
        REMEDIATION_DIR / "operator_dashboard_payload.json", _operator_payload(state),
    )
    write_json_atomic(
        REMEDIATION_PUBLIC_DIR / "operator_dashboard_payload.json", _operator_payload(state),
    )
    (REMEDIATION_DIR / "GO_NO_GO.md").write_text(state["marker"] + "\n", encoding="utf-8")
    (REMEDIATION_DIR / "V2_WORKER_POOL_QUEUE_CONSUMPTION_REMEDIATION_REPORT.md").write_text(
        _render_report(state), encoding="utf-8",
    )
    _refresh_mission_progress_status(state)


def _operator_payload(state: dict[str, Any]) -> dict[str, Any]:
    ps = state["pool_status"]
    acc = state["accounting"]
    return {
        "schema_version": "v2_worker_pool_queue_consumption_operator_payload_v1",
        "generated_utc": state["generated_utc"],
        "marker": state["marker"],
        "go_no_go": state["marker"],
        "ready": state["ready"],
        "blockers": state["blockers"],
        "active_lane_count": ps["active_lane_count"],
        "active_claude_workers": ps["active_claude_workers"],
        "active_codex_workers": ps["active_codex_workers"],
        "worker_count_busy": ps["worker_count_busy"],
        "worker_count_idle_ready": ps["worker_count_idle_ready"],
        "active_leases_count": ps["active_leases_count"],
        "current_automatable_count": ps["current_automatable_count"],
        "current_automatable_count_by_lane": ps["current_automatable_count_by_lane"],
        "current_task_assignments": ps["current_task_assignments"],
        "idle_workers_with_eligible_work_count": acc["idle_workers_with_eligible_work_count"],
        "completed_task_count_this_cycle": acc["completed_task_count_this_cycle"],
        "failed_task_count_this_cycle": acc["failed_task_count_this_cycle"],
        "remediation_created_count_this_cycle": acc["remediation_created_count_this_cycle"],
        "blocked_task_count_this_cycle": acc["blocked_task_count_this_cycle"],
        "still_running_task_count": acc["still_running_task_count"],
        "automation_state": (
            "execution_active"
            if (ps["worker_count_busy"] > 0 or ps["active_leases_count"] > 0)
            else "monitor_only"
        ),
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
        "next_action": (
            "Queue consumption READY — workers leasing and executing current work."
            if state["ready"] else
            f"Queue consumption BLOCKED: {state['blockers'][0]}."
        ),
    }


def _render_report(state: dict[str, Any]) -> str:
    ps = state["pool_status"]
    acc = state["accounting"]
    diag_after = state["diagnosis_after"]
    lines = [
        "# V2 Worker Pool Queue-Consumption Remediation Report",
        "",
        f"Marker: `{state['marker']}`",
        f"Generated: {state['generated_utc']}",
        "",
        "## Worker Pool",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| worker_count_total | {ps['worker_count_total']} |",
        f"| worker_count_active | {ps['worker_count_active']} |",
        f"| worker_count_busy | {ps['worker_count_busy']} |",
        f"| worker_count_idle_ready | {ps['worker_count_idle_ready']} |",
        f"| active_claude_workers | {ps['active_claude_workers']} |",
        f"| active_codex_workers | {ps['active_codex_workers']} |",
        f"| active_lane_count | {ps['active_lane_count']} |",
        f"| active_leases_count | {ps['active_leases_count']} |",
        f"| current_automatable_count | {ps['current_automatable_count']} |",
        "",
        "## Cycle Accounting",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| completed_task_count_this_cycle | {acc['completed_task_count_this_cycle']} |",
        f"| failed_task_count_this_cycle | {acc['failed_task_count_this_cycle']} |",
        f"| remediation_created_count_this_cycle | {acc['remediation_created_count_this_cycle']} |",
        f"| blocked_task_count_this_cycle | {acc['blocked_task_count_this_cycle']} |",
        f"| still_running_task_count | {acc['still_running_task_count']} |",
        f"| idle_workers_with_eligible_work_count | {acc['idle_workers_with_eligible_work_count']} |",
        "",
        "## Queue Consumption Diagnosis (current rows)",
        "",
        "| task_id | task_type | status | lease | blocker_if_not_leased |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in diag_after["rows"]:
        lines.append(
            f"| {row.get('task_id')} | {row.get('task_type')} | "
            f"{row.get('status')} | {row.get('lease_created')} | "
            f"{row.get('blocker_if_not_leased') or '-'} |"
        )
    lines.extend([
        "",
        "## Current Task Assignments (active leases only)",
        "",
        "| worker_id | task_id | lane_type | leased_at |",
        "| --- | --- | --- | --- |",
    ])
    for a in ps["current_task_assignments"]:
        lines.append(
            f"| {a['worker_id']} | {a['task_id']} | {a['lane_type']} | {a.get('leased_at')} |"
        )
    lines.extend([
        "",
        "## Zombies Reset",
        "",
        *([f"- {z['task_id']}" for z in state["zombies_reset"]] or ["- (none)"]),
        "",
        "## Lease Cycle Results",
        "",
        f"- claude_leases_created: {state['lease_cycle']['claude_leases_created']}",
        f"- codex_leases_created:  {state['lease_cycle']['codex_leases_created']}",
        "",
        "## Blockers",
        "",
        *([f"- {b}" for b in state["blockers"]] or ["- (none)"]),
        "",
        "## Safety",
        "",
        "- live_gate=blocked_human_only",
        "- live_symbols=[]",
        "- approves_live=false",
        "- approves_canary=false",
        "- approves_legacy_shutdown=false",
        "- approves_redis_trim=false",
        "",
    ])
    return "\n".join(lines)


def _refresh_mission_progress_status(state: dict[str, Any]) -> None:
    """Write a concise mission-progress refresh so the lane the operator
    has been reading from stays current with the new queue-consumption
    truth."""
    mp_dir = REPO_ROOT / "claude_worklog" / "final_readiness" / "v2_worker_pool_mission_progress" / "latest"
    mp_public_dir = REPO_ROOT / "v2" / "frontend" / "public" / "v2_worker_pool_mission_progress" / "latest"
    mp_dir.mkdir(parents=True, exist_ok=True)
    mp_public_dir.mkdir(parents=True, exist_ok=True)
    ps = state["pool_status"]
    acc = state["accounting"]
    payload = {
        "schema_version": "v2_worker_pool_mission_progress_refresh_v1",
        "generated_utc": state["generated_utc"],
        "worker_pool_marker": "V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_READY",
        "queue_consumption_marker": state["marker"],
        "active_lane_count": ps["active_lane_count"],
        "active_claude_workers": ps["active_claude_workers"],
        "active_codex_workers": ps["active_codex_workers"],
        "current_automatable_count": ps["current_automatable_count"],
        "active_leases_count": ps["active_leases_count"],
        "worker_count_busy": ps["worker_count_busy"],
        "worker_count_idle_ready": ps["worker_count_idle_ready"],
        "tasks_completed_last_cycle": acc["completed_task_count_this_cycle"],
        "tasks_failed_last_cycle": acc["failed_task_count_this_cycle"],
        "remediations_created_last_cycle": acc["remediation_created_count_this_cycle"],
        "idle_workers_with_eligible_work_count": acc["idle_workers_with_eligible_work_count"],
        "automation_state": (
            "execution_active"
            if (ps["worker_count_busy"] > 0 or ps["active_leases_count"] > 0)
            else "monitor_only"
        ),
        "queued_migration_work_count": ps["current_automatable_count"],
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    write_json_atomic(
        mp_dir / "operator_dashboard_payload.json", payload,
    )
    write_json_atomic(
        mp_public_dir / "operator_dashboard_payload.json", payload,
    )
    status_payload = {
        "schema_version": "v2_worker_pool_mission_progress_status_v2",
        "generated_utc": state["generated_utc"],
        "go_no_go": "V2_WORKER_POOL_MISSION_PROGRESS_STATUS",
        "mission_progress_state": payload["automation_state"],
        "worker_pool_reference": {
            "source": (
                "claude_worklog/final_readiness/"
                "v2_worker_pool_queue_consumption_remediation/latest/"
                "queue_consumption_remediation_status.json"
            ),
            "worker_pool_marker": payload["worker_pool_marker"],
            "queue_consumption_marker": payload["queue_consumption_marker"],
            "active_lane_count": payload["active_lane_count"],
            "active_claude_workers": payload["active_claude_workers"],
            "active_codex_workers": payload["active_codex_workers"],
            "current_automatable_count": payload["current_automatable_count"],
            "active_leases_count": payload["active_leases_count"],
            "worker_count_busy": payload["worker_count_busy"],
            "worker_count_idle_ready": payload["worker_count_idle_ready"],
        },
        "current_active_tasks": ps["current_task_assignments"],
        "current_active_task_note": (
            "Tasks listed here are active leases only; idle worker "
            "heartbeats are not counted as execution."
        ),
        "current_automatable_queue": state["diagnosis_after"]["rows"],
        "tasks_completed_last_hour": [],
        "codex_reviews_completed_last_hour": [],
        "remediations_generated_from_codex_fail": (
            acc["remediation_created_count_this_cycle"]
        ),
        "drift_controls": {
            "no_ui_only_drift_while_model_edge_blockers_remain": True,
            "report_only_work_counted_as_migration_progress": False,
            "automation_execution_based_on_active_leases": True,
        },
        "open_mission_blockers": [
            "paper_edge_not_proven",
            "native_model_not_production_ready",
            "checkpoint_not_ready",
            "legacy_shutdown_blocked",
            "live_gate_human_only",
        ],
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    write_json_atomic(mp_dir / "worker_pool_mission_progress_status.json", status_payload)
    write_json_atomic(
        mp_public_dir / "worker_pool_mission_progress_status.json",
        status_payload,
    )


# ----------------------------- main ----------------------------- #


def run_once(
    *,
    max_claude_leases: int,
    max_codex_leases: int,
    reset_zombies_flag: bool,
    wait_seconds: int,
    dry_run: bool,
) -> dict[str, Any]:
    ensure_dirs()
    ensure_remediation_dirs()

    diagnosis_before = diagnose_queue()
    write_json_atomic(
        REMEDIATION_DIR / "queue_consumption_diagnosis.json", diagnosis_before,
    )

    zombies_reset: list[dict[str, Any]] = []
    if reset_zombies_flag and not dry_run:
        zombies_reset = reset_zombie_running_descriptors(diagnosis_before)
        # Refresh diagnosis so leases see the new pending status.
        diagnosis_before = diagnose_queue()
    materialized_descriptors = materialize_current_descriptor_envelope(diagnosis_before)
    if materialized_descriptors:
        diagnosis_before = diagnose_queue()

    if dry_run:
        lease_cycle = {
            "claude_attempts": [], "codex_attempts": [],
            "claude_leases_created": 0, "codex_leases_created": 0,
            "skipped": True, "reason": "dry_run",
        }
    else:
        lease_cycle = force_lease_cycle(
            max_claude_leases=max_claude_leases,
            max_codex_leases=max_codex_leases,
        )

    if wait_seconds > 0 and not dry_run:
        time.sleep(wait_seconds)

    execution_proof = collect_execution_proof()
    accounting = compute_accounting(diagnosis_before)
    state = compute_state(
        diagnosis_before, zombies_reset, lease_cycle, execution_proof, accounting,
    )
    state["materialized_descriptors"] = materialized_descriptors
    emit_outputs(state)
    return state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-claude-leases", type=int, default=3)
    p.add_argument("--max-codex-leases", type=int, default=3)
    p.add_argument("--no-reset-zombies", action="store_true")
    p.add_argument("--wait-seconds", type=int, default=8)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    state = run_once(
        max_claude_leases=args.max_claude_leases,
        max_codex_leases=args.max_codex_leases,
        reset_zombies_flag=not args.no_reset_zombies,
        wait_seconds=args.wait_seconds,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        ps = state["pool_status"]
        acc = state["accounting"]
        print(json.dumps({
            "marker": state["marker"],
            "ready": state["ready"],
            "blockers": state["blockers"],
            "active_lane_count": ps["active_lane_count"],
            "active_leases_count": ps["active_leases_count"],
            "worker_count_busy": ps["worker_count_busy"],
            "worker_count_idle_ready": ps["worker_count_idle_ready"],
            "idle_workers_with_eligible_work_count": acc["idle_workers_with_eligible_work_count"],
            "completed_this_cycle": acc["completed_task_count_this_cycle"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
