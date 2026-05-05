#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

echo
echo "=== EVIDENCE RECONCILIATION ==="
python3 claude_worklog/tools/reconcile_evidence_status.py 2>/dev/null || true

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
echo "=== CLAUDE CODE PLANNER PROFILE ==="
python3 - <<'PY'
import json
from pathlib import Path

p = Path("claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json")
d = json.loads(p.read_text()) if p.exists() else {}
print(f"Claude Code profile: {d.get('claude_code_profile') or 'Max20 consolidated default'}")
print(f"task granularity mode: {d.get('task_granularity_mode') or 'consolidated_default'}")
print(f"planner lane lock enabled: {'yes' if d.get('planner_lane_lock_enabled', False) else 'no'}")
print(f"active lane: {d.get('active_lane') or '-'}")
print(f"active MVP target: {d.get('active_mvp_target') or '-'}")
print(f"current MVP milestone: {d.get('current_mvp_milestone') or '-'}")
print(f"next MVP milestone: {d.get('next_mvp_milestone') or d.get('next_paper_backtest_milestone') or '-'}")
print(f"next paper/backtest milestone: {d.get('next_paper_backtest_milestone') or '-'}")
distance = d.get("distance_to_v2_backtest_and_paper_mvp_ready") or {}
if isinstance(distance, dict):
    print(f"distance to V2_BACKTEST_AND_PAPER_MVP_READY: {distance.get('remaining_count', '-')} milestones remaining")
print(f"legacy evidence consulted: {d.get('legacy_evidence_consulted') or '-'}")
print(f"drift rejection count: {d.get('drift_rejection_count', d.get('rejected_drift_count', 0))}")
print(f"Codex recovery active: {'yes' if d.get('codex_recovery_active', False) else 'no'}")
print(f"split fallback enabled: {'yes' if d.get('split_fallback_enabled', True) else 'no'}")
print(f"quota monitor enabled: {'yes' if d.get('quota_monitor_enabled', True) else 'no'}")
print(f"Codex parallel lane: {d.get('codex_parallel_lane') or 'Codex Pro parallel review/autofix lane'}")
print(f"Codex parallel enabled: {'yes' if d.get('codex_parallel_lane_enabled', True) else 'no'}")
print(f"Codex parallel policy: {d.get('codex_parallel_lane_policy') or 'git_clean_and_no_active_dirty_claude_output'}")
PY

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
