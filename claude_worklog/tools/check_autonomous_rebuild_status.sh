#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

echo "=== TIME ==="
date -Is

echo
echo "=== GIT ==="
git status --short
git log --oneline -5

echo
echo "=== MASTER PLANNER ==="
./claude_worklog/tools/status_claude_master_rebuild_planner.sh 2>/dev/null || true

echo
echo "=== SUPERVISOR ==="
./claude_worklog/tools/status_autonomous_agent_supervisor.sh 2>/dev/null || true

echo
echo "=== ACTIVE AGENT PROCESSES ==="
ps -eo pid,ppid,etimes,cmd | grep -E "claude_master_rebuild_planner.py|agent_supervisor.py|claude --print|codex exec|ollama run" | grep -v grep || true

echo
echo "=== MASTER PLANNER STATUS ==="
cat claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json 2>/dev/null || true

echo
echo "=== CURRENT STATUS ==="
cat claude_worklog/agent_supervisor/status/current_status.json 2>/dev/null || true

echo
echo "=== QUEUE STATUS ==="
cat claude_worklog/agent_supervisor/status/queue_status.json 2>/dev/null || true

echo
echo "=== REQUIREMENTS INBOX ==="
find claude_worklog/requirements_inbox -maxdepth 1 -type f -name "*.md" | sort 2>/dev/null || true

echo
echo "=== LATEST EVENTS ==="
tail -n 80 claude_worklog/agent_supervisor/events.jsonl 2>/dev/null || true

echo
echo "=== SEQUENCE STATES ==="
python3 - <<'PY'
import json
from pathlib import Path

task_ids = [
    "015a_repo_package_skeleton",
    "015b_database_migration_skeleton",
    "015c_api_route_skeleton",
    "015d_enterprise_frontend_shell",
    "015e_test_ci_skeleton",
    "015f_agent_dashboard_integration",
    "030_legacy_ingestor_copy_and_hash_inventory",
    "031_dynamic_symbol_universe_foundation",
    "041_feature_snapshot_attribution_pipeline_foundation",
    "042_coinank_uploaded_symbol_alias_fixture",
]

for tid in task_ids:
    p = Path(f"claude_worklog/agent_supervisor/state/tasks/{tid}.json")
    d = json.loads(p.read_text()) if p.exists() else {}
    print(f"{tid}: {d.get('status')} | {d.get('last_summary', '')}")
PY

echo
echo "=== GIT END ==="
git status --short
