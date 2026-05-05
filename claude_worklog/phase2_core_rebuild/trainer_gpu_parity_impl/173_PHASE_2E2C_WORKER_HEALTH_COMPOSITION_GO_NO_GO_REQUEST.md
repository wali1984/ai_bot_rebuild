# Phase 2E2.C — Worker Health Composition Root GO / NO-GO Request

## Predecessor evidence

`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS` is the only line
of
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/169_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`.
This satisfies the "next planner action" clause in
`claude_worklog/agent_supervisor/tasks/107_trainer_parity_2e2b_codex_rereview_after_autofix.json`,
which directs the planner to open Phase 2E2.C (worker health
composition root) on a CODEX_PASS marker for 2E2.B.

`140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md` § "2E2.C — Worker health
composition root (later milestone)" identifies 2E2.C as the third
sub-phase under REQ_0006 Phase 2E2 and the closing wiring step of
the trainer-worker-health stack.

## Decision

OPEN Phase 2E2.C as the next consolidated non-live milestone under
REQ_0006. Implementation, the 20-test suite, and the implementation
report land in one supervisor task (`108`). The Codex review lands in
one supervisor task (`109`). No microsplit is authored unless `108`
fails for an emit, path, size, or timeout reason.

## Authoring inputs (read-only)

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/170_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/171_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/172_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_SAFETY_BOUNDARIES.md`
- `v2/backend/app/services/trainer_worker_health/__init__.py`
- `v2/backend/app/services/trainer_worker_health/errors.py`
- `v2/backend/app/services/trainer_worker_health/service.py`
- `v2/backend/app/domain/trainer_worker_health/__init__.py`
- `v2/backend/app/domain/trainer_worker_health/health_snapshot.py`
- `v2/backend/app/domain/trainer_worker_health/health_thresholds.py`
- `v2/backend/app/domain/trainer_liveness/__init__.py`
- `v2/backend/app/domain/trainer_liveness/signal_snapshot.py`

## Authored outputs (additive only)

- `v2/backend/app/composition/trainer_worker_health/__init__.py`.
- `v2/backend/app/composition/trainer_worker_health/errors.py`.
- `v2/backend/app/composition/trainer_worker_health/runtime.py`.
- `v2/backend/tests/unit/composition/trainer_worker_health/__init__.py`
  (empty package marker).
- The 20 test files enumerated in
  `171_PHASE_2E2C_WORKER_HEALTH_COMPOSITION_TEST_PLAN.md` § "Required
  test files".
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/174_2E2C_WORKER_HEALTH_COMPOSITION_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/175_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO.md`.

The pre-existing `v2/backend/app/composition/__init__.py` and
`v2/backend/tests/unit/composition/__init__.py` package markers
authored in Phase 2E1.E are reused as-is and are NOT re-emitted by
2E2.C.

## Marker chain

- Implementation gate (after 108):
  `175_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO.md` contains
  `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.
- Codex gate (after 109):
  `177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md` contains
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
- No modification of any prior-milestone artifact byte content.

## Recommendation

GO. Open Phase 2E2.C under task ID `108`. Codex review under task ID
`109`.

PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY
