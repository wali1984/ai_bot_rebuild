#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

echo "=== planner_status.json ==="
cat claude_worklog/agent_supervisor/status/planner_status.json 2>/dev/null || echo "missing"

echo
echo "=== current_status.json ==="
cat claude_worklog/agent_supervisor/status/current_status.json 2>/dev/null || echo "missing"

echo
echo "=== queue_status.json ==="
cat claude_worklog/agent_supervisor/status/queue_status.json 2>/dev/null || echo "missing"

echo
echo "=== latest events (tail 20) ==="
tail -n 20 claude_worklog/agent_supervisor/events.jsonl 2>/dev/null || echo "missing"

echo
echo "=== git status --short ==="
git status --short
