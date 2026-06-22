#!/usr/bin/env bash
# Stop the V2 FastAPI backend. Idempotent.
set -euo pipefail
systemctl --user disable --now ai-bot-v2-public-website-backend.service || true
systemctl --user --no-pager status ai-bot-v2-public-website-backend.service || true
