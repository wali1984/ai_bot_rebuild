# Phase 2F Sub-Phase Breakdown — Orchestrator Decision MVP

Phase 2F implements REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP`. It is the minimum-viable orchestrator decision surface needed to feed `RISK_GATEWAY_DEFAULT_DENY_MVP` (REQ_0017 milestone 3). Phase 2F MUST NOT expand into a position-sizing subdomain, a risk subsystem, an execution-side surface, a FastAPI surface, or a strategy library.

Each sub-phase is dispatched only after its predecessor's Codex review PASS marker is materialized. Sub-phases land sequentially. No sub-phase opens out of order.

## 2F.A — Orchestrator decision domain (this turn)

- Surface: `v2/backend/app/domain/orchestrator_decision/`.
- Files written: `__init__.py`, `errors.py`, `record.py`.
- Public surface: `OrchestratorDecisionDomainError`, `OrchestratorDecisionRecord`, four decision-action constants, eleven decision-reason constants (see 02 spec).
- Tests written: `v2/backend/tests/unit/domain/orchestrator_decision/` (34 test files enumerated in `03_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_TEST_PLAN.md`).
- Predecessor marker: `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS`.
- Implementation gate: `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS`.
- Implementation task: `117`. Codex review task: `118`.

## 2F.B — Orchestrator decision assembler service (later milestone)

- Surface: `v2/backend/app/services/orchestrator_decision/` (new package).
- Pure function `assemble_orchestrator_decision_record(...)` that takes a validated `TrainerPredictionRecord`, a low-confidence threshold (float in [0.0, 1.0]) and a `now_ms_clock` callable, and returns a frozen `OrchestratorDecisionRecord`. The function does NOT call a model, does NOT touch I/O, does NOT touch Redis, and does NOT register any FastAPI surface. The default-deny taxonomy maps:
  - missing freshness → `abstain` / `abstain_freshness_missing`
  - stale freshness → `abstain` / `abstain_freshness_stale`
  - worker `CRITICAL` → `abstain` / `abstain_worker_critical`
  - worker `DEGRADED` → `abstain` / `abstain_worker_degraded`
  - worker `UNKNOWN` → `abstain` / `abstain_worker_unknown`
  - confidence_calibrated < threshold → `abstain` / `abstain_low_confidence`
  - direction `flat` (and otherwise eligible) → `hold` / `hold_flat_direction`
  - direction `long` (and otherwise eligible) → `open_long` / `proceed_long`
  - direction `short` (and otherwise eligible) → `open_short` / `proceed_short`
- The decision_id format and the `decision_id` derivation from `prediction_id` are decided by 2F.B. 2F.A only validates the resulting string.
- Predecessor marker: `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS`.
- Implementation task: future. Codex review task: future.

### Services-layer naming-collision concern

`v2/backend/app/services/orchestrator_decision.py` is a one-line placeholder string. Creating a new `v2/backend/app/services/orchestrator_decision/` package collides with that file. 2F.B opens by deleting the placeholder file in a single supervisor task with allowed_output_prefixes scoped to the new package only and an explicit `forbidden_output_paths` entry preventing reintroduction of the placeholder. 2F.A does NOT modify the placeholder; the deletion is a 2F.B-scoped supervisor action documented in the 2F.B spec at the time it is opened. The same posture is used at the composition layer if a similar placeholder exists at the time 2F.C opens.

## 2F.C — Orchestrator decision composition root (later milestone)

- Surface: `v2/backend/app/composition/orchestrator_decision/` (new package).
- Pure binder `build_orchestrator_decision_evaluator(*, low_confidence_threshold: float, now_ms_clock: Callable[[], int]) -> OrchestratorDecisionEvaluator` that captures static configuration at build time and returns a single-call evaluator that adapts the 2F.B service.
- Predecessor marker: `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS`.
- Implementation task: future. Codex review task: future.

## Sequencing rule

If `118` (Codex review of 2F.A) returns FAIL with concrete blockers and no safety violation, the planner enqueues a remediation autofix task under REQ_0007 / REQ_0014 scoped to the 2F.A authored files only and does not advance to 2F.B. If `118` returns PASS, the planner opens a new turn to author the 2F.B scope and dispatch its tasks.

## Phase exit (closing Phase 2F → opening REQ_0017 milestone 3)

Phase 2F closes when the 2F.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 2 (`ORCHESTRATOR_DECISION_MVP`) is satisfied and the planner opens REQ_0017 milestone 3 (`RISK_GATEWAY_DEFAULT_DENY_MVP`). No risk-gateway behavior, no execution-side surface, and no strategy library is opened in between.

PHASE2F_ORCHESTRATOR_DECISION_MVP_PHASE_BREAKDOWN_READY
