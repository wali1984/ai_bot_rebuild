# Phase 2E3 Sub-Phase Breakdown — Trainer Prediction Output MVP

Phase 2E3 implements REQ_0017 milestone `TRAINER_PREDICTION_OUTPUT_MVP`.
It is the minimum-viable trainer-output surface needed to feed
`ORCHESTRATOR_DECISION_MVP`. Phase 2E3 must NOT expand into a
checkpoint/GPU runner subdomain, a broad model-loading subsystem, a
FastAPI surface, or any execution-side surface.

Each sub-phase is dispatched only after its predecessor's Codex review
PASS marker is materialized. Sub-phases land sequentially. No
sub-phase opens out of order.

## 2E3.A — Trainer prediction output domain (this milestone)

- Surface: `v2/backend/app/domain/trainer_prediction_output/`.
- Files written: `__init__.py`, `errors.py`, `record.py`.
- Public surface: `TrainerPredictionDomainError`,
  `TrainerPredictionRecord`, three direction constants, three
  freshness flag constants.
- Tests written: `v2/backend/tests/unit/domain/trainer_prediction_output/`
  (31 test files enumerated in
  `180_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_TEST_PLAN.md`).
- Predecessor marker: `PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS`.
- Implementation gate: `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_PASS`.
- Implementation task: `110`. Codex review task: `111`.

## 2E3.B — Trainer prediction record assembler service (later milestone)

- Surface: `v2/backend/app/services/trainer_prediction_output/`.
- Pure function `assemble_prediction_record(...)` that takes
  validated inputs (feature_snapshot_id, raw model output struct,
  worker health snapshot summary string, freshness inputs, model
  identity inputs, prediction identity inputs) and returns a
  `TrainerPredictionRecord`.
- No Redis, no I/O, no FastAPI, no GPU work. The service is a
  redis-clean function.
- Predecessor marker: `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_PASS`.
- Implementation task: future `112`. Codex review task: future `113`.

## 2E3.C — Trainer prediction output composition root (later milestone)

- Surface: `v2/backend/app/composition/trainer_prediction_output/`.
- Pure binder that captures static configuration (id-format policy,
  freshness threshold, attribution top-K) at build time and returns
  a callable that adapts the assembler service to a single-call
  evaluator.
- Inherits the redis-clean invariant from 2E3.B.
- Predecessor marker: `PHASE2E3B_TRAINER_PREDICTION_OUTPUT_SERVICE_CODEX_PASS`.
- Implementation task: future `114`. Codex review task: future `115`.

## Sequencing rule

If `111` (Codex review of 2E3.A) returns FAIL, the planner enqueues
a remediation autofix task under REQ_0007 / REQ_0014 scoped to the
2E3.A authored files only and does not advance to 2E3.B. If `111`
returns PASS, the planner opens a new turn to author the 2E3.B scope
and dispatch its tasks.

## Phase exit (closing Phase 2E3 → opening REQ_0017 Milestone 2)

Phase 2E3 closes when the 2E3.C composition-root Codex pass marker is
materialized. At that point REQ_0017 milestone 1
(`TRAINER_PREDICTION_OUTPUT_MVP`) is satisfied and the planner opens
REQ_0017 milestone 2 (`ORCHESTRATOR_DECISION_MVP`). No checkpoint/GPU
runner subsystem is opened in between.

PHASE2E3_TRAINER_PREDICTION_OUTPUT_MVP_PHASE_BREAKDOWN_READY
