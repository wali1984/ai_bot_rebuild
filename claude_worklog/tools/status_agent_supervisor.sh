#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

echo "=== current_status.json ==="
sed -n '1,220p' claude_worklog/agent_supervisor/status/current_status.json 2>/dev/null || echo "missing"

echo "=== queue_status.json ==="
sed -n '1,240p' claude_worklog/agent_supervisor/status/queue_status.json 2>/dev/null || echo "missing"

echo "=== last 20 events ==="
tail -n 20 claude_worklog/agent_supervisor/events.jsonl 2>/dev/null || echo "missing"

echo "=== git status --short ==="
git status --short