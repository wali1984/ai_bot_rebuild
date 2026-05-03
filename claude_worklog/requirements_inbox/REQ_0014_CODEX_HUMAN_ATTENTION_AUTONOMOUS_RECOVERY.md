# Requirement 0014 — Codex Autonomous Recovery for Non-Live Human Attention

Codex is granted full authority to resolve `human_attention_required` states inside the non-live AI BOT REBUILD project.

## Objective

Stop requiring human intervention for recoverable non-live blockers.

Codex may inspect, patch, validate, commit, push, and re-review any non-live rebuild blocker that enters `human_attention_required`, as long as all hard safety boundaries remain intact.

## Authority granted

For non-live V2 rebuild work, Codex may:

- inspect failed task stdout/stderr
- inspect runtime state
- inspect task definitions
- inspect generated files
- recover safe path mismatches
- patch task prompts
- patch implementation code
- patch tests
- patch documentation
- patch validation logs
- patch planner/supervisor reliability code
- patch safe path remap rules
- create recovery task definitions
- run local validation
- run high-confidence secret scans
- commit and push safe fixes
- run Codex re-review
- mark stale tasks as superseded by evidence
- restart the master planner only after clean validation

## Allowed paths

Codex may modify:

- `v2/`
- `claude_worklog/tools/`
- `claude_worklog/agent_supervisor/`
- `claude_worklog/phase2_core_rebuild/`
- `claude_worklog/v2_scaffold_reviews/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor_reliability/`

## Absolute forbidden actions

Codex may never:

- modify `/home/wali/Desktop/AI BOT`
- write Redis
- delete Redis keys
- restart live trainer/trader/orchestrator/Redis/VPN
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- run production migrations
- expose secrets
- commit secrets
- bypass final live approval
- perform L4/L5 actions without explicit human approval

## Live gate

Final live trading remains human-only.

Codex may prepare live-readiness reports, but may not approve or enable live trading.

## Human attention recovery loop

When a task becomes `human_attention_required`:

1. Codex diagnoses the failure.
2. Codex classifies it:
   - path mismatch
   - prompt/emit failure
   - validation failure
   - stale runtime state
   - Codex blocker
   - quota/auth issue
   - safety issue
3. If non-live and safe, Codex fixes it.
4. Codex validates.
5. Codex secret-scans.
6. Codex commits/pushes.
7. Codex runs re-review.
8. Planner continues.

## Stop conditions

Codex must stop and leave human_attention_required only if:

- live action is requested
- legacy mutation is required
- Redis write/delete is required
- service restart is required
- exchange action is required
- deployment is required
- secret scan fails
- ambiguous trading/business decision requires human judgment
- final live approval is requested

REQ_CODEX_HUMAN_ATTENTION_AUTONOMOUS_RECOVERY_READY
