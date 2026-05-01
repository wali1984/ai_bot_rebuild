# 01 — Agent Supervisor Reliability Hardening Requirements

## Objective
Harden the supervisor before any V2 scaffold implementation build begins. This is reliability and governance hardening only.

## Required architectural changes
1. Separate task definitions from runtime task state completely.
2. Add task state directory:
   - claude_worklog/agent_supervisor/state/tasks/<task_id>.json
3. Task JSON files under tasks/ become stable definitions only.
4. Runtime status files remain:
   - status/current_status.json (latest state)
   - status/queue_status.json (queue summary)
   - events.jsonl (append-only event stream)

## Heartbeat requirements
Create heartbeat file:
- claude_worklog/agent_supervisor/status/supervisor_heartbeat.json

Heartbeat MUST include:
- pid
- tmux session
- loop count
- last_loop_ts
- current_task
- last_event_ts

## Process-safety requirements
1. Lockfile required:
   - claude_worklog/agent_supervisor/supervisor.lock
2. Duplicate daemon protection required.
3. Stale running task detection required.
4. No-event-for-N-minutes detection required.
5. No-output-growth-for-N-minutes detection required.
6. Child process timeout detection required.
7. Quota/auth failure detection required.
8. human_attention_required classification required.

## Retry policy requirements
Safe retry policy MUST include:
- max_attempts
- retry_count
- resume_after_utc
- retry reason

## Dashboard requirements
Dashboard MUST surface stale-state alerts, including:
- stale running task
- no-event timeout
- no-output-growth timeout
- quota/auth blocked
- human_attention_required

## Packet review loop requirements
Reliability loop MUST include:
- hourly packet review
- daily packet review
- critical alert review

## Governance and runtime safety
- L4/L5 approval gate remains hard stop.
- No live bot mutation.
- No runtime changes to /home/wali/Desktop/AI BOT.
- No Redis writes/deletes.

AGENT_SUPERVISOR_RELIABILITY_REQUIREMENTS_READY
