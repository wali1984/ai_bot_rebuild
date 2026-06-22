#!/usr/bin/env bash
# Status snapshot for the V2 8h war-room daemon.
set -euo pipefail

REPO_ROOT="/home/wali/Desktop/AI BOT REBUILD"

echo "=== timer ==="
systemctl --user is-active ai-bot-v2-8h-war-room.timer || true
systemctl --user is-enabled ai-bot-v2-8h-war-room.timer || true

echo "=== service ==="
systemctl --user is-active ai-bot-v2-8h-war-room.service || true
systemctl --user is-enabled ai-bot-v2-8h-war-room.service || true

echo "=== timer schedule ==="
systemctl --user list-timers --all | grep -E "ai-bot-v2-8h-war-room" || true

echo "=== heartbeat ==="
redis-cli TTL v2:war_room:heartbeat || true
redis-cli GET v2:war_room:heartbeat | head -c 600 || true
echo

echo "=== latest status JSON ==="
ls -la "$REPO_ROOT/claude_worklog/final_readiness/v2_8h_war_room/latest/v2_8h_war_room_status.json" 2>/dev/null || true

echo "=== latest cycle log tail ==="
tail -n 20 "$REPO_ROOT/claude_worklog/agent_supervisor/logs/control_plane/v2_8h_war_room.log" 2>/dev/null || true
