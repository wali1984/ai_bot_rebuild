#!/usr/bin/env bash
# Internal restart loop for agent_supervisor.py. Invoked under tmux.
set -uo pipefail

ROOT="$HOME/Desktop/AI BOT REBUILD"
cd "$ROOT"

VENV_PY3="$ROOT/.venv/bin/python3"
if [ ! -x "$VENV_PY3" ]; then
  VENV_PY3="$(command -v python3 || true)"
fi
if [ -z "$VENV_PY3" ]; then
  echo "FATAL: no python3 available" >&2
  exit 1
fi
if [ ! -f "claude_worklog/tools/agent_supervisor.py" ]; then
  echo "FATAL: claude_worklog/tools/agent_supervisor.py not found" >&2
  exit 1
fi

LOG="$ROOT/claude_worklog/agent_supervisor/logs/control_plane/agent_supervisor.log"
mkdir -p "$(dirname "$LOG")"

while true; do
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting agent_supervisor daemon" >> "$LOG"
  "$VENV_PY3" claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30 >> "$LOG" 2>&1
  rc=$?
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] agent_supervisor daemon exited rc=$rc" >> "$LOG"
  sleep 5
done
