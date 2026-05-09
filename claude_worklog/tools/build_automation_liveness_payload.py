#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
OUT = ROOT / "claude_worklog/final_readiness/automation_liveness/latest"
PUBLIC = ROOT / "v2/frontend/public/automation_liveness/latest"
READY = "AUTOMATION_LIVENESS_AND_LEGACY_TRADER_DOWN_TOLERANCE_READY"
BLOCKED = "AUTOMATION_LIVENESS_AND_LEGACY_TRADER_DOWN_TOLERANCE_BLOCKED"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        shell=isinstance(cmd, str),
        text=True,
        capture_output=True,
        check=False,
    )


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return default


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def mtime(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "mtime": None, "size": None, "age_seconds": None}
    stat = path.stat()
    return {
        "exists": True,
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "size": stat.st_size,
        "age_seconds": int(time.time() - stat.st_mtime),
    }


def latest_file(root: Path) -> dict[str, Any]:
    latest: Path | None = None
    latest_ts = -1.0
    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                ts = path.stat().st_mtime
            except OSError:
                continue
            if ts > latest_ts:
                latest_ts = ts
                latest = path
    if latest is None:
        return {"path": None, "mtime": None, "age_seconds": None}
    return {
        "path": str(latest.relative_to(ROOT)),
        "mtime": datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat(),
        "age_seconds": int(time.time() - latest_ts),
    }


def process_snapshot() -> list[dict[str, Any]]:
    proc = run("ps -eo pid,ppid,etimes,stat,cmd")
    rows: list[dict[str, Any]] = []
    patterns = [
        "claude_master_rebuild_planner.py",
        "codex_non_live_watchdog.py",
        "parallel_capacity_scheduler.py",
        "agent_supervisor.py --task-id",
        "claude --print",
        "codex exec",
        "ollama run",
        "rl.hybrid_trainer",
        "rl.orchestrator_worker",
        "trading/trader.py",
    ]
    for line in proc.stdout.splitlines()[1:]:
        if not any(pattern in line for pattern in patterns):
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        rows.append(
            {
                "pid": int(parts[0]),
                "ppid": int(parts[1]),
                "age_seconds": int(parts[2]),
                "stat": parts[3],
                "cmd": sanitize_cmd(parts[4]),
            }
        )
    return rows


def sanitize_cmd(cmd: str) -> str:
    if "claude --print" in cmd:
        return "claude --print [prompt_redacted]"
    if "codex exec" in cmd:
        return "codex exec [prompt_redacted]"
    if "ollama run" in cmd:
        return "ollama run [prompt_redacted]"
    if "agent_supervisor.py --task-id" in cmd:
        parts = cmd.split("--task-id", 1)
        task = parts[1].strip().split()[0] if len(parts) > 1 and parts[1].strip() else "unknown"
        return f"python3 claude_worklog/tools/agent_supervisor.py --task-id {task}"
    return cmd.replace(str(ROOT), "$AI_BOT_REBUILD")


def child_process_present(task_id: str) -> bool:
    if not task_id:
        return False
    proc = run(["pgrep", "-af", task_id])
    return proc.returncode == 0 and bool(proc.stdout.strip())


def active_claude_or_codex_child() -> bool:
    proc = run("ps -eo cmd | grep -E 'claude --print|codex exec|ollama run' | grep -v grep || true")
    return bool(proc.stdout.strip())


def git_info() -> dict[str, Any]:
    status = run(["git", "status", "--short"]).stdout.splitlines()
    head = run(["git", "log", "--oneline", "-1"]).stdout.strip()
    pushed = run(["git", "log", "--oneline", "-1", "@{u}"]).stdout.strip()
    return {
        "status": status,
        "clean": not status,
        "head": head,
        "upstream_head": pushed or "evidence_missing",
    }


