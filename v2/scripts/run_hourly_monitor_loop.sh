#!/usr/bin/env bash
# V2 Continuous Hourly Monitor Loop
# Runs v2_continuous_hourly_monitor.py every INTERVAL_SECONDS (default 3600).
# Writes 9 final artifacts to raw_evidence/ each cycle.
# Idempotent: safe to run while paper_online_runtime is running.
# No exchange mutation. No legacy Redis writes.
# Gate: blocked_human_only

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${REPO_ROOT}/.venv/bin/python3"
MONITOR="${REPO_ROOT}/v2/backend/app/cli/v2_continuous_hourly_monitor.py"
OUTPUT_DIR="${REPO_ROOT}/raw_evidence"
REDIS_URL="${V2_REDIS_URL:-redis://localhost:6379/0}"
WINDOWS="${HOURLY_WINDOWS:-3}"
INTERVAL_SECONDS="${HOURLY_MONITOR_INTERVAL:-3600}"
LOG_FILE="/tmp/v2_hourly_monitor.log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] hourly monitor loop start: interval=${INTERVAL_SECONDS}s windows=${WINDOWS}" | tee -a "$LOG_FILE"

while true; do
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] running hourly monitor..." | tee -a "$LOG_FILE"
    "$VENV" "$MONITOR" \
        --windows "$WINDOWS" \
        --output-dir "$OUTPUT_DIR" \
        --redis-url "$REDIS_URL" \
        2>&1 | tee -a "$LOG_FILE" || true
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] hourly monitor done, sleeping ${INTERVAL_SECONDS}s..." | tee -a "$LOG_FILE"
    sleep "$INTERVAL_SECONDS"
done
