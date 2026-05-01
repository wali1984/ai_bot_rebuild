#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"
SESSION="ai_bot_agent_supervisor"
CMD='python3 claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30'

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required to start daemon session." >&2
  exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already running: $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" "cd '$HOME/Desktop/AI BOT REBUILD' && $CMD"
echo "started tmux session: $SESSION"