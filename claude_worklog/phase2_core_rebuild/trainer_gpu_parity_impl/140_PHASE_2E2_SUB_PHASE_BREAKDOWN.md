# Phase 2E2 Sub-Phase Breakdown — Trainer Prediction Worker Health

This document is the canonical sub-phase plan for Phase 2E2 of
REQ_0006. Phase 2E2 builds the richer prediction-worker health model
that REQ_0006 calls for in addition to the binary liveness alert
produced by Phase 2E1. Each sub-phase is dispatched only after its
predecessor's Codex review PASS marker is materialized. Sub-phases
land sequentially. No sub-phase opens until its predecessor is
Codex-passed.

## 2E2.A — Worker health domain (this turn)

- Surface: `v2/backend/app/domain/trainer_worker_health/`.
- Files written: `__init__.py`, `errors.py`, `health_status.py`,
  `health_thresholds.py`, `health_snapshot.py`, `health_evaluator.py`.
- Tests written: `v2/backend/tests/unit/domain/trainer_worker_health/`
  package marker plus 24 test files (see `142`).
- Inputs consumed (read-only, no modification): the
  `LivenessSignalSnapshot` value object from
  `v2.backend.app.domain.trainer_liveness`.
- Public surface: `TrainerWorkerHealthDomainError`,
  `TrainerWorkerHealthThresholds`, `TrainerWorkerHealthSnapshot`,
  `evaluate_trainer_worker_health`, plus the status-constant tuple
  `(HEALTH_STATUS_HEALTHY, HEALTH_STATUS_DEGRADED,
  HEALTH_STATUS_CRITICAL, HEALTH_STATUS_UNKNOWN)`, plus the reason
  constants enumerated in `141`.
- Codex gate: `101` reviews `100` outputs.

## 2E2.B — Worker health service (next milestone)

- Surface (planned): `v2/backend/app/services/trainer_worker_health/`.
- Files (planned): `service.py`, `errors.py`, `__init__.py`.
- Responsibility: orchestrate the evaluator over a sequence of
  `LivenessSignalSnapshot` instances, optionally delegating to the
  observation collector for snapshot construction; return a
  `TrainerWorkerHealthSnapshot` per call.
- Redis-clean import invariant identical to 2E1.D.
- Codex gate: future task pair.

## 2E2.C — Worker health composition root (later milestone)

- Surface (planned): `v2/backend/app/composition/trainer_worker_health/`.
- Files (planned): `__init__.py`, `errors.py`, `runtime.py`.
- Responsibility: build a callable that returns a
  `TrainerWorkerHealthSnapshot` from base inputs plus thresholds,
  using the gamma.real factory chain for any Redis-backed dependency
  it inherits from the 2E2.B service.
- Composition-root pattern identical to 2E1.E (separate top-level
  package to preserve the service's redis-clean invariant).
- Codex gate: future task pair.

## Sequencing rule

If `101` (Codex review of 2E2.A) returns FAIL with concrete blockers,
planner enqueues a narrow REQ_0007 / REQ_0014 autofix task scoped to
the six authored source files and the 24 new test files only and
does not advance to 2E2.B. If `101` returns PASS, planner opens a new
cycle to author the 2E2.B scope.

## Hard-stop reminders for every 2E2 sub-phase

- No legacy mutation under `/home/wali/Desktop/AI BOT`.
- No Redis read or write at the domain layer.
- No live service restart.
- No exchange action.
- No leverage or margin change.
- No live trading enabled.
- No deploy intent.
- No production migration.
- No secret exposure.

PHASE2E2_TRAINER_WORKER_HEALTH_SUB_PHASE_BREAKDOWN_READY
