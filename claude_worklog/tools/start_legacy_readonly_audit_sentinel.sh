#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

SESSION="ai_bot_legacy_readonly_audit_sentinel"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Legacy audit sentinel already running: $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" \
  "cd '$HOME/Desktop/AI BOT REBUILD' && while true; do python3 claude_worklog/tools/legacy_readonly_audit_sentinel.py; sleep 1800; done"

echo "started tmux session: $SESSION"
