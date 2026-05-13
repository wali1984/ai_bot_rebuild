#!/usr/bin/env python3
"""Automation utilization monitor for Claude/Codex non-live runtime."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "claude_worklog/final_readiness/always_on_claude_codex_runtime/latest"
EVENTS = ROOT / "claude_worklog/agent_supervisor/events.jsonl"
STATUS = ROOT / "claude_worklog/agent_supervisor/status"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(cmd: str | list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), text=True, capture_output=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def process_lines(pattern: str) -> list[str]:
    proc = run(f"ps -eo pid,ppid,etimes,pcpu,pmem,cmd | grep -E '{pattern}' | grep -v grep || true")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def event_rows(limit: int = 5000) -> list[dict[str, Any]]:
    if not EVENTS.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in EVENTS.read_text(errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def git_change_count() -> int:
    return len([line for line in run(["git", "status", "--short"]).stdout.splitlines() if line.strip()])


def latest_commit() -> str:
    return run(["git", "log", "--oneline", "-1"]).stdout.strip()


def dirty_counts() -> dict[str, int]:
    state = read_json(FINAL / "git_dirty_state.json")
    counts = state.get("counts", {})
    return counts if isinstance(counts, dict) else {}


def classify(claude: list[str], codex: list[str], queue: dict[str, Any], dirty_count: int, counts: dict[str, int], runner_state: dict[str, Any]) -> str:
    if claude or codex:
        return "ACTIVE_OK"
    if queue.get("final_live_gate_required_count"):
        return "IDLE_BLOCKED_HUMAN_FINAL_GATE"
    if counts.get("unknown_requires_review"):
        return "IDLE_GIT_DIRTY_UNKNOWN"
    if counts.get("active_task_owned"):
        return "IDLE_GIT_DIRTY_ACTIVE_TASK"
    if not queue.get("next_pending_task"):
        primary = runner_state.get("primary_task", {}) if isinstance(runner_state, dict) else {}
        if primary.get("selected"):
            return "IDLE_EXPECTED_BREAK"
        return "IDLE_NO_TASK_SELECTED"
    if queue.get("gate") == "NON_LIVE_DECISION_PACKETS_PRESENT_QUEUE_CONTINUES":
        return "IDLE_EXPECTED_BREAK"
    return "IDLE_UNACCEPTABLE"


def collect() -> dict[str, Any]:
    claude = process_lines(r"claude --print")
    codex = process_lines(r"codex exec")
    queue = read_json(STATUS / "queue_status.json")
    current = read_json(STATUS / "current_status.json")
    runner_state = read_json(FINAL / "always_on_runtime_state.json")
    events = event_rows()
    dirty = git_change_count()
    counts = dirty_counts()
    validation_events = [e for e in events if "validation" in str(e).lower() or "build" in str(e).lower()]
    codex_events = [e for e in events if "codex" in str(e).lower()]
    state = {
        "generated_at": now(),
        "classification": classify(claude, codex, queue, dirty, counts, runner_state),
        "claude_active_minutes": None,
        "codex_active_minutes": None,
        "active_child_count": len(claude) + len(codex),
        "active_claude_children": claude,
        "active_codex_children": codex,
        "primary_task_progress": {
            "current_task": current.get("task_id"),
            "current_status": current.get("status"),
            "next_pending_task": queue.get("next_pending_task"),
            "runner_selected_primary_task": (runner_state.get("primary_task") or {}).get("selected") if isinstance(runner_state, dict) else None,
            "runner_primary_action": (runner_state.get("primary_task") or {}).get("action") if isinstance(runner_state, dict) else None,
            "current_running_task": queue.get("current_running_task"),
            "queue_counts": queue.get("counts", {}),
        },
        "files_changed": dirty,
        "git_dirty_counts": counts,
        "artifacts_generated": len(list((ROOT / "claude_worklog/final_readiness").glob("*/latest/*"))),
        "commits_created_latest": latest_commit(),
        "validation_runs_observed": len(validation_events),
        "codex_audits_completed_or_observed": len(codex_events),
        "idle_minutes": None if claude or codex else 0,
        "idle_reason": "active child observed" if claude or codex else queue.get("gate") or "no child process",
        "next_action": "continue active work" if claude or codex else "always_on_objective_runner selects/dispatches next safe primary task",
    }
    write_json(FINAL / "automation_utilization_status.json", state)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    state = collect()
    print(json.dumps(state, indent=2, sort_keys=True) if args.json else state["classification"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
