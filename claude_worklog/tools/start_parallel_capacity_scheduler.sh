#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

SESSION="ai_bot_parallel_capacity_scheduler"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Parallel capacity scheduler already running: $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" \
  "cd '$HOME/Desktop/AI BOT REBUILD' && python3 claude_worklog/tools/parallel_capacity_scheduler.py --daemon --poll-seconds 600"

echo "started tmux session: $SESSION"
