# Requirement 0025 - Codex High-Utilization Review Queue

## Objective

Use Codex Pro/Max capacity aggressively and safely. Codex must not sit idle while non-live V2 work remains.

## Target behavior

Codex should continuously run useful non-live work:

- parallel read-only reviews
- test-hardening audits
- safety audits
- evidence-reconciliation audits
- legacy-evidence usage audits
- historical PnL/trade integration audits
- autofix tasks when safe
- Codex re-reviews after autofix

## Utilization target

If Codex usage is below 50% in a 5-hour build window and work remains, the scheduler should create more safe Codex review/audit tasks.

This is a target, not permission to bypass safety.

## Codex task types

### Read-only review tasks

Allowed while Claude is active.

Must write only to isolated report paths:

- `claude_worklog/codex_parallel_reviews/`

Must not modify:

- `v2/`
- task definitions
- planner/supervisor code
- active dirty files

### Autofix tasks

Allowed only when:

- no Claude/Codex child is active
- Git is clean or dirty state is fully classified
- blocker is non-live
- patch paths are inside AI BOT REBUILD

### Re-review tasks

Allowed after autofix or milestone completion.

## Review backlog

Codex should maintain a backlog for:

- trainer prediction output
- orchestrator decision
- risk gateway
- paper execution ledger
- replay/backtest runner
- paper mode
- shadow readiness
- decision explainability
- historical PnL/trade audit
- legacy read-only audit usage
- website/data-contract readiness
- stale evidence reconciliation
- no-live-side-effect safety

## Hard safety

Codex may never:

- modify `/home/wali/Desktop/AI BOT`
- write/delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets

REQ_CODEX_HIGH_UTILIZATION_REVIEW_QUEUE_READY
