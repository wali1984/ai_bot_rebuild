#!/usr/bin/env bash
# Install (but do NOT auto-enable) the user-mode systemd units for the
# V2 autonomous full-rebuild self-healing controller and the pending-task
# watchdog. The operator must explicitly enable the timers when they
# decide to switch on the automation cadence.
#
# Safety: this script only copies unit files into ~/.config/systemd/user/
# and runs ``systemctl --user daemon-reload``. It does NOT enable, start,
# or alter any existing service or timer. It does NOT touch the legacy
# bot, Redis, the exchange, or any live/canary/shutdown state.
set -euo pipefail

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$DEST_DIR"

UNITS=(
  "ai-bot-v2-autonomous-full-rebuild-self-healing-controller.service"
  "ai-bot-v2-autonomous-full-rebuild-self-healing-controller.timer"
  "ai-bot-v2-pending-task-watchdog.service"
  "ai-bot-v2-pending-task-watchdog.timer"
  "ai-bot-v2-executive-command-center.service"
  "ai-bot-v2-executive-command-center.timer"
)

for u in "${UNITS[@]}"; do
  install -m 0644 "$SRC_DIR/$u" "$DEST_DIR/$u"
  echo "installed: $DEST_DIR/$u"
done

systemctl --user daemon-reload || true

cat <<'EOF'

NEXT STEPS (manual; operator-only):

  # Enable + start the controller timer (every 5 minutes):
  systemctl --user enable --now ai-bot-v2-autonomous-full-rebuild-self-healing-controller.timer

  # Enable + start the watchdog timer (every 2 minutes):
  systemctl --user enable --now ai-bot-v2-pending-task-watchdog.timer

  # Enable + start the executive command center timer (every 15 minutes):
  systemctl --user enable --now ai-bot-v2-executive-command-center.timer

  # Inspect status:
  systemctl --user list-timers | grep ai-bot-v2
  journalctl --user -u ai-bot-v2-autonomous-full-rebuild-self-healing-controller.service -n 50
  journalctl --user -u ai-bot-v2-pending-task-watchdog.service -n 50

This installer never enables timers itself. The operator must explicitly
opt in.
EOF
