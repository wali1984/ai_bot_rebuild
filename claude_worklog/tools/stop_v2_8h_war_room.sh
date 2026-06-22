#!/usr/bin/env bash
# Disable + stop the V2 8h war-room timer (no exchange action).
set -euo pipefail

systemctl --user disable --now ai-bot-v2-8h-war-room.timer || true
systemctl --user stop ai-bot-v2-8h-war-room.service || true
systemctl --user daemon-reload || true
