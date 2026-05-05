# Planner Turn — Phase 2E3.A Open: Prediction Output Domain (Trainer Prediction Output MVP)

## Date

2026-05-05

## Predecessor evidence

`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS` is the
only line of
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`.
This satisfies the "next planner action" clause in
`claude_worklog/agent_supervisor/tasks/109_trainer_parity_2e2c_worker_health_composition_codex_review.json`,
which directs the planner to close Phase 2E2.C and Phase 2E2 as a
whole and open the next REQ_0006 sub-phase on a CODEX_PASS marker
for 2E2.C.

`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`
is the only line of
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/175_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO.md`,
confirming that the Codex re-review pass operated on a clean local
validation tree.

Phase 2E2.A, 2E2.B, and 2E2.C artifacts that 2E3.A reads as stable
contracts (read-only, byte-identical):

- `v2/backend/app/domain/trainer_worker_health/`
- `v2/backend/app/services/trainer_worker_health/`
- `v2/backend/app/composition/trainer_worker_health/`

Phase 2E1 artifacts that 2E3.A may consume read-only:

- `v2/backend/app/domain/trainer_liveness/`
- `v2/backend/app/services/trainer_parity/`
- `v2/backend/app/composition/trainer_parity/`

## Roadmap reconciliation under REQ_0017

REQ_0017 (Force Paper / Backtest MVP Track, committed at f5ed2f4) is
the active hard roadmap constraint. Its required milestone sequence
is `TRAINER_PREDICTION_OUTPUT_MVP` →
`ORCHESTRATOR_DECISION_MVP` →
`RISK_GATEWAY_DEFAULT_DENY_MVP` →
`PAPER_EXECUTION_LEDGER_MVP` →
`REPLAY_BACKTEST_RUNNER_MVP` →
`PAPER_MODE_MVP` →
`SHADOW_MODE_READINESS`.

REQ_0017 explicitly forbids broad checkpoint/GPU/metadata subdomain
expansion under REQ_0006 once the minimum validated prediction-output
path exists. The closing 2E2.C Codex pass means trust-and-observability
(worker health + liveness) is now sufficient. The planner therefore
does NOT open a "trainer GPU/checkpoint runner" sub-phase from the
master prompt's pre-REQ_0017 hint. Instead, the planner opens
Phase 2E3 (Trainer Prediction Output MVP) and starts with sub-phase
2E3.A: a single pure-domain value object capturing the trainer
prediction record contract that downstream orchestrator and risk
gateway milestones will consume.

This is the minimum viable surface required by REQ_0017 §"Trainer
Completion Boundary":

- prediction output contract (TrainerPredictionRecord)
- prediction identity (`prediction_id`)
- prediction freshness (`freshness_flag`, `source_freshness_age_ms`)
- prediction confidence / attribution summary sufficient for risk
  decisions (`confidence_raw`, `confidence_calibrated`,
  `top_positive_feature_codes`, `top_negative_feature_codes`)
- enough checkpoint/version metadata to identify model output
  (`model_version`, `checkpoint_id`, `worker_id`,
  `worker_health_status` snapshot string)

No service composition, no Redis-backed adapter, no FastAPI route, no
GPU/checkpoint subsystem expansion lands in 2E3.A. Those are deferred
to later 2E3 sub-phases or to subsequent REQ_0017 milestones in
sequence.

## Decision

Open Phase 2E3.A (trainer prediction output domain record) as the
next consolidated non-live milestone under REQ_0006 ∩ REQ_0017.

The implementation lives under a NEW domain package:

`v2/backend/app/domain/trainer_prediction_output/`

with three source files:

- `__init__.py` (public surface re-exports)
- `errors.py` (TrainerPredictionDomainError)
- `record.py` (direction + freshness constants + TrainerPredictionRecord)

