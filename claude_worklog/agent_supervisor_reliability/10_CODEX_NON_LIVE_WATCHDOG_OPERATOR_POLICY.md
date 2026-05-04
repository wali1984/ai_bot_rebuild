# Codex Non-Live Watchdog Operator Policy

## Purpose

Codex replaces the human operator for all routine non-live recovery and continuation work.

## Non-live issues Codex must fix automatically

- dirty-tree dispatch holds
- generated planner artifacts pending commit
- END_FILE marker leakage
- invalid generated task JSON
- stale queue/current_status/dashboard views
- evidence-wire gaps
- superseded task execution attempts
- human_attention_required from path mismatch
- human_attention_required from missing materialization
- Claude emit-format failures
- Codex FAIL remediation
- planner no-progress/noop/halt loops
- dead supervisor lock
- live-root false positives inside AI BOT REBUILD
- quota pause/restart handling
- stale runtime prompt files

## Codex may modify

- v2/
- claude_worklog/tools/
- claude_worklog/agent_supervisor/
- claude_worklog/agent_supervisor_reliability/
- claude_worklog/phase2_core_rebuild/
- claude_worklog/security/
- claude_worklog/autonomous_control_plane/
- claude_worklog/requirements_inbox/

## Codex may never modify

- /home/wali/Desktop/AI BOT

## Codex may never perform

- Redis writes/deletes
- live service restarts
- exchange actions
- leverage/margin changes
- deployment
- production migrations
- live trading enablement
- secret exposure

## Stop condition

The only normal endpoint is:

FINAL_LIVE_GATE_REQUIRES_HUMAN_APPROVAL

CODEX_NON_LIVE_WATCHDOG_OPERATOR_POLICY_READY
