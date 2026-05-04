#!/usr/bin/env bash
set -euo pipefail

SESSION="ai_bot_codex_non_live_watchdog"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION"
  echo "stopped tmux session: $SESSION"
else
  echo "no tmux session: $SESSION"
fi
