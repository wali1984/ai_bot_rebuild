#!/usr/bin/env bash
set -euo pipefail

SESSION="ai_bot_claude_master_rebuild_planner"
ROOT="$HOME/Desktop/AI BOT REBUILD"
CMD="python3 claude_worklog/tools/claude_master_rebuild_planner.py --daemon --poll-seconds 120"
QUOTA_STATUS="$ROOT/claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required to start Claude master rebuild planner." >&2
  exit 2
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already running: $SESSION"
  exit 0
fi

if [ -f "$QUOTA_STATUS" ] && grep -q "blocked_or_limited" "$QUOTA_STATUS"; then
  echo "Claude quota blocked; not starting $SESSION. Codex takeover remains active until quota reset."
  exit 0
fi

tmux new-session -d -s "$SESSION" "cd '$ROOT' && $CMD"
echo "started tmux session: $SESSION"
