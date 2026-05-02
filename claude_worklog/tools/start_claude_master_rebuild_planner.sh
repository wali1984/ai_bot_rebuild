#!/usr/bin/env bash
set -euo pipefail

SESSION="ai_bot_claude_master_rebuild_planner"
ROOT="$HOME/Desktop/AI BOT REBUILD"
CMD="python3 claude_worklog/tools/claude_master_rebuild_planner.py --daemon --poll-seconds 120"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required to start Claude master rebuild planner." >&2
  exit 2
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already running: $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" "cd '$ROOT' && $CMD"
echo "started tmux session: $SESSION"
