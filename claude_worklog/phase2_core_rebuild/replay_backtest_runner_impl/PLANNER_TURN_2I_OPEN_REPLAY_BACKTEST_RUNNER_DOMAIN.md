# Phase 2I Planner Turn — Open Replay/Backtest Runner Domain (2I.A)

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md (replay/backtest runner lane is co-active under REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 paper_backtest_mvp lane).
Active MVP milestone (opening): REPLAY_BACKTEST_RUNNER_MVP, sub-step 2I.A replay/backtest runner domain.
Lane: paper_backtest_mvp.
Planner state: ADVANCE — Phase 2H closed (reconciled PASS on 2H.A/B/C); Phase 2I.A opened with consolidated planning artifacts plus tasks 143/144.

## What this turn emits

This turn emits exactly the consolidated Phase 2I.A planning bundle, the 2I.A implementation and Codex-review task definitions, and this planner-turn note. Nine artifacts total:

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/00_PHASE_2I_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/03_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/04_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/05_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO_REQUEST.md`
- `claude_worklog/agent_supervisor/tasks/143_replay_backtest_runner_2ia_domain_implementation.json`
- `claude_worklog/agent_supervisor/tasks/144_replay_backtest_runner_2ia_domain_codex_review.json`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_OPEN_REPLAY_BACKTEST_RUNNER_DOMAIN.md` (this note)

No 2H artifact is modified. No prior-milestone V2 source or test file is modified. No master planner prompt is modified. No supervisor task definition outside the new 143/144 pair is modified. The two unprocessed worklog files captured in the entry-state (the 2H.C reconciliation addendum 27_ and the 2H.C planner-turn note) are left as-is for the codex watchdog to commit and reconcile per the 2H.B precedent at `18_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.

## Why Phase 2I.A is opened in this turn

The prior planner turn (`PLANNER_TURN_2HC_RECONCILED_2H_CLOSED_2I_NEXT.md`) closed Phase 2H with reconciled PASS on 2H.A, 2H.B, and 2H.C, satisfied REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP`, and explicitly enumerated the consolidated artifact set the next planner turn must emit to open Phase 2I (`REPLAY_BACKTEST_RUNNER_MVP`). This turn fulfills that exact enumeration. The planner does not co-emit Phase 2I.B or 2I.C planning artifacts; those open in subsequent consolidated milestone turns gated on the 2I.A Codex pass marker.

## Decided next safest non-live rebuild milestone

`PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN`. Pure value objects (`ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`) at a NEW package `v2/backend/app/domain/replay_backtest_runner/`, sibling of `v2/backend/app/domain/paper_execution_ledger/`. Five authored source files (`__init__.py`, `errors.py`, `run.py`, `step.py`, `summary.py`) and 51 test files plus a zero-byte `__init__.py` test-package marker.

The new directory choice is deliberate: `v2/backend/app/domain/replay/` exists as a 015A scaffold placeholder (zero-byte `__init__.py` and a one-line `deterministic.py` docstring) and is left UNCHANGED. `v2/backend/app/services/replay_runner.py` is a one-line scaffold placeholder and is left UNCHANGED. `v2/backend/app/domain/execution/` 015A placeholders are left UNCHANGED. This mirrors the 2H.A precedent where `domain/paper_execution_ledger/` was created as a sibling of `domain/execution/` rather than reusing the placeholder directory.

## Scope cap

2I.A is value-object only. Out of scope and explicitly forbidden in 2I.A:
- replay engine, scheduler, background loop, paper trader process
- service-layer assembler (deferred to 2I.B)
- composition-root binder (deferred to 2I.C)
- PnL, position sizing, quantity, price, fees, slippage, risk-adjusted return
- ledger persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis)
- FastAPI surface, adapter expansion, GPU/checkpoint/model-loading subsystem, strategy library
- import of `v2.backend.app.domain.paper_execution_ledger` / `risk_gateway` / `orchestrator_decision` / `trainer_prediction_output` / `replay` / `execution` at the value-object layer (the projected paper-ledger taxonomy is validated as plain strings via membership in private frozensets)
- wall-clock helper invocation, `os.environ` / `os.getenv`, `subprocess` outside permitted import-isolation tests, `socket`, `logging`, `print(`
- any construction of `ReplayBacktestRun`, `ReplayBacktestStep`, or `ReplayBacktestSummary` with `live_blocked == False`
- presence of `PaperExecutionLedgerEntry`, `RiskDecisionRecord`, or `OrchestratorDecisionRecord` token in any 2I.A source file

## Lane and MVP relevance

