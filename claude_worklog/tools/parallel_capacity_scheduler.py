#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[2]
EVENTS = WORKSPACE / "claude_worklog/agent_supervisor/events.jsonl"
STATUS_PATH = WORKSPACE / "claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json"
TASKS_DIR = WORKSPACE / "claude_worklog/agent_supervisor/tasks"
STATE_DIR = WORKSPACE / "claude_worklog/agent_supervisor/state/tasks"
PHASE2_DIR = WORKSPACE / "claude_worklog/phase2_core_rebuild"

SCHEDULER_SESSION = "ai_bot_parallel_capacity_scheduler"
WATCHDOG_SESSION = "ai_bot_codex_non_live_watchdog"
PLANNER_SESSION = "ai_bot_claude_master_rebuild_planner"

MVP_SEQUENCE = [
    "TRAINER_PREDICTION_OUTPUT_MVP",
    "ORCHESTRATOR_DECISION_MVP",
    "RISK_GATEWAY_DEFAULT_DENY_MVP",
    "PAPER_EXECUTION_LEDGER_MVP",
    "REPLAY_BACKTEST_RUNNER_MVP",
    "PAPER_MODE_MVP",
    "SHADOW_MODE_READINESS",
]

PASS_MARKER = re.compile(r"\b([A-Z0-9_]+(?:CODEX_PASS|PASSED|READY))\b")
FAIL_MARKER = re.compile(r"\b(CODEX_FAIL|CODEX_REVIEW_FAIL|[A-Z0-9_]+_FAILED)\b")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    if isinstance(cmd, str):
        return subprocess.run(cmd, cwd=WORKSPACE, shell=True, text=True, capture_output=True)
    return subprocess.run(cmd, cwd=WORKSPACE, text=True, capture_output=True)


def append_event(event: dict[str, Any]) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", now())
    with EVENTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_text(path: Path, limit: int = 100_000) -> str:
    try:
        return path.read_text(errors="replace")[:limit]
    except Exception:
        return ""


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def process_lines(pattern: str) -> list[str]:
    proc = run(f"ps -eo pid,ppid,etimes,cmd | grep -E '{pattern}' | grep -v grep || true")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def active_claude_children() -> list[str]:
    return process_lines(r"claude --print")


def active_codex_children() -> list[str]:
    return process_lines(r"codex exec|agent_supervisor.py --task-id")


def active_ollama_children() -> list[str]:
    return process_lines(r"ollama run")


def git_status_lines() -> list[str]:
    return [line for line in run(["git", "status", "--short"]).stdout.splitlines() if line.strip()]


def tmux_running(session: str) -> bool:
    return run(["tmux", "has-session", "-t", session]).returncode == 0


def latest_event_matching(pattern: str) -> dict[str, Any]:
    if not EVENTS.exists():
        return {}
    regex = re.compile(pattern)
    latest: dict[str, Any] = {}
    try:
        lines = EVENTS.read_text(errors="replace").splitlines()
    except Exception:
        return {}
    for line in lines[-2000:]:
        try:
            event = json.loads(line)
        except Exception:
            if regex.search(line):
                latest = {"raw": line}
            continue
        if regex.search(str(event.get("event", ""))):
            latest = event
    return latest


def latest_human_attention_task() -> str | None:
    candidates: list[tuple[str, str]] = []
    for path in STATE_DIR.glob("*.json"):
        data = read_json(path)
        if data.get("status") == "human_attention_required":
            candidates.append((data.get("last_status_change_ts", ""), data.get("task_id") or path.stem))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def latest_fail_marker() -> str | None:
    candidates: list[tuple[float, Path]] = []
    if not PHASE2_DIR.exists():
        return None
    for path in PHASE2_DIR.rglob("*"):
        if not path.is_file():
            continue
        if "GO_NO_GO" not in path.name and "GO-NO-GO" not in path.name:
            continue
        text = read_text(path, 20_000)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if any(FAIL_MARKER.search(line) for line in lines) and not any(PASS_MARKER.search(line) for line in lines):
            candidates.append((path.stat().st_mtime, path))
    if not candidates:
        return None
    candidates.sort()
    return str(candidates[-1][1].relative_to(WORKSPACE))


