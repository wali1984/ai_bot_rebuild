#!/usr/bin/env bash
# Print status of the V2 FastAPI backend.
set -euo pipefail
echo "--- TIMER/UNIT ---"
systemctl --user --no-pager status ai-bot-v2-public-website-backend.service || true
echo
echo "--- HEALTH PROBE ---"
HOST="${V2_BACKEND_HOST:-127.0.0.1}"
PORT="${V2_BACKEND_PORT:-8000}"
for path in /api/v1/_meta/agent-health /api/v1/_meta/queue-status /api/v1/_meta/build-status; do
    printf "GET %s ... " "$path"
    code=$(curl -sS -o /tmp/v2-backend-resp -w "%{http_code}" "http://${HOST}:${PORT}${path}" --max-time 5 || echo "000")
    echo "HTTP $code"
done
