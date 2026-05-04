# Requirement 0015 — Planner-Level Human Attention Codex Autorecovery

Codex autonomous recovery must also handle master-planner-level `human_attention_required` states, not only supervisor task failures.

## Objective

Eliminate manual intervention when the master planner blocks on a safe non-live materialization, dispatch, evidence, stale-state, or allowlist issue inside AI BOT REBUILD.

## Trigger

If all conditions are true:

- `master_rebuild_planner_status.json` has `human_attention_required = true`
- no active Claude/Codex/Ollama child is running
- blocked reason is one of:
  - planner materialization refusal
  - safe generated-doc path refusal
  - safe generated-task path refusal
  - dispatch bridge gap
  - stale evidence/state conflict
  - END_FILE marker leakage
  - safe path remap gap
- dirty files are inside allowed AI BOT REBUILD paths
- no live/legacy/Redis/exchange/deploy/secret issue is present

then the supervisor/planner should automatically create and dispatch a Codex recovery task.

## Allowed recovery scope

Codex may inspect, patch, validate, commit, push, and re-review non-live planner-level blockers under:

- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/phase2_core_rebuild/`
- `claude_worklog/agent_supervisor_reliability/`
- `claude_worklog/security/`
- `claude_worklog/tools/` for recovery tooling only
- `v2/` only if the recovery explicitly concerns already-approved non-live V2 implementation artifacts

## Required behavior

For planner-level human attention:

1. Snapshot status and dirty files.
2. Classify the blocker.
3. If safe and non-live, create a narrow Codex recovery task.
4. Run Codex recovery.
5. Validate JSON/docs/code as applicable.
6. Remove standalone END_FILE marker leakage only in the recovery scope.
7. Run high-confidence secret scan.
8. Commit and push safe recovery artifacts.
9. Restart planner only from a clean repository.

## Forbidden

Codex may never:

- modify `/home/wali/Desktop/AI BOT`
- write or delete Redis keys
- restart live services
- place or cancel orders
- change leverage or margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets
- bypass final live approval

## Stop conditions

Leave `human_attention_required` unresolved and stop if the blocker involves:

- live action
- legacy mutation
- Redis write/delete
- service restart
- exchange action
- deployment
- secret scan failure
- ambiguous business/trading decision
- L4/L5 action
- final live approval

REQ_PLANNER_LEVEL_HUMAN_ATTENTION_CODEX_AUTORECOVERY_READY
