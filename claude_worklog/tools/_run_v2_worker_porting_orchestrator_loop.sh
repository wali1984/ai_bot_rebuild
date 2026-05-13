#!/usr/bin/env bash
# Internal restart loop for the orchestrator daemon. Invoked by
# start_v2_worker_porting_control_plane.sh inside a tmux session.
# Loops a single daemon invocation; if it crashes, sleep 5 and restart.
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

LOG="$ROOT/claude_worklog/agent_supervisor/logs/control_plane/v2_worker_porting_orchestrator.log"
mkdir -p "$(dirname "$LOG")"

while true; do
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting v2_worker_porting_orchestrator daemon" >> "$LOG"
  "$VENV_PY3" claude_worklog/tools/v2_worker_porting_orchestrator.py --daemon --poll-seconds 120 >> "$LOG" 2>&1
  rc=$?
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] orchestrator daemon exited rc=$rc" >> "$LOG"
  sleep 5
done
