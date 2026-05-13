# Automation Utilization Policy

Generated: 2026-05-13T03:04:28.450818+00:00

## Current Status
- Classification: IDLE_EXPECTED_BREAK
- Active child count: 0
- Files changed: 209
- Next action: always_on_objective_runner selects/dispatches next safe primary task
- Latest commit observed: 4cb00e0 Remediate CoinAnk Plan3 runtime contract

## Required Classifications
- ACTIVE_OK
- IDLE_EXPECTED_BREAK
- IDLE_RATE_LIMIT
- IDLE_AUTH
- IDLE_GIT_DIRTY_ACTIVE_TASK
- IDLE_GIT_DIRTY_UNKNOWN
- IDLE_NO_TASK_SELECTED
- IDLE_DISPATCH_FAILURE
- IDLE_QUEUE_STALE
- IDLE_BLOCKED_HUMAN_FINAL_GATE
- IDLE_UNACCEPTABLE

## Enforcement
Claude idle for more than 15 minutes with incomplete primary work and no blocker is unacceptable. Codex idle for more than 30 minutes while safe audits exist is unacceptable. The objective runner must select or create safe primary/audit work unless the final live/capital gate requires human approval.

Detailed status: `automation_utilization_status.json`.
