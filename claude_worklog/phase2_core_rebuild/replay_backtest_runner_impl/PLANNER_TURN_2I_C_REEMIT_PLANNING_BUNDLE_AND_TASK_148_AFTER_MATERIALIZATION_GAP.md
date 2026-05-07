# Planner Turn — Re-Emit 2I.C Planning Bundle and Task 148 After Materialization Gap

## Date

2026-05-07.

## Active requirement and lane

- Active requirement: REQ_0006 ∩ REQ_0017 (replay/backtest runner MVP).
- Lane: `paper_backtest_mvp` for the implementation task `148`; `codex_watchdog` for the Codex review task `149`.
- Current MVP milestone: `REPLAY_BACKTEST_RUNNER_MVP` (REQ_0017 milestone 5).
- Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 3 milestones remaining; drops to 2 once 2I.C Codex passes.

## Materialization gap diagnosis

The prior planner turn `PLANNER_TURN_2I_OPEN_2I_C_AFTER_2I_B_CODEX_PASS.md` declared the 2I.C planning bundle (`18`, `19`, `20`, `21`) and the consolidated implementation / Codex tasks (`148`, `149`) emitted, but only the planner-turn note itself, the parallel-capacity Lane C readonly-review marker for 2I.A, and the Codex review task `149_replay_backtest_runner_2ic_composition_root_codex_review.json` were materialized into the working tree. Files `18`, `19`, `20`, `21` and the implementation task `148_replay_backtest_runner_2ic_composition_root_implementation.json` did NOT land.

Evidence verified before this re-emission:

- `git ls-files claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/ | grep -E '^(18|19|20|21|22|23|24|25)_'` returns zero output lines.
- `git ls-files claude_worklog/agent_supervisor/tasks/148_replay_backtest_runner_2ic_composition_root_implementation.json` returns zero output lines.
- `git ls-files claude_worklog/agent_supervisor/tasks/149_replay_backtest_runner_2ic_composition_root_codex_review.json` returns exactly one output line.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md` contains exactly `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/17_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` contains exactly `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS`.
- `git status --porcelain` returns exactly the planner-prompt dirty entry that the supervisor's worktree-isolation contract excludes; no other dirty entry is present.

Both predecessor markers required by `00_PHASE_2I_SUB_PHASE_BREAKDOWN.md` for opening 2I.C remain present. Task `149` already on disk references task `148` as its predecessor and references `23_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO.md` as its predecessor marker file; both will be created by the implementation task. Task `149` is byte-identical to its prior on-disk content and is NOT re-emitted in this turn.

The prior planner-turn note `PLANNER_TURN_2I_OPEN_2I_C_AFTER_2I_B_CODEX_PASS.md` is committed and is NOT modified. This turn note is additive and supersedes the prior note's "Seven artifacts emitted" language by acknowledging that only one of the supervisor tasks (`149`) and the planner-turn note itself landed in the prior turn, and that this turn re-emits the missing five artifacts (`18`, `19`, `20`, `21`, `148`) plus this acknowledgment note.

## Decision

Re-emit the missing 2I.C planning bundle (`18`, `19`, `20`, `21`) and the missing implementation task `148_replay_backtest_runner_2ic_composition_root_implementation.json`, preserving every contract decision documented in the prior planner-turn note. Specifically:

- 2I.C composition root binds a single `now_ms_clock` once at build time.
- The binder returns a slotted `ReplayBacktestRunner` instance whose two-attribute surface (`assemble_step`, `assemble_summary`) exposes two keyword-only assembler closures.
- Both closures share the same captured clock identity; the binder MUST NOT invoke either assembler service or the clock at build time.
- Service and domain errors raised by the 2I.B service propagate unchanged through the closures.
- No direct construction of `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` in any authored 2I.C source file. No upstream `RiskDecisionRecord` or `OrchestratorDecisionRecord` import.
- The 2I.C package lives at `v2/backend/app/composition/replay_backtest_runner/` as a sibling of the existing composition packages. The `v2/backend/app/composition/__init__.py` package marker is reused as-is and is NOT re-emitted by this milestone.

The planner emits the consolidated 2I.C planning bundle (`18`, `19`, `20`, `21`) and the consolidated implementation task `148` in this turn. Task `149` is already on disk and is NOT re-emitted. Sub-task split is reserved for recovery only, per the consolidated_default planner profile.

## Sequencing

1. Supervisor verifies dispatch preconditions: clean worktree (with the standing exclusions for the planner prompt and durable Lane C parallel-capacity markers), 2I.B markers materialized, the new 2I.C planning artifacts (`18`, `19`, `20`, `21`) materialized, and the cross-isolation diff is clean.
2. Supervisor dispatches `148_replay_backtest_runner_2ic_composition_root_implementation`.
3. On `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at `23_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO.md`, supervisor dispatches `149_replay_backtest_runner_2ic_composition_root_codex_review`.
4. On `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at `25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`, the planner closes Phase 2I, marks REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` satisfied, and opens REQ_0017 milestone 6 `PAPER_MODE_MVP` under a fresh consolidated milestone turn.
5. On any concrete-blocker FAIL with no safety violation at either step, supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the 2I.C authored source files plus the 35 new test files only. On any safety violation at either step, surface to human attention; no autofix is permitted.

## Codex parallel lane disposition

While `148` is dispatched and the worktree is dirty for 2I.C build output, Codex parallel review activity is restricted to read-only diagnostics on already-committed milestones (Lane C `codex_watchdog`). Codex may not patch dirty 2I.C output until `148` completes and lands. Once `148` lands and the worktree is clean, Codex may be dispatched on `149` (in-lane Codex review of 2I.C) per the parallel capacity scheduler in REQ_0021.

## Hard safety still in force

- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis writes / deletes.
- No live service restart.
- No exchange / order / leverage / margin action.
- No deployment.
- No live trading enablement.
- No secret exposure.
- No L4 / L5 action without explicit human approval.
- Final live gate remains human-only.

## Authored artifacts (this turn)

Planning bundle (re-emission):

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/18_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SPEC.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/19_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/20_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/21_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md`

Supervisor task (re-emission):

- `claude_worklog/agent_supervisor/tasks/148_replay_backtest_runner_2ic_composition_root_implementation.json`

Planner turn note (this file):

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_REEMIT_PLANNING_BUNDLE_AND_TASK_148_AFTER_MATERIALIZATION_GAP.md`

Not re-emitted (already on disk byte-identical):

- `claude_worklog/agent_supervisor/tasks/149_replay_backtest_runner_2ic_composition_root_codex_review.json`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_OPEN_2I_C_AFTER_2I_B_CODEX_PASS.md`

## Legacy evidence consulted

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/legacy_runtime_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`
- 2H.C composition-root precedent (`v2/backend/app/composition/paper_execution_ledger/` and the 2H.C planning artifacts at 19-22, 25, 26 under `paper_execution_ledger_impl/`).
- 2I.B service surface (`v2/backend/app/services/replay_backtest_runner/__init__.py`, `errors.py`, `service.py`).

## Legacy failure addressed

Legacy replay/backtest tooling forced every downstream consumer to re-thread `now_ms_clock` through every call site, increasing the surface for clock-drift / clock-rebinding bugs and making it impossible to assert clock-identity invariants across step and summary calls. The 2I.C composition root introduces a typed pure-binder boundary that captures the wall-clock reference once at build time and adapts the 2I.B assembler-service surface for downstream paper / shadow / explainability consumers. Both inner closures share the same captured clock; the slotted `ReplayBacktestRunner` class enforces a fixed two-attribute surface so consumers cannot accidentally attach foreign state to the runner. This forms the consumable surface for REQ_0017 milestone 6 `PAPER_MODE_MVP` and milestone 7 `SHADOW_MODE_READINESS` without coupling those downstream milestones to the assembler-service module path.

## V2 proof gate

Phase 2I closes when `25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` materializes the marker `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`. At that point REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` is satisfied; the planner opens REQ_0017 milestone 6 `PAPER_MODE_MVP` under a fresh consolidated milestone turn.

PLANNER_TURN_2I_C_REEMIT_PLANNING_BUNDLE_AND_TASK_148_AFTER_MATERIALIZATION_GAP_READY
