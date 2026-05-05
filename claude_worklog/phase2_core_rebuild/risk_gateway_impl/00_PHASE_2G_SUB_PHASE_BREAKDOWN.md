# Phase 2G Sub-Phase Breakdown — Risk Gateway Default-Deny MVP

Phase 2G implements REQ_0017 milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`. It is the minimum-viable risk-gateway decision surface needed to feed `PAPER_EXECUTION_LEDGER_MVP` (REQ_0017 milestone 4). Phase 2G MUST NOT expand into a position-sizing subdomain, an exposure-tracking subsystem, an execution-side surface, a FastAPI surface, a strategy library, or any model/GPU/checkpoint subsystem.

Each sub-phase is dispatched only after its predecessor's Codex review PASS marker is materialized. Sub-phases land sequentially. No sub-phase opens out of order.

## 2G.A — Risk gateway domain (this turn)

- Surface: `v2/backend/app/domain/risk_gateway/`.
- Files written: `__init__.py`, `errors.py`, `record.py`.
- Public surface: `RiskGatewayDomainError`, `RiskDecisionRecord`, two risk-action constants, five risk-reason constants (see 02 spec).
- Tests written: `v2/backend/tests/unit/domain/risk_gateway/` (31 test files plus a zero-byte `__init__.py`, enumerated in `03_PHASE_2G_A_RISK_GATEWAY_DOMAIN_TEST_PLAN.md`).
- Predecessor marker: `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`.
- Implementation gate: `PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS`.
- Implementation task: `126`. Codex review task: `127`.

## 2G.B — Risk gateway default-deny assembler service (later milestone)

- Surface: `v2/backend/app/services/risk_gateway/` (new package).
- Pure function `assemble_risk_decision_record(*, decision: OrchestratorDecisionRecord, now_ms_clock: Callable[[], int]) -> RiskDecisionRecord` that takes a validated `OrchestratorDecisionRecord` and a `now_ms_clock` callable, and returns a frozen `RiskDecisionRecord`. The function does NOT call a model, does NOT touch I/O, does NOT touch Redis, and does NOT register any FastAPI surface. The default-deny taxonomy maps:
  - orchestrator action `open_long` with reason `proceed_long` → `allow` / `allow_proceed_long`
  - orchestrator action `open_short` with reason `proceed_short` → `allow` / `allow_proceed_short`
  - orchestrator action `hold` with reason `hold_flat_direction` → `deny` / `deny_orchestrator_held`
  - orchestrator action `abstain` (any abstain reason) → `deny` / `deny_orchestrator_abstained`
- The `risk_decision_id` format and the `risk_decision_id` derivation from `decision_id` are decided by 2G.B. 2G.A only validates the resulting string.
- 2G.B is default-deny by construction: the 2G.B service has exactly four exhaustive branches (one per orchestrator action) and any unrecognized action raises a service error before producing a record. The reserved `RISK_DECISION_REASON_DENY_DEFAULT` taxonomy member is held for a future enrichment of 2G.B (e.g., a tradable input that fails an exposure or freshness gate added to the assembler) and is validated at the value-object layer in 2G.A as part of the cross-field rule that a `deny_default` reason MUST be paired with a tradable input action (`open_long` or `open_short`).
- Predecessor marker: `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS`.
- Implementation task: future. Codex review task: future.

### Services-layer naming-collision concern

`v2/backend/app/services/risk_gateway.py` is a one-line placeholder docstring file. Creating a new `v2/backend/app/services/risk_gateway/` package collides with that file. 2G.B opens by deleting the placeholder file in a single supervisor task with allowed_output_prefixes scoped to the new package only and an explicit `forbidden_output_paths` entry preventing reintroduction of the placeholder. 2G.A does NOT modify the placeholder; the deletion is a 2G.B-scoped supervisor action documented in the 2G.B spec at the time it is opened. The same posture is used at the composition layer if a similar placeholder exists at the time 2G.C opens.

The pre-existing `v2/backend/app/domain/risk/` directory containing legacy-style scaffold stubs (`kill_switch.py`, `live_readiness_state.py`, `phases.py`, `policy_bundle.py`) is separately read-only and is NOT modified, NOT renamed, and NOT used by Phase 2G. The new domain package lives at `v2/backend/app/domain/risk_gateway/` to avoid collision. The existing empty `v2/backend/app/domain/decisions/` directory is also NOT modified.

## 2G.C — Risk gateway composition root (later milestone)

- Surface: `v2/backend/app/composition/risk_gateway/` (new package).
- Pure binder `build_risk_decision_evaluator(*, now_ms_clock: Callable[[], int]) -> RiskDecisionEvaluator` that captures the static `now_ms_clock` callable at build time and returns a single-call evaluator that adapts the 2G.B service.
- Predecessor marker: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`.
- Implementation task: future. Codex review task: future.

## Sequencing rule

If `127` (Codex review of 2G.A) returns FAIL with concrete blockers and no safety violation, the planner enqueues a remediation autofix task under REQ_0007 / REQ_0014 scoped to the 2G.A authored files only and does not advance to 2G.B. If `127` returns PASS, the planner opens a new turn to author the 2G.B scope and dispatch its tasks.

## Phase exit (closing Phase 2G → opening REQ_0017 milestone 4)

Phase 2G closes when the 2G.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 3 (`RISK_GATEWAY_DEFAULT_DENY_MVP`) is satisfied and the planner opens REQ_0017 milestone 4 (`PAPER_EXECUTION_LEDGER_MVP`). No execution-side behavior, no paper executor, and no strategy library is opened in between.

PHASE2G_RISK_GATEWAY_DEFAULT_DENY_MVP_PHASE_BREAKDOWN_READY
