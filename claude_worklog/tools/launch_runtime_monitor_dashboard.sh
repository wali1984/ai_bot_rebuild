#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/Desktop/AI BOT REBUILD"
DASH_CMD='cd "$HOME/Desktop/AI BOT REBUILD"; python3 claude_worklog/tools/runtime_monitor_dashboard.py --target-hours 16 --min-hours 12 --refresh-seconds 15'

cd "$ROOT"

if command -v gnome-terminal >/dev/null 2>&1; then
  gnome-terminal --title="AI BOT Runtime Monitor Dashboard" -- bash -lc "$DASH_CMD; exec bash"
  echo "Dashboard launched in gnome-terminal"
elif command -v xterm >/dev/null 2>&1; then
  xterm -T "AI BOT Runtime Monitor Dashboard" -e "$DASH_CMD"
  echo "Dashboard launched in xterm"
else
  tmux new-session -d -s ai_bot_monitor_dashboard "$DASH_CMD"
  echo "Dashboard launched in tmux session: ai_bot_monitor_dashboard"
  echo "Attach with: tmux attach -t ai_bot_monitor_dashboard"
fi