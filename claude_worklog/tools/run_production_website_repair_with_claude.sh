#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/Desktop/AI BOT REBUILD"
cd "$ROOT"

echo "production_website_repair: repository=$ROOT"
echo "production_website_repair: dirty_state_begin"
git status --short || true

python3 claude_worklog/tools/crawl_dashboard_routes.py --kind both

(
  cd v2/frontend
  npm run build:operator-truth
  npm run sync:proof-artifacts
  npm run typecheck
  npm run build
)

python3 -m v2.backend.app.cli.production_website_full_rebuild

echo "production_website_repair: completed without legacy mutation, old Redis writes, exchange actions, or live enablement"
