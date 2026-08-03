#!/usr/bin/env bash
# install_guardian_watchdog.sh — Install systemd user units for the Capital Guardian resume loop.
# Run as the wali user (no sudo needed for --user systemd units).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SYSTEMD_SRC="$REPO_ROOT/v2/tools/systemd"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
GOAL_DIR="$REPO_ROOT/goal_state/V2_CLAUDE_CONTINUOUS_ADVERSARIAL_VALIDATION_AND_CAPITAL_PRODUCTIVITY_GUARDIAN"

echo "Installing Claude Capital Guardian watchdog..."
echo "  Source:  $SYSTEMD_SRC"
echo "  Target:  $SYSTEMD_USER_DIR"

mkdir -p "$SYSTEMD_USER_DIR"

cp "$SYSTEMD_SRC/claude-guardian.service" "$SYSTEMD_USER_DIR/"
cp "$SYSTEMD_SRC/claude-guardian.timer"   "$SYSTEMD_USER_DIR/"

systemctl --user daemon-reload
systemctl --user enable  claude-guardian.timer
systemctl --user start   claude-guardian.timer

echo ""
echo "Guardian watchdog installed and started."
echo "  Timer fires every 30 minutes."
echo "  Log: $GOAL_DIR/guardian_autorun.log"
echo ""
echo "To check status:"
echo "  systemctl --user status claude-guardian.timer"
echo "  systemctl --user status claude-guardian.service"
echo ""
echo "To disable:"
echo "  systemctl --user disable --now claude-guardian.timer"
