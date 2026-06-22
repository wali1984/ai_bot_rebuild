#!/usr/bin/env bash
# Start the V2 FastAPI backend under uvicorn.
#
# This script is read-only with respect to external services:
# - it does not touch the legacy bot tree
# - it does not start any live ingestor
# - it does not write to legacy Redis keys
# - it does not enable live trading
#
# The backend serves the public website + admin payloads consumed
# by the V2 frontend. Routes under /api/v1 and /api/v2 are mounted
# from claude_worklog/v2_scaffold_planning. The live-block guard
# already rejects any live-trading endpoint at request time; this
# script ships no override.
set -euo pipefail

REBUILD_ROOT="/home/wali/Desktop/AI BOT REBUILD"
BACKEND_DIR="$REBUILD_ROOT/v2/backend"
VENV_PY="$REBUILD_ROOT/.venv/bin/python3"

# Defaults — operator can override via env. REDIS_URL is read-only
# from V2's perspective (the backend only reads v2:* prefixed keys
# and never writes legacy namespaces).
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export LEGACY_REDIS_URL="${LEGACY_REDIS_URL:-redis://localhost:6379/0}"
export V2_REDIS_PREFIX="${V2_REDIS_PREFIX:-v2:}"
export V2_MODE="${V2_MODE:-paper}"
export LIVE_GATE="${LIVE_GATE:-blocked_human_only}"
export PYTHONPATH="$BACKEND_DIR"

UVICORN_HOST="${V2_BACKEND_HOST:-127.0.0.1}"
UVICORN_PORT="${V2_BACKEND_PORT:-8000}"
UVICORN_WORKERS="${V2_BACKEND_WORKERS:-1}"

cd "$BACKEND_DIR"

exec "$VENV_PY" -m uvicorn \
    app.main:create_app \
    --factory \
    --host "$UVICORN_HOST" \
    --port "$UVICORN_PORT" \
    --workers "$UVICORN_WORKERS" \
    --proxy-headers \
    --forwarded-allow-ips "127.0.0.1" \
    --log-level info
