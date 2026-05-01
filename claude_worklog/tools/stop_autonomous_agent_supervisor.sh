#!/usr/bin/env bash
set -euo pipefail

SESSION="ai_bot_autonomous_agent_supervisor"
if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION"
  echo "stopped tmux session: $SESSION"
else
  echo "tmux session not running: $SESSION"
fi
