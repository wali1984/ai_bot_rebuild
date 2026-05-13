#!/usr/bin/env bash
# Start the V2 worker-porting control-plane daemons under tmux.
# Safe to re-run: each session is created only if missing.
# Does NOT start anything live, anything legacy, or anything that places orders.
set -euo pipefail

ROOT="$HOME/Desktop/AI BOT REBUILD"
cd "$ROOT"

if [ -f "claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md" ]; then
  echo "BLOCKED: final approval token present; refusing to start control plane."
  exit 2
fi

VENV_PY3="$ROOT/.venv/bin/python3"
if [ ! -x "$VENV_PY3" ]; then
  echo "WARN: .venv/bin/python3 not found; falling back to system python3"
  VENV_PY3="$(command -v python3)"
fi

mkdir -p "$ROOT/claude_worklog/agent_supervisor/logs/control_plane"

start_session () {
  local name="$1"
  local cmd="$2"
  if tmux has-session -t "$name" 2>/dev/null; then
    echo "session $name already alive"
    return 0
  fi
  tmux new-session -d -s "$name" "bash -c 'cd \"$ROOT\" && $cmd'"
  echo "started session $name"
}

start_session "ai_bot_worker_porting_orchestrator" \
  "while true; do '$VENV_PY3' claude_worklog/tools/v2_worker_porting_orchestrator.py --daemon --poll-seconds 120 >> claude_worklog/agent_supervisor/logs/control_plane/v2_worker_porting_orchestrator.log 2>&1; echo restart_loop >> claude_worklog/agent_supervisor/logs/control_plane/v2_worker_porting_orchestrator.log; sleep 5; done"

start_session "ai_bot_agent_supervisor" \
  "while true; do '$VENV_PY3' claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30 >> claude_worklog/agent_supervisor/logs/control_plane/agent_supervisor.log 2>&1; echo restart_loop >> claude_worklog/agent_supervisor/logs/control_plane/agent_supervisor.log; sleep 5; done"

if [ -f "claude_worklog/tools/parallel_capacity_scheduler.py" ]; then
  start_session "ai_bot_parallel_scheduler" \
    "while true; do '$VENV_PY3' claude_worklog/tools/parallel_capacity_scheduler.py --daemon --poll-seconds 600 >> claude_worklog/agent_supervisor/logs/control_plane/parallel_capacity_scheduler.log 2>&1; echo restart_loop >> claude_worklog/agent_supervisor/logs/control_plane/parallel_capacity_scheduler.log; sleep 5; done"
fi

if [ -f "claude_worklog/tools/codex_non_live_watchdog.py" ]; then
  start_session "ai_bot_codex_watchdog" \
    "while true; do '$VENV_PY3' claude_worklog/tools/codex_non_live_watchdog.py --daemon --poll-seconds 300 >> claude_worklog/agent_supervisor/logs/control_plane/codex_non_live_watchdog.log 2>&1; echo restart_loop >> claude_worklog/agent_supervisor/logs/control_plane/codex_non_live_watchdog.log; sleep 5; done"
fi

tmux list-sessions || true
echo "control plane requested"
