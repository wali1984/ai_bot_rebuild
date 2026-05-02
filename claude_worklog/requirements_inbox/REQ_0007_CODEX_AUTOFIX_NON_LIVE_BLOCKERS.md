# Requirement 0007 — Codex Autofix for Non-Live V2 Blockers

Codex should be allowed to fix its own non-live V2 review blockers automatically.

## Objective

Reduce manual intervention when Codex identifies concrete blockers in non-live V2 code/docs/tests.

## Allowed Codex autofix scope

Codex may modify:
- v2/
- claude_worklog/phase2_core_rebuild/
- claude_worklog/v2_scaffold_reviews/
- claude_worklog/security/
- claude_worklog/agent_supervisor/tasks/

Codex may:
- patch non-live V2 code
- patch tests
- patch validation docs
- patch review/remediation reports
- create follow-up task definitions
- rerun tests through supervisor
- produce remediation artifacts
- request re-review

## Forbidden

Codex may never:
- modify /home/wali/Desktop/AI BOT
- write Redis
- delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- run production migrations
- expose secrets
- commit secret values

## Required loop

When Codex review fails:
1. Capture blockers.
2. Create Codex autofix task.
3. Patch only allowed paths.
4. Run validation.
5. Run high-confidence secret scan.
6. Commit/push remediation.
7. Run Codex re-review.
8. Continue only if PASS.

## Required events

- codex_autofix_task_created
- codex_autofix_started
- codex_autofix_completed
- codex_autofix_validation_failed
- codex_autofix_safety_blocked
- codex_autofix_rereview_passed
- codex_autofix_rereview_failed

## Stop conditions

Stop for:
- live/legacy/Redis/exchange/deploy attempt
- secret scan failure
- repeated Codex failure after max attempts
- L4/L5 behavior
- ambiguous blocker requiring human decision

REQ_CODEX_AUTOFIX_NON_LIVE_BLOCKERS_READY
