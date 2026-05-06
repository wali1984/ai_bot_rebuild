#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

echo "=== historical pnl audit tmux ==="
tmux ls | grep ai_bot_historical_pnl_trade_audit || echo "HISTORICAL_PNL_AUDIT_NOT_RUNNING"

echo
echo "=== latest marker ==="
cat claude_worklog/historical_pnl_audit/10_GO_NO_GO.md 2>/dev/null || true

echo
echo "=== latest files ==="
ls -lh claude_worklog/historical_pnl_audit 2>/dev/null || true
