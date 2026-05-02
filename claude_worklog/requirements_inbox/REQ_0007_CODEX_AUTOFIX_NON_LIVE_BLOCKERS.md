# Requirement 0007 — Codex Autofix for Non-Live V2 Blockers

Codex may automatically fix concrete non-live V2 blockers that Codex itself identifies.

Allowed scope:
- v2/
- claude_worklog/phase2_core_rebuild/
- claude_worklog/v2_scaffold_reviews/
- claude_worklog/security/
- claude_worklog/agent_supervisor/tasks/

Allowed actions:
- patch non-live V2 code
- patch tests
- patch validation docs
- patch remediation/review reports
- create follow-up task definitions
- run validation through supervisor
- run high-confidence secret scans
- commit/push safe remediation artifacts
- request Codex re-review

Forbidden:
- modify /home/wali/Desktop/AI BOT
- write/delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets

Required loop:
Claude implements → Codex reviews → if Codex FAIL, Codex autofix may patch allowed paths → validation → secret scan → commit/push → Codex re-review → continue only if PASS.

Stop conditions:
- live/legacy/Redis/exchange/deploy attempt
- secret scan failure
- repeated Codex failure after max attempts
- L4/L5 behavior
- ambiguous blocker requiring human decision

REQ_CODEX_AUTOFIX_NON_LIVE_BLOCKERS_READY
