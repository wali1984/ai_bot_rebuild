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

mkdir -p "$ROOT/claude_worklog/agent_supervisor/logs/control_plane"

start_session () {
  local name="$1"
  local loop_script="$2"
  if tmux has-session -t "$name" 2>/dev/null; then
    echo "session $name already alive"
    return 0
  fi
  if [ ! -x "$loop_script" ]; then
    echo "WARN: $loop_script not executable; skipping $name"
    return 0
  fi
  tmux new-session -d -s "$name" "$loop_script"
  echo "started session $name"
}

start_session "ai_bot_worker_porting_orchestrator" \
  "$ROOT/claude_worklog/tools/_run_v2_worker_porting_orchestrator_loop.sh"

start_session "ai_bot_agent_supervisor" \
  "$ROOT/claude_worklog/tools/_run_agent_supervisor_loop.sh"

start_session "ai_bot_parallel_scheduler" \
  "$ROOT/claude_worklog/tools/_run_parallel_capacity_scheduler_loop.sh"

start_session "ai_bot_codex_watchdog" \
  "$ROOT/claude_worklog/tools/_run_codex_non_live_watchdog_loop.sh"

tmux list-sessions || true
echo "control plane requested"
