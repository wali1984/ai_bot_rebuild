#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_BOT_REBUILD_ROOT:-$HOME/Desktop/AI BOT REBUILD}"
cd "$ROOT"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required for rebuild control-plane persistence" >&2
  exit 2
fi

RUNTIME_DIR="claude_worklog/agent_supervisor/runtime/control_plane"
LOG_DIR="claude_worklog/agent_supervisor/logs/control_plane"
EVENTS="claude_worklog/agent_supervisor/events.jsonl"
STOP_FILE="$RUNTIME_DIR/STOP_REBUILD_CONTROL_PLANE"
START_RECORD="$RUNTIME_DIR/rebuild_control_plane_start.json"

mkdir -p "$RUNTIME_DIR" "$LOG_DIR" "$(dirname "$EVENTS")"
rm -f "$STOP_FILE"

append_event() {
  local event="$1"
  local detail="${2:-}"
  printf '{"ts":"%s","event":"%s","detail":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$event" "$detail" >> "$EVENTS"
}

clear_dead_supervisor_lock() {
  python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path.cwd()
lock = root / "claude_worklog/agent_supervisor/supervisor.lock"
events = root / "claude_worklog/agent_supervisor/events.jsonl"
if not lock.exists():
    raise SystemExit(0)
try:
    payload = json.loads(lock.read_text())
    pid = int(payload.get("pid") or 0)
except Exception:
    pid = 0
alive = False
if pid:
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
if alive:
    print(f"supervisor lock is live: pid={pid}")
else:
    lock.unlink(missing_ok=True)
    events.parent.mkdir(parents=True, exist_ok=True)
    with events.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": __import__("datetime").datetime.datetime.now(__import__("datetime").datetime.timezone.utc).isoformat(), "event": "rebuild_control_plane_cleared_dead_supervisor_lock", "dead_pid": pid}) + "\n")
    print(f"cleared dead supervisor lock: pid={pid}")
PY
}

start_loop_session() {
  local session="$1"
  local command="$2"
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "already running: $session"
    return 0
  fi
  tmux new-session -d -s "$session" "cd '$ROOT' && $command"
  echo "started: $session"
}

clear_dead_supervisor_lock

AGENT_SUPERVISOR_ARGS="${AGENT_SUPERVISOR_ARGS:---daemon --poll-seconds 30}"

agent_loop="while true; do \
  if [ -f '$ROOT/$STOP_FILE' ]; then echo stop-file-seen; exit 0; fi; \
  printf '[%s] starting agent_supervisor.py %s\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" '$AGENT_SUPERVISOR_ARGS' >> '$ROOT/$LOG_DIR/agent_supervisor.log'; \
  python3 claude_worklog/tools/agent_supervisor.py $AGENT_SUPERVISOR_ARGS >> '$ROOT/$LOG_DIR/agent_supervisor.log' 2>&1; \
  rc=\$?; \
  printf '{\"ts\":\"%s\",\"event\":\"agent_supervisor_loop_exit\",\"rc\":%s}\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$rc\" >> '$ROOT/$EVENTS'; \
  sleep 10; \
done"

scheduler_loop="while true; do \
  if [ -f '$ROOT/$STOP_FILE' ]; then echo stop-file-seen; exit 0; fi; \
  printf '[%s] starting parallel_capacity_scheduler.py\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" >> '$ROOT/$LOG_DIR/parallel_capacity_scheduler.log'; \
  python3 claude_worklog/tools/parallel_capacity_scheduler.py --daemon --poll-seconds 600 >> '$ROOT/$LOG_DIR/parallel_capacity_scheduler.log' 2>&1; \
  rc=\$?; \
  printf '{\"ts\":\"%s\",\"event\":\"parallel_capacity_scheduler_loop_exit\",\"rc\":%s}\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$rc\" >> '$ROOT/$EVENTS'; \
  sleep 30; \
done"

watchdog_loop="while true; do \
  if [ -f '$ROOT/$STOP_FILE' ]; then echo stop-file-seen; exit 0; fi; \
  printf '[%s] starting codex_non_live_watchdog.py\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" >> '$ROOT/$LOG_DIR/codex_non_live_watchdog.log'; \
  python3 claude_worklog/tools/codex_non_live_watchdog.py --daemon --poll-seconds 300 >> '$ROOT/$LOG_DIR/codex_non_live_watchdog.log' 2>&1; \
  rc=\$?; \
  printf '{\"ts\":\"%s\",\"event\":\"codex_non_live_watchdog_loop_exit\",\"rc\":%s}\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"\$rc\" >> '$ROOT/$EVENTS'; \
  sleep 30; \
done"

start_loop_session "ai_bot_agent_supervisor" "$agent_loop"
start_loop_session "ai_bot_parallel_capacity_scheduler" "$scheduler_loop"
start_loop_session "ai_bot_codex_non_live_watchdog" "$watchdog_loop"

python3 - <<PY
import json, subprocess
from datetime import datetime, timezone
from pathlib import Path

record = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "root": str(Path.cwd()),
    "managed_sessions": [
        "ai_bot_agent_supervisor",
        "ai_bot_parallel_capacity_scheduler",
        "ai_bot_codex_non_live_watchdog",
    ],
    "agent_supervisor_args": ${AGENT_SUPERVISOR_ARGS@Q},
    "not_managed": [
        "legacy trainer",
        "legacy trader",
        "legacy orchestrator",
        "Redis",
        "VPN",
        "exchange services",
    ],
    "tmux_sessions": subprocess.run(["tmux", "list-sessions"], text=True, capture_output=True).stdout.splitlines(),
}
path = Path("$START_RECORD")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
PY

append_event "control_plane_started" "rebuild_control_plane_tmux_wrapper"
./claude_worklog/tools/status_rebuild_control_plane.sh || true
