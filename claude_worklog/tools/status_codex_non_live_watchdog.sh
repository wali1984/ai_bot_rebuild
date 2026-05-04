#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

echo "=== codex watchdog tmux ==="
tmux ls | grep ai_bot_codex_non_live_watchdog || echo "CODEX_WATCHDOG_NOT_RUNNING"

echo
echo "=== agent processes ==="
ps -eo pid,ppid,etimes,cmd | grep -E "codex_non_live_watchdog.py|claude_master_rebuild_planner.py|agent_supervisor.py|claude --print|codex exec|ollama run" | grep -v grep || true

echo
echo "=== latest watchdog events ==="
grep -nE "codex_watchdog" claude_worklog/agent_supervisor/events.jsonl 2>/dev/null | tail -50 || true

echo
echo "=== git ==="
git status --short
