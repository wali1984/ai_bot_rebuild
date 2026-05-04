#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

SESSION="ai_bot_codex_non_live_watchdog"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Codex watchdog already running: $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" \
  "cd '$HOME/Desktop/AI BOT REBUILD' && python3 claude_worklog/tools/codex_non_live_watchdog.py --daemon --poll-seconds 300"

echo "started tmux session: $SESSION"
