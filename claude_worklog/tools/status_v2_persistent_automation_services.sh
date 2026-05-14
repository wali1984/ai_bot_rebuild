#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/wali/Desktop/AI BOT REBUILD"
UNITS=(
  ai-bot-v2-worker-porting-orchestrator.service
  ai-bot-v2-agent-supervisor.service
  ai-bot-v2-parallel-scheduler.service
  ai-bot-v2-codex-watchdog.service
  ai-bot-v2-paper-online-runtime.service
  ai-bot-v2-paper-shadow-observation.service
  ai-bot-v2-feature-snapshot-builder.service
  ai-bot-v2-trainer-bridge.service
  ai-bot-v2-automation-liveness-watchdog.timer
)

cd "$ROOT"

echo "=== V2 persistent automation services ==="
if command -v systemctl >/dev/null 2>&1 && systemctl --user is-system-running >/dev/null 2>&1; then
  for unit in "${UNITS[@]}"; do
    printf '%-55s %s\n' "$unit" "$(systemctl --user is-active "$unit" 2>/dev/null || true)"
  done
else
  echo "SYSTEMD_USER_UNAVAILABLE_TMUX_FALLBACK"
fi

echo
echo "=== active processes ==="
ps -eo pid,ppid,etimes,cmd --no-headers \
  | grep -E "v2_worker_porting_orchestrator|agent_supervisor.py|parallel_capacity_scheduler|codex_non_live_watchdog|paper_online_runtime|paper_shadow_observation|v2_feature_snapshot_builder|v2_trainer_bridge" \
  | grep -v "sleep 900" \
  | grep -v "sleep 65" \
  | grep -v "grep -E" || echo "(no V2 automation processes found)"

echo
echo "=== current worker snapshot ==="
if [ -f "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json" ]; then
  ./.venv/bin/python3 - <<'PY'
import json
from pathlib import Path

data = json.loads(Path("claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json").read_text())
for key in [
    "next_worker",
    "in_flight_workers",
    "last_completed_worker",
    "live_gate",
    "final_approval_token",
    "redis_trim_approval",
    "git_corruption_detected",
]:
    print(f"{key}: {data.get(key)}")
next_action = data.get("next_action")
print("next_action:", next_action.get("kind") if isinstance(next_action, dict) else next_action)
PY
else
  echo "(worker porting state not found)"
fi

echo
echo "=== approval markers ==="
test -f claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md && echo "final approval token: present" || echo "final approval token: absent"
test -f claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md && echo "Redis trim approval: present" || echo "Redis trim approval: absent"

echo
echo "=== latest control-plane logs ==="
for log in \
  claude_worklog/agent_supervisor/logs/control_plane/v2_worker_porting_orchestrator.log \
  claude_worklog/agent_supervisor/logs/control_plane/agent_supervisor.log \
  claude_worklog/agent_supervisor/logs/control_plane/parallel_capacity_scheduler.log \
  claude_worklog/agent_supervisor/logs/control_plane/codex_non_live_watchdog.log \
  claude_worklog/agent_supervisor/logs/control_plane/v2_automation_liveness_watchdog.log; do
  echo "--- $log"
  tail -5 "$log" 2>/dev/null || echo "(no log yet)"
done
