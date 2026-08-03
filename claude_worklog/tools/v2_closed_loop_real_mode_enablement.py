"""V2 Closed-Loop Execution Engine — Real-Mode Enablement orchestrator.

This is a one-shot orchestrator that converts the closed-loop engine
from descriptor-only automation into bounded real-mode execution.
Strictly bounded: at most 3 Claude lanes and 3 Codex lanes per pass,
filtered through the current-work filter, with all safety gates kept
blocked.

Phases (mapped to the spec):

1. Build the current-work queue with ``v2_current_work_filter``.
2. Install + enable the three systemd user timers that the closed-loop
   executor already shipped under
   ``claude_worklog/final_readiness/v2_closed_loop_execution/latest/systemd/``.
3. Materialize bounded SAFE heartbeat-probe descriptors (3 Claude + 3
   Codex) if the current queue is empty, then dispatch through the
   existing runners with ``dry_run=False`` and ``max_lanes=3``.
4. Collect proof-of-life for every active lane: pid, log path, file
   lock group, expected outputs, last-log-bytes, heartbeat timestamp.
5. Refresh every payload listed in the spec.
6. Emit ``GO_NO_GO.md`` exactly equal to one of:
   - ``V2_CLOSED_LOOP_EXECUTION_ENGINE_REAL_MODE_ENABLEMENT_READY``
   - ``V2_CLOSED_LOOP_EXECUTION_ENGINE_REAL_MODE_ENABLEMENT_BLOCKED``
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import v2_claude_task_runner as claude_runner
import v2_closed_loop_claude_codex_executor as coordinator
import v2_codex_review_runner as codex_runner
import v2_current_work_filter as current_filter
from v2_closed_loop_lifecycle import (
    HEARTBEAT_DIR,
    LIFECYCLE_DIR,
    LOG_DIR,
    PUBLIC_DIR,
    REPO_ROOT,
    TASKS_DIR,
    ensure_dirs,
    pid_alive,
    read_heartbeat,
    read_json,
    normalize_descriptor,
    utc_iso,
    write_heartbeat,
    write_json_atomic,
)

REAL_MODE_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_execution_real_mode_enablement"
    / "latest"
)
REAL_MODE_PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_closed_loop_execution_real_mode_enablement"
    / "latest"
)
SYSTEMD_SRC = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_execution"
    / "latest"
    / "systemd"
)
SYSTEMD_DST = Path(os.path.expanduser("~/.config/systemd/user"))

LIVE_BLOCKED_ENVELOPE = {
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

PROBE_TIMER_UNITS = (
    "ai-bot-v2-closed-loop-executor.service",
    "ai-bot-v2-closed-loop-executor.timer",
    "ai-bot-v2-claude-task-runner.service",
    "ai-bot-v2-claude-task-runner.timer",
    "ai-bot-v2-codex-review-runner.service",
    "ai-bot-v2-codex-review-runner.timer",
)
TIMERS = (
    "ai-bot-v2-closed-loop-executor.timer",
    "ai-bot-v2-claude-task-runner.timer",
    "ai-bot-v2-codex-review-runner.timer",
)


CLAUDE_PROBE_PROMPT = (
    "You are the V2 closed-loop lane heartbeat probe. Print only the literal "
    "token V2_CLOSED_LOOP_LANE_HEARTBEAT_OK and then exit. Do not modify any "
    "file, do not approve live, do not write Redis."
)
CODEX_PROBE_PROMPT = (
    "Run a single-shot heartbeat review for the V2 closed-loop engine. Print "
    "only the literal token V2_CLOSED_LOOP_LANE_HEARTBEAT_OK_CODEX_PASS and "
    "then exit. Do not approve live, canary, legacy shutdown, or Redis trim."
)


def ensure_real_mode_dirs() -> None:
    REAL_MODE_DIR.mkdir(parents=True, exist_ok=True)
    REAL_MODE_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)


# ----------------------------- Phase 2 ----------------------------- #


def install_timers(*, install: bool, enable: bool) -> dict[str, Any]:
    """Copy the closed-loop systemd unit files into the user's
    ``~/.config/systemd/user`` directory and (if ``enable``) issue
    ``systemctl --user enable --now <timer>`` for each timer.

    Pure verification (no copy, no enable) is the default. Both ``install``
    and ``enable`` are explicit so the orchestrator can be re-run safely.
    """
    result: dict[str, Any] = {
        "src": str(SYSTEMD_SRC),
        "dst": str(SYSTEMD_DST),
        "copied": [],
        "skipped": [],
        "installed": install,
        "enabled": enable,
        "daemon_reload": None,
        "enable_commands": [],
        "verification": {},
        "errors": [],
    }
    if not SYSTEMD_SRC.exists():
        result["errors"].append(f"systemd source missing: {SYSTEMD_SRC}")
        return result
    SYSTEMD_DST.mkdir(parents=True, exist_ok=True)

    if install:
        for unit in PROBE_TIMER_UNITS:
            src = SYSTEMD_SRC / unit
            dst = SYSTEMD_DST / unit
            if not src.exists():
                result["errors"].append(f"missing unit: {src}")
                continue
            # Only copy if absent or content differs.
            try:
                if dst.exists() and dst.read_bytes() == src.read_bytes():
                    result["skipped"].append(unit)
                    continue
            except OSError:
                pass
            try:
                shutil.copyfile(src, dst)
                result["copied"].append(unit)
            except OSError as exc:
                result["errors"].append(f"copy failed: {unit} ({exc})")

        # daemon-reload after copying.
        result["daemon_reload"] = _run_systemctl(
            ["--user", "daemon-reload"]
        )

    if enable:
        for timer in TIMERS:
            outcome = _run_systemctl(["--user", "enable", "--now", timer])
            result["enable_commands"].append({"timer": timer, **outcome})

    # Verification: is-enabled / is-active for each timer.
    for timer in TIMERS:
        is_enabled = _run_systemctl(["--user", "is-enabled", timer])
        is_active = _run_systemctl(["--user", "is-active", timer])
        result["verification"][timer] = {
            "is_enabled": is_enabled,
            "is_active": is_active,
        }
    return result


def _run_systemctl(args: list[str]) -> dict[str, Any]:
    cmd = ["systemctl", *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return {
            "cmd": cmd,
            "returncode": r.returncode,
            "stdout": (r.stdout or "").strip(),
            "stderr": (r.stderr or "").strip(),
        }
    except FileNotFoundError:
        return {"cmd": cmd, "returncode": -127, "stdout": "", "stderr": "systemctl_not_found"}
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "returncode": -1, "stdout": "", "stderr": "timeout"}


# ----------------------------- Phase 3 ----------------------------- #


def materialize_probe_descriptors() -> list[dict[str, Any]]:
    """Create three Claude + three Codex SAFE heartbeat-probe descriptors
    if none of them already exist. They live in the regular tasks dir
    but are tagged ``current_active=true`` so the filter accepts them
    and the rest of the historical queue stays excluded.
    """
    out: list[dict[str, Any]] = []
    pairs = [
        ("real_mode_probe_claude_alpha", "CLAUDE_IMPLEMENTATION", "CLAUDE", CLAUDE_PROBE_PROMPT, "real_mode_probe_alpha"),
        ("real_mode_probe_claude_beta", "CLAUDE_IMPLEMENTATION", "CLAUDE", CLAUDE_PROBE_PROMPT, "real_mode_probe_beta"),
        ("real_mode_probe_claude_gamma", "CLAUDE_IMPLEMENTATION", "CLAUDE", CLAUDE_PROBE_PROMPT, "real_mode_probe_gamma"),
        ("real_mode_probe_codex_alpha", "CODEX_REVIEW", "CODEX", CODEX_PROBE_PROMPT, "real_mode_probe_codex_alpha"),
        ("real_mode_probe_codex_beta", "CODEX_REVIEW", "CODEX", CODEX_PROBE_PROMPT, "real_mode_probe_codex_beta"),
        ("real_mode_probe_codex_gamma", "CODEX_REVIEW", "CODEX", CODEX_PROBE_PROMPT, "real_mode_probe_codex_gamma"),
    ]
    for task_id, ttype, owner, prompt, lock_group in pairs:
        path = TASKS_DIR / f"{task_id}.json"
        if path.exists():
            out.append({"task_id": task_id, "path": str(path.relative_to(REPO_ROOT)), "created": False})
            continue
        descriptor = {
            "task_id": task_id,
            "task_type": ttype,
            "agent": owner.lower(),
            "owner": owner,
            "status": "pending",
            "current_active": True,
            "file_lock_group": lock_group,
            "created_at": utc_iso(),
            "updated_at": utc_iso(),
            "prompt": prompt,
            "expected_output_paths": [],
            "stall_threshold_seconds": 90,
            "max_stall_relaunches": 0,
            "safety": dict(LIVE_BLOCKED_ENVELOPE),
        }
        write_json_atomic(path, descriptor)
        out.append({"task_id": task_id, "path": str(path.relative_to(REPO_ROOT)), "created": True})
    return out


def bounded_real_mode_pass(
    probe_records: list[dict[str, Any]],
    *,
    allow_real_dispatch: bool,
    max_claude_lanes: int = 3,
    max_codex_lanes: int = 3,
) -> dict[str, Any]:
    """Execute one bounded real-mode pass that dispatches *only* the
    probe descriptors — never the broader historical queue.

    Each probe is launched through the existing runner helpers, so the
    safety guarantees (file lock, heartbeat, descriptor mutation) match
    a normal scheduled pass. The orchestrator never touches the
    coordinator's full queue scan during the real-mode pass — that is
    what prevents accidental drainage of 552 stale descriptors.
    """
    result: dict[str, Any] = {
        "skipped": not allow_real_dispatch,
        "claude_executor": claude_runner.discover_claude_executor(),
        "codex_executor": codex_runner.discover_codex_executor(),
        "claude_dispatch_attempts": [],
        "codex_dispatch_attempts": [],
        "claude_state": None,
        "codex_state": None,
    }
    if not allow_real_dispatch:
        result["reason"] = "allow_real_dispatch=False"
        return result

    claude_executor = result["claude_executor"]
    codex_executor = result["codex_executor"]

    claude_launched = 0
    codex_launched = 0
    for record in probe_records:
        path = REPO_ROOT / record["path"]
        d = read_json(path)
        if not isinstance(d, dict):
            continue
        ttype = d.get("task_type")
        if ttype == "CLAUDE_IMPLEMENTATION" and claude_launched < max_claude_lanes:
            if not claude_executor.get("available"):
                result["claude_dispatch_attempts"].append({
                    "task_id": d.get("task_id"),
                    "action": "blocked",
                    "reason": "CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED",
                })
                continue
            res = claude_runner.launch_claude_task(path, d, claude_executor, dry_run=False)
            result["claude_dispatch_attempts"].append(res)
            if res.get("action") == "launched":
                claude_runner.mark_descriptor(path, {
                    "status": "running",
                    "pid_or_job_id": res.get("pid"),
                    "log_path": res.get("log_path"),
                    "started_at": utc_iso(),
                })
                claude_launched += 1
        elif ttype == "CODEX_REVIEW" and codex_launched < max_codex_lanes:
            if not codex_executor.get("available"):
                result["codex_dispatch_attempts"].append({
                    "task_id": d.get("task_id"),
                    "action": "blocked",
                    "reason": "CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED",
                })
                continue
            codex_runner.mark_descriptor(path, {"status": "running", "started_at": utc_iso()})
            res = codex_runner.run_codex_review(path, d, codex_executor, dry_run=False, timeout=60)
            result["codex_dispatch_attempts"].append(res)
            codex_launched += 1
            verdict = res.get("verdict") or ""
            if verdict.endswith("_CODEX_PASS"):
                codex_runner.mark_descriptor(path, {
                    "status": "completed",
                    "completed_at": utc_iso(),
                })
            else:
                codex_runner.mark_descriptor(path, {
                    "status": "failed",
                    "fail_blockers": res.get("fail_blockers") or [verdict],
                })
    result["claude_state"] = {
        "executor": claude_executor,
        "dispatched": [
            a for a in result["claude_dispatch_attempts"] if a.get("action") == "launched"
        ],
    }
    result["codex_state"] = {
        "executor": codex_executor,
        "started_this_pass": codex_launched,
        "reviews": result["codex_dispatch_attempts"],
    }
    return result


# ----------------------------- Phase 4 ----------------------------- #


def collect_active_lane_proof(probe_records: list[dict[str, Any]]) -> dict[str, Any]:
    """For every probe/current descriptor, look up its descriptor +
    heartbeat and confirm whether the lane is alive *right now*.

    Real means: pid_or_job_id is set, the OS still sees that pid, and a
    heartbeat record exists while the descriptor is still marked running.
    We never count anything else as active.
    """
    records = list(probe_records)
    if not records:
        try:
            result = current_filter.build_current_work_queue(active_window_hours=24)
            queue = result.get("queue") or {}
            records = [
                {
                    "task_id": row.get("task_id"),
                    "path": str((TASKS_DIR / f"{row.get('task_id')}.json").relative_to(REPO_ROOT)),
                    "created": False,
                }
                for row in queue.get("current", [])
                if row.get("task_id") and (TASKS_DIR / f"{row.get('task_id')}.json").exists()
            ]
        except Exception:  # noqa: BLE001
            records = []
    lanes: list[dict[str, Any]] = []
    claude_active = 0
    codex_active = 0
    for record in records:
        path = REPO_ROOT / record["path"]
        d = read_json(path) or {}
        if not isinstance(d, dict):
            continue
        d = normalize_descriptor(d, path)
        pid = d.get("pid_or_job_id")
        hb = read_heartbeat(d.get("task_id") or path.stem) or {}
        log_path = d.get("log_path")
        last_log_bytes = None
        if isinstance(log_path, str):
            lp = REPO_ROOT / log_path
            if lp.exists():
                try:
                    last_log_bytes = lp.stat().st_size
                except OSError:
                    last_log_bytes = None
        alive = pid_alive(pid)
        has_heartbeat = bool(hb.get("updated_at"))
        is_running = d.get("status") == "running"
        active = alive and has_heartbeat and is_running
        if active:
            kind = str(d.get("task_type") or "").upper()
            owner = str(d.get("agent") or d.get("owner") or "").lower()
            if kind in ("CLAUDE_IMPLEMENTATION", "REMEDIATION") or owner.startswith("claude"):
                claude_active += 1
            elif kind in ("CODEX_REVIEW", "CODEX_TAKEOVER") or owner.startswith("codex"):
                codex_active += 1
        lanes.append({
            "task_id": d.get("task_id"),
            "task_type": d.get("task_type"),
            "command_executor": d.get("agent") or d.get("owner"),
            "pid_or_job_id": pid,
            "pid_alive": alive,
            "heartbeat_present": has_heartbeat,
            "counted_active": active,
            "started_at": d.get("started_at"),
            "log_path": log_path,
            "heartbeat_timestamp": hb.get("updated_at"),
            "file_lock_group": d.get("file_lock_group"),
            "expected_output_paths": d.get("expected_output_paths") or [],
            "last_log_bytes": last_log_bytes,
            "status": d.get("status"),
        })
    return {
        "lanes": lanes,
        "active_claude_jobs": claude_active,
        "active_codex_jobs": codex_active,
        "active_lane_count": claude_active + codex_active,
    }


# ----------------------------- Phase 5 + 6 ----------------------------- #


def compute_real_mode_state(
    *,
    filter_result: dict[str, Any],
    timer_result: dict[str, Any],
    probe_records: list[dict[str, Any]],
    pass_result: dict[str, Any],
    proof: dict[str, Any],
    target_lanes: int,
) -> dict[str, Any]:
    queue = filter_result["queue"]
    util = {
        "schema_version": "v2_closed_loop_real_mode_utilization_v1",
        "generated_utc": utc_iso(),
        "active_claude_jobs": proof["active_claude_jobs"],
        "active_codex_jobs": proof["active_codex_jobs"],
        "active_lane_count": proof["active_lane_count"],
        "target_active_lanes": target_lanes,
        "automatable_work_count_current": queue["current_automatable_count"],
        "automatable_work_count_historical_excluded": queue["historical_excluded_count"],
        "utilization_percent": (
            100.0
            if target_lanes == 0
            else round(100.0 * proof["active_lane_count"] / max(1, target_lanes), 1)
        ),
        "real_dispatch_count": _count_real_dispatch(pass_result),
        "dry_run": False,
        "latest_started_jobs": [
            lane for lane in proof["lanes"] if lane.get("pid_alive")
        ],
        "blocker": None,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }

    if pass_result.get("claude_state"):
        claude_exec_ok = bool(
            pass_result["claude_state"].get("executor", {}).get("available")
        )
    else:
        claude_exec_ok = bool(
            claude_runner.discover_claude_executor().get("available")
        )
    if pass_result.get("codex_state"):
        codex_exec_ok = bool(
            pass_result["codex_state"].get("executor", {}).get("available")
        )
    else:
        codex_exec_ok = bool(
            codex_runner.discover_codex_executor().get("available")
        )

    blockers: list[str] = []
    if not claude_exec_ok:
        blockers.append("CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED")
    if not codex_exec_ok:
        blockers.append("CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED")
    codex_attempts = pass_result.get("codex_dispatch_attempts") or []
    failed_codex_attempts = [
        a for a in codex_attempts
        if a.get("action") != "completed"
        or a.get("returncode") not in (None, 0)
        or a.get("timed_out") is True
    ]
    if failed_codex_attempts:
        blockers.append("CODEX_REAL_MODE_REVIEW_EXECUTION_FAILED")
    claude_attempts = pass_result.get("claude_dispatch_attempts") or []
    failed_claude_attempts = [
        a for a in claude_attempts if a.get("action") != "launched"
    ]
    if failed_claude_attempts:
        blockers.append("CLAUDE_REAL_MODE_DISPATCH_FAILED")
    if queue["current_automatable_count"] > 0 and proof["active_lane_count"] < min(3, target_lanes):
        blockers.append("ACTIVE_LANES_BELOW_MINIMUM")
    if any(
        not v["is_enabled"].get("stdout", "").startswith("enabled")
        for v in timer_result.get("verification", {}).values()
    ):
        blockers.append("CLOSED_LOOP_TIMERS_NOT_ENABLED")

    util["blocker"] = blockers[0] if blockers else None

    # READY semantics from spec:
    monitor_only = (
        queue["current_automatable_count"] == 0
        and proof["active_lane_count"] == 0
        and claude_exec_ok
        and codex_exec_ok
        and not any(b == "CLOSED_LOOP_TIMERS_NOT_ENABLED" for b in blockers)
    )
    ready = (not blockers) or monitor_only
    marker = (
        "V2_CLOSED_LOOP_EXECUTION_ENGINE_REAL_MODE_ENABLEMENT_READY"
        if ready else
        "V2_CLOSED_LOOP_EXECUTION_ENGINE_REAL_MODE_ENABLEMENT_BLOCKED"
    )

    state = {
        "schema_version": "v2_closed_loop_real_mode_enablement_status_v1",
        "generated_utc": utc_iso(),
        "marker": marker,
        "ready": ready,
        "monitor_only": monitor_only,
        "blockers": blockers,
        "target_active_lanes": target_lanes,
        "current_work_queue": {
            "current_automatable_count": queue["current_automatable_count"],
            "historical_excluded_count": queue["historical_excluded_count"],
            "allowlist_size": queue["allowlist_size"],
            "report_center_blocker_refs_size": queue["report_center_blocker_refs_size"],
            "recent_codex_fail_refs_size": queue["recent_codex_fail_refs_size"],
        },
        "timer_install": {
            "copied": timer_result.get("copied"),
            "skipped": timer_result.get("skipped"),
            "errors": timer_result.get("errors"),
            "verification": timer_result.get("verification"),
        },
        "probe_descriptors": probe_records,
        "real_mode_pass": {
            "skipped": pass_result.get("skipped"),
            "claude_dispatch_attempts": pass_result.get("claude_dispatch_attempts") or [],
            "codex_dispatch_attempts": pass_result.get("codex_dispatch_attempts") or [],
            "claude_dispatched": (
                len(pass_result.get("claude_state", {}).get("dispatched", []))
                if pass_result.get("claude_state") else 0
            ),
            "codex_started_this_pass": (
                pass_result.get("codex_state", {}).get("started_this_pass", 0)
                if pass_result.get("codex_state") else 0
            ),
        },
        "proof": proof,
        "utilization": util,
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
    }
    return state


def _count_real_dispatch(pass_result: dict[str, Any]) -> int:
    n = 0
    cs = pass_result.get("claude_state") or {}
    n += len(cs.get("dispatched", []) or [])
    n += len(cs.get("relaunched", []) or [])
    co = pass_result.get("codex_state") or {}
    n += int(co.get("started_this_pass") or 0)
    return n


def emit_outputs(
    state: dict[str, Any], filter_result: dict[str, Any]
) -> None:
    ensure_real_mode_dirs()
    # Phase 1 outputs
    current_filter.write_outputs(filter_result, out_dir=REAL_MODE_DIR)
    current_filter.write_outputs(filter_result, out_dir=REAL_MODE_PUBLIC_DIR)
    # Phase 5/6 outputs
    write_json_atomic(REAL_MODE_DIR / "real_mode_enablement_status.json", state)
    write_json_atomic(REAL_MODE_PUBLIC_DIR / "real_mode_enablement_status.json", state)
    write_json_atomic(REAL_MODE_DIR / "operator_dashboard_payload.json", _operator_payload(state))
    write_json_atomic(REAL_MODE_PUBLIC_DIR / "operator_dashboard_payload.json", _operator_payload(state))
    (REAL_MODE_DIR / "GO_NO_GO.md").write_text(state["marker"] + "\n", encoding="utf-8")
    (REAL_MODE_DIR / "V2_CLOSED_LOOP_EXECUTION_ENGINE_REAL_MODE_ENABLEMENT_REPORT.md").write_text(
        _render_report(state), encoding="utf-8"
    )


def _operator_payload(state: dict[str, Any]) -> dict[str, Any]:
    util = state.get("utilization", {})
    return {
        "schema_version": "v2_closed_loop_real_mode_operator_payload_v1",
        "generated_utc": state["generated_utc"],
        "marker": state["marker"],
        "ready": state.get("ready", False),
        "monitor_only": state.get("monitor_only"),
        "active_claude_jobs": util.get("active_claude_jobs"),
        "active_codex_jobs": util.get("active_codex_jobs"),
        "active_lane_count": util.get("active_lane_count"),
        "target_active_lanes": util.get("target_active_lanes"),
        "automatable_work_count_current": util.get("automatable_work_count_current"),
        "automatable_work_count_historical_excluded": util.get("automatable_work_count_historical_excluded"),
        "utilization_percent": util.get("utilization_percent"),
        "real_dispatch_count": util.get("real_dispatch_count"),
        "dry_run": util.get("dry_run"),
        "blockers": state.get("blockers"),
        "timer_verification": state.get("timer_install", {}).get("verification"),
        "safety": dict(LIVE_BLOCKED_ENVELOPE),
        "next_action": (
            "Real-mode enablement READY. Closed-loop timers and probe lanes are live."
            if state.get("ready") else
            "Real-mode enablement BLOCKED. See blockers in the report."
        ),
    }


def _render_report(state: dict[str, Any]) -> str:
    util = state.get("utilization", {})
    blockers = state.get("blockers") or []
    verif = state.get("timer_install", {}).get("verification") or {}
    lines = [
        "# V2 Closed-Loop Execution Engine — Real-Mode Enablement Report",
        "",
        f"Marker: `{state['marker']}`",
        f"Generated: {state['generated_utc']}",
        "",
        "## Utilization",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| active_claude_jobs | {util.get('active_claude_jobs')} |",
        f"| active_codex_jobs | {util.get('active_codex_jobs')} |",
        f"| active_lane_count | {util.get('active_lane_count')} |",
        f"| target_active_lanes | {util.get('target_active_lanes')} |",
        f"| automatable_work_count_current | {util.get('automatable_work_count_current')} |",
        f"| automatable_work_count_historical_excluded | {util.get('automatable_work_count_historical_excluded')} |",
        f"| utilization_percent | {util.get('utilization_percent')} |",
        f"| real_dispatch_count | {util.get('real_dispatch_count')} |",
        f"| dry_run | {util.get('dry_run')} |",
        "",
        "## Timers",
        "",
        "| timer | is-enabled | is-active |",
        "| --- | --- | --- |",
    ]
    for timer, info in verif.items():
        lines.append(
            f"| {timer} | {info.get('is_enabled', {}).get('stdout')} | {info.get('is_active', {}).get('stdout')} |"
        )
    lines.extend([
        "",
        "## Active Lanes",
        "",
        "| task_id | task_type | pid | alive | log_path | heartbeat |",
        "| --- | --- | --- | --- | --- | --- |",
    ])
    for lane in state.get("proof", {}).get("lanes", []) or []:
        lines.append(
            f"| {lane.get('task_id')} | {lane.get('task_type')} | "
            f"{lane.get('pid_or_job_id')} | {lane.get('pid_alive')} | "
            f"{lane.get('log_path')} | {lane.get('heartbeat_timestamp')} |"
        )
    lines.extend([
        "",
        "## Blockers",
        "",
        *([f"- {b}" for b in blockers] or ["- (none)"]),
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


# ----------------------------- main ----------------------------- #


def run_once(
    *,
    install_timers_flag: bool,
    enable_timers_flag: bool,
    allow_real_dispatch: bool,
    materialize_probes: bool,
    active_window_hours: int,
    target_lanes: int,
    wait_after_dispatch_seconds: int,
) -> dict[str, Any]:
    ensure_real_mode_dirs()
    ensure_dirs()

    # Phase 1: filter
    filter_result = current_filter.build_current_work_queue(
        active_window_hours=active_window_hours,
    )

    # Phase 2: timer install/enable.
    timer_result = install_timers(
        install=install_timers_flag, enable=enable_timers_flag
    )

    # Phase 3: probe descriptors + bounded dispatch.
    probe_records = (
        materialize_probe_descriptors() if materialize_probes else []
    )
    # Refresh the filter result after probes show up; they carry
    # ``current_active=true`` so the filter will pick them up.
    if materialize_probes:
        filter_result = current_filter.build_current_work_queue(
            active_window_hours=active_window_hours,
        )

    pass_result = bounded_real_mode_pass(
        probe_records, allow_real_dispatch=allow_real_dispatch
    )

    # Allow log/heartbeat files to appear before we sample.
    if wait_after_dispatch_seconds > 0 and allow_real_dispatch:
        time.sleep(wait_after_dispatch_seconds)

    # Phase 4: proof
    proof = collect_active_lane_proof(probe_records)

    # Phase 5: compute final state
    state = compute_real_mode_state(
        filter_result=filter_result,
        timer_result=timer_result,
        probe_records=probe_records,
        pass_result=pass_result,
        proof=proof,
        target_lanes=target_lanes,
    )

    # Phase 5/6: emit outputs (writes filter + status + payloads + GO_NO_GO).
    emit_outputs(state, filter_result)

    # Refresh the closed-loop coordinator payloads too, so the upstream
    # engine's status reflects the real-mode pass we just ran.
    coordinator.run_once(
        claude_lanes=3, codex_lanes=3, target_lanes=target_lanes, dry_run=True,
    )
    return state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--install-timers", action="store_true", default=False)
    p.add_argument("--enable-timers", action="store_true", default=False)
    p.add_argument("--allow-real-dispatch", action="store_true", default=False,
                   help="Permit actually launching real Claude/Codex CLI subprocesses for the probe lanes.")
    p.add_argument("--no-probes", action="store_true", default=False,
                   help="Skip probe descriptor materialization (filter+timers only).")
    p.add_argument("--active-window-hours", type=int, default=24)
    p.add_argument("--target-lanes", type=int, default=3)
    p.add_argument("--wait-after-dispatch-seconds", type=int, default=2)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    state = run_once(
        install_timers_flag=args.install_timers,
        enable_timers_flag=args.enable_timers,
        allow_real_dispatch=args.allow_real_dispatch,
        materialize_probes=not args.no_probes,
        active_window_hours=args.active_window_hours,
        target_lanes=args.target_lanes,
        wait_after_dispatch_seconds=args.wait_after_dispatch_seconds,
    )
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": state["generated_utc"],
            "marker": state["marker"],
            "ready": state["ready"],
            "active_lane_count": state["utilization"]["active_lane_count"],
            "current_automatable_count": state["current_work_queue"]["current_automatable_count"],
            "real_dispatch_count": state["utilization"]["real_dispatch_count"],
            "blockers": state["blockers"],
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
