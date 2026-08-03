#!/usr/bin/env bash
# Install (and optionally enable/start) the V2 parallel Spark automation service.
#
# Safety: copies the unit file into ~/.config/systemd/user/ and reloads systemd.
# Does not alter live/canary/trader settings.
set -euo pipefail

SRC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

ENABLE_NOW=0
if [[ "${1:-}" == "--enable" ]]; then
  ENABLE_NOW=1
elif [[ "${1:-}" == "--enable-now" ]]; then
  ENABLE_NOW=1
fi

mkdir -p "$DEST_DIR"

UNIT="ai-bot-v2-parallel-spark-automation.service"
install -m 0644 "$SRC_DIR/$UNIT" "$DEST_DIR/$UNIT"

echo "installed: $DEST_DIR/$UNIT"

echo "reloading user systemd"
systemctl --user daemon-reload || true

if [[ "$ENABLE_NOW" == "1" ]]; then
  echo "enabling and starting $UNIT"
  systemctl --user enable --now "$UNIT"
  echo "
status:"
  systemctl --user status "$UNIT" --no-pager | sed -n '1,20p'
  echo "
recent logs:"
  journalctl --user -u "$UNIT" -n 40 --no-pager
else
  echo "
Installed only. To start it:

  systemctl --user enable --now $UNIT
"
fi