The package is a sibling of the existing `trainer_liveness/` and
`trainer_worker_health/` packages. It does NOT live inside either,
because the prediction record contract is a distinct Stage A trainer
output binding (per
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`)
with its own enumerations, dataclass, and invariants.

No 2E1 or 2E2 file is modified by this milestone.

The four canonical worker health status strings ("HEALTHY",
"DEGRADED", "CRITICAL", "UNKNOWN") are duplicated as a private
frozenset literal inside `record.py`. The 2E3.A domain takes a
SNAPSHOT STRING of the worker health status as a lineage field, not
a live coupling to the trainer_worker_health domain. Duplication is
the correct call here: the values are stable contract strings, the
domain boundary stays clean, and `trainer_worker_health` does not
become a transitive import of every prediction record consumer.

Granularity: consolidated. The implementation, the 31-test suite,
the implementation report, and the GO/NO-GO marker land in one
supervisor task (`110`). The Codex review lands in one supervisor
task (`111`). No microsplit is authored unless `110` fails for an
emit, path, size, or timeout reason.

## Artifacts emitted in this turn

1. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/178_PHASE_2E3_SUB_PHASE_BREAKDOWN.md`
2. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/179_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_SPEC.md`
3. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/180_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_TEST_PLAN.md`
4. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/181_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_SAFETY_BOUNDARIES.md`
5. `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/182_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_GO_NO_GO_REQUEST.md`
6. `claude_worklog/agent_supervisor/tasks/110_trainer_parity_2e3a_prediction_output_domain_implementation.json`
7. `claude_worklog/agent_supervisor/tasks/111_trainer_parity_2e3a_prediction_output_domain_codex_review.json`
8. `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3A_OPEN_PREDICTION_OUTPUT_DOMAIN.md` (this file)

## Marker chain

- Implementation gate (after `110`):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/184_2E3A_PREDICTION_OUTPUT_DOMAIN_GO_NO_GO.md`
  contains
  `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate (after `111`):
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/186_2E3A_PREDICTION_OUTPUT_DOMAIN_CODEX_GO_NO_GO.md`
  contains
  `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_PASS`.

## Hard stops carried into 2E3.A

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
  (including all 2E1 and 2E2 source, tests, and validation reports).
- No expansion outside REQ_0017 §"Trainer Completion Boundary":
  no checkpoint/GPU runner subdomain, no broad model-loading
  subsystem, no FastAPI route, no service composition, no adapter,
  no composition root in this sub-phase.

## Next supervisor action

On the next reconciliation tick, with the working tree clean and the
predecessor marker
`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS` in place
at `177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`, the
supervisor dispatches
`110_trainer_parity_2e3a_prediction_output_domain_implementation.json`
to local Codex CLI. On
`PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_IMPL_AND_VALIDATION_PASSED`
in `184`, the supervisor dispatches
`111_trainer_parity_2e3a_prediction_output_domain_codex_review.json`.
On `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_PASS` in `186`,
the planner closes Phase 2E3.A and opens Phase 2E3.B (trainer
prediction record assembler service) on the next turn — still inside
the REQ_0017 `TRAINER_PREDICTION_OUTPUT_MVP` milestone, still without
any checkpoint/GPU subsystem expansion.

## Next planner action contingencies

- On
  `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_IMPL_AND_VALIDATION_FAILED`
  with concrete non-safety blockers, the planner enqueues a narrow
  REQ_0007 / REQ_0014 autofix task scoped to the three authored
  source files plus the new test files only and does not advance to
  Phase 2E3.B.
- On `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_FAIL` with
  concrete non-safety blockers, the planner enqueues the same kind
  of narrow autofix task and re-runs Codex review.
- On any safety violation in 2E3.A, the planner surfaces to human
  attention; no autofix is permitted.
- On REQ_0011 parallel Codex usage: while `110` is the active dirty
  Claude output target, Codex parallel lane only reviews already
  committed prior-milestone artifacts (2E2.A/B/C, 2E1.E, 2E1.D);
  no parallel Codex run touches the 2E3.A authored paths until
  `110` commits clean.

PHASE2E3A_PLANNER_TURN_OPEN_READY
END_FILE: claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3A_OPEN_PREDICTION_OUTPUT_DOMAIN.md