def build_payload() -> dict[str, Any]:
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json", {})
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json", {})
    agent_health = read_json(ROOT / "claude_worklog/agent_supervisor/status/agent_health.json", {})
    scheduler = read_json(ROOT / "claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json", {})

    task_id = current.get("task_id") or queue.get("current_running_task")
    run_pid = current.get("run_pid")
    stdout_path = ROOT / str(current.get("stdout_path", ""))
    stderr_path = ROOT / str(current.get("stderr_path", ""))
    summary_path = ROOT / "claude_worklog/agent_supervisor/runs" / str(task_id or "") / "summary.json"
    current_started = current.get("start_time")

    stdout_meta = mtime(stdout_path)
    stderr_meta = mtime(stderr_path)
    summary_meta = mtime(summary_path)
    event_meta = mtime(ROOT / "claude_worklog/agent_supervisor/events.jsonl")
    queue_meta = mtime(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    latest_artifact = latest_file(ROOT / "claude_worklog/final_readiness")

    processes = process_snapshot()
    task_process_alive = False
    if run_pid:
        task_process_alive = any(row["pid"] == run_pid for row in processes) or Path(f"/proc/{run_pid}").exists()

    actual_child_present = active_claude_or_codex_child()
    supervisor_task_present = child_process_present(str(task_id or ""))
    no_output = (
        stdout_meta["exists"]
        and stderr_meta["exists"]
        and stdout_meta["size"] == 0
        and stderr_meta["size"] == 0
    )

    liveness_warnings: list[str] = []
    if current.get("status") == "running" and supervisor_task_present and not actual_child_present:
        liveness_warnings.append("supervisor_task_running_but_no_claude_codex_child_detected")
    if current.get("status") == "running" and no_output:
        liveness_warnings.append("active_task_stdout_stderr_zero_bytes")
    if queue.get("stale_running_count"):
        liveness_warnings.append("queue_reports_stale_running_tasks")
    if queue.get("human_attention_required_count"):
        liveness_warnings.append("queue_reports_human_attention_required")

    legacy_trader_policy = {
        "legacy_trader_status": "intentionally_disabled_or_not_required_for_v2_non_live_build",
        "legacy_trader_intentionally_disabled": True,
        "legacy_trader_required_for_v2_build": False,
        "legacy_trader_required_for_live_cutover": "human_review_required_later",
        "legacy_trader_down_should_not_block_non_live_rebuild": True,
        "legacy_trainer_and_ingestors_may_continue_as_readonly_evidence_sources": True,
        "operator_note": "Do not restart legacy trader. Missing trader execution evidence is a comparison gap, not a V2 build blocker.",
    }

    blocked = bool(queue.get("human_attention_required_count")) or bool(queue.get("blocked_quota"))
    marker = BLOCKED if blocked else READY

    automation_assessment = "actively_working"
    if current.get("status") == "running" and liveness_warnings:
        automation_assessment = "running_with_liveness_warnings"
    if not current.get("task_id") and not queue.get("current_running_task"):
        automation_assessment = "idle_ready_for_next_task"
    if blocked:
        automation_assessment = "blocked"

    return {
        "generated_at": now_iso(),
        "marker": marker,
        "automation_assessment": automation_assessment,
        "processes": processes,
        "queue": queue,
        "current_status": current,
        "agent_health": agent_health,
        "scheduler": scheduler,
        "git": git_info(),
        "task_liveness": {
            "task_id": task_id,
            "status": current.get("status"),
            "run_pid": run_pid,
            "supervisor_task_process_present": supervisor_task_present,
            "task_process_alive": task_process_alive,
            "claude_codex_child_present": actual_child_present,
            "start_time": current_started,
            "stdout": stdout_meta,
            "stderr": stderr_meta,
            "summary": summary_meta,
            "required_outputs_missing": _required_outputs_missing(str(task_id or "")),
            "warnings": liveness_warnings,
        },
        "progress_clocks": {
            "last_event_log_update": event_meta,
            "last_queue_status_update": queue_meta,
            "last_final_readiness_artifact": latest_artifact,
        },
        "quota_auth_state": {
            "blocked_quota": queue.get("blocked_quota"),
            "blocked_auth_tasks": _tasks_by_status("blocked_auth"),
            "blocked_dependency_tasks": _tasks_by_status("blocked_dependency"),
            "human_attention_required_count": queue.get("human_attention_required_count", 0),
        },
        "legacy_trader_policy": legacy_trader_policy,
        "dashboard_summary": {
            "claude_planner_running": any("claude_master_rebuild_planner.py" in row["cmd"] for row in processes),
            "codex_watchdog_running": any("codex_non_live_watchdog.py" in row["cmd"] for row in processes),
            "scheduler_running": any("parallel_capacity_scheduler.py" in row["cmd"] for row in processes),
            "current_task_id": task_id or "none",
            "last_event_timestamp": event_meta.get("mtime"),
            "last_artifact_update": latest_artifact.get("mtime"),
            "last_commit": git_info()["head"],
            "stale_running_count": queue.get("stale_running_count", 0),
            "human_attention_count": queue.get("human_attention_required_count", 0),
            "legacy_trader_disabled_non_blocking": True,
            "next_runnable_task": queue.get("next_pending_task"),
            "latest_blocker_reason": ", ".join(liveness_warnings) if liveness_warnings else "none",
        },
    }


def _tasks_by_status(status: str) -> list[str]:
    rows = []
    state_dir = ROOT / "claude_worklog/agent_supervisor/state/tasks"
    for path in state_dir.glob("*.json"):
        data = read_json(path, {})
        if data.get("status") == status:
            rows.append(data.get("task_id") or path.stem)
    return sorted(rows)


def _required_outputs_missing(task_id: str) -> list[str]:
    if not task_id:
        return []
    task = read_json(ROOT / f"claude_worklog/agent_supervisor/tasks/{task_id}.json", {})
    missing = []
    for rel in task.get("required_output_files", []):
        if not (ROOT / rel).exists():
            missing.append(rel)
    return missing


def write_outputs(payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)

    files = {
        "agent_process_snapshot.json": payload["processes"],
        "task_queue_liveness.json": {
            "queue": payload["queue"],
            "current_status": payload["current_status"],
            "task_liveness": payload["task_liveness"],
            "progress_clocks": payload["progress_clocks"],
            "quota_auth_state": payload["quota_auth_state"],
        },
        "dashboard_liveness_payload.json": payload,
    }
    for name, data in files.items():
        text = json.dumps(data, indent=2, sort_keys=True) + "\n"
        write(OUT / name, text)
        write(PUBLIC / name, text)

    write(OUT / "GO_NO_GO.md", payload["marker"] + "\n")
    write(PUBLIC / "GO_NO_GO.md", payload["marker"] + "\n")
    write(OUT / "AUTOMATION_LIVENESS_REPORT.md", _report(payload))
    write(OUT / "stale_task_recovery_report.md", _stale_report(payload))
    write(OUT / "legacy_trader_down_tolerance.md", _legacy_policy(payload))


def _report(payload: dict[str, Any]) -> str:
    task = payload["task_liveness"]
    summary = payload["dashboard_summary"]
    return "\n".join(
        [
            "# Automation Liveness Report",
            "",
            f"Generated: {payload['generated_at']}",
            "",
            f"- marker: `{payload['marker']}`",
            f"- automation_assessment: `{payload['automation_assessment']}`",
            f"- current_task: `{summary['current_task_id']}`",
            f"- next_runnable_task: `{summary['next_runnable_task']}`",
            f"- last_event_timestamp: `{summary['last_event_timestamp']}`",
            f"- last_artifact_update: `{summary['last_artifact_update']}`",
            f"- last_commit: `{summary['last_commit']}`",
            f"- stale_running_count: `{summary['stale_running_count']}`",
            f"- human_attention_count: `{summary['human_attention_count']}`",
            f"- quota_blocked: `{payload['queue'].get('blocked_quota')}`",
            "",
            "## Active Task Liveness",
            "",
            f"- task_id: `{task['task_id']}`",
            f"- status: `{task['status']}`",
            f"- run_pid: `{task['run_pid']}`",
            f"- supervisor_task_process_present: `{task['supervisor_task_process_present']}`",
            f"- claude_codex_child_present: `{task['claude_codex_child_present']}`",
            f"- stdout_size: `{task['stdout']['size']}`",
            f"- stderr_size: `{task['stderr']['size']}`",
            f"- required_outputs_missing: `{len(task['required_outputs_missing'])}`",
            f"- warnings: `{', '.join(task['warnings']) if task['warnings'] else 'none'}`",
            "",
            "## Legacy Trader Policy",
            "",
            "- legacy trader intentionally disabled is allowed for non-live V2 rebuild.",
            "- legacy trader is not required for V2 non-live build progress.",
            "- legacy trader live execution evidence gaps must be recorded as missing comparison evidence.",
            "- live cutover remains human-reviewed later.",
            "",
            payload["marker"],
            "",
        ]
    )


def _stale_report(payload: dict[str, Any]) -> str:
    task = payload["task_liveness"]
    lines = [
        "# Stale Task Recovery Report",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"- stale_running_count: `{payload['queue'].get('stale_running_count', 0)}`",
        f"- active_task: `{task['task_id']}`",
        f"- active_task_status: `{task['status']}`",
        f"- supervisor_task_process_present: `{task['supervisor_task_process_present']}`",
        f"- claude_codex_child_present: `{task['claude_codex_child_present']}`",
        f"- warnings: `{', '.join(task['warnings']) if task['warnings'] else 'none'}`",
        "",
    ]
    if task["warnings"]:
        lines.extend(
            [
                "## Classification",
                "",
                "The active task has liveness warnings but was not killed. Existing supervisor stale-running policy must reconcile it if it crosses its timeout.",
                "",
            ]
        )
    else:
        lines.extend(["## Classification", "", "No stale task recovery required.", ""])
    lines.append("STALE_TASK_RECOVERY_REPORT_READY")
    lines.append("")
    return "\n".join(lines)


def _legacy_policy(payload: dict[str, Any]) -> str:
    policy = payload["legacy_trader_policy"]
    return "\n".join(
        [
            "# Legacy Trader Down Tolerance",
            "",
            f"Generated: {payload['generated_at']}",
            "",
            f"- legacy_trader_intentionally_disabled: `{policy['legacy_trader_intentionally_disabled']}`",
            f"- legacy_trader_required_for_v2_build: `{policy['legacy_trader_required_for_v2_build']}`",
            f"- legacy_trader_required_for_live_cutover: `{policy['legacy_trader_required_for_live_cutover']}`",
            f"- legacy_trader_down_should_not_block_non_live_rebuild: `{policy['legacy_trader_down_should_not_block_non_live_rebuild']}`",
            f"- legacy_trainer_and_ingestors_may_continue_as_readonly_evidence_sources: `{policy['legacy_trainer_and_ingestors_may_continue_as_readonly_evidence_sources']}`",
            "",
            "The legacy trader must not be restarted by automation. If trader execution evidence is needed for a comparison, record the comparison as missing evidence and continue non-live V2 build work.",
            "",
            "LEGACY_TRADER_DOWN_TOLERANCE_READY",
            "",
        ]
    )


def main() -> int:
    payload = build_payload()
    write_outputs(payload)
    print(payload["marker"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
