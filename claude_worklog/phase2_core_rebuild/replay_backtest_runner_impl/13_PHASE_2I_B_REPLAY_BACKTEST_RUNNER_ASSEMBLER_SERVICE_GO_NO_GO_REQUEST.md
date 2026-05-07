# Phase 2I.B — Replay/Backtest Runner Assembler Service GO/NO-GO Request

## Predecessor gates

- `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md` — REQUIRED.
- `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md` — REQUIRED.

If either is absent or different, NO-GO.

## Lane lock

- lane: paper_backtest_mvp
- mvp_relevance: opens REQ_0017 milestone 5 second sub-step. Builds the pure derivation surface that maps a 2H-validated `PaperExecutionLedgerEntry` and a 2I.A-validated `ReplayBacktestRun` into a frozen `ReplayBacktestStep` with full lineage propagation, plus an aggregate `ReplayBacktestSummary` whose three partition-sum equalities hold by construction. Distance to V2_BACKTEST_AND_PAPER_MVP_READY remains 3 milestones; 2I.B advances inside-2I work from 1/3 to 2/3.
- blocked_by: PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS; PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED
- next_gate: PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED

## Authored files (exact set)

- `v2/backend/app/services/replay_backtest_runner/__init__.py`
- `v2/backend/app/services/replay_backtest_runner/errors.py`
- `v2/backend/app/services/replay_backtest_runner/service.py`
- `v2/backend/tests/unit/services/replay_backtest_runner/__init__.py` (zero bytes)
- 40 sibling test files per `11_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/14_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md`

## Validation matrix

- py_compile of all three authored source files
- pytest of `v2/backend/tests/unit/services/replay_backtest_runner/`
- pytest of `v2/backend/tests/unit/domain/replay_backtest_runner/` (must remain green)
- pytest of `v2/backend/tests/unit/services/paper_execution_ledger/` (must remain green)
- pytest of `v2/backend/tests/unit/domain/paper_execution_ledger/` (must remain green)
- pytest of `v2/backend/tests/unit/services/risk_gateway/` (must remain green)
- pytest of `v2/backend/tests/unit/domain/risk_gateway/` (must remain green)
- pytest of `v2/backend/tests/unit/services/orchestrator_decision/` (must remain green)
- pytest of `v2/backend/tests/unit/domain/orchestrator_decision/` (must remain green)
- pytest of `v2/backend/tests/unit/domain/trainer_prediction_output/` (must remain green)
- forbidden-token scan of `v2/backend/app/services/replay_backtest_runner/` (zero matches per token)
- subprocess-based import-isolation tests for redis / url_env / fastapi

## Safety review

All boundaries from `12_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md` must report "none observed" in the implementation report.

## Outcome marker

- PASS path: `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` written to `15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md`.
- FAIL path: `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_FAILED` written to `15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md` with violation captured in 14.

PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST_READY
