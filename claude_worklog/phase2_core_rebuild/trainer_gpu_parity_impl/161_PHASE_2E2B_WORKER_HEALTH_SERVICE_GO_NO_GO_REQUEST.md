# Phase 2E2.B — Worker Health Service GO/NO-GO Request

## Predecessor

`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS` is materialized
at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/152_2E2A_CODEX_REREVIEW_AFTER_ADDENDUM_GO_NO_GO.md`.

The Phase 2E2.A domain surface
(`v2/backend/app/domain/trainer_worker_health/`) is closed and
exposes a stable public surface that 2E2.B consumes read-only:

- `TrainerWorkerHealthDomainError`
- `TrainerWorkerHealthThresholds`
- `TrainerWorkerHealthSnapshot`
- `evaluate_trainer_worker_health`
- the four `HEALTH_STATUS_*` constants
- the ten `HEALTH_REASON_*` constants

## Scope of 2E2.B

Implement the worker health service layer per
`158_PHASE_2E2B_WORKER_HEALTH_SERVICE_SPEC.md`. The service
orchestrates the 2E2.A domain evaluator over a single
`LivenessSignalSnapshot` per call, validates inputs, calls the
clock exactly once, propagates the resulting
`TrainerWorkerHealthSnapshot` unchanged, and preserves the
redis-clean import invariant.

## Authored files

Three source files under
`v2/backend/app/services/trainer_worker_health/`:

- `__init__.py`
- `errors.py`
- `service.py`

One package marker plus 22 test files under
`v2/backend/tests/unit/services/trainer_worker_health/` per
`159_PHASE_2E2B_WORKER_HEALTH_SERVICE_TEST_PLAN.md`.

Two phase artifacts:

- `162_2E2B_WORKER_HEALTH_SERVICE_IMPLEMENTATION_REPORT.md`
- `163_2E2B_WORKER_HEALTH_SERVICE_GO_NO_GO.md`

## Forbidden in this milestone

See `160_PHASE_2E2B_WORKER_HEALTH_SERVICE_SAFETY_BOUNDARIES.md`.

The implementation task must NOT modify any path under:

- `v2/backend/app/domain/trainer_worker_health/` (Phase 2E2.A)
- `v2/backend/app/services/trainer_parity/` (Phase 2E1.D)
- `v2/backend/app/composition/trainer_parity/` (Phase 2E1.E)
- any other path enumerated in 160 cross-isolation list.

The implementation task must NOT:

- read or write any Redis key.
- import `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`,
  `requests`, or
  `v2.backend.app.adapters.redis_v2.url_env`.
- modify `/home/wali/Desktop/AI BOT`.
- restart live services.
- place or cancel exchange orders.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run any production migration.
- expose or commit credentials.
- approve the live gate.

## Approval

Phase 2E2.B is approved to dispatch under task
`104_trainer_parity_2e2b_worker_health_service_implementation.json`.
Codex review under task
`105_trainer_parity_2e2b_worker_health_service_codex_review.json`
follows after `163_2E2B_WORKER_HEALTH_SERVICE_GO_NO_GO.md` carries
`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_IMPL_AND_VALIDATION_PASSED`.

PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_GO_NO_GO_REQUEST_READY
