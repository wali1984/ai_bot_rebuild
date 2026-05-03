# Codex Planner Halt Loop Diagnostic

Task: `075_codex_readonly_planner_halt_loop_diagnostic`
Date: 2026-05-03
Mode: read-only diagnostic except this report and GO/NO-GO file.

## Diagnosis

The halt/reaffirmation/noop/standby loop is primarily a missing current-dispatch bridge hook combined with a planner prompt/runtime artifact issue.

The current Claude master planner path in `claude_worklog/tools/claude_master_rebuild_planner.py` only auto-dispatches task ids returned by `ready_to_fire_task_ids()` or ids freshly materialized in the same Claude stdout. `ready_to_fire_task_ids()` is hard-coded to the original task `060_trainer_parity_2e1c_alpha_implementation` path and the split-060 recovery sequence (`060b`, then `060c`). It has no bridge for the currently actionable tasks called out by the planner artifacts: `061_trainer_parity_2e1c_alpha_local_validation` and `069_decision_explainability_2ha0_lineage_inventory`.

Once task 060 and the split recovery tasks were superseded/completed, `ready_to_fire_task_ids()` returned no work. `run_once()` then invoked Claude again instead of dispatching the next marker-ready supervisor tasks. Claude obeyed the prompt's `BEGIN_FILE` output policy and kept materializing allowed control-plane markdown: pass checkpoints and then repeated `master_planner_halt_reaffirmation_2026_05_03.md` updates. The latest `master_rebuild_planner_status.json` confirms this pattern: returncode 0, materialized only `claude_worklog/autonomous_control_plane/master_planner_halt_reaffirmation_2026_05_03.md`, generated no task ids, and ran no supervisor task results.

## Classified Causes

| Candidate | Classification | Evidence |
| --- | --- | --- |
| Missing dispatch bridge hook | Primary cause | `claude_master_rebuild_planner.py` has `READY_TO_FIRE_TASKS` only for `060`, plus split-060 logic. No general scan bridges marker-ready pending tasks such as `061` or `069`. |
| Planner prompt runtime artifact issue | Primary amplifier | `run_once()` calls `claude --print` whenever no hard-coded ready task exists. The prompt requires `BEGIN_FILE` output and permits `claude_worklog/autonomous_control_plane/`, so held-state explanations become real files on every pass. |
| Stale evidence wire | Contributing bug | Task `061` expects `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`, while the actual current marker in `46_2E1C_ALPHA_GO_NO_GO.md` is `PHASE2E1C_ALPHA_TRAINER_LIVENESS_READY_FOR_LOCAL_VALIDATION`. Planner directives treat the latter as ready. |
| Superseded task queue noise | Contributing bug | `reconcile_evidence_status.py` marks `060`, `060c`, old trainer liveness Codex tasks, etc. superseded, but task definitions still show stale `status` values and `queue_status.json` still reports old pending task `031` as next pending. |
| Git dirty guard | Secondary blocker, not root cause | The bridge's `substantive_git_dirty()` would block dispatch after untracked control-plane artifacts appear. Current looping occurs before any current-task bridge is attempted. Claude artifacts also explicitly self-halt on the dirty doc-only set. |
| Active child guard | Not evidenced as root cause | Active-child checks only run inside the dispatch bridge. Latest planner status shows no bridge result, so this guard was not reached for the repeated halt materializations. |
| Quota guard conflict | Not evidenced as current cause | Latest planner returncode is 0 with stderr 0. No current `blocked_quota` in queue status. Historical quota/retry signals existed during earlier task failures but do not explain the current file materialization loop. |

## Additional Supervisor Findings

`agent_supervisor.py` does not enforce `predecessor_required_marker` or `predecessor_required_marker_file` in `dependency_blockers()` or `run_task()`. It only checks `depends_on`. This is risky in both directions:

- A marker-ready task is not discovered by marker logic; it is just another pending task in lexical/priority order.
- A marker-gated task can be selected even if its marker is absent, because marker fields are ignored.

This explains why the planner artifacts can state "dispatch 061/069" while the supervisor queue reports `031_codex_review_phase2_symbol_universe` as next pending. The queue is ordered by pending task files and dependencies, not by planner marker gates.

## Safe Remediation Plan

1. Add marker-gate support to `agent_supervisor.py`.
   - Implement a `predecessor_marker_blockers(task)` helper.
   - Treat missing marker file or missing marker string as `blocked_dependency`.
   - Include marker blockers in `select_next_task_file()`, `write_health_and_queue()`, and `run_task()`.
   - Keep the change non-live and limited to supervisor scheduling/status logic.

2. Add a current-task dispatch bridge to `claude_master_rebuild_planner.py`.
   - Scan pending supervisor tasks for satisfied `predecessor_required_marker_file` + marker.
   - Exclude completed, running, superseded, failed, cancelled, auth/approval blocked, human-attention tasks, and deferred retry/quota tasks.
   - Prefer explicit current-lane tasks (`061`, `069`) over stale low-number pending work.
   - Reuse `dispatch_approved_supervisor_task()` so existing standing approval, forbidden-action, active-child, dead-lock, and git-dirty guards remain in force.

3. Correct the stale 061 marker wire.
   - Either update task `061` to expect `PHASE2E1C_ALPHA_TRAINER_LIVENESS_READY_FOR_LOCAL_VALIDATION`, or update the marker-producing evidence file only through a separate approved remediation if that marker name is truly wrong.
   - The evidence already on disk supports updating task metadata/prompt expectations, not changing runtime/domain code.

4. Stop materializing held-state control-plane noise.
   - In `claude_master_rebuild_planner.py`, before invoking Claude, detect the state "no current dispatchable task, no new requirement, no changed trigger marker" and update status only.
   - Do not call Claude just to reaffirm a prior halt.
   - Optionally allow one tracked status file update under runtime/status, not a new or appended autonomous-control-plane artifact.

5. Reconcile queue noise in a dedicated cleanup task.
   - Extend evidence reconciliation to stale pending task families that are already superseded by committed PASS evidence.
   - Surface stale-but-not-runnable tasks separately from `next_pending_task`.
   - Do not delete task definitions; update runtime state only unless a later explicit cleanup task authorizes doc/task metadata changes.

6. Handle the dirty doc-only set intentionally.
   - Commit or archive the existing doc-only control-plane artifacts before bridge dispatch, or update the bridge's dirty policy only if the operator wants doc-only control-plane churn ignored.
   - Do not broaden the dirty allowlist until halt materialization suppression is in place, or the loop will hide itself rather than stop.

## Go / No-Go

Diagnostic is ready. Remediation should be implemented in a separate non-live autofix task scoped to `claude_worklog/tools/`, supervisor task metadata/status reconciliation, and doc-only control-plane hygiene. Do not restart services, write Redis, run live trainer, or enable live trading.
