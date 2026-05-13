#!/usr/bin/env bash
# Report status of the worker-porting control plane.
# Primary persistence is the systemd user service layer; tmux is fallback only.
set -euo pipefail

ROOT="$HOME/Desktop/AI BOT REBUILD"
cd "$ROOT"

if [ -x "$ROOT/claude_worklog/tools/status_v2_persistent_automation_services.sh" ]; then
  echo "=== systemd-primary V2 automation status ==="
  bash "$ROOT/claude_worklog/tools/status_v2_persistent_automation_services.sh"
  echo
  echo "=== tmux fallback status ==="
fi

echo "=== live gate state ==="
test -f "claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md" && echo "WARNING: final approval token present" || echo "no final approval token"
test -f "claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md" && echo "WARNING: Redis trim approval present" || echo "no Redis trim approval"

echo
echo "=== tmux sessions ==="
tmux list-sessions 2>/dev/null | grep -E "ai_bot_worker_porting_orchestrator|ai_bot_agent_supervisor|ai_bot_parallel_scheduler|ai_bot_codex_watchdog" || echo "(no control-plane tmux sessions alive)"

echo
echo "=== active processes ==="
ps -eo pid,etimes,cmd --no-headers \
  | grep -E "v2_worker_porting_orchestrator|agent_supervisor.py|parallel_capacity_scheduler|codex_non_live_watchdog" \
  | grep -v "grep -E" || echo "(no daemons in ps)"

echo
echo "=== last 5 orchestrator log lines ==="
tail -5 claude_worklog/agent_supervisor/logs/control_plane/v2_worker_porting_orchestrator.log 2>/dev/null || echo "(no orchestrator log)"

echo
echo "=== current worker porting snapshot ==="
if [ -f "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/operator_dashboard_payload.json" ]; then
  .venv/bin/python3 -c "
import json
d = json.load(open('claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/operator_dashboard_payload.json'))
keys = ['live_gate','final_approval_token','current_worker','last_completed_worker','progress_p0','progress_p1','progress_p2','v2_local_online_state','git_corruption_detected']
for k in keys:
    print(f'  {k}: {d.get(k)}')
print('  next_action:', d.get('next_action', {}).get('kind'))
"
else
  echo "(no orchestrator state file yet — run --once)"
fi
