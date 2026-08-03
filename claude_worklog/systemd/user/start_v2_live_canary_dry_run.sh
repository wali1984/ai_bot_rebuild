#!/usr/bin/env bash
# Symlink + enable + start the V2 live-canary DRY-RUN timer.
# This script NEVER enables live trading; it only schedules the
# dry-run executor (FakeExchangeAdapter, dry_run=true, live_enabled=false)
# on a 60s cadence.
#
# Idempotent: safe to re-run after edits to the unit file.
set -euo pipefail

UNIT_DIR_SRC="/home/wali/Desktop/AI BOT REBUILD/claude_worklog/systemd/user"
UNIT_DIR_DST="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR_DST"

for unit in \
    ai-bot-v2-live-canary-dry-run.service \
    ai-bot-v2-live-canary-dry-run.timer
do
    src="$UNIT_DIR_SRC/$unit"
    dst="$UNIT_DIR_DST/$unit"
    if [[ ! -L "$dst" ]] || [[ "$(readlink "$dst")" != "$src" ]]; then
        ln -sfn "$src" "$dst"
        echo "linked $unit"
    fi
done

systemctl --user daemon-reload
systemctl --user enable --now ai-bot-v2-live-canary-dry-run.timer
systemctl --user --no-pager status ai-bot-v2-live-canary-dry-run.timer || true
