#!/usr/bin/env bash
set -euo pipefail

SESSION="ai_bot_historical_pnl_trade_audit"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION"
  echo "stopped tmux session: $SESSION"
else
  echo "no tmux session: $SESSION"
fi
