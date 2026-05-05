# Phase 2F.C — Orchestrator Decision Composition Root Safety Boundaries

This document fixes the safety boundaries for Phase 2F.C of REQ_0006 ∩ REQ_0017. It MUST be enforced by both the implementation task (`124`) and the Codex review task (`125`). Any violation is an unconditional FAIL with no autofix path; surface to human attention.

## Hard live-gate boundaries

The 2F.C milestone MUST NOT, in any layer, in any code path, at any time:

- modify `/home/wali/Desktop/AI BOT`.
- read or write any literal `red` + `is` key.
- invoke any literal `red` + `is` command at any time.
- restart any live trainer, trader, orchestrator, ingestor, or `red` + `is` service.
- place, cancel, or modify any exchange order.
- change leverage or margin.
- enable live trading.
- deploy or release to any environment.
- run any production migration.
- expose or commit any credential.
- approve the live gate.

## Cross-isolation paths (must NOT be modified by 2F.C)

The implementation task and the Codex review task MUST NOT cause any byte change under any of the following paths. The set is enforced by `git status -s` returning zero output lines outside the additive 2F.C scope:

- `/home/wali/Desktop/AI BOT`
- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/services/`
- `v2/backend/app/adapters/`
- `v2/backend/app/domain/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/frontend/`
- `v2/backend/tests/unit/__init__.py`
- `v2/backend/tests/unit/composition/__init__.py`
- `v2/backend/tests/unit/composition/trainer_parity/`
- `v2/backend/tests/unit/composition/trainer_worker_health/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/` (the 2F.C tasks `124` and `125` are CREATED ONCE by the planner and never modified again by 2F.C work)
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/00_PHASE_2F_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/02_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/03_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/04_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/05_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/06_2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/07_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/08_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/09_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/10_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/11_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/12_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/13_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/14_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/15_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/16_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/17_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/18_PHASE_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_SPEC.md` (this milestone's planning artifacts are emitted by the planner and immutable thereafter)
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/19_PHASE_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/20_PHASE_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/21_PHASE_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md`
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` artifact
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` artifact

## Forbidden runtime behaviors in authored 2F.C source files

The three authored source files (`__init__.py`, `errors.py`, `runtime.py`) MUST NOT exhibit any of the following runtime behaviors at module scope or at any call site reachable from public API:

- live behavior of any kind
- any literal `red` + `is` access at any layer
- any literal `red` + `is` command at any time
- any legacy mutation
- any release intent in any environment
- any modification of any prior-milestone source or test file
- any FastAPI lifespan or router or singleton or cache or wall-clock helper
- any `os.environ` or `subprocess` (outside test files only) or `socket` use
- any direct literal `red` + `is` or `url` + `_env` or factory import
- any URL or credential leakage
- any `trainer_worker_health`, `trainer_parity`, or `trainer_prediction_output` service or composition import in any authored 2F.C source file
- any `now_ms_clock` invocation at build time
- any `assemble_orchestrator_decision_record` invocation at build time
- any threshold mutation at runtime
- any caller-supplied input mutation
- any REQ_0017 scope-cap violation (no risk gateway, no execution-side surface, no FastAPI surface, no adapter expansion, no expansion of the binder beyond the two build-time parameters and the one call-time `prediction` parameter; no checkpoint runner, no GPU runner, no model-loading subsystem)

## REQ_0017 / REQ_0020 scope cap

Phase 2F.C closes Phase 2F. The 2F.C milestone MUST NOT, in code or in artifact:

- introduce risk-gateway behavior, risk-gate result types, or risk-decision lineage IDs.
- introduce execution-side surface, paper ledger, or replay runner.
- introduce a FastAPI or HTTP surface.
- introduce an adapter (`v2/backend/app/adapters/`) or a service-layer expansion outside the existing 2F.B boundary.
- introduce strategy-library logic.
- introduce model-loading, GPU, or checkpoint subsystem expansion.
- introduce a new lineage ID at the composition layer beyond the `decision_id` already derived inside the 2F.B service.

When 2F.C Codex review PASSes, the planner closes Phase 2F entirely, satisfies REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP`, and opens REQ_0017 milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP` under a fresh consolidated milestone turn.

## Stop conditions

On any of the following, write FAIL/FAILED to the appropriate go-no-go file, document the violation in the implementation report or Codex review report, and stop. Do NOT autofix in either task; the supervisor dispatches a separate REQ_0007 / REQ_0014 autofix task when and only when the failure is concrete, non-safety, and scoped to the 2F.C authored source files plus the 2F.C test files:

- live action requested
- legacy mutation requested
- `red` + `is` write or delete required
- live service restart required
- exchange action required
- deployment required
- secret scan failure
- ambiguous trading or business decision requiring human judgment
- final live approval requested
- any modification of any prior-milestone artifact
- any modification of any 2F.C planning artifact at 18-21 after the planner emits them
- any modification of any task definition under `claude_worklog/agent_supervisor/tasks/`
- any modification of the master planner prompt

PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY
