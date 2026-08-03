#!/usr/bin/env bash
# One-command backend deploy: sync repo v2/backend into the current release and
# restart the public backend. Frontend deploys still go through the full
# release build; this covers API/source truth updates only.
set -euo pipefail
REPO="/home/wali/Desktop/AI BOT REBUILD"
RELEASE="/home/wali/releases/nervyx-one/current"
rsync -a --delete \
  --exclude "__pycache__" --exclude "*.pyc" --exclude ".pytest_cache" \
  "$REPO/v2/backend/app/" "$RELEASE/v2/backend/app/"
cd "$RELEASE/v2/backend"
"$REPO/.venv/bin/python3" -c "import sys; sys.path.insert(0,'.'); import app.main; print('release import OK')"
systemctl --user restart ai-bot-v2-public-website-backend.service
sleep 5
systemctl --user is-active ai-bot-v2-public-website-backend.service
curl -s -o /dev/null -w "paper/runtime-status -> %{http_code}\n" http://127.0.0.1:8000/api/v2/paper/runtime-status
curl -s -o /dev/null -w "mobile/summary -> %{http_code}\n" http://127.0.0.1:8000/api/v2/mobile/summary