def latest_committed_milestone() -> dict[str, str]:
    candidates: list[tuple[float, Path, str]] = []
    if PHASE2_DIR.exists():
        for path in PHASE2_DIR.rglob("*"):
            if not path.is_file():
                continue
            if "REQUEST" in path.name:
                continue
            if "GO_NO_GO" not in path.name and "GO-NO-GO" not in path.name:
                continue
            text = read_text(path, 20_000)
            marker_lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(marker_lines) != 1:
                continue
            marker = marker_lines[0]
            match = PASS_MARKER.fullmatch(marker)
            if match:
                candidates.append((path.stat().st_mtime, path, match.group(1)))
    if not candidates:
        return {}
    candidates.sort()
    _, path, marker = candidates[-1]
    return {"marker": marker, "path": str(path.relative_to(WORKSPACE))}


def current_mvp_status() -> dict[str, Any]:
    planner = read_json(WORKSPACE / "claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json")
    current = planner.get("current_mvp_milestone") or MVP_SEQUENCE[0]
    next_milestone = planner.get("next_mvp_milestone") or planner.get("next_paper_backtest_milestone")
    distance = planner.get("distance_to_v2_backtest_and_paper_mvp_ready") or {}
    remaining = distance.get("remaining_milestones") if isinstance(distance, dict) else None
    return {
        "active_lane": planner.get("active_lane") or "paper_backtest_mvp",
        "active_mvp_target": planner.get("active_mvp_target") or "V2_BACKTEST_AND_PAPER_MVP_READY",
        "current_mvp_milestone": current,
        "next_mvp_milestone": next_milestone or "-",
        "remaining_milestones": remaining or MVP_SEQUENCE,
    }


def quota_status() -> dict[str, Any]:
    path = WORKSPACE / "claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md"
    text = read_text(path, 20_000)
    if not text:
        return {"state": "unknown", "path": str(path.relative_to(WORKSPACE))}
    if "\nready\n" in text.lower() or "state:\nready" in text.lower():
        state = "ready"
    elif "blocked_or_limited" in text:
        state = "blocked_or_limited"
    else:
        state = "unknown"
    return {"state": state, "path": str(path.relative_to(WORKSPACE))}


def review_task_exists(marker: str) -> bool:
    if not marker:
        return False
    needle = marker.lower()
    for path in TASKS_DIR.glob("parallel_capacity_readonly_review_*.json"):
        if needle in path.name:
            return True
    return False


