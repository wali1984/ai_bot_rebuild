# Phase 2I.C — Replay/Backtest Runner Composition Root Safety Boundaries

This document fixes the safety boundaries for Phase 2I.C of REQ_0006 ∩ REQ_0017. It MUST be enforced by both the implementation task and the Codex review task. Any violation is an unconditional FAIL with no autofix path; surface to human attention.

## Hard live-gate boundaries

The 2I.C milestone MUST NOT, in any layer, in any code path, at any time:

- modify `/home/wali/Desktop/AI BOT`.
- read or write any literal `red`+`is` key.
- invoke any literal `red`+`is` command at any time.
- restart any live trainer, trader, orchestrator, ingestor, or `red`+`is` service.
- place, cancel, or modify any exchange order.
- change leverage or margin.
- enable live trading.
- deploy or release to any environment.
- run any production migration.
- expose or commit any credential.
- approve the live gate.

## Cross-isolation paths (must NOT be modified by 2I.C)

The implementation task and the Codex review task MUST NOT cause any byte change under any of the following paths. The set is enforced by `git status -s` returning zero output lines outside the additive 2I.C scope:

- `/home/wali/Desktop/AI BOT`
- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/composition/paper_execution_ledger/`
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
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/composition/trainer_parity/`
- `v2/backend/tests/unit/composition/trainer_worker_health/`
- `v2/backend/tests/unit/composition/trainer_prediction_output/`
- `v2/backend/tests/unit/composition/paper_execution_ledger/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/` (the 2I.C tasks `148` and `149` are CREATED ONCE by the planner and never modified again by 2I.C work)
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/decision_explainability/` (entire directory)
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/00_PHASE_2I_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/03_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/04_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/05_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/06_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/08_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/10_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/11_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/12_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/13_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/14_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/16_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/17_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/18_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SPEC.md` (this milestone's planning artifacts are emitted by the planner and immutable thereafter)
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/19_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/20_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/21_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md`
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` artifact
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` artifact

## Forbidden runtime behaviors in authored 2I.C source files

The three authored source files (`__init__.py`, `errors.py`, `runtime.py`) MUST NOT exhibit any of the following runtime behaviors at module scope or at any call site reachable from public API:

- live behavior of any kind
- any literal `red`+`is` access at any layer
- any literal `red`+`is` command at any time
- any legacy mutation
- any release intent in any environment
- any modification of any prior-milestone source or test file
- any FastAPI lifespan or router or singleton or cache or wall-clock helper
- any `os.environ` or `subprocess` (outside test files only) or `socket` use
- any direct literal `red`+`is` or `url`+`_env` or factory import
- any URL or credential leakage
- any `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, `orchestrator_decision`, `risk_gateway`, or `paper_execution_ledger` service or composition import in any authored 2I.C source file (the `paper_execution_ledger` domain `PaperExecutionLedgerEntry` value-object import is the only allowed reference into the 2H.A domain layer)
- any `now_ms_clock` invocation at build time
- any `assemble_replay_backtest_step` or `assemble_replay_backtest_summary` invocation at build time
- any direct construction of `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` in authored 2I.C source files (value-object construction is the responsibility of the 2I.B assembler service alone)
- any caller-supplied input mutation
- any import or emission of `RiskDecisionRecord` or `OrchestratorDecisionRecord` in any authored 2I.C source file
- any import or emission of `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, or the literal `mirror_deny_default` in any authored 2I.C source file
- any successful construction of a `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` with `live_blocked == False` (the 2H.B and 2I.B services hard-code `live_blocked=True`; 2I.C only forwards)
- any reintroduction of any prior-milestone placeholder
- any introduction of a `v2/backend/app/composition/replay_backtest_runner.py` flat-file placeholder
- any modification of `v2/backend/app/services/replay_runner.py`
- any modification of `v2/backend/app/services/paper_loop.py`
- any population of `v2/backend/app/domain/execution/`
- any introduction of replay or ledger persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger)
- any introduction of PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted-return computation
- any REQ_0017 scope-cap violation (no execution-side surface beyond the existing 2H.A / 2H.B / 2H.C ledger boundary plus the 2I.A / 2I.B / 2I.C replay/backtest runner boundary, no paper executor, no shadow executor, no replay engine, no scheduler, no background loop, no paper trader process, no strategy library, no FastAPI surface, no adapter expansion, no expansion of the binder beyond the one build-time `now_ms_clock` parameter and the slotted runner's two attribute closures; no checkpoint runner, no GPU runner, no model-loading subsystem; no new lineage ID at the composition layer beyond the `replay_step_id` and `replay_summary_id` already derived inside the 2I.B service)

## REQ_0017 / REQ_0020 scope cap

Phase 2I.C closes Phase 2I. The 2I.C milestone MUST NOT, in code or in artifact:

- introduce execution-side surface beyond the existing 2H ledger boundary plus the existing 2I replay/backtest runner boundary, paper executor, shadow executor, replay engine, scheduler, background loop, paper trader process, or strategy library.
- introduce a FastAPI or HTTP surface.
- introduce an adapter (`v2/backend/app/adapters/`) or a service-layer expansion outside the existing 2I.B boundary.
- introduce strategy-library logic.
- introduce model-loading, GPU, or checkpoint subsystem expansion.
- introduce a new lineage ID at the composition layer beyond the `replay_step_id` and `replay_summary_id` already derived inside the 2I.B service.
- import or reference `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, or the literal `mirror_deny_default`.
- introduce replay or ledger persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger).
- introduce PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted-return computation.

When 2I.C Codex review PASSes, the planner closes Phase 2I entirely, satisfies REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP`, and opens REQ_0017 milestone 6 `PAPER_MODE_MVP` under a fresh consolidated milestone turn.

## Stop conditions

On any of the following, write FAIL/FAILED to the appropriate go-no-go file, document the violation in the implementation report or Codex review report, and stop. Do NOT autofix in either task; the supervisor dispatches a separate REQ_0007 / REQ_0014 autofix task when and only when the failure is concrete, non-safety, and scoped to the 2I.C authored source files plus the 2I.C test files:

- live action requested
- legacy mutation requested
- `red`+`is` write or delete required
- live service restart required
- exchange action required
- deployment required
- secret scan failure
- ambiguous trading or business decision requiring human judgment
- final live approval requested
- any modification of any prior-milestone artifact
- any modification of any 2I.C planning artifact at 18-21 after the planner emits them
- any modification of any task definition under `claude_worklog/agent_supervisor/tasks/`
- any modification of the master planner prompt
- any import or emission of `RiskDecisionRecord` or `OrchestratorDecisionRecord`
- any import or emission of `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, or the literal `mirror_deny_default`
- any direct construction of a `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` in an authored 2I.C source file
- any successful construction of a `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` with `live_blocked == False`
- any introduction of a `v2/backend/app/composition/replay_backtest_runner.py` flat-file placeholder
- any modification of `v2/backend/app/services/replay_runner.py` or `v2/backend/app/services/paper_loop.py`
- any population of `v2/backend/app/domain/execution/`
- any introduction of replay or ledger persistence
- any introduction of PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted-return computation

PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY
