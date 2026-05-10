#!/usr/bin/env python3
"""Codex acting-governor status and task selection.

This deterministic helper runs only inside AI BOT REBUILD and does not execute
live, Redis, legacy, or exchange mutations. It gives the scheduler a concrete
Codex lane decision while Claude is rate-limited.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "claude_worklog/final_readiness/claude_codex_rate_limit_handoff/latest"
TASKS = ROOT / "claude_worklog/agent_supervisor/tasks"
STATE = ROOT / "claude_worklog/agent_supervisor/state/tasks"
EVENTS = ROOT / "claude_worklog/agent_supervisor/events.jsonl"
SAFE_RISK_LEVELS = {"L0", "L1", "L2"}
TERMINAL_OK = {"completed", "superseded_by_evidence"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def append_event(event: dict[str, Any]) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", now())
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def task_file(task_id: str) -> Path:
    return TASKS / f"{task_id}.json"


def task_state(task_id: str) -> dict[str, Any]:
    return read_json(STATE / f"{task_id}.json")


def task_status(task_id: str, task: dict[str, Any]) -> str:
    return str(task_state(task_id).get("status") or task.get("status") or "pending")


def required_outputs_exist(task: dict[str, Any]) -> bool:
    required = [str(x) for x in task.get("required_output_files", []) if str(x).strip()]
    return bool(required) and all((ROOT / rel).exists() for rel in required)


def mark_source_superseded_if_materialized(task_id: str, task: dict[str, Any]) -> bool:
    if task_status(task_id, task) in TERMINAL_OK:
        return False
    if not required_outputs_exist(task):
        return False
    STATE.mkdir(parents=True, exist_ok=True)
    state = task_state(task_id)
    state.update(
        {
            "task_id": task_id,
            "status": "superseded_by_evidence",
            "run_pid": None,
            "last_run": {"start": None, "end": now(), "status": "superseded_by_evidence"},
            "last_summary": "Codex takeover materialized required outputs while Claude was rate-limited.",
            "last_status_change_ts": now(),
            "last_event_ts": now(),
            "resume_after_utc": None,
            "attention_reason": None,
            "materialized_files": task.get("required_output_files", []),
        }
    )
    history = state.get("history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "ts": now(),
            "status": "superseded_by_evidence",
            "reason": "required outputs exist from Codex acting-governor takeover",
        }
    )
    state["history"] = history
    write_json(STATE / f"{task_id}.json", state)
    append_event({"event": "codex_acting_governor_source_superseded", "source_task_id": task_id})
    return True


def dependencies_satisfied(task: dict[str, Any]) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for dep in list(task.get("depends_on", []) or []) + list(task.get("predecessor_task_ids", []) or []):
        dep_id = str(dep).strip()
        if not dep_id:
            continue
        dep_task = read_json(task_file(dep_id))
        if task_status(dep_id, dep_task) not in TERMINAL_OK:
            missing.append(dep_id)
    return not missing, missing


def is_safe_takeover_candidate(task: dict[str, Any]) -> tuple[bool, str]:
    risk = str(task.get("risk_level") or "").upper()
    if risk not in SAFE_RISK_LEVELS:
        return False, f"risk level {risk or 'missing'} is not eligible for Codex takeover"
    if str(task.get("agent")) == "codex":
        return True, "already codex task"
    if str(task.get("agent")) != "claude":
        return False, f"agent {task.get('agent')} is not eligible for Claude-rate-limit takeover"
    prompt = str(task.get("prompt") or "").lower()
    hard_live_terms = [
        "final live approval",
        "enable live mode",
        "turn on live mode",
        "place real order",
        "cancel real order",
        "change leverage",
        "change margin",
        "xtrim",
        "redis trim",
    ]
    for term in hard_live_terms:
        idx = prompt.find(term)
        if idx == -1:
            continue
        window = prompt[max(0, idx - 32):idx]
        if "do not" in window or "not " in window or "never" in window or "forbidden" in window:
            continue
        return False, f"prompt contains unguarded high-risk term: {term}"
    return True, "safe non-live Claude task eligible for Codex takeover"


def make_takeover_task(source_task_id: str, task: dict[str, Any]) -> tuple[str | None, str]:
    safe, reason = is_safe_takeover_candidate(task)
    if not safe:
        return None, reason
    deps_ok, missing = dependencies_satisfied(task)
    if not deps_ok:
        return None, "waiting on dependencies: " + ", ".join(missing)
    if required_outputs_exist(task):
        mark_source_superseded_if_materialized(source_task_id, task)
        return None, "source task already materialized required outputs"

    takeover_id = f"codex_takeover_{source_task_id}"
    takeover_path = task_file(takeover_id)
    takeover = dict(task)
    takeover["task_id"] = takeover_id
    takeover["agent"] = "codex"
    takeover["status"] = "pending"
    takeover["priority"] = int(task.get("priority") or 0) + 1
    takeover["auto_commit"] = False
    takeover["commit_message"] = f"Codex takeover outputs for {source_task_id}"
    takeover["description"] = (
        f"Codex acting-governor takeover for {source_task_id} while Claude is rate-limited."
    )
    takeover["prompt"] = (
        "You are Codex acting-governor because Claude Code is rate-limited. "
        f"Complete the safe non-live source task {source_task_id} through the supervisor. "
        "Respect the source task output contract exactly. Do not modify legacy. Do not write Redis. "
        "Do not restart services. Do not place/cancel exchange orders. Do not change leverage or margin. "
        "Do not enable live trading. Do not expose secrets. Human input is required only for final live/capital gate.\n\n"
        + str(task.get("prompt") or "")
    )
    if takeover_path.exists():
        existing = read_json(takeover_path)
        if task_status(takeover_id, existing) in TERMINAL_OK:
            mark_source_superseded_if_materialized(source_task_id, task)
            return None, "existing takeover task already completed"
    else:
        write_json(takeover_path, takeover)
        append_event(
            {
                "event": "codex_acting_governor_created_takeover_task",
                "source_task_id": source_task_id,
                "takeover_task_id": takeover_id,
            }
        )
    return takeover_id, reason


def run_supervisor_task(task_id: str) -> dict[str, Any]:
    append_event({"event": "codex_acting_governor_dispatch_started", "task_id": task_id})
    proc = subprocess.run(
        ["python3", "claude_worklog/tools/agent_supervisor.py", "--task-id", task_id],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    result = {
        "task_id": task_id,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }
    append_event({"event": "codex_acting_governor_dispatch_finished", **result})
    return result


def select_takeover_task(queue: dict[str, Any]) -> tuple[str | None, str, dict[str, Any]]:
    source_task_id = str(queue.get("next_pending_task") or "").strip()
    if not source_task_id:
        return None, "no queue next_pending_task", {}
    task = read_json(task_file(source_task_id))
    if not task:
        return None, f"task definition missing for {source_task_id}", {}
    takeover_id, reason = make_takeover_task(source_task_id, task)
    return takeover_id, reason, task


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dispatch", action="store_true", help="Dispatch selected takeover task through agent_supervisor")
    args = parser.parse_args()

    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    scheduler = read_json(ROOT / "claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json")
    takeover_task_id, selection_reason, source_task = select_takeover_task(queue)
    dispatch_result: dict[str, Any] | None = None
    if args.dispatch and takeover_task_id:
        dispatch_result = run_supervisor_task(takeover_task_id)
        source_task_id = str(queue.get("next_pending_task") or "").strip()
        if source_task_id and source_task:
            mark_source_superseded_if_materialized(source_task_id, source_task)

    selection = {
        "generated_at": now(),
        "mode": "codex_acting_governor",
        "claude_rate_limited": scheduler.get("claude_rate_limited", True),
        "selected_task": takeover_task_id or queue.get("next_pending_task") or "safe_non_live_backlog_review",
        "source_queue_task": queue.get("next_pending_task"),
        "selection_reason": selection_reason,
        "dispatch_requested": bool(args.dispatch),
        "dispatch_result": dispatch_result,
        "can_codex_execute_now": True,
        "can_codex_review_now": True,
        "can_ollama_prepare_evidence": True,
        "requires_claude_after_reset": bool(queue.get("next_pending_task") and not takeover_task_id),
        "final_live_gate_required": False,
        "live_gate_status": "blocked_human_only",
        "forbidden_actions": [
            "legacy mutation",
            "Redis mutation without exact approval",
            "real exchange action",
            "live leverage/margin/position-mode changes",
            "live trading enablement",
            "secret exposure",
        ],
    }
    write_json(OUT / "codex_acting_governor_selection.json", selection)
    with (OUT / "codex_takeover_task_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": now(), "event": "codex_acting_governor_selection", **selection}, sort_keys=True) + "\n")
    return 0 if not dispatch_result or dispatch_result.get("returncode") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
