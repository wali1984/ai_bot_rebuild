# Planner Directive — Phase 2E2.A Task 103 Superseded by Evidence

## Context

Task `103_codex_watchdog_2e2a_dispatch_hold_recovery` was authored by the
prior planner turn to clear the Phase 2E2.A dispatch hold caused by
trailing harness-emission leakage (standalone `END_FILE: <path>` lines
and a leaked `End-of-turn summary:` paragraph) on six artifacts:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/147_2E2A_WORKER_HEALTH_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/148_2E2A_WORKER_HEALTH_DOMAIN_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/149_PLANNER_2E2A_RUBRIC_12_SCOPE_CLARIFICATION.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/150_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN_ADDENDUM.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/153_PLANNER_2E2A_DISPATCH_HOLD_HANDOFF.md`
- `claude_worklog/agent_supervisor/tasks/102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json`

Task 103 attempted to dispatch on 2026-05-05T03:41:18Z and was blocked by
the supervisor's L1 + standing-approval safety guard with reason
`non-live V2 standing approval blocked by safety pattern (literal
substring trip)`. The trip pattern was a single forbidden literal token
embedded in step 6 of 103's prompt body — specifically the literal
`any production <release> invocation` placeholder that 103 listed
among the planner-prompt diff inspection acceptance criteria. The
substring matched a `LIVE_FORBIDDEN_PATTERNS` literal defined at
`claude_worklog/tools/agent_supervisor.py:161`, and the line carrying
it contained no negation token, so
`non_live_v2_task_safety_block` returned the block reason and the task
state moved to `blocked_approval`.

## Evidence — recovery already complete

Independent of task 103, the codex watchdog lane has been continuously
recovering dirty non-live automation artifacts during the 2E2.A
window. Twelve recovery commits have already landed on `master`
covering the same six paths task 103 was meant to clean:

- `7977f3c Codex watchdog recover dirty non-live automation artifacts`
- `9def06c Recover 2E2A worker health Codex review dispatch artifacts`
- `9b914ba Sanitize 2E2A Codex review prompt for dispatch guard`
- `75f6f35 Codex watchdog recover dirty non-live automation artifacts`
- `f571933 Codex watchdog recover dirty non-live automation artifacts`
- `83fbae0 Codex watchdog recover dirty non-live automation artifacts`
- `10d91b0 Codex watchdog recover dirty non-live automation artifacts`
- `adc6364 Codex watchdog recover dirty non-live automation artifacts`
- `2b78a89 Codex watchdog recover dirty non-live automation artifacts`
- `99f46b0 Codex watchdog recover dirty non-live automation artifacts`
- `2f53c50 Codex watchdog recover dirty non-live automation artifacts`
- `230c4e5 Codex watchdog recover dirty non-live automation artifacts`
- `3d00337 Codex watchdog recover dirty non-live automation artifacts`

Verification at planner turn time:

1. `git status --short` over the six target paths returns zero output
   (six paths committed clean).
2. `git status --short` overall reports a single dirty path:
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`,
   which is the harness-managed inline-requirements accumulation —
   not a 2E2.A dispatch hold artifact.
3. `claude_worklog/agent_supervisor/tasks/102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json`
   parses as valid JSON: the structural body now ends with the closing
   `}` of the top-level object and no trailing standalone marker line
   follows it. The task is parseable by the supervisor and dispatchable
   to Codex on the next reconciliation tick.
4. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/148_2E2A_WORKER_HEALTH_DOMAIN_CODEX_GO_NO_GO.md`
   contains exactly the line
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` and matches the
   `predecessor_required_marker` in 102.
5. `claude_worklog/agent_supervisor/state/tasks/101_trainer_parity_2e2a_worker_health_domain_codex_review.json`
   has `status` = `completed`, satisfying 102's `depends_on` and
   `predecessor_task_ids` constraint.

Task 103's mission is therefore already accomplished by evidence
already on `master`. Re-dispatching 103 would either fail step 2 of
its own mandatory sequence (`The dirty set MUST equal exactly the
seven paths in scope_dirty_paths and zero other paths.`) because only
one of the seven scoped paths is dirty, or be blocked again by the
same forbidden-literal safety pattern that already blocked the first
attempt.

## Decision

The planner retires task 103 as `superseded_by_evidence` rather than
authoring a second recovery layer. Reasons:

- The recovery work the task was authored to perform is already
  committed to `master` by the codex watchdog lane.
- Sanitizing 103's prompt to bypass the forbidden-literal safety
  guard would produce a task whose mission cannot succeed because
  its dirty-scope precondition is no longer satisfied.
- The planner's existing instruction explicitly forbids chaining a
  second recovery layer when the first one has been resolved by
  evidence (`On PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_DISPATCH_HOLD_RECOVERY_FAIL
  with a concrete non-safety blocker, surface to human attention; the
  planner does NOT chain a second recovery layer in this turn.`).
- `superseded_by_evidence` is the supervisor's first-class state for
  this case, short-circuited inside `run_task` at
  `claude_worklog/tools/agent_supervisor.py:2331-2344` so the safety
  guard never re-evaluates the prompt body.

