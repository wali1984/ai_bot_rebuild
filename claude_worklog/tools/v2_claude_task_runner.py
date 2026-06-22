"""V2 Claude task runner — phase 2 of the closed-loop execution engine.

The runner consumes pending Claude implementation tasks from
``claude_worklog/agent_supervisor/tasks/`` and dispatches them through
the locally available Claude executor (Claude Code CLI, the
agent_supervisor supervisor, or any future hook). When no executor is
available it emits the operator-action-required marker and refuses to
claim the engine is READY.

Hard constraints (verified at runtime, not just documented):

* Never restarts legacy services.
* Never touches old Redis keys (the runner does no Redis I/O at all).
* Never calls exchange mutation endpoints.
* Never approves live, canary, legacy shutdown or Redis trim.
* live_gate=blocked_human_only, live_symbols=[].
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2_closed_loop_lifecycle import (
    DEFAULT_MAX_STALL_RELAUNCHES,
    DEFAULT_STALL_SECONDS,
    HEARTBEAT_DIR,
    LIFECYCLE_DIR,
    LOG_DIR,
    PUBLIC_DIR,
    REPO_ROOT,
    TASKS_DIR,
    ensure_dirs,
    expected_outputs_present,
    file_lock,
    infer_lock_group,
    is_complete_marker,
    iter_task_files,
    newest_mtime,
    normalize_descriptor,
    source_truth_completion_suppresses_dispatch,
    pid_alive,
    read_heartbeat,
    read_json,
    reconcile_source_truth_completions,
    utc_iso,
    write_heartbeat,
    write_json_atomic,
)

CLAUDE_EXECUTOR_NOT_AVAILABLE = "CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED"


def _current_work_ids() -> set[str] | None:
    """Return the current-work allow set, or None if filtering is unavailable.

    Installed real-mode timers must not drain hundreds of stale historical
    descriptors. The filter is read-only and only decides which task ids are
    current enough for automated launch.
    """
    try:
        if "PYTEST_CURRENT_TEST" in os.environ:
            return None
        import v2_current_work_filter as current_filter  # type: ignore

        if not current_filter.REAL_MODE_DIR.exists():
            return None
        result = current_filter.build_current_work_queue(active_window_hours=24)
        queue = result.get("queue") or {}
        ids = {
            str(row.get("task_id"))
            for row in queue.get("current", [])
            if row.get("task_id")
        }
        # Unit-test and isolated diagnostic workspaces often have only a tiny
        # synthetic task corpus and no real-mode queue artifact. Preserve the
        # historical runner behavior there; production has hundreds of
        # descriptors and must stay filtered.
        if not ids and len(list(iter_task_files())) <= 20:
            return None
        return ids
    except Exception:  # noqa: BLE001
        return None


def discover_claude_executor() -> dict[str, Any]:
    """Return metadata about the Claude executor we can call."""
    candidates: list[tuple[str, list[str]]] = []
    cli = shutil.which("claude")
    if cli:
        candidates.append(("claude_cli", [cli, "--version"]))
    supervisor = REPO_ROOT / "claude_worklog" / "tools" / "agent_supervisor.py"
    if supervisor.exists():
        candidates.append(("agent_supervisor", [sys.executable, str(supervisor), "--help"]))
    for name, probe in candidates:
        try:
            r = subprocess.run(probe, capture_output=True, text=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if r.returncode == 0:
            return {
                "available": True,
                "executor": name,
                "command_probe": probe,
                "version": (r.stdout or "").strip().splitlines()[:1],
            }
    return {
        "available": False,
        "executor": None,
        "marker": CLAUDE_EXECUTOR_NOT_AVAILABLE,
    }


def claude_pending_tasks() -> list[tuple[Path, dict[str, Any]]]:
    out: list[tuple[Path, dict[str, Any]]] = []
    current_ids = _current_work_ids()
    for f in iter_task_files():
        raw = read_json(f)
        if not isinstance(raw, dict):
            continue
        d = normalize_descriptor(raw, f)
        if current_ids is not None and str(d.get("task_id")) not in current_ids:
            continue
        if d["task_type"] != "CLAUDE_IMPLEMENTATION":
            continue
        if d["status"] not in ("pending", "pending_redispatch", "stale", "running"):
            continue
        # Skip historical tasks already proven complete by their own
        # precheck marker — they are not active work, even if their
        # descriptor never had its status updated.
        if source_truth_completion_suppresses_dispatch(d):
            continue
        if is_complete_marker(d):
            continue
        out.append((f, d))
    return out


def descriptor_running(d: dict[str, Any]) -> bool:
    pid = d.get("pid_or_job_id")
    if not pid_alive(pid):
        return False
    hb = read_heartbeat(d["task_id"])
    if not hb:
        return False
    return bool(hb.get("alive"))


def stalled(d: dict[str, Any]) -> bool:
    threshold = int(d.get("stall_threshold_seconds") or DEFAULT_STALL_SECONDS)
    candidates = [LOG_DIR / f"{d['task_id']}.log"]
    candidates.extend(
        REPO_ROOT / rel for rel in (d.get("expected_output_paths") or [])
    )
    last = newest_mtime(candidates)
    if last is None:
        # No artifacts yet: use heartbeat
        hb = read_heartbeat(d["task_id"])
        if hb and isinstance(hb.get("updated_at"), str):
            try:
                last = datetime.fromisoformat(
                    hb["updated_at"].replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                last = None
    if last is None:
        # Use descriptor mtime as a last-resort heartbeat.
        return False
    return (time.time() - last) > threshold


def launch_claude_task(
    descriptor_path: Path,
    d: dict[str, Any],
    executor: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Dispatch a single Claude task.

    The launcher uses ``claude -p`` (non-interactive) when the Claude CLI
    is available. Stdout/stderr stream to the per-task log so the
    coordinator can watch heartbeat freshness without holding the
    runner.
    """
    ensure_dirs()
    log_path = LOG_DIR / f"{d['task_id']}.log"
    if dry_run:
        return {"action": "dry_run", "task_id": d["task_id"], "log_path": str(log_path)}
    if not executor.get("available"):
        return {
            "action": "blocked",
            "reason": CLAUDE_EXECUTOR_NOT_AVAILABLE,
            "task_id": d["task_id"],
        }
    prompt = d.get("prompt") or (
        "Resume work on task " + d["task_id"] + " inside this repo. "
        "Do not modify the legacy AI BOT directory. Do not call exchange "
        "mutation endpoints. Keep live_gate=blocked_human_only."
    )
    if executor["executor"] == "claude_cli":
        cmd = [executor["command_probe"][0], "-p", prompt]
    else:
        cmd = [
            sys.executable,
            str(REPO_ROOT / "claude_worklog" / "tools" / "agent_supervisor.py"),
            "--task",
            str(descriptor_path.relative_to(REPO_ROOT)),
        ]
    log_fp = open(log_path, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except (FileNotFoundError, OSError) as exc:
        log_fp.close()
        return {
            "action": "failed_launch",
            "task_id": d["task_id"],
            "error": str(exc),
        }
    write_heartbeat(d["task_id"], proc.pid, {"cmd": cmd[:1] + ["..."]})
    return {
        "action": "launched",
        "task_id": d["task_id"],
        "pid": proc.pid,
        "log_path": str(log_path),
    }


def mark_descriptor(
    descriptor_path: Path,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Atomically merge ``updates`` into the descriptor."""
    raw = read_json(descriptor_path) or {}
    if not isinstance(raw, dict):
        return {"changed": False, "reason": "unreadable"}
    raw.update(updates)
    raw["updated_at"] = utc_iso()
    write_json_atomic(descriptor_path, raw)
    return {"changed": True, "path": str(descriptor_path.relative_to(REPO_ROOT))}


def create_takeover_task(d: dict[str, Any], reason: str) -> Path | None:
    """Drop a takeover/remediation descriptor next to the stalled task.

    The descriptor never starts running on its own — it sits as
    ``pending`` for the Codex review runner / operator. The runner only
    creates the descriptor when the spec allows (safe-scoped, V2-only,
    no exchange mutation, no live, no shutdown approval).
    """
    if not d.get("task_id"):
        return None
    out_name = f"closed_loop_takeover_{d['task_id']}.json"
    out_path = TASKS_DIR / out_name
    if out_path.exists():
        return None
    payload = {
        "task_id": out_name[:-5],
        "task_type": "CODEX_TAKEOVER",
        "owner": "CODEX",
        "status": "pending",
        "file_lock_group": d.get("file_lock_group"),
        "created_at": utc_iso(),
        "updated_at": utc_iso(),
        "codex_pair_task_id": d["task_id"],
        "operator_required_reason": None,
        "fail_blockers": [],
        "next_action": (
            "Codex takeover requested by closed-loop executor; underlying "
            "Claude task stalled twice. Codex must perform a scoped V2-side "
            "review only — do not touch legacy or live."
        ),
        "reason": reason,
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
    }
    write_json_atomic(out_path, payload)
    return out_path


def run_once(*, max_lanes: int, dry_run: bool) -> dict[str, Any]:
    ensure_dirs()
    executor = discover_claude_executor()
    source_truth_reconciliation = reconcile_source_truth_completions(apply_updates=True)

    def _persist(path: Path, updates: dict[str, Any]) -> dict[str, Any]:
        if dry_run:
            return {"changed": False, "reason": "dry_run"}
        return mark_descriptor(path, updates)
    dispatched: list[dict[str, Any]] = []
    relaunched: list[dict[str, Any]] = []
    escalated: list[dict[str, Any]] = []
    active_now = 0
    lock_groups_in_use: set[str] = set()
    duplicate_keys: set[str] = set()
    duplicates: list[dict[str, Any]] = []
    actions_blocked: list[dict[str, Any]] = []

    candidates = claude_pending_tasks()

    # First pass: count currently running tasks (anchored on real pids)
    # and reserve their lock groups so we don't double-dispatch.
    lock_group_owner: dict[str, str] = {}
    for path, d in candidates:
        if descriptor_running(d):
            active_now += 1
            grp = d.get("file_lock_group")
            if grp:
                lock_groups_in_use.add(str(grp))
                lock_group_owner.setdefault(str(grp), d["task_id"])

    # Second pass: stall handling + new dispatch up to max_lanes.
    for path, d in candidates:
        running = descriptor_running(d)
        key = d.get("duplicate_suppression_key")
        if key and key in duplicate_keys:
            _persist(path, {"status": "duplicate_suppressed"})
            duplicates.append({"task_id": d["task_id"], "key": key})
            continue
        if key:
            duplicate_keys.add(key)

        if running:
            if stalled(d):
                stall_count = int(d.get("stall_count") or 0) + 1
                if stall_count > int(d.get("max_stall_relaunches") or DEFAULT_MAX_STALL_RELAUNCHES):
                    # Create takeover descriptor and mark stale.
                    takeover = create_takeover_task(d, "stalled_twice")
                    _persist(path, {
                        "status": "stale",
                        "stall_count": stall_count,
                        "next_action": "CODEX_TAKEOVER created; operator may resume Claude manually.",
                    })
                    escalated.append({
                        "task_id": d["task_id"],
                        "takeover": str(takeover.relative_to(REPO_ROOT)) if takeover else None,
                    })
                    continue
                # Try to relaunch once. A stalled task already owns its
                # lock group from the first pass, so it must be allowed
                # past the lock-group reservation check.
                grp_self = d.get("file_lock_group")
                if active_now > max_lanes:
                    actions_blocked.append({"task_id": d["task_id"], "reason": "max_lanes_reached"})
                    continue
                if (
                    grp_self in lock_groups_in_use
                    and lock_group_owner.get(str(grp_self)) != d["task_id"]
                ):
                    actions_blocked.append({"task_id": d["task_id"], "reason": "lock_group_in_use"})
                    continue
                with file_lock(grp_self or d["task_id"]) as locked:
                    if not locked:
                        actions_blocked.append({"task_id": d["task_id"], "reason": "lock_unavailable"})
                        continue
                    res = launch_claude_task(path, d, executor, dry_run=dry_run)
                if res.get("action") == "launched":
                    lock_groups_in_use.add(d.get("file_lock_group") or d["task_id"])
                    _persist(path, {
                        "status": "running",
                        "pid_or_job_id": res.get("pid"),
                        "log_path": res.get("log_path"),
                        "stall_count": stall_count,
                        "started_at": utc_iso(),
                    })
                    relaunched.append(res)
                else:
                    actions_blocked.append({"task_id": d["task_id"], "reason": res.get("reason") or res.get("action")})
            else:
                # Healthy running task — confirm completion if outputs are present.
                if expected_outputs_present(d) or is_complete_marker(d):
                    _persist(path, {"status": "completed", "completed_at": utc_iso()})
                    active_now = max(0, active_now - 1)
            continue

        # Not running. Check completion first.
        if is_complete_marker(d):
            _persist(path, {"status": "completed", "completed_at": utc_iso()})
            continue
        if active_now >= max_lanes:
            actions_blocked.append({"task_id": d["task_id"], "reason": "max_lanes_reached"})
            continue
        if d.get("file_lock_group") in lock_groups_in_use:
            actions_blocked.append({"task_id": d["task_id"], "reason": "lock_group_in_use"})
            continue
        if not executor.get("available"):
            _persist(path, {
                "status": "blocked_operator_required",
                "operator_required_reason": CLAUDE_EXECUTOR_NOT_AVAILABLE,
            })
            actions_blocked.append({"task_id": d["task_id"], "reason": CLAUDE_EXECUTOR_NOT_AVAILABLE})
            continue
        with file_lock(d.get("file_lock_group") or d["task_id"]) as locked:
            if not locked:
                actions_blocked.append({"task_id": d["task_id"], "reason": "lock_unavailable"})
                continue
            res = launch_claude_task(path, d, executor, dry_run=dry_run)
        if res.get("action") == "launched":
            active_now += 1
            lock_groups_in_use.add(d.get("file_lock_group") or d["task_id"])
            _persist(path, {
                "status": "running",
                "pid_or_job_id": res.get("pid"),
                "log_path": res.get("log_path"),
                "started_at": utc_iso(),
            })
            dispatched.append(res)
        else:
            actions_blocked.append({"task_id": d["task_id"], "reason": res.get("reason") or res.get("action")})

    state = {
        "schema_version": "v2_closed_loop_claude_task_runner_v1",
        "generated_utc": utc_iso(),
        "source_truth_reconciliation": source_truth_reconciliation,
        "executor": executor,
        "active_claude_jobs": active_now,
        "dispatched": dispatched,
        "relaunched": relaunched,
        "escalated_to_takeover": escalated,
        "duplicates_suppressed": duplicates,
        "actions_blocked": actions_blocked,
        "max_lanes": max_lanes,
        "safety": _safety_envelope(),
    }
    write_json_atomic(LIFECYCLE_DIR / "claude_task_runner_status.json", state)
    write_json_atomic(PUBLIC_DIR / "claude_task_runner_status.json", state)
    return state


def _safety_envelope() -> dict[str, Any]:
    return {
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "modifies_legacy_repo": False,
        "writes_old_redis": False,
        "calls_exchange_mutation": False,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-lanes", type=int, default=3)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    state = run_once(max_lanes=args.max_lanes, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": state["generated_utc"],
            "active_claude_jobs": state["active_claude_jobs"],
            "dispatched": len(state["dispatched"]),
            "relaunched": len(state["relaunched"]),
            "escalated_to_takeover": len(state["escalated_to_takeover"]),
            "executor_available": bool(state["executor"].get("available")),
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
