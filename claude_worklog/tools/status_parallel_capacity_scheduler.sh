#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

echo "=== parallel capacity scheduler tmux ==="
tmux ls | grep ai_bot_parallel_capacity_scheduler || echo "PARALLEL_CAPACITY_SCHEDULER_NOT_RUNNING"

echo
echo "=== lane processes ==="
ps -eo pid,ppid,etimes,cmd | grep -E "parallel_capacity_scheduler.py|codex_non_live_watchdog.py|claude_master_rebuild_planner.py|agent_supervisor.py --task-id|claude --print|codex exec|ollama run" | grep -v grep || true

echo
echo "=== scheduler status ==="
cat claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json 2>/dev/null || echo "NO_SCHEDULER_STATUS"

echo
echo "=== latest scheduler events ==="
grep -nE "parallel_capacity_scheduler" claude_worklog/agent_supervisor/events.jsonl 2>/dev/null | tail -50 || true

echo
echo "=== latest watchdog events ==="
grep -nE "codex_watchdog" claude_worklog/agent_supervisor/events.jsonl 2>/dev/null | tail -30 || true

echo
echo "=== git ==="
git status --short
