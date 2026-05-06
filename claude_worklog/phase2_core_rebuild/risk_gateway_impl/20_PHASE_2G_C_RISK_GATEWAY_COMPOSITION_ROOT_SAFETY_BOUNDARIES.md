# Phase 2G.C — Risk Gateway Composition Root Safety Boundaries

This document fixes the safety boundaries for Phase 2G.C of REQ_0006 ∩ REQ_0017. It MUST be enforced by both the implementation task (`131`) and the Codex review task (`132`). Any violation is an unconditional FAIL with no autofix path; surface to human attention.

## Hard live-gate boundaries

The 2G.C milestone MUST NOT, in any layer, in any code path, at any time:

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

## Cross-isolation paths (must NOT be modified by 2G.C)

The implementation task and the Codex review task MUST NOT cause any byte change under any of the following paths. The set is enforced by `git status -s` returning zero output lines outside the additive 2G.C scope:

- `/home/wali/Desktop/AI BOT`
- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/`
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
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `v2/backend/tests/unit/composition/trainer_parity/`
- `v2/backend/tests/unit/composition/trainer_worker_health/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/` (the 2G.C tasks `131` and `132` are CREATED ONCE by the planner and never modified again by 2G.C work)
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/00_PHASE_2G_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/01_PHASE_2G_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/02_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/03_PHASE_2G_A_RISK_GATEWAY_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/04_PHASE_2G_A_RISK_GATEWAY_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/05_PHASE_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/06_2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/08_2G_A_RISK_GATEWAY_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/10_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/11_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/12_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/13_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/16_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/18_PHASE_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_SPEC.md` (this milestone's planning artifacts are emitted by the planner and immutable thereafter)
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/19_PHASE_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/20_PHASE_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/21_PHASE_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md`
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` artifact
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` artifact

## Forbidden runtime behaviors in authored 2G.C source files

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
- any `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, or `orchestrator_decision` service or composition import in any authored 2G.C source file
- any `now_ms_clock` invocation at build time
- any `assemble_risk_decision_record` invocation at build time
- any caller-supplied input mutation
- any import or emission of `RISK_DECISION_REASON_DENY_DEFAULT` or the literal `deny_default` in any authored 2G.C source file
- any successful construction of a record with `live_blocked == False` (the 2G.B service hard-codes `live_blocked=True`; 2G.C only forwards)
- any reintroduction of any prior-milestone placeholder (notably `v2/backend/app/services/risk_gateway.py` deleted by 2G.B)
- any REQ_0017 scope-cap violation (no execution-side surface, no paper executor, no shadow executor, no replay runner, no paper ledger, no FastAPI surface, no adapter expansion, no expansion of the binder beyond the one build-time `now_ms_clock` parameter and the one call-time `decision` parameter; no checkpoint runner, no GPU runner, no model-loading subsystem; no new lineage ID at the composition layer beyond the `risk_decision_id` already derived inside the 2G.B service)

## REQ_0017 / REQ_0020 scope cap

Phase 2G.C closes Phase 2G. The 2G.C milestone MUST NOT, in code or in artifact:

- introduce execution-side surface, paper ledger, replay runner, paper executor, shadow executor, or strategy library.
- introduce a FastAPI or HTTP surface.
- introduce an adapter (`v2/backend/app/adapters/`) or a service-layer expansion outside the existing 2G.B boundary.
- introduce strategy-library logic.
- introduce model-loading, GPU, or checkpoint subsystem expansion.
- introduce a new lineage ID at the composition layer beyond the `risk_decision_id` already derived inside the 2G.B service.
- import or emit `RISK_DECISION_REASON_DENY_DEFAULT` or the literal `deny_default`.

When 2G.C Codex review PASSes, the planner closes Phase 2G entirely, satisfies REQ_0017 milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`, and opens REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP` under a fresh consolidated milestone turn.

## Stop conditions

On any of the following, write FAIL/FAILED to the appropriate go-no-go file, document the violation in the implementation report or Codex review report, and stop. Do NOT autofix in either task; the supervisor dispatches a separate REQ_0007 / REQ_0014 autofix task when and only when the failure is concrete, non-safety, and scoped to the 2G.C authored source files plus the 2G.C test files:

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
- any modification of any 2G.C planning artifact at 18-21 after the planner emits them
- any modification of any task definition under `claude_worklog/agent_supervisor/tasks/`
- any modification of the master planner prompt
- any import or emission of `RISK_DECISION_REASON_DENY_DEFAULT` or the literal `deny_default`
- any successful construction of a `RiskDecisionRecord` with `live_blocked == False`
- any reintroduction of `v2/backend/app/services/risk_gateway.py` placeholder

PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY
