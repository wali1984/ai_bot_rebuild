#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

DAYS="${DAYS:-30}"
SYMBOLS="${SYMBOLS:-}"
BINANCE_FLAG="${BINANCE_FLAG:-}"

if [ "$BINANCE_FLAG" = "1" ]; then
  python3 claude_worklog/tools/historical_pnl_trade_audit.py --days "$DAYS" --symbols "$SYMBOLS" --binance
else
  python3 claude_worklog/tools/historical_pnl_trade_audit.py --days "$DAYS" --symbols "$SYMBOLS"
fi
