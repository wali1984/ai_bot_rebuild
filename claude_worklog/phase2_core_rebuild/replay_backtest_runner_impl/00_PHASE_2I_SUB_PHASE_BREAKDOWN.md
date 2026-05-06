# Phase 2I Sub-Phase Breakdown — Replay/Backtest Runner MVP

Phase 2I implements REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP`. It is the minimum-viable typed surface that consumes the paper-execution-ledger mirror produced by Phase 2H and projects it as a structured replay/backtest run with per-step lineage and an aggregate summary. Phase 2I MUST NOT expand into a paper trader process, a replay engine, a scheduler, a background loop, a strategy library, a FastAPI surface, a model/GPU/checkpoint subsystem, persistent storage, PnL/sizing computation, or any execution-side surface.

Each sub-phase is dispatched only after its predecessor's Codex review PASS marker is materialized. Sub-phases land sequentially. No sub-phase opens out of order.

## 2I.A — Replay/backtest runner domain (this turn)

- Surface: `v2/backend/app/domain/replay_backtest_runner/` (NEW package; sibling of `v2/backend/app/domain/paper_execution_ledger/`).
- Files written: `__init__.py`, `errors.py`, `run.py`, `step.py`, `summary.py`.
- Public surface: `ReplayBacktestRunnerDomainError`, `ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`, two run-mode constants, two step-action constants, five step-reason constants (see 02 spec).
- Tests written: `v2/backend/tests/unit/domain/replay_backtest_runner/` (51 test files plus a zero-byte `__init__.py`, enumerated in `03_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_TEST_PLAN.md`).
- Predecessor marker: `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (reconciled per `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` mirroring the 2H.A/2H.B precedent).
- Implementation gate: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`.
- Implementation task: `143`. Codex review task: `144`.

## 2I.B — Replay/backtest runner assembler service (later milestone)

- Surface: `v2/backend/app/services/replay_backtest_runner/` (NEW package).
- Pure function `assemble_replay_backtest_step(*, paper_ledger_entry: PaperExecutionLedgerEntry, replay_run: ReplayBacktestRun, now_ms_clock: Callable[[], int]) -> ReplayBacktestStep` that takes a validated `PaperExecutionLedgerEntry`, an in-flight `ReplayBacktestRun`, and a `now_ms_clock` callable; returns a frozen `ReplayBacktestStep`. The mirror taxonomy maps exhaustively from paper-ledger taxonomy to step taxonomy:
  - paper `record_allow` / `mirror_allow_proceed_long` → step `step_record_allow` / `step_mirror_allow_proceed_long`
  - paper `record_allow` / `mirror_allow_proceed_short` → step `step_record_allow` / `step_mirror_allow_proceed_short`
  - paper `record_deny` / `mirror_deny_orchestrator_held` → step `step_record_deny` / `step_mirror_deny_orchestrator_held`
  - paper `record_deny` / `mirror_deny_orchestrator_abstained` → step `step_record_deny` / `step_mirror_deny_orchestrator_abstained`
  - paper `record_deny` / `mirror_deny_default` → step `step_record_deny` / `step_mirror_deny_default`
- A second pure function `assemble_replay_backtest_summary(*, replay_run: ReplayBacktestRun, steps: tuple[ReplayBacktestStep, ...], now_ms_clock: Callable[[], int]) -> ReplayBacktestSummary` produces the aggregate. The new lineage IDs `replay_step_id` and `replay_summary_id` are derived inside 2I.B; 2I.A only validates the resulting strings.
- Predecessor marker: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`.

## 2I.C — Replay/backtest runner composition root (later milestone)

- Surface: `v2/backend/app/composition/replay_backtest_runner/` (NEW package).
- Pure binder `build_replay_backtest_runner(*, now_ms_clock: Callable[[], int]) -> ReplayBacktestRunner` that captures the static `now_ms_clock` callable at build time and returns a single-call runner that adapts the 2I.B service. No persistence; the runner returns the value objects to its caller.
- Predecessor marker: `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS`.

## Domain placeholder reuse decision

`v2/backend/app/domain/replay/` exists as a 015A scaffold placeholder (zero-byte `__init__.py` and a one-line `deterministic.py` docstring) committed in `26e49b7 Materialize 015A V2 repo package skeleton`. It is left UNCHANGED by Phase 2I. The new 2I.A package lives at `v2/backend/app/domain/replay_backtest_runner/` to make the replay/backtest runner boundary explicit and to leave room for any future replay-only or backtest-only narrower domain. This mirrors the 2H.A precedent where `domain/paper_execution_ledger/` was created as a sibling of the placeholder `domain/execution/` rather than reusing the placeholder.

`v2/backend/app/services/replay_runner.py` is a one-line scaffold placeholder docstring file. It is left UNCHANGED by Phase 2I. 2I.B opens with `allowed_output_prefixes` scoped to the new `services/replay_backtest_runner/` package and an explicit `forbidden_output_paths` entry preventing any modification of `replay_runner.py`. The same posture is used at the composition layer if a similar placeholder exists at the time 2I.C opens.

## Sequencing rule

If `144` (Codex review of 2I.A) returns FAIL with concrete blockers and no safety violation, the planner enqueues a remediation autofix task under REQ_0007 / REQ_0014 scoped to the 2I.A authored files only and does not advance to 2I.B. If `144` returns PASS, the planner opens a new turn to author the 2I.B scope and dispatch its tasks.

## Phase exit (closing Phase 2I → opening REQ_0017 milestone 6)

Phase 2I closes when the 2I.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 5 (`REPLAY_BACKTEST_RUNNER_MVP`) is satisfied and the planner opens REQ_0017 milestone 6 (`PAPER_MODE_MVP`). No live execution behavior, no paper trader process, no strategy library, no replay engine, and no scheduler is opened in between.

PHASE2I_REPLAY_BACKTEST_RUNNER_MVP_PHASE_BREAKDOWN_READY
