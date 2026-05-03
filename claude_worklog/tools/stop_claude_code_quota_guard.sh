#!/usr/bin/env bash
set -euo pipefail

SESSION="ai_bot_claude_code_quota_guard"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed." >&2
  exit 0
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION"
  echo "stopped tmux session: $SESSION"
else
  echo "tmux session not running: $SESSION"
fi
