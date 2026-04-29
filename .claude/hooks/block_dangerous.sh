#!/usr/bin/env bash
set -euo pipefail

payload="$(cat || true)"

blocked_patterns=(
  "futures_create_order"
  "futures_change_leverage"
  "futures_change_margin_type"
  "futures_change_position_mode"
  "create_order"
  "cancel_order"
  "python .*trading/trader.py"
  "python .*hybrid_trainer.py.*live"
  "python .*live"
  "redis-cli DEL"
  "redis-cli XDEL"
  "redis-cli XTRIM"
  "redis-cli FLUSHALL"
  "redis-cli FLUSHDB"
  "../AI BOT/"
  "chmod .*../AI BOT"
  "rm -rf .*AI BOT"
)

for pattern in "${blocked_patterns[@]}"; do
  if echo "$payload" | grep -Eiq "$pattern"; then
    echo "BLOCKED dangerous Claude Code action: $pattern"
    exit 2
  fi
done

exit 0
