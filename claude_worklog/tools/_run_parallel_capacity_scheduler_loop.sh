#!/usr/bin/env bash
set -uo pipefail

ROOT="$HOME/Desktop/AI BOT REBUILD"
cd "$ROOT"

VENV_PY3="$ROOT/.venv/bin/python3"
if [ ! -x "$VENV_PY3" ]; then
  VENV_PY3="$(command -v python3 || true)"
fi
if [ -z "$VENV_PY3" ]; then exit 1; fi
if [ ! -f "claude_worklog/tools/parallel_capacity_scheduler.py" ]; then exit 0; fi

LOG="$ROOT/claude_worklog/agent_supervisor/logs/control_plane/parallel_capacity_scheduler.log"
mkdir -p "$(dirname "$LOG")"

while true; do
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting parallel_capacity_scheduler" >> "$LOG"
  "$VENV_PY3" claude_worklog/tools/parallel_capacity_scheduler.py --daemon --poll-seconds 600 >> "$LOG" 2>&1
  rc=$?
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] scheduler exited rc=$rc" >> "$LOG"
  sleep 5
done
