#!/usr/bin/env bash
set -euo pipefail

ROOT="${AI_BOT_REBUILD_ROOT:-$HOME/Desktop/AI BOT REBUILD}"
cd "$ROOT"

RUNTIME_DIR="claude_worklog/agent_supervisor/runtime/control_plane"
EVENTS="claude_worklog/agent_supervisor/events.jsonl"
STOP_FILE="$RUNTIME_DIR/STOP_REBUILD_CONTROL_PLANE"

mkdir -p "$RUNTIME_DIR" "$(dirname "$EVENTS")"
touch "$STOP_FILE"

append_event() {
  printf '{"ts":"%s","event":"%s","detail":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${2:-}" >> "$EVENTS"
}

for session in \
  ai_bot_agent_supervisor \
  ai_bot_parallel_capacity_scheduler \
  ai_bot_codex_non_live_watchdog
do
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux send-keys -t "$session" C-c 2>/dev/null || true
    sleep 1
    tmux kill-session -t "$session" 2>/dev/null || true
    echo "stopped: $session"
  else
    echo "not running: $session"
  fi
done

append_event "control_plane_stopped" "rebuild_control_plane_tmux_wrapper"
./claude_worklog/tools/status_rebuild_control_plane.sh || true
