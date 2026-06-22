#!/usr/bin/env bash
# Install (but do NOT auto-enable) the user-mode systemd unit for the
# V2 Report Center indexer. The operator must explicitly enable the
# timer when they decide to switch on the 60-second indexer cadence.
#
# Safety: copies the unit files into ~/.config/systemd/user/ and runs
# ``systemctl --user daemon-reload``. It does NOT enable, start, or
# alter any existing service or timer. It does NOT touch the legacy
# bot, Redis, the exchange, or any live/canary/shutdown state.
set -euo pipefail

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$DEST_DIR"

UNITS=(
  "ai-bot-v2-report-center-indexer.service"
  "ai-bot-v2-report-center-indexer.timer"
)

for u in "${UNITS[@]}"; do
  install -m 0644 "$SRC_DIR/$u" "$DEST_DIR/$u"
  echo "installed: $DEST_DIR/$u"
done

systemctl --user daemon-reload || true

cat <<'EOF'

NEXT STEPS (manual; operator-only):

  # Enable + start the report-center indexer timer (every 60 seconds):
  systemctl --user enable --now ai-bot-v2-report-center-indexer.timer

  # Inspect:
  systemctl --user list-timers | grep ai-bot-v2-report-center
  journalctl --user -u ai-bot-v2-report-center-indexer.service -n 50

This installer never enables timers itself. The operator must explicitly opt in.
EOF