- Lane: `paper_backtest_mvp`.
- MVP relevance: Opens `REPLAY_BACKTEST_RUNNER_MVP` (REQ_0017 milestone 5) value-object surface so REQ_0017 milestones 6 (`PAPER_MODE_MVP`) and 7 (`SHADOW_MODE_READINESS`) can consume a typed, lineage-anchored projection of paper-ledger entries. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` reduces from 3 remaining milestones to 2 remaining milestones once Phase 2I closes.
- Blocked by: `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` (reconciled via `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`); `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`. The dispatch supervisor MUST verify the `26_...md` file contains the literal `_CODEX_PASS` marker (matching the 2H.B precedent at `18_...md`) before dispatching task 143; if `26_...md` still contains `_CODEX_FAIL` because the codex watchdog reconciliation has not yet committed and overwritten the marker, the task is held under the standard `requires_clean_worktree` and predecessor-marker preconditions.
- Next gate: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`, then `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`.
- Legacy evidence consulted: `claude_worklog/legacy_runtime_audit/00..12`; the trainer/trader/orchestrator/feature-flow/signal-to-execution/risk-and-safety/failure-mode runtime audits; the 2H.A/B/C paper-execution-ledger artifacts as the upstream typed mirror taxonomy precedent; the 015A scaffold commit `26e49b7` for the `domain/replay/` and `domain/execution/` placeholder posture; the LAB hedge-unwind / squeeze failure case (REQ_0022) as the leading replay/backtest scenario class.
- Legacy failure addressed: legacy replay/backtest tooling lacked typed lineage value objects, partition-sum aggregate invariants, typed mode discrimination (replay vs backtest), and a hard-locked live-blocked invariant; aggregate counters drifted silently, and replay-anchored decision-explainability could not be reconstructed for LAB-class scenarios. The 2I.A value-object surface fixes these gaps at the type level by carrying every lineage identifier from `replay_step_id` back through `paper_trade_id` to `feature_snapshot_id`, enforcing the mirror prefix discipline at the step level, enforcing three partition-sum equalities at the summary level, and enforcing `live_blocked == True` on every value object.

## Codex parallel lane posture

- Codex parallel lane is allowed only when git is clean and no active dirty Claude output exists (per REQ_0011 / REQ_0021).
- Codex must NOT dispatch task 144 before task 143 emits `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` to `07_...md`.
- Codex watchdog under REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016 retains full authority to commit the unprocessed 2H.C reconciliation addendum (`27_...md`) and the 2H.C planner-turn note, reconcile `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` to `_CODEX_PASS`, and dispatch task 143 once the predecessor marker reconciliation is committed and the worktree is clean.

## Hard safety reaffirmation

This turn:

- did not modify `/home/wali/Desktop/AI BOT`
- did not read or write any literal `red`+`is` key
- did not invoke any `red`+`is` command at any time
- did not restart any live trainer, trader, orchestrator, ingestor, or `red`+`is` service
- did not place, cancel, or modify any exchange order
- did not change leverage or margin
- did not enable live trading
- did not deploy or release to any environment
- did not run any production migration
- did not expose or commit any credential
- did not request L4/L5 authority
- did not approve any live gate
- did not modify any file under `v2/backend/app/domain/replay_backtest_runner/` (the package will be authored by task 143; this turn emits planning artifacts and task definitions only)
- did not modify any file under `v2/backend/tests/unit/domain/replay_backtest_runner/`
- did not modify any 2H.A, 2H.B, or 2H.C planning, implementation, or GO/NO-GO file
- did not modify any 2G.A, 2G.B, 2G.C, 2F.A, 2F.B, 2F.C, 2E1, 2E2, or 2E3 artifact
- did not modify the master planner prompt
- did not modify any task definition under `claude_worklog/agent_supervisor/tasks/` outside the new 143/144 pair
- did not modify any 015A scaffold placeholder under `v2/backend/app/domain/replay/`, `v2/backend/app/domain/execution/`, `v2/backend/app/services/paper_loop.py`, or `v2/backend/app/services/replay_runner.py`
- did not introduce any new lineage ID at the 2I.A value-object layer beyond those documented in 02 (replay_run_id, replay_step_id, replay_summary_id plus the propagated paper_trade_id / risk_decision_id / decision_id / prediction_id / feature_snapshot_id chain)
- did not introduce any FastAPI / HTTP surface, adapter expansion, ledger persistence, PnL/sizing/quantity/price/fees/slippage, GPU/checkpoint/model-loading subsystem, replay engine, scheduler, or background loop in any artifact

Final live approval remains human-only. Live trading remains BLOCKED.

PLANNER_TURN_2I_OPEN_REPLAY_BACKTEST_RUNNER_DOMAIN_READY
END_FILE: claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_OPEN_REPLAY_BACKTEST_RUNNER_DOMAIN.md

Phase 2I.A is now opened. Nine artifacts emitted as BEGIN_FILE/END_FILE blocks: six Phase 2I planning files (00–05), the consolidated implementation task `143` and Codex-review task `144`, and this planner-turn note. Materialization is left to the harness.

Next-turn expectations: the codex watchdog commits the unprocessed `27_...md` reconciliation addendum and the `PLANNER_TURN_2HC_RECONCILED_2H_CLOSED_2I_NEXT.md` note, reconciles `26_2H_C_..._CODEX_GO_NO_GO.md` to the literal `_CODEX_PASS` marker per the 2H.B precedent, and dispatches task 143 once the worktree is clean. Task 144 dispatches only after task 143 emits `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`. After 2I.A Codex PASS, a fresh consolidated milestone turn opens 2I.B (replay/backtest assembler service at a new `v2/backend/app/services/replay_backtest_runner/` package).