def make_task_id(marker: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", marker).strip("_").lower()
    return f"parallel_capacity_readonly_review_{safe[:72]}"


def create_readonly_review_task(milestone: dict[str, str]) -> str | None:
    marker = milestone.get("marker")
    path = milestone.get("path")
    if not marker or not path or review_task_exists(marker):
        return None
    task_id = make_task_id(marker)
    task_path = TASKS_DIR / f"{task_id}.json"
    report = f"claude_worklog/phase2_core_rebuild/parallel_capacity_reviews/{task_id}_REPORT.md"
    go_no_go = f"claude_worklog/phase2_core_rebuild/parallel_capacity_reviews/{task_id}_GO_NO_GO.md"
    task = {
        "task_id": task_id,
        "agent": "codex",
        "risk_level": "L1",
        "status": "pending",
        "lane": "codex_watchdog",
        "mvp_relevance": "Parallel read-only review of the latest committed milestone while builder capacity continues on the paper/backtest MVP path.",
        "blocked_by": [],
        "next_gate": "CODEX_PARALLEL_READONLY_REVIEW_READY",
        "legacy_evidence_consulted": [
            "latest committed milestone evidence",
            "runtime task states",
            "paper/backtest MVP requirement set",
        ],
        "legacy_failure_addressed": [
            "serial review bottleneck",
            "late discovery of paper/backtest compatibility gaps",
        ],
        "cwd": str(WORKSPACE),
        "emit_files": True,
        "allowed_output_prefixes": [
            "claude_worklog/phase2_core_rebuild/parallel_capacity_reviews/",
        ],
        "required_output_files": [report, go_no_go],
        "prompt": (
            f"You are local Codex CLI in {WORKSPACE}. Run a read-only parallel review of committed milestone "
            f"{marker} from {path}. Do not patch source files. Do not modify current dirty work. Do not touch "
            "/home/wali/Desktop/AI BOT. Do not write Redis. Do not restart live services. Do not place/cancel "
            "orders. Do not enable live trading. Review for paper/backtest MVP compatibility, risk-gateway "
            "handoff completeness, lineage/explainability gaps, stale evidence, and missing test-hardening "
            "recommendations. Output exactly two BEGIN_FILE blocks for the report and GO/NO-GO. GO/NO-GO must "
            "contain one line: CODEX_PARALLEL_READONLY_REVIEW_READY or CODEX_PARALLEL_READONLY_REVIEW_BLOCKED."
        ),
        "next_recommended_action": "If READY, planner may consume recommendations without blocking current build. If BLOCKED, Codex watchdog may open a non-live autofix when no builder child is active.",
    }
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    append_event({"event": "parallel_capacity_scheduler_created_readonly_review_task", "task_id": task_id, "marker": marker})
    return task_id


def run_task(task_id: str) -> int:
    append_event({"event": "parallel_capacity_scheduler_running_codex_task", "task_id": task_id})
    proc = run(["python3", "claude_worklog/tools/agent_supervisor.py", "--task-id", task_id])
    append_event(
        {
            "event": "parallel_capacity_scheduler_codex_task_finished",
            "task_id": task_id,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    )
    return proc.returncode


def run_watchdog_once() -> int:
    append_event({"event": "parallel_capacity_scheduler_invoking_watchdog_once"})
    proc = run(["python3", "claude_worklog/tools/codex_non_live_watchdog.py"])
    append_event(
        {
            "event": "parallel_capacity_scheduler_watchdog_once_finished",
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    )
    return proc.returncode


def start_service(script: str) -> None:
    run([f"./claude_worklog/tools/{script}"])


def cycle(enable_actions: bool) -> dict[str, Any]:
    generated_at = now()
    claude_children = active_claude_children()
    codex_children = active_codex_children()
    ollama_children = active_ollama_children()
    git_status = git_status_lines()
    git_clean = not git_status
    planner_running = tmux_running(PLANNER_SESSION)
    watchdog_running = tmux_running(WATCHDOG_SESSION)
    scheduler_running = tmux_running(SCHEDULER_SESSION)
    mvp = current_mvp_status()
    latest_milestone = latest_committed_milestone()
    fail_marker = latest_fail_marker()
    human_attention = latest_human_attention_task()

    available_work: list[str] = []
    next_safe_codex_task: str | None = None
    actions: list[dict[str, Any]] = []

    if human_attention:
        available_work.append(f"recover human_attention_required task {human_attention}")
    if fail_marker:
        available_work.append(f"recover failed marker {fail_marker}")
    if git_status and not claude_children and not codex_children:
        available_work.append("recover dirty tree through Codex watchdog")
    if latest_milestone and not codex_children:
        available_work.append(f"read-only review latest committed milestone {latest_milestone.get('marker')}")

    if claude_children:
        claude_lane = "active"
    elif quota_status().get("state") == "blocked_or_limited":
        claude_lane = "blocked_quota"
    elif planner_running:
        claude_lane = "planner_waiting"
    else:
        claude_lane = "idle"

    codex_watchdog_lane = "active" if watchdog_running else "idle"
    codex_review_lane = "active" if codex_children else "idle"
    codex_autofix_lane = "available" if (human_attention or fail_marker) and not codex_children else "idle"

    if claude_children and git_status:
        next_safe_codex_task = "read-only review already committed milestone; do not patch dirty current work"
    elif not claude_children and git_status:
        next_safe_codex_task = "run Codex watchdog dirty-tree recovery"
    elif human_attention:
        next_safe_codex_task = f"run Codex recovery for {human_attention}"
    elif fail_marker:
        next_safe_codex_task = f"run Codex fail-marker recovery for {fail_marker}"
    elif latest_milestone:
        next_safe_codex_task = f"queue read-only review for {latest_milestone.get('marker')}"

    if enable_actions:
        if not watchdog_running:
            start_service("start_codex_non_live_watchdog.sh")
            actions.append({"action": "started_codex_watchdog"})
            watchdog_running = True
            codex_watchdog_lane = "active"

        if not claude_children and git_status and not codex_children:
            rc = run_watchdog_once()
            actions.append({"action": "ran_watchdog_dirty_tree_recovery", "returncode": rc})
            git_status = git_status_lines()
            git_clean = not git_status

        if git_clean and not claude_children and not codex_children and (human_attention or fail_marker):
            rc = run_watchdog_once()
            actions.append({"action": "ran_watchdog_blocker_recovery", "returncode": rc})

        if git_clean and not claude_children and not codex_children and latest_milestone:
            task_id = create_readonly_review_task(latest_milestone)
            if task_id:
                rc = run_task(task_id)
                actions.append({"action": "ran_parallel_readonly_review", "task_id": task_id, "returncode": rc})

        if git_clean and not planner_running and not active_claude_children():
            start_service("start_claude_master_rebuild_planner.sh")
            actions.append({"action": "started_master_planner"})
            planner_running = True

    status = {
        "generated_at": generated_at,
        "mode": "actions_enabled" if enable_actions else "status_only",
        "claude_lane_status": claude_lane,
        "codex_review_lane_status": codex_review_lane,
        "codex_autofix_lane_status": codex_autofix_lane,
        "codex_watchdog_lane_status": codex_watchdog_lane,
        "active_claude_child": bool(claude_children),
        "active_codex_child": bool(codex_children),
        "active_ollama_child": bool(ollama_children),
        "claude_child_processes": claude_children[:10],
        "codex_child_processes": codex_children[:10],
        "git_clean": not git_status,
        "git_status": git_status,
        "planner_running": planner_running,
        "codex_watchdog_running": watchdog_running,
        "parallel_capacity_scheduler_running": scheduler_running,
        "quota_probe": quota_status(),
        "current_mvp_milestone": mvp.get("current_mvp_milestone"),
        "next_mvp_milestone": mvp.get("next_mvp_milestone"),
        "active_lane": mvp.get("active_lane"),
        "active_mvp_target": mvp.get("active_mvp_target"),
        "remaining_mvp_milestones": mvp.get("remaining_milestones"),
        "latest_committed_milestone": latest_milestone,
        "latest_fail_marker": fail_marker,
        "latest_human_attention_task": human_attention,
        "available_parallel_work": available_work,
        "next_safe_codex_task": next_safe_codex_task,
        "codex_idle_while_work_available": bool(available_work and not codex_children),
        "last_codex_parallel_review": latest_event_matching("parallel_capacity_scheduler_.*review"),
        "last_codex_autofix": latest_event_matching("codex_watchdog_.*recovered|codex_watchdog_.*recovery"),
        "last_codex_watchdog_recovery": latest_event_matching("codex_watchdog_dirty_tree_recovered|codex_watchdog_restarted_planner"),
        "actions": actions,
        "final_live_gate_status": "blocked_human_only",
    }
    write_json(STATUS_PATH, status)
    append_event(
        {
            "event": "parallel_capacity_scheduler_cycle",
            "mode": status["mode"],
            "claude_lane_status": claude_lane,
            "codex_review_lane_status": codex_review_lane,
            "codex_autofix_lane_status": codex_autofix_lane,
            "codex_watchdog_lane_status": codex_watchdog_lane,
            "codex_idle_while_work_available": status["codex_idle_while_work_available"],
            "next_safe_codex_task": next_safe_codex_task,
            "actions": actions,
        }
    )
    return status


def daemon(poll_seconds: int, enable_actions: bool) -> int:
    while True:
        try:
            cycle(enable_actions=enable_actions)
        except Exception as exc:
            append_event({"event": "parallel_capacity_scheduler_exception", "error": repr(exc)})
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=600)
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    enable_actions = not args.status_only
    if args.daemon:
        return daemon(args.poll_seconds, enable_actions=enable_actions)
    print(json.dumps(cycle(enable_actions=enable_actions), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
