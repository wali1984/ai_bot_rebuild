#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/wali/Desktop/AI BOT REBUILD"
UNITS=(
  ai-bot-v2-worker-porting-orchestrator.service
  ai-bot-v2-agent-supervisor.service
  ai-bot-v2-parallel-scheduler.service
  ai-bot-v2-codex-watchdog.service
  ai-bot-v2-paper-online-runtime.service
  ai-bot-v2-paper-shadow-observation.service
  ai-bot-v2-feature-snapshot-builder.service
  ai-bot-v2-trainer-bridge.service
  ai-bot-v2-automation-liveness-watchdog.timer
)

cd "$ROOT"

if ! command -v systemctl >/dev/null 2>&1 || ! systemctl --user is-system-running >/dev/null 2>&1; then
  echo "SYSTEMD_USER_UNAVAILABLE_TMUX_FALLBACK"
  exec bash "$ROOT/claude_worklog/tools/start_v2_worker_porting_control_plane.sh"
fi

systemctl --user daemon-reload
for unit in "${UNITS[@]}"; do
  systemctl --user start "$unit"
done

bash "$ROOT/claude_worklog/tools/status_v2_persistent_automation_services.sh"
