#!/usr/bin/env python3
"""Persistent V2 automation liveness watchdog.

This watchdog observes the non-live V2 automation service layer, restarts
installed user services when allowed, and publishes a public status payload. It
does not start legacy runtime, unlock live mode, or call exchange mutation APIs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
STATE_PATH = ROOT / "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json"
AGENT_QUEUE_PATH = ROOT / "claude_worklog/agent_supervisor/status/queue_status.json"
AGENT_CURRENT_STATUS_PATH = ROOT / "claude_worklog/agent_supervisor/status/current_status.json"
TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/tasks"
STATE_TASKS_DIR = ROOT / "claude_worklog/agent_supervisor/state/tasks"
LOCAL_OUT = (
    ROOT
    / "claude_worklog/final_readiness/v2_persistent_automation_service_layer/latest/automation_liveness_watchdog_status.json"
)
PUBLIC_OUT = ROOT / "v2/frontend/public/v2_persistent_automation_service_layer/latest/automation_liveness_watchdog_status.json"
PAPER_RUNTIME_STATUS = (
    ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json"
)
FINAL_APPROVAL = ROOT / "claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md"
REDIS_TRIM_APPROVAL = (
    ROOT / "claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md"
)

SERVICE_UNITS = [
    "ai-bot-v2-worker-porting-orchestrator.service",
    "ai-bot-v2-agent-supervisor.service",
    "ai-bot-v2-parallel-scheduler.service",
    "ai-bot-v2-codex-watchdog.service",
    "ai-bot-v2-paper-online-runtime.service",
    "ai-bot-v2-paper-shadow-observation.service",
    "ai-bot-v2-feature-snapshot-builder.service",
    "ai-bot-v2-trainer-bridge.service",
]
TIMER_UNITS = ["ai-bot-v2-automation-liveness-watchdog.timer"]

PROCESS_PATTERNS = {
    "v2_worker_porting_orchestrator": "v2_worker_porting_orchestrator.py",
    "agent_supervisor": "agent_supervisor.py --daemon",
    "parallel_capacity_scheduler": "parallel_capacity_scheduler.py --daemon",
    "codex_non_live_watchdog": "codex_non_live_watchdog.py --daemon",
    "paper_online_runtime": "paper_online_runtime",
    "paper_shadow_observation": "paper_shadow_observation",
    "feature_snapshot_builder": "v2_feature_snapshot_builder",
    "trainer_bridge": "v2_trainer_bridge",
    "claude_worker": "claude --print",
}


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def systemd_user_available() -> bool:
    if run(["bash", "-lc", "command -v systemctl >/dev/null"]).returncode != 0:
        return False
    return run(["systemctl", "--user", "is-system-running"]).returncode == 0


def unit_installed(unit: str) -> bool:
    proc = run(["systemctl", "--user", "list-unit-files", unit])
    return unit in proc.stdout


def unit_state(unit: str) -> dict[str, Any]:
    if not systemd_user_available():
        return {"unit": unit, "installed": False, "active_state": "systemd_user_unavailable"}
    installed = unit_installed(unit)
    active = run(["systemctl", "--user", "is-active", unit]).stdout.strip() or "unknown"
    enabled = run(["systemctl", "--user", "is-enabled", unit]).stdout.strip() or "unknown"
    return {"unit": unit, "installed": installed, "active_state": active, "enabled_state": enabled}


def restart_unit(unit: str) -> dict[str, Any]:
    proc = run(["systemctl", "--user", "restart", unit], timeout=30)
    return {
        "unit": unit,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip()[-2000:],
        "stderr": proc.stderr.strip()[-2000:],
    }


def process_snapshot() -> dict[str, list[str]]:
    proc = run(["ps", "-eo", "pid,ppid,etimes,cmd", "--no-headers"])
    lines = proc.stdout.splitlines()
    found: dict[str, list[str]] = {}
    for name, needle in PROCESS_PATTERNS.items():
        found[name] = [
            line.strip()
            for line in lines
            if needle in line
            and "v2_automation_liveness_watchdog.py" not in line
            and "watch -n" not in line
            and " rg " not in line
        ]
    return found


def pending_codex_reviews() -> list[str]:
    pending: list[str] = []
    for task_path in sorted(TASKS_DIR.glob("codex_review_*.json")):
        task = read_json(task_path)
        state = read_json(STATE_TASKS_DIR / task_path.name)
        status = state.get("status") or task.get("status") or "pending"
        if status in {"pending", "retry_scheduled", "blocked_dependency"}:
            pending.append(task_path.name)
    return pending


def parse_utc(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).timestamp()
    except Exception:
        return None


def paper_runtime_freshness(now_ts: float) -> dict[str, Any]:
    payload = read_json(PAPER_RUNTIME_STATUS)
    generated_at = payload.get("generated_at") if isinstance(payload, dict) else None
    ts = parse_utc(generated_at)
    if ts is None:
        return {
            "path": str(PAPER_RUNTIME_STATUS.relative_to(ROOT)),
            "status": "missing_or_unparseable",
            "generated_at": generated_at,
            "age_seconds": None,
        }
    age = max(0, int(now_ts - ts))
    return {
        "path": str(PAPER_RUNTIME_STATUS.relative_to(ROOT)),
        "status": "fresh" if age <= 180 else "stale",
        "generated_at": generated_at,
        "age_seconds": age,
    }


def build_status(no_restart: bool) -> dict[str, Any]:
    now_ts = time.time()
    state = read_json(STATE_PATH)
    processes = process_snapshot()
    systemd_available = systemd_user_available()
    unit_states = [unit_state(unit) for unit in SERVICE_UNITS + TIMER_UNITS]
    pending_reviews = pending_codex_reviews()
    supervisor_current = read_json(AGENT_CURRENT_STATUS_PATH)

    blockers: list[str] = []
    actions: list[dict[str, Any]] = []
    if FINAL_APPROVAL.exists():
        blockers.append("final_live_approval_token_present")
    if REDIS_TRIM_APPROVAL.exists():
        blockers.append("redis_trim_approval_present")

    next_action = state.get("next_action") if isinstance(state, dict) else {}
    next_kind = next_action.get("kind") if isinstance(next_action, dict) else None
    selected_descriptor = next_action.get("task_descriptor") if isinstance(next_action, dict) else None
    selected_task_id = Path(str(selected_descriptor)).stem if selected_descriptor else None
    in_flight = state.get("in_flight_workers") if isinstance(state, dict) else []
    if not isinstance(in_flight, list):
        in_flight = []

    agent_alive = bool(processes.get("agent_supervisor"))
    if next_kind and str(next_kind).startswith("dispatch_") and not agent_alive:
        blockers.append("dispatch_action_pending_but_agent_supervisor_not_alive")

    state_age: int | None = None
    state_ts = parse_utc(state.get("as_of_utc") if isinstance(state, dict) else None)
    if state_ts is not None:
        state_age = max(0, int(now_ts - state_ts))
        if state_age > 600 and not in_flight:
            blockers.append("worker_porting_state_stale_and_no_worker_in_flight")

    codex_idle = not any(processes.get(name) for name in ("codex_non_live_watchdog",))
    if pending_reviews and codex_idle:
        blockers.append("codex_review_pending_but_codex_watchdog_not_alive")

    supervisor_task_id = supervisor_current.get("task_id") if isinstance(supervisor_current, dict) else None
    supervisor_status = supervisor_current.get("status") if isinstance(supervisor_current, dict) else None
    current_worker_dispatch_proof = {
        "selected_task_id": selected_task_id,
        "supervisor_task_id": supervisor_task_id,
        "supervisor_status": supervisor_status,
        "claude_worker_process_active": bool(processes.get("claude_worker")),
        "proved": bool(
            selected_task_id
            and supervisor_task_id == selected_task_id
            and supervisor_status == "running"
        ),
    }

    if systemd_available and not blockers[:2]:
        for item in unit_states:
            unit = item["unit"]
            if not unit.endswith(".service"):
                continue
            if item.get("installed") and item.get("active_state") not in {"active", "activating"}:
                if no_restart:
                    actions.append({"unit": unit, "action": "restart_skipped_no_restart"})
                else:
                    actions.append({"unit": unit, "action": "restart", "result": restart_unit(unit)})
    elif not systemd_available:
        actions.append(
            {
                "action": "fallback_required",
                "command": "bash claude_worklog/tools/install_v2_persistent_automation_services.sh",
            }
        )

    payload = {
        "generated_at": iso_now(),
        "classification": [
            "SYSTEMD_USER_PERSISTENCE_REQUIRED",
            "LIVE_GATE_BLOCKED_HUMAN_ONLY",
            "NO_LEGACY_RESTART",
        ],
        "systemd_user_available": systemd_available,
        "service_units": unit_states,
        "processes": processes,
        "worker_state_path": str(STATE_PATH.relative_to(ROOT)),
        "current_worker": state.get("current_worker") if isinstance(state, dict) else None,
        "next_worker": state.get("next_worker") if isinstance(state, dict) else None,
        "next_action": next_kind,
        "in_flight_workers": in_flight,
        "last_completed_worker": state.get("last_completed_worker") if isinstance(state, dict) else None,
        "live_gate": state.get("live_gate") if isinstance(state, dict) else "blocked_human_only",
        "final_approval_token": "present" if FINAL_APPROVAL.exists() else "absent",
        "redis_trim_approval": "present" if REDIS_TRIM_APPROVAL.exists() else "absent",
        "git_corruption_detected": state.get("git_corruption_detected") if isinstance(state, dict) else None,
        "state_age_seconds": state_age,
        "pending_codex_reviews": pending_reviews,
        "supervisor_current_status": {
            "task_id": supervisor_task_id,
            "status": supervisor_status,
            "run_pid": supervisor_current.get("run_pid") if isinstance(supervisor_current, dict) else None,
        },
        "current_worker_dispatch_proof": current_worker_dispatch_proof,
        "paper_runtime_freshness": paper_runtime_freshness(now_ts),
        "blockers": blockers,
        "actions": actions,
        "result": "PASS" if not blockers else "BLOCKED",
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()

    os.chdir(ROOT)
    payload = build_status(no_restart=args.no_restart)
    if args.write:
        write_json(LOCAL_OUT, payload)
        write_json(PUBLIC_OUT, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["final_approval_token"] == "absent" else 2


if __name__ == "__main__":
    raise SystemExit(main())
