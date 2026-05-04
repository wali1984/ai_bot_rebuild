# Phase 2E2.A — Trainer Worker Health Domain GO/NO-GO Request

The planner authored `140` (sub-phase breakdown), `141` (spec),
`142` (test plan), and `143` (safety boundaries) for Phase 2E2.A and
is requesting GO authorization to dispatch supervisor task
`100_trainer_parity_2e2a_worker_health_domain_implementation`.

## Predecessor evidence

- `139_2E1E_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md` contains
  exactly `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`
  (verified at planner turn 2026-05-04). This is the authoritative
  2E1.E Codex pass marker and closes Phase 2E1.

## Scope summary

- New domain package
  `v2/backend/app/domain/trainer_worker_health/` with six authored
  source files: `__init__.py`, `errors.py`, `health_status.py`,
  `health_thresholds.py`, `health_snapshot.py`, `health_evaluator.py`.
- New test directory
  `v2/backend/tests/unit/domain/trainer_worker_health/` with the
  package marker plus 24 unit tests.
- Public surface: `TrainerWorkerHealthDomainError`,
  `TrainerWorkerHealthThresholds`, `TrainerWorkerHealthSnapshot`,
  `evaluate_trainer_worker_health`, plus four status constants and
  ten reason constants — 18 names total.
- Inputs: the existing 2E1
  `v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`
  consumed without modification.
- Outputs: a new `TrainerWorkerHealthSnapshot` dataclass with
  HEALTHY / DEGRADED / CRITICAL / UNKNOWN status and a structured
  reasons tuple.
- Redis-clean. Adapter-clean. No import of any redis_v2 module, no
  `url_env`, no `os.environ`, no wall-clock helper, no logging, no
  printing.

## Hard stops not triggered

- No legacy mutation. `/home/wali/Desktop/AI BOT` is untouched.
- No Redis read or write at any layer.
- No live trainer / trader / orchestrator / Redis / VPN restart.
- No exchange action.
- No leverage or margin change.
- No live trading enabled.
- No deploy intent.
- No production migration.
- No secret exposure.
- No L4 / L5 behavior.

## Dispatch sequence directive

1. Supervisor commits this turn's working-tree artifacts (the four
   spec markdown files, the two task JSON files, this turn note
   under `claude_worklog/autonomous_control_plane/`, and the
   already-modified
   `claude_master_rebuild_planner_prompt.txt`). Working tree
   returns to clean.

2. Supervisor reconciles `099` as `superseded_by_evidence`: its
   required outputs `138` and `139` already exist with PASS at the
   moment of this turn. No re-dispatch of `099` is permitted.

3. Supervisor dispatches
   `100_trainer_parity_2e2a_worker_health_domain_implementation`.
   `100` emits the six source files plus the 24 test files plus
   `145` (implementation report) and `146` (impl GO/NO-GO marker).

4. On `100` PASS marker
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_IMPL_AND_VALIDATION_PASSED`,
   supervisor dispatches
   `101_trainer_parity_2e2a_worker_health_domain_codex_review`.
   `101` emits `147` (Codex review report) and `148` (Codex
   GO/NO-GO marker).

5. On `101` PASS marker
   `PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS`, the planner
   closes Phase 2E2.A and opens Phase 2E2.B (worker health service)
   under a fresh consolidated milestone turn.

## REQ_0007 / REQ_0014 fallback

- `100` FAIL with concrete blockers and zero safety violation:
  supervisor dispatches a narrow REQ_0007 / REQ_0014 autofix task
  scoped to the six authored source files plus the 24 new test
  files only.
- `101` FAIL with concrete blockers and zero safety violation:
  same scope as the `100` fallback.
- Any safety violation in `100` or `101`: surface to human
  attention; no autofix permitted.

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_GO_NO_GO_REQUEST_READY
