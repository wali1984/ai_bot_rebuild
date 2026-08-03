#!/usr/bin/env bash
# Enable + start the V2 8h war-room user timer.
# Paper/shadow only. Never enables live trading.
set -euo pipefail

REPO_ROOT="/home/wali/Desktop/AI BOT REBUILD"
UNIT_DIR_SRC="$REPO_ROOT/claude_worklog/systemd/user"
UNIT_DIR_DST="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR_DST"
for unit in ai-bot-v2-8h-war-room.service ai-bot-v2-8h-war-room.timer; do
  src="$UNIT_DIR_SRC/$unit"
  dst="$UNIT_DIR_DST/$unit"
  if [ ! -L "$dst" ] || [ "$(readlink -f "$dst")" != "$src" ]; then
    ln -sf "$src" "$dst"
  fi
done

systemctl --user daemon-reload
systemctl --user enable --now ai-bot-v2-8h-war-room.timer
systemctl --user list-timers --all | grep -E "ai-bot-v2-8h-war-room" || true
