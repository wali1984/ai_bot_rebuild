#!/usr/bin/env bash
set -u

cd "$HOME/Desktop/AI BOT REBUILD" || exit 1

echo "=== legacy audit sentinel tmux ==="
tmux ls | grep ai_bot_legacy_readonly_audit_sentinel || echo "LEGACY_AUDIT_SENTINEL_NOT_RUNNING"

echo
echo "=== latest audit marker ==="
cat claude_worklog/legacy_readonly_audit/10_GO_NO_GO.md 2>/dev/null || true

echo
echo "=== latest audit files ==="
ls -lh claude_worklog/legacy_readonly_audit 2>/dev/null || true
