# Requirement 0011 — Parallel Codex Review and Autofix Lane

Codex Pro capacity should be used in parallel with Claude Code Max20.

## Objective

Reduce serial bottlenecks by letting Codex continuously review, test, and fix non-live V2 blockers while Claude Code continues planning/building.

## Role split

Claude Code:
- planner
- architect
- primary builder
- requirement interpreter
- implementation generator

Codex:
- adversarial reviewer
- concrete blocker fixer
- test hardener
- safety auditor
- regression detector
- Codex re-review authority

Ollama:
- summarization
- evidence compression
- log/context summaries

Copilot:
- terminal/status operator only

## Allowed Codex parallel scope

Codex may modify:
- v2/
- claude_worklog/phase2_core_rebuild/
- claude_worklog/v2_scaffold_reviews/
- claude_worklog/security/
- claude_worklog/agent_supervisor/tasks/
- claude_worklog/tools/ only for safety/status/review tooling

## Forbidden

Codex may never:
- modify /home/wali/Desktop/AI BOT
- write/delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets

## Parallel operating loop

For each active Claude milestone:

1. Claude builds milestone N.
2. Codex reviews completed milestone N-1 or current staged output if safe.
3. If Codex finds concrete blockers, create Codex autofix task.
4. Codex patches only allowed non-live paths.
5. Run validation and high-confidence secret scan.
6. Commit/push remediation.
7. Run Codex re-review.
8. Mark PASS before planner advances.

## Codex should proactively review

- trainer liveness implementation
- trainer parity service
- feature attribution contracts
- risk gateway
- trader fleet paper adapter
- paper/shadow pipeline
- frontend explainability pages
- safety gates
- queue/planner/supervisor automation

## Stop conditions

Stop for:
- live/legacy/Redis/exchange/deploy attempt
- secret scan failure
- repeated Codex failure after max attempts
- ambiguous product/strategy decision
- L4/L5 action
- final live approval

REQ_PARALLEL_CODEX_REVIEW_AND_AUTOFIX_LANE_READY
