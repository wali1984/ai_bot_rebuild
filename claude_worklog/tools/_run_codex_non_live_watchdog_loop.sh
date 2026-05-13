#!/usr/bin/env bash
set -uo pipefail

ROOT="$HOME/Desktop/AI BOT REBUILD"
cd "$ROOT"

VENV_PY3="$ROOT/.venv/bin/python3"
if [ ! -x "$VENV_PY3" ]; then
  VENV_PY3="$(command -v python3 || true)"
fi
if [ -z "$VENV_PY3" ]; then exit 1; fi
if [ ! -f "claude_worklog/tools/codex_non_live_watchdog.py" ]; then exit 0; fi

LOG="$ROOT/claude_worklog/agent_supervisor/logs/control_plane/codex_non_live_watchdog.log"
mkdir -p "$(dirname "$LOG")"

while true; do
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting codex_non_live_watchdog" >> "$LOG"
  "$VENV_PY3" claude_worklog/tools/codex_non_live_watchdog.py --daemon --poll-seconds 300 >> "$LOG" 2>&1
  rc=$?
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] watchdog exited rc=$rc" >> "$LOG"
  sleep 5
done
