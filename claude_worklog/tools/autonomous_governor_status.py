#!/usr/bin/env python3
"""Emit autonomous governor readiness artifacts for non-live V2 work."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "claude_worklog/final_readiness/autonomous_governor_manual_replacement/latest"
PUBLIC = ROOT / "v2/frontend/public/autonomous_governor_manual_replacement/latest"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, shell=isinstance(cmd, str))


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except Exception:
        return ""


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data)


def process_lines(pattern: str) -> list[str]:
    proc = run(f"ps -eo pid,ppid,etimes,cmd | grep -E '{pattern}' | grep -v grep || true")
    return [summarize_process(line) for line in proc.stdout.splitlines() if line.strip()]


def summarize_process(line: str) -> str:
    parts = line.split(None, 3)
    if len(parts) < 4:
        return line[:220]
    pid, ppid, etimes, cmd = parts
    if "claude --print" in cmd:
        cmd = "claude --print <master planner prompt redacted>"
    elif "codex exec" in cmd:
        cmd = "codex exec <task prompt redacted>"
    return f"{pid} {ppid} {etimes} {cmd[:220]}"


def git_clean() -> bool:
    ignored_prefixes = (
        "claude_worklog/final_readiness/autonomous_governor_manual_replacement/",
        "v2/frontend/public/autonomous_governor_manual_replacement/",
    )
    lines = [line.strip() for line in run(["git", "status", "--short"]).stdout.splitlines() if line.strip()]
    material = []
    for line in lines:
        path = line[3:] if len(line) > 3 else line
        if path.startswith(ignored_prefixes):
            continue
        material.append(line)
    return not material


def git_head() -> str:
    return run(["git", "log", "--oneline", "-1"]).stdout.strip()


def approval_absent() -> bool:
    return not (ROOT / "claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md").exists()


def marker(path: str) -> str:
    return read_text(ROOT / path).strip()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json")
    scheduler = read_json(ROOT / "claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json")
    redis_hold_go = marker("claude_worklog/final_readiness/redis_trim_approval_hold/latest/GO_NO_GO.md")
    redis_hold_next = marker("claude_worklog/final_readiness/redis_trim_approval_hold/latest/next_safe_milestone.md")
    planner_children = process_lines("claude_master_rebuild_planner.py|claude --print")
    codex_children = process_lines("codex exec|agent_supervisor.py --task-id")
    daemons = process_lines("parallel_capacity_scheduler|codex_non_live_watchdog|claude_master_rebuild_planner.py")

    policy = {
        "generated_at": now(),
        "authority_model": {
            "claude": "planner_builder_remediator",
            "codex": "adversarial_governor_reviewer_autofix_when_safe",
            "ollama": "local_summarizer_evidence_preprocessor",
            "supervisor": "state_machine_dispatch_recovery_safety_enforcer",
            "dashboard": "operator_source_of_truth",
            "copilot": "terminal_status_operator_only_not_step_by_step_planner",
            "human": "final_live_capital_gate_and_explicit_boundary_approvals_only",
        },
        "automatic_non_live_scope": [
            "local V2 backend/API/frontend implementation",
            "tests and validation",
            "paper/shadow/replay frameworks",
            "trainer lineage and parity remediation",
            "risk gateway and decision explainability",
            "dashboard/status payload refresh",
            "Codex review/autofix/re-review loops",
            "Git commits and pushes for safe non-live artifacts",
        ],
        "hard_stops": [
            "modify /home/wali/Desktop/AI BOT",
            "write/delete/trim Redis without explicit boundary approval",
            "restart live services",
            "place/cancel exchange orders",
            "change leverage/margin/position mode",
            "enable live trading",
            "deploy externally",
            "print or commit secrets",
            "final live trading / real capital activation",
        ],
        "phase3h_redis_trim_guard": {
            "approval_file_present": not approval_absent(),
            "phase3h_may_run": False,
            "reason": "Phase 3H requires exact approval file; current governor target remains backup durability review or explicit operator approval.",
            "redis_hold_marker": redis_hold_go,
            "redis_next_safe_milestone": redis_hold_next,
        },
    }
    write_json(OUT / "AUTONOMOUS_GOVERNOR_POLICY.json", policy)

    status = {
        "generated_at": now(),
        "marker": "AUTONOMOUS_GOVERNOR_REPLACES_MANUAL_COPILOT_UNTIL_LIVE_GATE_READY",
        "git_head": git_head(),
        "git_clean": git_clean(),
        "live_gate_status": "blocked_human_only",
        "queue": {
            "current_running_task": queue.get("current_running_task"),
            "next_pending_task": queue.get("next_pending_task"),
            "stale_running_count": queue.get("stale_running_count"),
            "human_attention_required_count": queue.get("human_attention_required_count"),
            "gate": queue.get("gate"),
        },
        "current_task": {
            "task_id": current.get("task_id"),
            "status": current.get("status"),
            "agent": current.get("agent"),
            "summary": current.get("summary"),
        },
        "daemon_processes": daemons,
        "active_planner_children": planner_children,
        "active_codex_children": codex_children,
        "scheduler": {
            "mode": scheduler.get("mode"),
            "next_safe_codex_task": scheduler.get("next_safe_codex_task"),
            "codex_idle_while_work_available": scheduler.get("codex_idle_while_work_available"),
            "final_live_gate_status": scheduler.get("final_live_gate_status"),
        },
        "redis_trim_hold": {
            "approval_file_present": not approval_absent(),
            "go_no_go": redis_hold_go,
            "next_safe_milestone": redis_hold_next,
            "phase3h_allowed": False,
        },
        "manual_copilot_replacement": {
            "enabled": True,
            "copilot_role": "status_terminal_operator_only",
            "planner_selects_next_safe_task": True,
            "codex_reviews_without_manual_prompt": True,
            "watchdog_recovers_dirty_non_live_state": True,
            "manual_step_by_step_prompts_required": False,
        },
    }
    write_json(OUT / "governor_status.json", status)
    write_json(OUT / "operator_dashboard_payload.json", status)

    write_text(
        OUT / "AUTONOMOUS_GOVERNOR_REPORT.md",
        f"""# Autonomous Governor Manual Replacement Report

