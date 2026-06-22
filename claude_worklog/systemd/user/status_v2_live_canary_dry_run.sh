#!/usr/bin/env bash
# Print status of the V2 live-canary DRY-RUN timer/service.
set -euo pipefail
echo "--- TIMER ---"
systemctl --user --no-pager status ai-bot-v2-live-canary-dry-run.timer || true
echo "--- SERVICE (last run) ---"
systemctl --user --no-pager status ai-bot-v2-live-canary-dry-run.service || true
echo "--- TIMER LIST ---"
systemctl --user list-timers --all | grep -E "dry-run|NEXT" || true
