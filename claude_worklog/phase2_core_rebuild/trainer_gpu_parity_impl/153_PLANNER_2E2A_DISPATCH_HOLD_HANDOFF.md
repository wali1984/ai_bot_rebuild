# Planner Directive — Phase 2E2.A Dispatch Hold Handoff to Codex Watchdog

## Context

The prior planner turn emitted three files to remediate the Phase 2E2.A
Rubric 12 scope inconsistency surfaced by Codex review marker
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` in
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/148_2E2A_WORKER_HEALTH_DOMAIN_CODEX_GO_NO_GO.md`:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/149_PLANNER_2E2A_RUBRIC_12_SCOPE_CLARIFICATION.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/150_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN_ADDENDUM.md`
- `claude_worklog/agent_supervisor/tasks/102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json`

The harness materialized those files but did not strip the trailing
`END_FILE: <path>` boundary marker lines from the file bodies. The
leakage is:

- `149_PLANNER_2E2A_RUBRIC_12_SCOPE_CLARIFICATION.md` contains a
  trailing standalone `END_FILE: <its own path>` line after its
  intended terminal marker
  `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_RUBRIC_12_SCOPE_CLARIFICATION_READY`.
- `150_PHASE_2E2A_WORKER_HEALTH_DOMAIN_TEST_PLAN_ADDENDUM.md` contains
  a trailing standalone `END_FILE: <its own path>` line after its
  intended terminal marker
  `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TEST_PLAN_ADDENDUM_READY`.
- `102_trainer_parity_2e2a_codex_rereview_after_test_plan_addendum.json`
  contains a trailing `END_FILE: <its own path>` line and a leaked
  `End-of-turn summary: ...` paragraph AFTER the closing `}` of the
  top-level JSON object. Standard `json.load` raises
  `json.JSONDecodeError` on the trailing content. Task 102 is
  therefore unparseable by the supervisor in its current state and
  cannot be dispatched.

## Decision

The planner hands the cleanup off to the codex watchdog under
REQ_0014, REQ_0015, and REQ_0016 authority. The watchdog operating
loop directly addresses this case:

- step 7: "Remove standalone END_FILE leakage."
- step 11: "If dispatch bridge is blocked by git_dirty, clean/commit
  and restart."

No `v2/` source or test files are modified. No prior-milestone source
or test files are modified. No legacy is touched. No Redis access. No
live behavior. No release intent. No deployment. No secret exposure.

## Action

The planner emits this directive plus
`claude_worklog/agent_supervisor/tasks/103_codex_watchdog_2e2a_dispatch_hold_recovery.json`
— a narrow codex watchdog task that:

1. Confirms the dirty file scope.
2. Strips harness-emission leakage (trailing standalone `END_FILE:
   <host-path>` marker lines and any content after the structural end
   of a JSON file) from 147, 148, 149, 150, and 102 if present.
3. Validates that 102 and 103 parse as JSON.
4. Runs a high-confidence secret scan over the dirty paths.
5. Inspects the dirty edit to
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`,
   verifies the diff touches no `v2/` source, no live behavior, no
   Redis/legacy/exchange/deploy/secret patterns, and commits it
   alongside the recovered 2E2.A artifacts only if the diff is safe.
6. Commits all cleaned dirty paths on the current branch with explicit
   `git add` by name (no `git add -A`/`-.`).
7. Pushes the recovery commit to `origin`.
8. Emits
   `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/154_CODEX_WATCHDOG_2E2A_DISPATCH_HOLD_RECOVERY_REPORT.md`
   with cleanup actions, JSON validation, secret scan, planner-prompt
   diff verdict, commit SHA, push result, and safety review.

## Forbidden under this handoff

- modify `/home/wali/Desktop/AI BOT`
- modify any source under `v2/backend/app/`
- modify any test under `v2/backend/tests/`
- modify any file under `v2/frontend/`
- modify any prior-milestone artifact byte-content (only trailing
  harness leakage may be truncated)
- write or delete Redis keys
- restart any live service
- place or cancel exchange orders
- change leverage or margin
- enable live trading
- deploy or run production migrations
- expose or commit secrets
- approve the live gate

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

## Next planner action

After task 103 emits 154 with `PASS` and the supervisor confirms the
working tree is clean and 102 parses as valid JSON, the supervisor
dispatches task 102 (Codex re-review). On
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS` from task 102, the
planner opens the next consolidated 2E2 sub-phase (worker health
observation collector or worker health composition) under a fresh
consolidated milestone turn. On
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` from task 102 with
concrete non-Rubric-12 blockers, the planner does NOT chain a second
addendum layer; surface to human attention. On any safety violation
during task 103 or task 102, surface to human attention; no further
remediation is permitted.

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_DISPATCH_HOLD_HANDOFF_READY
