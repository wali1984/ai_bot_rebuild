#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_BOT_REBUILD_ROOT:-$HOME/Desktop/AI BOT REBUILD}"
cd "$ROOT"

OUT="claude_worklog/agent_supervisor/runtime/control_plane/rebuild_control_plane_status.json"
JSON_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out)
      OUT="$2"
      shift 2
      ;;
    --json-only)
      JSON_ONLY=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

export CONTROL_PLANE_STATUS_OUT="$OUT"
export CONTROL_PLANE_JSON_ONLY="$JSON_ONLY"

python3 - <<'PY'
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

root = Path.cwd()
out = root / os.environ["CONTROL_PLANE_STATUS_OUT"]
json_only = os.environ.get("CONTROL_PLANE_JSON_ONLY") == "1"


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso() -> str:
    return now().isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=root, shell=isinstance(cmd, str), text=True, capture_output=True)


def read_json(rel: str) -> dict[str, Any]:
    try:
        return json.loads((root / rel).read_text())
    except Exception:
        return {}


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def age_seconds(value: Any) -> int | None:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((now() - parsed).total_seconds()))


def ps_lines(pattern: str) -> list[str]:
    proc = run(f"ps -eo pid,ppid,etimes,cmd | grep -E '{pattern}' | grep -v grep || true")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def tmux_sessions() -> list[str]:
    proc = run(["tmux", "list-sessions"])
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def has_session(name: str, sessions: list[str]) -> bool:
    return any(line.startswith(f"{name}:") for line in sessions)


sessions = tmux_sessions()
heartbeat = read_json("claude_worklog/agent_supervisor/status/supervisor_heartbeat.json")
queue = read_json("claude_worklog/agent_supervisor/status/queue_status.json")
current = read_json("claude_worklog/agent_supervisor/status/current_status.json")
scheduler_status = read_json("claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json")
planner_status = read_json("claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json")
governor_selection = read_json("claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json")
paper_runtime = read_json("v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json")
start_record = read_json("claude_worklog/agent_supervisor/runtime/control_plane/rebuild_control_plane_start.json")

agent_processes = ps_lines(r"agent_supervisor.py .*--daemon|agent_supervisor.py --daemon")
scheduler_processes = ps_lines(r"parallel_capacity_scheduler.py --daemon")
watchdog_processes = ps_lines(r"codex_non_live_watchdog.py --daemon")
planner_processes = ps_lines(r"claude_master_rebuild_planner.py --daemon")
legacy_trader_processes = ps_lines(r"trading/trader.py")
legacy_live_related_processes = ps_lines(r"rl.hybrid_trainer|rl.orchestrator_worker|trading/trader.py|vpn_monitor.py|proton\\.vpn|pia-|pured")

heartbeat_age = age_seconds(heartbeat.get("last_loop_ts"))
queue_age = age_seconds(queue.get("generated_at"))
current_age = age_seconds(current.get("generated_at") or current.get("end_time") or current.get("start_time"))
scheduler_age = age_seconds(scheduler_status.get("generated_at"))
planner_age = age_seconds(planner_status.get("generated_at"))
paper_age = age_seconds(paper_runtime.get("generated_at") or paper_runtime.get("paper_runtime", {}).get("generated_at"))

payload = {
    "generated_at": iso(),
    "root": str(root),
    "live_gate_status": "blocked_human_only",
    "redis_trim_status": "deferred_non_blocking",
    "managed_scope": [
        "agent_supervisor.py",
        "parallel_capacity_scheduler.py",
        "codex_non_live_watchdog.py",
    ],
    "not_managed": [
        "legacy trainer",
        "legacy trader",
        "legacy orchestrator",
        "Redis",
        "VPN",
        "exchange services",
    ],
    "tmux": {
        "sessions": sessions,
        "agent_supervisor": has_session("ai_bot_agent_supervisor", sessions),
        "parallel_capacity_scheduler": has_session("ai_bot_parallel_capacity_scheduler", sessions),
        "codex_non_live_watchdog": has_session("ai_bot_codex_non_live_watchdog", sessions),
        "claude_master_rebuild_planner": has_session("ai_bot_claude_master_rebuild_planner", sessions),
    },
    "processes": {
        "agent_supervisor": agent_processes,
        "parallel_capacity_scheduler": scheduler_processes,
        "codex_non_live_watchdog": watchdog_processes,
        "claude_master_rebuild_planner": planner_processes,
        "legacy_trader_visible": legacy_trader_processes,
        "legacy_live_related_processes_observed_not_managed": legacy_live_related_processes,
    },
    "freshness": {
        "supervisor_heartbeat_age_seconds": heartbeat_age,
        "queue_status_age_seconds": queue_age,
        "current_status_age_seconds": current_age,
        "scheduler_status_age_seconds": scheduler_age,
        "master_planner_status_age_seconds": planner_age,
        "paper_runtime_age_seconds": paper_age,
    },
    "supervisor": {
        "alive": bool(agent_processes),
        "heartbeat_fresh": heartbeat_age is not None and heartbeat_age <= 120,
        "heartbeat": heartbeat,
        "current_task": heartbeat.get("current_task") or queue.get("current_running_task") or current.get("task_id"),
        "next_task": queue.get("next_pending_task") or governor_selection.get("selected_task_id"),
        "queue_status": {
            "generated_at": queue.get("generated_at"),
            "current_running_task": queue.get("current_running_task"),
            "next_pending_task": queue.get("next_pending_task"),
            "counts": queue.get("counts"),
            "gate": queue.get("gate"),
        },
        "current_status": current,
    },
    "scheduler": {
        "alive": bool(scheduler_processes),
        "status_fresh": scheduler_age is not None and scheduler_age <= 900,
        "status": scheduler_status,
    },
    "codex_watchdog": {
        "alive": bool(watchdog_processes),
    },
    "governor": {
        "selection": governor_selection,
        "status": "selection_file_present" if governor_selection else "selection_missing",
    },
    "master_planner": {
        "alive": bool(planner_processes),
        "status_fresh": planner_age is not None and planner_age <= 300,
        "status": planner_status,
        "policy": "not started by rebuild control-plane wrapper unless separately allowed",
    },
    "paper_runtime": {
        "fresh": paper_age is not None and paper_age <= 120,
        "status": paper_runtime.get("status") or paper_runtime.get("paper_runtime", {}).get("status"),
        "age_seconds": paper_age,
    },
    "legacy_trader": {
        "visible": bool(legacy_trader_processes),
        "classification": "legacy_observed_not_managed",
    },
    "start_record": start_record,
}
payload["healthy"] = bool(agent_processes) and bool(watchdog_processes) and bool(scheduler_processes) and (heartbeat_age is not None and heartbeat_age <= 120)

out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if json_only:
    print(json.dumps(payload, indent=2, sort_keys=True))
else:
    print("=== rebuild control plane status ===")
    print(f"healthy: {payload['healthy']}")
    print(f"agent_supervisor_alive: {payload['supervisor']['alive']}")
    print(f"heartbeat_age_seconds: {heartbeat_age}")
    print(f"scheduler_alive: {payload['scheduler']['alive']}")
    print(f"codex_watchdog_alive: {payload['codex_watchdog']['alive']}")
    print(f"master_planner_alive: {payload['master_planner']['alive']}")
    print(f"paper_runtime_age_seconds: {paper_age}")
    print(f"live_gate_status: {payload['live_gate_status']}")
    print(f"legacy_trader_visible: {payload['legacy_trader']['visible']}")
    print(f"json: {out.relative_to(root)}")
PY
