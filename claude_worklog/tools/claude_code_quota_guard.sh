#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/Desktop/AI BOT REBUILD"

STATUS="claude_worklog/quota/CLAUDE_CODE_QUOTA_GUARD_STATUS.md"
LOG="claude_worklog/quota/CLAUDE_CODE_QUOTA_GUARD.log"
READY_INTERVAL_SECONDS="${CLAUDE_CODE_QUOTA_READY_INTERVAL_SECONDS:-18000}"
BLOCKED_INTERVAL_SECONDS="${CLAUDE_CODE_QUOTA_BLOCKED_INTERVAL_SECONDS:-600}"
SUPERVISOR_POLL_SECONDS="${CLAUDE_CODE_QUOTA_SUPERVISOR_POLL_SECONDS:-120}"

mkdir -p claude_worklog/quota

write_status() {
  local state="$1"
  local action="$2"
  local detail="$3"
  cat > "$STATUS" <<EOF
# Claude Code Quota Guard Status

Generated: $(date -Is)

State:
$state

Last action:
$action

Detail:
$detail

Cadence:
- ready_probe_seconds: $READY_INTERVAL_SECONDS
- blocked_probe_seconds: $BLOCKED_INTERVAL_SECONDS
- supervisor_poll_seconds: $SUPERVISOR_POLL_SECONDS

Safety:
- planner may be stopped on blocked_or_limited
- planner may restart only when Claude Code probe is ready
- no legacy bot, Redis, live service, exchange, deploy, or live trading action is allowed

CLAUDE_CODE_QUOTA_GUARD_STATUS_RECORDED
EOF
}

log() {
  echo "$(date -Is) $*" >> "$LOG"
}

planner_running() {
  tmux has-session -t ai_bot_claude_master_rebuild_planner 2>/dev/null
}

start_planner_if_clean() {
  local dirty
  dirty="$(git status --short | grep -Ev 'claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt|claude_worklog/quota/CLAUDE_CODE_QUOTA_(CHECK|GUARD|STATUS)' || true)"
  if [ -n "$dirty" ]; then
    write_status "ready_but_git_dirty" "planner_not_started" "$dirty"
    log "planner_not_started git_dirty"
    return 1
  fi

  if planner_running; then
    write_status "ready" "planner_already_running" "Claude Code ready; planner already running."
    return 0
  fi

  ./claude_worklog/tools/start_claude_master_rebuild_planner.sh >/dev/null 2>&1 || true
  write_status "ready" "planner_started" "Claude Code ready; planner start requested."
  log "planner_started"
}

stop_planner_for_quota() {
  ./claude_worklog/tools/stop_claude_master_rebuild_planner.sh >/dev/null 2>&1 || true
  write_status "blocked_or_limited" "planner_stopped" "Claude Code appears blocked or limited."
  log "planner_stopped_for_quota"
}

probe_claude_ready() {
  ./claude_worklog/tools/check_claude_code_quota_status.sh >/dev/null 2>&1 || true
  grep -q '^ready$' claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md 2>/dev/null
}

supervisor_reports_quota_block() {
  grep -Riq '"blocked_quota"\\|"status": "blocked_quota"\\|blocked_or_limited' \
    claude_worklog/agent_supervisor/status \
    claude_worklog/agent_supervisor/state/tasks \
    2>/dev/null
}

last_ready_probe=0
blocked_mode=0
write_status "starting" "guard_started" "Starting Claude Code quota guard."
log "guard_started"

while true; do
  now="$(date +%s)"

  if supervisor_reports_quota_block; then
    blocked_mode=1
    stop_planner_for_quota
  fi

  if [ "$blocked_mode" = "1" ]; then
    if probe_claude_ready; then
      blocked_mode=0
      last_ready_probe="$now"
      start_planner_if_clean || true
    else
      stop_planner_for_quota
      sleep "$BLOCKED_INTERVAL_SECONDS"
      continue
    fi
  elif [ $((now - last_ready_probe)) -ge "$READY_INTERVAL_SECONDS" ]; then
    if probe_claude_ready; then
      last_ready_probe="$now"
      start_planner_if_clean || true
    else
      blocked_mode=1
      stop_planner_for_quota
      sleep "$BLOCKED_INTERVAL_SECONDS"
      continue
    fi
  elif planner_running; then
    write_status "monitoring" "planner_running" "Next ready probe in $((READY_INTERVAL_SECONDS - (now - last_ready_probe))) seconds."
  else
    write_status "monitoring" "planner_stopped_between_probes" "Waiting for next ready probe."
  fi

  sleep "$SUPERVISOR_POLL_SECONDS"
done
