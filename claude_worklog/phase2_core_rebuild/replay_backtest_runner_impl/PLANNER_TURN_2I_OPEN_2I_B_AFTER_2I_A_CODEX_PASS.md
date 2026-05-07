# Phase 2I Planner Turn — Open Replay/Backtest Runner Assembler Service (2I.B)

Date: 2026-05-07
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md (replay/backtest runner lane co-active under REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 paper_backtest_mvp lane).
Active MVP milestone: REPLAY_BACKTEST_RUNNER_MVP, sub-step 2I.B replay/backtest runner assembler service.
Lane: paper_backtest_mvp.
Planner state: ADVANCE — Phase 2I.A landed PASS (06 implementation report, 07 IMPL_AND_VALIDATION_PASSED, 08 Codex review, 09 CODEX_PASS); Phase 2I.B opened with consolidated planning artifacts plus tasks 146/147.

## Entry-state evidence

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md` contains exactly `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md` contains exactly `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/08_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_REVIEW.md` recommends PASS with zero concrete blockers and zero safety violations across 60 PASS rubric findings, 51 unit tests passing in the new package, and four prior-milestone test packages remaining green (paper_execution_ledger 30 / risk_gateway 32 / orchestrator_decision 34 / trainer_prediction_output 31).
- `git status --porcelain` at this turn entry shows the two untracked Codex review artifacts (08, 09) plus the master planner prompt MVP-milestone string update. The codex watchdog will commit these per REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016. Dispatch of 146 is gated on the supervisor's clean-worktree precondition.

## What this turn emits

This turn emits exactly the consolidated Phase 2I.B planning bundle, the 2I.B implementation and Codex-review task definitions, and this planner-turn note. Seven artifacts total:

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/10_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/11_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/12_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/13_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`
- `claude_worklog/agent_supervisor/tasks/146_replay_backtest_runner_2ib_assembler_service_implementation.json`
- `claude_worklog/agent_supervisor/tasks/147_replay_backtest_runner_2ib_assembler_service_codex_review.json`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_OPEN_2I_B_AFTER_2I_A_CODEX_PASS.md` (this note)

No 2I.A planning artifact (00-05) is modified. No 2I.A authored source or test file under `v2/backend/app/domain/replay_backtest_runner/` or `v2/backend/tests/unit/domain/replay_backtest_runner/` is modified. No prior-milestone V2 source or test file is modified. No master planner prompt is modified beyond the existing MVP-milestone string update tracked by the watchdog. No supervisor task definition outside the new 146/147 pair is modified.

## Decided next safest non-live rebuild milestone

`PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE`. Two pure assembler functions plus one service-level error class at a NEW package `v2/backend/app/services/replay_backtest_runner/`, sibling of `v2/backend/app/services/paper_execution_ledger/`. Three authored source files (`__init__.py`, `errors.py`, `service.py`) and the test-package `__init__.py` plus 40 single-test files at `v2/backend/tests/unit/services/replay_backtest_runner/`.

The new directory is deliberate: `v2/backend/app/services/replay_runner.py` exists as a 015A scaffold one-line docstring placeholder and is left UNCHANGED. This mirrors the 2H.B precedent where `services/paper_execution_ledger/` was created as a sibling package rather than reusing the placeholder file.

## Scope cap

2I.B is service-layer only. Out of scope and explicitly forbidden in 2I.B:
- composition-root binder (deferred to 2I.C)
- replay engine, scheduler, background loop, paper trader process, paper executor, shadow executor, strategy library
- PnL, position sizing, quantity, price, fees, slippage, risk-adjusted return
- ledger persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger)
- FastAPI surface, adapter expansion, GPU/checkpoint/model-loading subsystem
- module-level singleton, cache, lock primitive
- wall-clock helper invocation, `os.environ` / `os.getenv`, `subprocess` outside permitted import-isolation tests, `socket`, `logging`, `print(`
- any construction of `ReplayBacktestStep` or `ReplayBacktestSummary` with `live_blocked == False`
- modification of any 2I.A source or test file or planning artifact

## Lane and MVP relevance

- lane: paper_backtest_mvp
- mvp_relevance: opens REQ_0017 milestone 5 second sub-step. Builds the pure derivation surface that maps a 2H-validated `PaperExecutionLedgerEntry` and a 2I.A-validated `ReplayBacktestRun` into a frozen `ReplayBacktestStep` with full lineage propagation, plus an aggregate `ReplayBacktestSummary` whose three partition-sum equalities hold by construction. Distance to V2_BACKTEST_AND_PAPER_MVP_READY remains 3 milestones; 2I.B advances the inside-2I work from 1/3 to 2/3.
- blocked_by: PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS; PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED
- next_gate: PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED → PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS

## Legacy evidence consulted

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/legacy_runtime_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`
- 2H.B assembler service precedent: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/11_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC.md`
- 2I.A value-object surface: `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`
- 2H.A value-object precedent for the mirror taxonomy and `live_blocked` invariant
- REQ_0022 LAB hedge-unwind / squeeze failure case as the leading replay/backtest scenario class

## Legacy failure addressed

Legacy replay/backtest tooling lacked a typed pure-derivation boundary between paper-ledger entries and replay-step value objects, lacked a typed pure-derivation boundary between replay-step tuples and replay-summary value objects, and lacked aggregate counter integrity invariants. Aggregate counts could drift silently, lineage could break across the paper→step boundary, and a summary could be emitted with inconsistent partition sums. The 2I.B assembler service fixes these gaps at the service layer by enforcing a deterministic ordered validation pipeline, an exhaustive 5-row mirror derivation table from the paper-ledger taxonomy to the step taxonomy, a deterministic ordered count-aggregation pipeline, the 2I.A `live_blocked == True` invariant on every constructed value object, and the 2I.A summary partition-sum equalities by construction. The 2I.B service is the consumable surface for the upcoming 2I.C composition root, REQ_0017 milestone 6 PAPER_MODE_MVP, and REQ_0017 milestone 7 SHADOW_MODE_READINESS.

## Sequencing

Task `146_replay_backtest_runner_2ib_assembler_service_implementation` is held under `requires_clean_worktree` and the `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS` predecessor-marker precondition. The supervisor MUST verify the literal `_CODEX_PASS` marker in `09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md` is present and that `git status --porcelain` returns zero output lines under the dispatch worktree-isolation contract before dispatching 146. If 146 returns FAIL with concrete blockers and no safety violation, the planner enqueues a remediation autofix task under REQ_0007 / REQ_0014 scoped to the three authored source files plus the 40 new test files only and does not advance to 147. If 146 returns PASS, the supervisor dispatches 147 once the worktree is clean. If 147 returns FAIL, the codex autofix loop applies. If 147 returns PASS, the planner opens 2I.C in a subsequent consolidated milestone turn.

## Hard stops (unchanged)

- MUST NOT modify `/home/wali/Desktop/AI BOT`.
- MUST NOT read or write any Redis key.
- MUST NOT restart any live service.
- MUST NOT place or cancel exchange orders.
- MUST NOT change leverage or margin.
- MUST NOT enable live trading.
- MUST NOT deploy.
- MUST NOT run production migrations.
- MUST NOT expose or commit secrets.
- MUST stop on L4/L5, live/legacy/Redis/exchange/deploy/secrets, or Codex hard fail with no safe remediation.

PHASE2I_OPEN_2I_B_AFTER_2I_A_CODEX_PASS_PLANNER_TURN_READY
