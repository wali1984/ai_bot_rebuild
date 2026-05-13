#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/wali/Desktop/AI BOT REBUILD"
UNIT_SRC="$ROOT/claude_worklog/systemd/user"
UNIT_DST="$HOME/.config/systemd/user"
SERVICES=(
  ai-bot-v2-worker-porting-orchestrator.service
  ai-bot-v2-agent-supervisor.service
  ai-bot-v2-parallel-scheduler.service
  ai-bot-v2-codex-watchdog.service
  ai-bot-v2-paper-online-runtime.service
  ai-bot-v2-paper-shadow-observation.service
  ai-bot-v2-feature-snapshot-builder.service
)
TIMERS=(ai-bot-v2-automation-liveness-watchdog.timer)

cd "$ROOT"

systemd_user_available() {
  command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1
}

if ! systemd_user_available; then
  echo "SYSTEMD_USER_UNAVAILABLE_TMUX_FALLBACK"
  echo "Systemd user services are not available in this session; starting the tmux fallback."
  exec bash "$ROOT/claude_worklog/tools/start_v2_worker_porting_control_plane.sh"
fi

mkdir -p "$UNIT_DST"
cp "$UNIT_SRC"/ai-bot-v2-*.service "$UNIT_SRC"/ai-bot-v2-*.timer "$UNIT_DST"/
systemctl --user daemon-reload

for unit in "${SERVICES[@]}"; do
  systemctl --user enable "$unit"
done
for timer in "${TIMERS[@]}"; do
  systemctl --user enable "$timer"
done

for unit in "${SERVICES[@]}"; do
  systemctl --user start "$unit"
done
for timer in "${TIMERS[@]}"; do
  systemctl --user start "$timer"
done

if command -v loginctl >/dev/null 2>&1; then
  linger="$(loginctl show-user "$USER" -p Linger 2>/dev/null || true)"
  echo "login_linger_status=${linger:-unknown}"
  echo "To keep services alive after logout, run from a normal terminal if policy allows:"
  echo "  loginctl enable-linger \"$USER\""
fi

bash "$ROOT/claude_worklog/tools/status_v2_persistent_automation_services.sh"
