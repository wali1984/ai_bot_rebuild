# Planner Turn — Phase 2E2.B Open: Worker Health Service

## Date

2026-05-05

## Predecessor evidence

`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS` is the only line
of
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/152_2E2A_CODEX_REREVIEW_AFTER_ADDENDUM_GO_NO_GO.md`.
This satisfies the "next planner action" clause in
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/156_PLANNER_2E2A_TASK_103_SUPERSEDED_BY_EVIDENCE.md`,
which directs the planner to open the next consolidated 2E2 sub-phase
on a CODEX_PASS marker for 2E2.A.

Phase 2E2.A artifacts that 2E2.B reads as a stable contract:

- `v2/backend/app/domain/trainer_worker_health/__init__.py`
- `v2/backend/app/domain/trainer_worker_health/errors.py`
- `v2/backend/app/domain/trainer_worker_health/health_status.py`
- `v2/backend/app/domain/trainer_worker_health/health_thresholds.py`
- `v2/backend/app/domain/trainer_worker_health/health_snapshot.py`
- `v2/backend/app/domain/trainer_worker_health/health_evaluator.py`

`v2/backend/app/domain/trainer_liveness/signal_snapshot.py` (the
`LivenessSignalSnapshot` value object) is also consumed read-only.

## Decision

Open Phase 2E2.B (worker health service) as the next consolidated
non-live milestone under REQ_0006. 2E2.C (worker health composition
root) follows on a 2E2.B Codex pass, in line with the dependency
order established in
`140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md`.

The planner picks 2E2.B over 2E2.C because the composition root in
2E2.C is required to consume the 2E2.B service surface as a callable
dependency. Authoring the composition root before the service is not
viable. The breakdown sequencing rule is preserved.

Granularity: consolidated. The implementation, the 22-test suite,
and the implementation report all land in one supervisor task
(`104`). The Codex review lands in one supervisor task (`105`). No
microsplit is authored unless 104 fails for an emit, path, size, or
timeout reason.

## Artifacts emitted in this turn

1. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/158_PHASE_2E2B_WORKER_HEALTH_SERVICE_SPEC.md`
2. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/159_PHASE_2E2B_WORKER_HEALTH_SERVICE_TEST_PLAN.md`
3. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/160_PHASE_2E2B_WORKER_HEALTH_SERVICE_SAFETY_BOUNDARIES.md`
4. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/161_PHASE_2E2B_WORKER_HEALTH_SERVICE_GO_NO_GO_REQUEST.md`
5. `claude_worklog/agent_supervisor/tasks/104_trainer_parity_2e2b_worker_health_service_implementation.json`
6. `claude_worklog/agent_supervisor/tasks/105_trainer_parity_2e2b_worker_health_service_codex_review.json`
7. `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E2B_OPEN_WORKER_HEALTH_SERVICE.md` (this file)

## Marker chain

- Implementation gate (after 104):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/163_2E2B_WORKER_HEALTH_SERVICE_GO_NO_GO.md`
  contains
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- Codex gate (after 105):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/165_2E2B_WORKER_HEALTH_SERVICE_CODEX_GO_NO_GO.md`
  contains
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS`.

## Hard stops carried into 2E2.B

- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis read or write at any layer.
- No Redis command of any kind.
- No live service restart.
- No order placement or cancellation.
- No leverage or margin change.
- No live trading enablement.
- No shipping anywhere.
- No migration in any environment.
- No credential exposure.
- No live-gate approval.

## Next supervisor action

On the next reconciliation tick, with the working tree clean and the
predecessor marker in place, the supervisor dispatches
`104_trainer_parity_2e2b_worker_health_service_implementation.json`
to local Codex CLI. On
`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_IMPL_AND_VALIDATION_PASSED`
in 163, the supervisor dispatches
`105_trainer_parity_2e2b_worker_health_service_codex_review.json`.
On
`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS` in 165, the
planner opens Phase 2E2.C (worker health composition root) on the
next turn.

## Next planner action contingencies

- On
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_IMPL_AND_VALIDATION_FAILED`
  with concrete non-safety blockers, the planner enqueues a narrow
  REQ_0007 / REQ_0014 autofix task scoped to the three authored
  source files plus the 22 new test files only and does not advance
  to 2E2.C.
- On
  `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_FAIL` with concrete
  non-safety blockers, the planner enqueues the same kind of narrow
  autofix task and re-runs Codex review.
- On any safety violation in 2E2.B, the planner surfaces to human
  attention; no autofix is permitted.
- On REQ_0011 parallel Codex usage: while 104 is the active dirty
  Claude output target, Codex parallel lane only reviews already
  committed prior-milestone artifacts; no parallel Codex run touches
  the 2E2.B authored paths until 104 commits clean.

PHASE2E2B_PLANNER_TURN_OPEN_READY
