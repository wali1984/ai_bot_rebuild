#!/usr/bin/env bash
set -euo pipefail

UNIT_DST="$HOME/.config/systemd/user"
UNITS=(
  ai-bot-v2-automation-liveness-watchdog.timer
  ai-bot-v2-automation-liveness-watchdog.service
  ai-bot-v2-feature-snapshot-builder.service
  ai-bot-v2-paper-shadow-observation.service
  ai-bot-v2-paper-online-runtime.service
  ai-bot-v2-codex-watchdog.service
  ai-bot-v2-parallel-scheduler.service
  ai-bot-v2-agent-supervisor.service
  ai-bot-v2-worker-porting-orchestrator.service
)

if command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1; then
  for unit in "${UNITS[@]}"; do
    systemctl --user disable --now "$unit" 2>/dev/null || true
  done
  for unit in "${UNITS[@]}"; do
    rm -f "$UNIT_DST/$unit"
  done
  systemctl --user daemon-reload
else
  for unit in "${UNITS[@]}"; do
    rm -f "$UNIT_DST/$unit"
  done
fi

echo "Removed only AI Bot V2 persistent automation user units. Repo files are untouched."
