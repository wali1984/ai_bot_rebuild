#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

SESSION="ai_bot_historical_pnl_trade_audit"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Historical PnL audit sentinel already running: $SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" \
  "cd '$HOME/Desktop/AI BOT REBUILD' && while true; do DAYS=30 BINANCE_FLAG=\${BINANCE_FLAG:-0} SYMBOLS=\"\${SYMBOLS:-}\" ./claude_worklog/tools/run_historical_pnl_trade_audit_once.sh; sleep 21600; done"

echo "started tmux session: $SESSION"
