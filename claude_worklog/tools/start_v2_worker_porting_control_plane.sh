#!/usr/bin/env bash
# Fallback tmux starter for the V2 worker-porting control plane.
# Primary persistence is now the systemd user service layer:
#   bash claude_worklog/tools/install_v2_persistent_automation_services.sh
#
# Keep this script for environments where systemd user services are not
# available. Sessions launched from a chat harness may be collected with the
# parent shell, so this script is no longer the durable path.
set -euo pipefail

ROOT="$HOME/Desktop/AI BOT REBUILD"
cd "$ROOT"

SYSTEMD_UNITS=(
  ai-bot-v2-worker-porting-orchestrator.service
  ai-bot-v2-agent-supervisor.service
  ai-bot-v2-parallel-scheduler.service
  ai-bot-v2-codex-watchdog.service
)

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1; then
  running=0
  for unit in "${SYSTEMD_UNITS[@]}"; do
    if systemctl --user is-active --quiet "$unit"; then
      running=$((running + 1))
    fi
  done
  if [ "$running" -eq "${#SYSTEMD_UNITS[@]}" ]; then
    echo "systemd user control-plane services are already active; tmux fallback not needed"
    bash "$ROOT/claude_worklog/tools/status_v2_persistent_automation_services.sh"
    exit 0
  fi
  echo "systemd user services are available; prefer:"
  echo "  bash claude_worklog/tools/install_v2_persistent_automation_services.sh"
fi

echo "WARNING: tmux fallback sessions launched from a chat harness may not persist after the shell exits."

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