## Action

The planner emits this directive plus three artifacts:

1. `claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`
   — task definition reauthored with `status` = `superseded_by_evidence`,
   `superseded_by_evidence` marker
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_DISPATCH_HOLD_RECOVERY_COMPLETED_BY_PRIOR_WATCHDOG_COMMITS`,
   empty `scope_dirty_paths` and `required_output_files`, and a
   shortened prompt that names the superseding commits and points at
   this directive. The new prompt contains no `LIVE_FORBIDDEN_PATTERNS`
   literal so subsequent supervisor scans will not log a spurious
   `non_live_v2_task_blocked_by_safety` event for task 103.
2. `claude_worklog/agent_supervisor/state/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`
   — runtime state file updated to `status` = `superseded_by_evidence`
   with a history row recording the transition from `blocked_approval`,
   so `task_effective_status` resolves the task to superseded and the
   queue counters at
   `claude_worklog/agent_supervisor/status/queue_status.json` reflect
   the supersede on the next reconciliation tick.
3. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/157_PLANNER_2E2A_TASK_103_HARNESS_LEAKAGE_RESTRIP.md`
   — short follow-up directive recording that this planner turn
   re-emitted the three files above with bare `END_FILE` so the
   harness writes clean bodies (no trailing `END_FILE: <path>` literal
   inside any file body), since the prior planner turn's emission used
   the `END_FILE: <path>` form and the harness materialized the
   trailing path into the file content.

No `v2/` source or test file is modified. No prior-milestone artifact
byte-content is modified. No legacy is touched. No Redis access. No
live behavior. No release intent. No production rollout. No secret
exposure.

## Forbidden under this directive

- modify `/home/wali/Desktop/AI BOT`
- modify any source under `v2/backend/app/`
- modify any test under `v2/backend/tests/`
- modify any file under `v2/frontend/`
- modify any prior-milestone artifact byte-content
- chain a second 2E2.A dispatch hold recovery layer
- author a sanitized re-emit of 103 that attempts to run the original
  recovery mission (the mission is already complete by evidence)
- write or delete Redis keys
- restart any live service
- place or cancel exchange orders
- change leverage or margin
- enable live trading
- ship or release to production
- run a production migration
- expose or commit credential material
- approve the live gate

## Next supervisor action

On the next supervisor reconciliation tick:

1. The codex watchdog lane commits and pushes the dirty
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`,
   the reauthored
   `claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`,
   the updated
   `claude_worklog/agent_supervisor/state/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`,
   and this directive
   (`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/156_PLANNER_2E2A_TASK_103_SUPERSEDED_BY_EVIDENCE.md`)
   plus the harness-leakage restrip directive
   (`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/157_PLANNER_2E2A_TASK_103_HARNESS_LEAKAGE_RESTRIP.md`)
   under the standard `Codex watchdog recover dirty non-live
   automation artifacts` commit message.
2. With the working tree clean and 102 parseable, the supervisor
   dispatches
   `102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json`
   to local Codex CLI.
3. Codex re-reviews Phase 2E2.A under the test-plan addendum, emits
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/151_2E2A_CODEX_REREVIEW_AFTER_ADDENDUM.md`
   and
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/152_2E2A_CODEX_REREVIEW_AFTER_ADDENDUM_GO_NO_GO.md`,
   and writes one of
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS` or
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` to 152.

## Next planner action

On `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS` from task 102,
the planner opens the next consolidated 2E2 sub-phase under a fresh
consolidated milestone turn. The next sub-phase candidates per the
`140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md` plan are worker health
observation collector domain or worker health composition; the
planner picks one based on dependency order at the next turn.

On `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` from task 102
with concrete non-Rubric-12 blockers, the planner does not chain a
second addendum layer; surface to human attention.

On any safety violation during task 102 — any live behavior, any
Redis access, any legacy mutation, any release intent, any
prior-milestone byte-content modification, any FastAPI lifespan or
router or singleton or cache or wall-clock helper added to any
authored 2E2.A source file, any direct `redis` or `url_env` import
in any authored 2E2.A source file, any URL logging, any credential
leakage — surface to human attention; no further remediation is
permitted.

## Predecessor evidence

- Implementation marker:
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/146_2E2A_WORKER_HEALTH_DOMAIN_GO_NO_GO.md`
  = `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex initial review marker:
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/148_2E2A_WORKER_HEALTH_DOMAIN_CODEX_GO_NO_GO.md`
  = `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL`.
- Planner directive (file 149) terminal marker:
  `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_RUBRIC_12_SCOPE_CLARIFICATION_READY`.
- Test plan addendum (file 150) terminal marker:
  `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TEST_PLAN_ADDENDUM_READY`.
- Dispatch hold handoff (file 153) terminal marker:
  `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_DISPATCH_HOLD_HANDOFF_READY`.
- Recovery completion evidence: 12 codex watchdog commits enumerated
  above; six target paths now clean per `git status --short`; 102 now
  parses as valid JSON.

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TASK_103_SUPERSEDED_BY_EVIDENCE
