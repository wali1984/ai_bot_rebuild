#!/usr/bin/env bash
# run_daily_backtests.sh -- Periodic backtest scheduler.
# Runs V2 backtests for BTCUSDT/ETHUSDT/SOLUSDT on 1h and 4h timeframes.
#
# SAFE: never places exchange orders, never mutates trading state.
# All writes go to v2:backtest:* Redis namespace only.
#
# Usage: ./run_daily_backtests.sh
# Cron:  0 1 * * * PATH_TO_THIS_SCRIPT >> /tmp/v2_backtests.log 2>&1

set -euo pipefail

REBUILD_ROOT="/home/wali/Desktop/AI BOT REBUILD"
BACKEND_DIR="$REBUILD_ROOT/v2/backend"
VENV_PY="$REBUILD_ROOT/.venv/bin/python3"

export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export PYTHONPATH="$BACKEND_DIR"

SYMBOLS=(BTCUSDT ETHUSDT SOLUSDT)
TIMEFRAMES=(1h 4h)
LOOKBACK=100

ts() { date -u "+%Y-%m-%dT%H:%M:%SZ" ; }

echo "[bt_scheduler] Start: $(ts)"

FAIL=0
for SYM in "${SYMBOLS[@]}"; do
    for TF in "${TIMEFRAMES[@]}"; do
        echo "[bt_scheduler] symbol=$SYM timeframe=$TF"
        if "$VENV_PY" -m app.cli.v2_backtest_runner \
               --symbol "$SYM" \
               --timeframe "$TF" \
               --lookback-candles "$LOOKBACK" \
               2>&1 | tail -n 5; then
            echo "[bt_scheduler] OK: $SYM $TF"
        else
            echo "[bt_scheduler] FAIL: $SYM $TF"
            FAIL=1
        fi
    done
done

echo "[bt_scheduler] Done: $(ts) fail=$FAIL"
exit "$FAIL"
