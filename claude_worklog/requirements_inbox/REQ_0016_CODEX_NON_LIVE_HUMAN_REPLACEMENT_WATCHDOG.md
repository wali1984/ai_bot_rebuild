# Requirement 0016 - Codex Non-Live Human-Replacement Watchdog

Codex must replace the human operator for routine non-live status checking, recovery, cleanup, remediation, and continuation.

## Objective

The system must stop asking the human to inspect dashboard/status and manually recover every non-live automation issue.

Codex should continuously monitor AI BOT REBUILD and automatically fix all non-live blockers.

## Codex authority

Codex has full authority inside AI BOT REBUILD for non-live work.

Codex may:
- inspect statuses
- inspect git dirty state
- inspect stdout/stderr
- inspect runtime state
- inspect task definitions
- inspect GO/NO-GO markers
- fix dirty-tree dispatch holds
- fix planner no-progress loops
- fix stale queue/current_status/dashboard noise
- fix path/materialization mismatches
- recover BEGIN_FILE outputs
- patch safe path remap rules
- patch task prompts
- patch supervisor/planner/dashboard scripts
- patch V2 code
- patch tests
- patch docs
- run validation
- run high-confidence secret scans
- commit/push
- run Codex review/re-review
- restart the master planner when clean
- continue until final live gate

## Codex must pause only for hard forbidden gates

Codex must stop and request human only for:
- final live trading approval
- modifying `/home/wali/Desktop/AI BOT`
- Redis write/delete
- live service restart
- exchange/order/leverage/margin action
- deployment / production migration
- secret exposure or committed secret
- L4/L5 action requiring human approval
- ambiguous trading/business decision that cannot be inferred safely

## Operating loop

Every cycle:
1. Check active processes.
2. If Claude/Codex child is active, monitor only unless safety violation appears.
3. If no child and git is dirty, classify dirty files.
4. Restore runtime prompt noise.
5. Archive planner no-progress/noop/standby notes.
6. Validate generated task JSON/docs.
7. Remove standalone END_FILE leakage.
8. Secret scan.
9. Commit durable artifacts.
10. If human_attention_required exists, create/run Codex recovery.
11. If dispatch bridge is blocked by git_dirty, clean/commit and restart.
12. If stale queue/status conflicts with PASS evidence, reconcile evidence.
13. If current task ready and git clean, dispatch/restart planner.
14. Repeat until final live gate.

## Required events

- codex_watchdog_cycle_started
- codex_watchdog_monitor_only_active_child
- codex_watchdog_dirty_tree_recovered
- codex_watchdog_human_attention_recovered
- codex_watchdog_dispatch_hold_recovered
- codex_watchdog_restarted_planner
- codex_watchdog_paused_for_live_gate
- codex_watchdog_paused_for_safety

REQ_CODEX_NON_LIVE_HUMAN_REPLACEMENT_WATCHDOG_READY
