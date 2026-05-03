#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

echo "=== tmux ==="
tmux ls 2>/dev/null | grep -E "ai_bot_claude_code_quota_guard|ai_bot_claude_master_rebuild_planner" || true

echo
echo "=== active processes ==="
ps -eo pid,ppid,etimes,cmd | grep -E "claude_code_quota_guard.sh|claude_master_rebuild_planner.py|claude --print|agent_supervisor.py" | grep -v grep || true

echo
echo "=== quota guard status ==="
cat claude_worklog/quota/CLAUDE_CODE_QUOTA_GUARD_STATUS.md 2>/dev/null || true

echo
echo "=== quota probe status ==="
cat claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md 2>/dev/null || true

echo
echo "=== quota guard log tail ==="
tail -n 40 claude_worklog/quota/CLAUDE_CODE_QUOTA_GUARD.log 2>/dev/null || true
