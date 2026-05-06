# Phase 2I Planner Turn — Re-emit 2I.A Planning Bundle After Materialization Gap

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md (replay/backtest runner lane is co-active under REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 paper_backtest_mvp lane).
Active MVP milestone (opening): REPLAY_BACKTEST_RUNNER_MVP, sub-step 2I.A replay/backtest runner domain.
Lane: paper_backtest_mvp.
Planner state: ADVANCE — Phase 2H closed (reconciled PASS on 2H.A/B/C); Phase 2I.A re-opened with the consolidated planning artifacts and tasks 143/144 that the prior planner-turn note `PLANNER_TURN_2I_OPEN_REPLAY_BACKTEST_RUNNER_DOMAIN.md` enumerated but whose BEGIN_FILE/END_FILE blocks were not materialized in the previous turn.

## Why this re-emit turn is needed

The prior planner turn (`PLANNER_TURN_2I_OPEN_REPLAY_BACKTEST_RUNNER_DOMAIN.md`, committed in `afa7be1`) enumerated the consolidated Phase 2I.A planning bundle and tasks 143/144 as the nine artifacts that turn was responsible for emitting. The planner-turn note itself was committed by the codex watchdog, but the eight other artifacts (the six 00-05 planning files plus tasks 143 and 144) were never materialized. `git ls-files v2/backend/app/domain/replay_backtest_runner/` returns zero output, `git ls-files claude_worklog/agent_supervisor/tasks/143_*.json` returns zero output, and `git ls-files claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/0[0-5]_*.md` returns zero output.

This turn re-emits the eight missing artifacts as BEGIN_FILE/END_FILE blocks for the harness to materialize:

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/00_PHASE_2I_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/03_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/04_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/05_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO_REQUEST.md`
- `claude_worklog/agent_supervisor/tasks/143_replay_backtest_runner_2ia_domain_implementation.json`
- `claude_worklog/agent_supervisor/tasks/144_replay_backtest_runner_2ia_domain_codex_review.json`

Plus this short re-emit planner-turn note. Nine artifacts total in this turn. No prior-milestone V2 source or test file is modified. No 2H.A/B/C artifact is modified. No master planner prompt is modified. No supervisor task definition outside the new 143/144 pair is modified. The prior `PLANNER_TURN_2I_OPEN_REPLAY_BACKTEST_RUNNER_DOMAIN.md` is left as-is on disk; this re-emit note records the materialization-gap recovery for future audit.

## Predecessor marker reconciliation status

`claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` currently contains `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL`. The reconciliation addendum at `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` (committed in `afa7be1`) documents the corrected PASS verdict on the same evidentiary basis as the 2H.A and 2H.B precedents (`10_...md` and `19_...md`).

The planner does NOT flip the `26_...md` marker itself. Per REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016, the codex watchdog has the authority to reconcile the marker file from `_CODEX_FAIL` to `_CODEX_PASS` when the reconciliation addendum is committed and the worktree is clean. Tasks 143 and 144 will hold under their `requires_clean_worktree` and `predecessor_required_marker` preconditions until that marker reconciliation lands. This is the same posture documented in the prior planner-turn note and matches the 2H.B precedent.

## Decided next safest non-live rebuild milestone

`PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN`. Pure value objects (`ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`) at a NEW package `v2/backend/app/domain/replay_backtest_runner/`, sibling of `v2/backend/app/domain/paper_execution_ledger/`. Five authored source files (`__init__.py`, `errors.py`, `run.py`, `step.py`, `summary.py`) and 51 test files plus a zero-byte `__init__.py` test-package marker.

The new directory choice is deliberate and unchanged from the prior planner-turn note: `v2/backend/app/domain/replay/` (015A scaffold, zero-byte `__init__.py` and a one-line `deterministic.py` docstring), `v2/backend/app/services/replay_runner.py` (one-line scaffold), and `v2/backend/app/domain/execution/` (015A scaffold) are left UNCHANGED. This mirrors the 2H.A precedent where `domain/paper_execution_ledger/` was created as a sibling of the placeholder `domain/execution/` rather than reusing the placeholder.

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
- Blocked by: `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` (reconciled per `27_...md`); `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.
- Next gate: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`, then `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`.
- Legacy evidence consulted: `claude_worklog/legacy_runtime_audit/00..12`; the trainer/trader/orchestrator/feature-flow/signal-to-execution/risk-and-safety/failure-mode runtime audits; `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`; the 2H.A/B/C paper-execution-ledger artifacts as the upstream typed mirror taxonomy precedent; the 015A scaffold commit `26e49b7` for the `domain/replay/`, `domain/execution/`, and `services/replay_runner.py` placeholder posture; the LAB hedge-unwind / squeeze failure case (REQ_0022) as the leading replay/backtest scenario class.
- Legacy failure addressed: legacy replay/backtest tooling lacked typed lineage value objects, partition-sum aggregate invariants, typed mode discrimination (replay vs backtest), and a hard-locked live-blocked invariant; aggregate counters drifted silently, and replay-anchored decision-explainability could not be reconstructed for LAB-class scenarios. The 2I.A value-object surface fixes these gaps at the type level.

## Codex parallel lane posture

- Codex parallel lane is allowed only when git is clean and no active dirty Claude output exists (per REQ_0011 / REQ_0021).
- Codex must NOT dispatch task 144 before task 143 emits `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` to `07_...md`.
- Codex watchdog under REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016 retains full authority to reconcile `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` to `_CODEX_PASS`, commit any remaining unprocessed reconciliation artifacts, and dispatch task 143 once the predecessor marker reconciliation is committed and the worktree is clean.

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
- did not flip the `26_2H_C_..._CODEX_GO_NO_GO.md` marker (codex watchdog reconciliation per REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016)
- did not overwrite the prior `PLANNER_TURN_2I_OPEN_REPLAY_BACKTEST_RUNNER_DOMAIN.md` note

Final live approval remains human-only. Live trading remains BLOCKED.

PLANNER_TURN_2I_REEMIT_2IA_PLANNING_BUNDLE_AFTER_MATERIALIZATION_GAP_READY

Phase 2I.A is re-opened. Nine artifacts emitted as BEGIN_FILE/END_FILE blocks: six Phase 2I.A planning files (00–05), the consolidated implementation task `143` and Codex-review task `144`, and this re-emit planner-turn note. Materialization is left to the harness.

Next-turn expectations: the codex watchdog reconciles `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` to the literal `_CODEX_PASS` marker per the 2H.A/2H.B precedent, dispatches task `143` once the predecessor marker is in place and the worktree is clean, and dispatches task `144` only after task `143` emits `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`. After 2I.A Codex PASS, a fresh consolidated milestone turn opens 2I.B (replay/backtest assembler service at a new `v2/backend/app/services/replay_backtest_runner/` package).
