#!/usr/bin/env bash
# Operator-run installer for the two new ingestor units (Fable goal, 2026-07-06).
set -euo pipefail
cd "$(dirname "$0")"
install -m 0644 ai-bot-v2-agg-trades-ingestor-loop.service ~/.config/systemd/user/
install -m 0644 ai-bot-v2-santiment-pro-ingestor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-bot-v2-agg-trades-ingestor-loop.service ai-bot-v2-santiment-pro-ingestor.service
systemctl --user status ai-bot-v2-agg-trades-ingestor-loop.service ai-bot-v2-santiment-pro-ingestor.service --no-pager | head -20
