# Phase 2K.C — Shadow-Mode-Readiness Flag Composition Root Safety Boundaries

This document fixes the safety boundaries for Phase 2K.C of REQ_0006 ∩ REQ_0017. It MUST be enforced by both the implementation task and the Codex review task. Any violation is an unconditional FAIL with no autofix path; surface to human attention.

## Hard live-gate boundaries

The 2K.C milestone MUST NOT, in any layer, in any code path, at any time:

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

## Cross-isolation paths (must NOT be modified by 2K.C)

The implementation task and the Codex review task MUST NOT cause any byte change under any of the following paths. The set is enforced by `git status -s` returning zero output lines outside the additive 2K.C scope:

- `/home/wali/Desktop/AI BOT`
- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/composition/paper_execution_ledger/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/composition/paper_mode/`
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
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/paper_mode/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/` (the 2K.C tasks `160` and `161` are CREATED ONCE by the planner and never modified again by 2K.C work)
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/decision_explainability/` (entire directory)
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` (entire directory)
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/` (entire directory)
- `claude_worklog/phase2_core_rebuild/automation_reliability/` (entire directory)
- `claude_worklog/phase2_core_rebuild/legacy_evidence/` (entire directory)
- `claude_worklog/phase2_core_rebuild/legacy_service_map/` (entire directory)
- `claude_worklog/phase2_core_rebuild/symbol_universe/` (entire directory)
- `claude_worklog/phase2_core_rebuild/feature_snapshots/` (entire directory)
- `claude_worklog/phase2_core_rebuild/ingestors/` (entire directory)
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` (entire directory)
- `claude_worklog/phase2_core_rebuild/frontend_design/` (entire directory)
- any prior 2K.A artifact at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/00-09`
- any prior 2K.B artifact at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/10-17`
- the 2K.C planning artifacts at `18-21` themselves once written
- the existing 2K PLANNER_TURN notes at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/PLANNER_TURN_2K_OPEN_SHADOW_MODE_READINESS.md`, `PLANNER_TURN_2K_B_OPEN_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE.md`, and `PLANNER_TURN_2K_C_OPEN_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT.md`

## Forbidden output paths

The implementation task MUST NOT write to any path outside the additive 2K.C scope. The supervisor enforces this via `forbidden_output_paths` on task `160`. The 2K.C composition-root implementation does NOT modify the 2K.B service surface, the 2K.A domain surface, the 2J.C / 2J.B / 2J.A paper-mode surface, the 2I.C / 2I.B / 2I.A replay/backtest runner surface, the 2H.C / 2H.B / 2H.A paper execution ledger surface, the 2G.C / 2G.B / 2G.A risk gateway surface, the 2F.C / 2F.B / 2F.A orchestrator decision surface, or any 2E1 / 2E2 / 2E3 trainer parity surface.

## Cross-isolation invariants

Phase 2K.C authors no file under any of the following paths and modifies no byte of any prior-milestone file:

- `v2/backend/app/composition/__init__.py`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/composition/trainer_parity/`
- `v2/backend/app/composition/trainer_worker_health/`
- `v2/backend/app/composition/trainer_prediction_output/`
- `v2/backend/app/composition/paper_execution_ledger/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/composition/paper_mode/`
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
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/paper_mode/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`
- `claude_worklog/autonomous_control_plane/`
- `claude_worklog/agent_supervisor/tasks/`
- `claude_worklog/security/`
- `claude_worklog/requirements_inbox/`
- any `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and `trainer_gpu_parity_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/decision_explainability/` artifact
- any `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/paper_mode_impl/` artifact
- any `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/` artifact at 00-17 (prior 2K.A and 2K.B artifacts) and the 2K.C planning artifacts at 18-21 themselves once written

## Hard stops

The 2K.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file authored in Phases 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, 2I.C, 2J.A, 2J.B, 2J.C, 2K.A, or 2K.B.
- read or write any literal `red`+`is` key.
- invoke any literal `red`+`is` command.
- restart any live service.
- place or cancel any exchange order.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run any production migration.
- expose or commit any credential.
- approve the live gate.
- emit a standalone marker line in any authored file body matching the harness BEGIN/END framing tokens.
- introduce any execution-side surface beyond the existing 2H.A / 2H.B / 2H.C ledger boundary plus the 2I.A / 2I.B / 2I.C replay/backtest runner boundary plus the 2J.A / 2J.B / 2J.C paper-mode flag boundary plus the 2K.A / 2K.B / 2K.C shadow-mode-readiness flag boundary; no paper executor, shadow executor, replay engine, scheduler, background loop, paper trader process, shadow trader process, or strategy library.
- introduce a FastAPI or HTTP surface.
- introduce an adapter or a service-layer expansion outside the existing 2K.B boundary.
- introduce model-loading, GPU, or checkpoint subsystem expansion.
- introduce a new lineage ID at the composition layer beyond the `flag_emitted_ts_ms` already derived inside the 2K.B service.
- import or reference `RiskDecisionRecord`, `OrchestratorDecisionRecord`, the reserved 2G.A constant `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, the literal `mirror_deny_default`, `PaperExecutionLedgerEntry`, `ReplayBacktestStep`, `ReplayBacktestSummary`, `ReplayBacktestRun`, or `PaperModeFlag` in any authored 2K.C source file.
- introduce ledger or replay persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger).
- introduce PnL, position sizing, quantity, price, fees, slippage, or risk-adjusted-return computation.
- modify `v2/backend/app/services/paper_loop.py`.
- modify `v2/backend/app/services/replay_runner.py`.
- populate `v2/backend/app/domain/replay/`.
- populate `v2/backend/app/domain/execution/`.
- introduce any `live`, `live_enabled`, or `enable_live` requested-state branch at the composition layer; the 2K.B service is the single boundary that resolves the mirror taxonomy, and it accepts only `not_ready` and `ready`.
- introduce any `SHADOW_MODE_LIVE_ENABLED`, `SHADOW_MODE_LIVE`, `live_enabled`, `enable_live`, or `shadow_decision_id` constant or token in any authored 2K.C source file.
- construct `ShadowModeReadinessFlag` directly in any authored 2K.C source file (the call-form token `ShadowModeReadinessFlag(` is on the forbidden-token list).
- call `now_ms_clock` or `assemble_shadow_mode_readiness_flag` at build time inside `build_shadow_mode_readiness_runtime`.
- call `now_ms_clock` more than once per inner-closure invocation.
- catch, wrap, or rewrap `ShadowModeReadinessServiceError` or `ShadowModeReadinessDomainError` in the inner closure.

## Codex review enforcement

The Codex review task `161` MUST verify all of the above. Codex MUST mark the milestone FAIL on any cross-isolation diff line, any forbidden-token match, any unsanctioned import, any FastAPI / HTTP / Redis / URL / wall-clock helper introduction, any direct construction of `ShadowModeReadinessFlag` in source, any module-level singleton/cache/lock, or any introduction of a `live` / `live_enabled` / `enable_live` requested-state branch at the composition layer.

PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY
