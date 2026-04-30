#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"
CMD='python3 claude_worklog/tools/agent_supervisor_dashboard.py --refresh-seconds 10'

if command -v gnome-terminal >/dev/null 2>&1; then
  gnome-terminal -- bash -lc "$CMD; exec bash" >/dev/null 2>&1 &
  echo "gnome-terminal"
  exit 0
fi

if command -v xterm >/dev/null 2>&1; then
  xterm -e bash -lc "$CMD" >/dev/null 2>&1 &
  echo "xterm"
  exit 0
fi

if command -v tmux >/dev/null 2>&1; then
  SESSION="ai_bot_agent_supervisor_dashboard"
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION" || true
  fi
  tmux new-session -d -s "$SESSION" "cd '$HOME/Desktop/AI BOT REBUILD' && $CMD"
  echo "tmux"
  exit 0
fi

echo "failed"
exit 1
