#!/usr/bin/env bash
# Stop + disable the V2 live-canary DRY-RUN timer/service.
# Use this when an operator wants to pause the dry-run schedule.
# Does NOT modify the kill switch; does NOT touch live mode.
set -euo pipefail
systemctl --user disable --now ai-bot-v2-live-canary-dry-run.timer || true
systemctl --user stop ai-bot-v2-live-canary-dry-run.service || true
systemctl --user --no-pager status ai-bot-v2-live-canary-dry-run.timer || true