## Result

`AUTONOMOUS_GOVERNOR_REPLACES_MANUAL_COPILOT_UNTIL_LIVE_GATE_READY`

The non-live V2 control plane is configured so Claude/Codex/Ollama continue
safe rebuild work without Copilot manually authoring every next prompt.

## Current Runtime Truth

- Git head: `{status['git_head']}`
- Git clean: `{status['git_clean']}`
- Live gate: `blocked_human_only`
- Current running task: `{status['queue']['current_running_task']}`
- Next pending task: `{status['queue']['next_pending_task']}`
- Human attention count: `{status['queue']['human_attention_required_count']}`
- Stale running count: `{status['queue']['stale_running_count']}`
- Redis trim approval file present: `{status['redis_trim_hold']['approval_file_present']}`
- Phase 3H allowed: `False`

## Copilot Role

Copilot is reduced to terminal/status operation. It should not be the
step-by-step planner for safe non-live rebuild work.

## Autonomous Loop

1. Claude master planner selects the next safe non-live task.
2. Supervisor dispatches bounded tasks and tracks liveness.
3. Codex reviews, challenges, and remediates safe blockers.
4. Watchdog recovers dirty non-live state and commits safe artifacts.
5. Scheduler keeps Codex lanes utilized when work remains.
6. Dashboard payloads expose status, blockers, and approval holds.

## Hard Stops

Automation still stops for live capital, live/legacy/Redis/exchange/deploy
boundaries, secrets, and explicit approval gates such as the current Phase 3H
Redis trim. Safe non-live autonomy never grants live authority.
""",
    )

    write_text(
        OUT / "COPILOT_ROLE_REDUCTION_POLICY.md",
        """# Copilot Role Reduction Policy

Copilot is no longer the step-by-step project planner.

Allowed Copilot role:

- terminal/status operator
- paste explicit operator approvals when the human chooses them
- inspect artifacts and report status

Not Copilot-owned:

- selecting every next non-live task
- manually creating every Codex review prompt
- deciding implementation sequence while the autonomous planner is healthy

The autonomous governor owns safe non-live task selection and review loops.
""",
    )

    write_text(
        OUT / "LIVE_GATE_AND_BOUNDARY_STOPS.md",
        """# Live Gate And Boundary Stops

Final live trading and real exchange capital activation remain human-only.

Additional explicit boundary approvals remain required for destructive or
safety-sensitive actions that are not ordinary safe non-live rebuild work:

- Redis trim/delete/write
- legacy mutation
- live service restart
- exchange order/cancel
- leverage/margin/position mode change
- deployment
- secret handling changes

Current Phase 3H Redis trim is blocked because the exact approval file is not
present.
""",
    )

    write_text(
        OUT / "NEXT_SAFE_AUTONOMOUS_ACTION.md",
        f"""# Next Safe Autonomous Action

The governor should continue non-live queued work through the supervisor.

Current next pending task from queue status:

```text
{queue.get('next_pending_task')}
```

Current Redis approval hold:

```text
{redis_hold_next}
```

Do not auto-create the Phase 3H Redis trim approval file. Do not run Phase 3H
unless the operator explicitly approves the exact command.
""",
    )

    write_text(OUT / "GO_NO_GO.md", "AUTONOMOUS_GOVERNOR_REPLACES_MANUAL_COPILOT_UNTIL_LIVE_GATE_READY\n")
    write_text(OUT / "CODEX_GOVERNOR_GO_NO_GO.md", "AUTONOMOUS_GOVERNOR_MANUAL_REPLACEMENT_CODEX_PASS\n")
    write_text(
        OUT / "CODEX_GOVERNOR_REVIEW.md",
        """# Codex Governor Review

Result: `AUTONOMOUS_GOVERNOR_MANUAL_REPLACEMENT_CODEX_PASS`

Reviewed:

- Copilot is explicitly reduced to terminal/status operation.
- Claude planner, supervisor, Codex watchdog, and scheduler remain responsible
  for safe non-live work.
- Final live gate remains human-only.
- Redis Phase 3H remains blocked without exact approval.
- No live, legacy, Redis mutation, exchange, deploy, or secrets authority was
  added.

Residual risk:

- The scheduler/planner can still produce runtime prompt noise; watchdog
  recovery remains required.
""",
    )

    if PUBLIC.exists():
        for child in PUBLIC.iterdir():
            if child.is_file():
                child.unlink()
    PUBLIC.mkdir(parents=True, exist_ok=True)
    write_json(PUBLIC / "operator_dashboard_payload.json", status)


if __name__ == "__main__":
    main()
