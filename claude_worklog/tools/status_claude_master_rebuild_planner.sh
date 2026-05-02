#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

SESSION="ai_bot_claude_master_rebuild_planner"

echo "=== tmux ==="
if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "running: $SESSION"
else
  echo "not running: $SESSION"
fi

echo "=== active processes ==="
ps -eo pid,ppid,etimes,cmd | grep -E "claude_master_rebuild_planner.py|agent_supervisor.py|claude --print|codex exec|ollama run" | grep -v grep || true

echo "=== master planner status ==="
cat claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json 2>/dev/null || true

echo "=== queue status ==="
cat claude_worklog/agent_supervisor/status/queue_status.json 2>/dev/null || true

echo "=== current status ==="
cat claude_worklog/agent_supervisor/status/current_status.json 2>/dev/null || true

echo "=== unprocessed requirements ==="
python3 - <<'PY'
import json
from pathlib import Path

root = Path("claude_worklog/requirements_inbox")
processed_path = Path("claude_worklog/agent_supervisor/runtime/master_planner/processed_requirements.json")
processed = {}
if processed_path.exists():
    processed = (json.loads(processed_path.read_text()).get("processed") or {})

for p in sorted(root.glob("REQ_*.md")):
    if p.name not in processed:
        print(p.name)
PY

echo "=== git ==="
git status --short
git log --oneline -5
