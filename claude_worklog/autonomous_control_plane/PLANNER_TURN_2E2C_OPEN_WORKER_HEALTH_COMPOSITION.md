# Planner Turn — Phase 2E2.C Open: Worker Health Composition Root

## Date

2026-05-05

## Predecessor evidence

`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS` is the only line
of
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/169_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`.
This satisfies the "next planner action" clause in
`claude_worklog/agent_supervisor/tasks/107_trainer_parity_2e2b_codex_rereview_after_autofix.json`,
which directs the planner to close Phase 2E2.B and open Phase 2E2.C
(worker health composition root) on a CODEX_PASS marker for 2E2.B.

`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_AUTOFIX_PASSED` is the only
line of
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/167_2E2B_AUTOFIX_GO_NO_GO.md`,
confirming that the post-autofix tree was the basis of the Codex
re-review pass.

Phase 2E2.B artifacts that 2E2.C reads as a stable contract:

- `v2/backend/app/services/trainer_worker_health/__init__.py`
- `v2/backend/app/services/trainer_worker_health/errors.py`
- `v2/backend/app/services/trainer_worker_health/service.py`

Phase 2E2.A artifacts that 2E2.C reads as a stable contract:

- `v2/backend/app/domain/trainer_worker_health/__init__.py`
- `v2/backend/app/domain/trainer_worker_health/health_snapshot.py`
- `v2/backend/app/domain/trainer_worker_health/health_thresholds.py`

`v2/backend/app/domain/trainer_liveness/signal_snapshot.py` (the
`LivenessSignalSnapshot` value object) is also consumed read-only.

## Decision

Open Phase 2E2.C (worker health composition root) as the next
consolidated non-live milestone under REQ_0006. 2E2.C is the closing
wiring milestone of the trainer-worker-health stack, in line with
the dependency order established in
`140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md` § "2E2.C — Worker health
composition root (later milestone)".

The planner picks 2E2.C over any new 2E1.x continuation because the
breakdown sequencing rule places 2E2.C immediately after a 2E2.B
Codex pass. The 2E2.B service binds nothing — it is a redis-clean
function with `(snapshot, *, thresholds, now_ms_clock)` — so the
2E2.C composition root is a pure binder that captures
`thresholds` and `now_ms_clock` at build time and returns a callable
taking a `LivenessSignalSnapshot` and returning a
`TrainerWorkerHealthSnapshot`. This is the inverse of the 2E1.E
composition root, which DOES load Redis because 2E1.D consumes a
Redis-backed reader. 2E2.C inherits 2E2.B's redis-clean invariant
without any exemption.

The composition root lives under a new sub-package
`v2/backend/app/composition/trainer_worker_health/` that reuses the
existing 2E1.E `composition/__init__.py` package marker as-is. No
prior-milestone file is modified.

Granularity: consolidated. The implementation, the 20-test suite,
and the implementation report all land in one supervisor task
(`108`). The Codex review lands in one supervisor task (`109`). No
microsplit is authored unless 108 fails for an emit, path, size, or
timeout reason.

## Artifacts emitted in this turn

1. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/170_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_SPEC.md`
2. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/171_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_TEST_PLAN.md`
3. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/172_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_SAFETY_BOUNDARIES.md`
4. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/173_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO_REQUEST.md`
5. `claude_worklog/agent_supervisor/tasks/108_trainer_parity_2e2c_worker_health_composition_implementation.json`
6. `claude_worklog/agent_supervisor/tasks/109_trainer_parity_2e2c_worker_health_composition_codex_review.json`
7. `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E2C_OPEN_WORKER_HEALTH_COMPOSITION.md` (this file)

## Marker chain

- Implementation gate (after 108):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/175_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO.md`
  contains
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.
- Codex gate (after 109):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`
  contains
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS`.

## Hard stops carried into 2E2.C

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
- No modification of any prior-milestone artifact byte content
  (including the 2E1.E composition package marker, the 2E1.E
  trainer_parity composition runtime, the 2E1.D trainer_parity
  service, the 2E2.A worker health domain, and the 2E2.B worker
  health service).

## Next supervisor action

On the next reconciliation tick, with the working tree clean and the
predecessor marker `PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS`
in place at
`169_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`, the supervisor
dispatches
`108_trainer_parity_2e2c_worker_health_composition_implementation.json`
to local Codex CLI. On
`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`
in 175, the supervisor dispatches
`109_trainer_parity_2e2c_worker_health_composition_codex_review.json`.
On
`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS` in 177,
the planner closes Phase 2E2.C and Phase 2E2 as a whole and opens
the next REQ_0006 sub-phase (trainer GPU/checkpoint runner or trainer
confidence attribution per the consolidated milestone hint in the
master planner prompt) on the next turn.

## Next planner action contingencies

- On
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_FAILED`
  with concrete non-safety blockers, the planner enqueues a narrow
  REQ_0007 / REQ_0014 autofix task scoped to the three authored
  source files plus the 20 new test files only and does not advance
  to the next 2E sub-phase.
- On
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_FAIL` with
  concrete non-safety blockers, the planner enqueues the same kind
  of narrow autofix task and re-runs Codex review.
- On any safety violation in 2E2.C, the planner surfaces to human
  attention; no autofix is permitted.
- On REQ_0011 parallel Codex usage: while 108 is the active dirty
  Claude output target, Codex parallel lane only reviews already
  committed prior-milestone artifacts (2E2.A, 2E2.B, 2E1.E, 2E1.D);
  no parallel Codex run touches the 2E2.C authored paths until 108
  commits clean.

PHASE2E2C_PLANNER_TURN_OPEN_READY
