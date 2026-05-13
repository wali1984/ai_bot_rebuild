#!/usr/bin/env bash
# Stop the V2 worker-porting control-plane tmux sessions.
# Does NOT kill paper_online_runtime, paper_shadow_observation, or any
# legacy-owned process.
set -euo pipefail

for name in ai_bot_worker_porting_orchestrator ai_bot_agent_supervisor ai_bot_parallel_scheduler ai_bot_codex_watchdog; do
  if tmux has-session -t "$name" 2>/dev/null; then
    tmux kill-session -t "$name"
    echo "stopped tmux session $name"
  else
    echo "no session $name"
  fi
done
