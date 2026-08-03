#!/usr/bin/env bash
# Operator-run installer for new ingestor units (Fable goal, 2026-07-06).
# Santiment unit removed by operator directive 2026-07-16.
# Whale-walls intel loop added 2026-07-16 (native orderbook-derived lane,
# extracted from the removed combined AICoin free-tier worker).
set -euo pipefail
cd "$(dirname "$0")"
install -m 0644 ai-bot-v2-agg-trades-ingestor-loop.service ~/.config/systemd/user/
install -m 0644 ai-bot-v2-whale-walls-intel-loop.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-bot-v2-agg-trades-ingestor-loop.service ai-bot-v2-whale-walls-intel-loop.service
systemctl --user status ai-bot-v2-agg-trades-ingestor-loop.service ai-bot-v2-whale-walls-intel-loop.service --no-pager | head -30
