# Planner Turn 2J Open — Paper Mode MVP

Planner date: 2026-05-07.
Planner HEAD at this turn: 63567e9 (with the 25_2I_C marker rewrite to `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` and the new `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` staged in the worktree pending the next durable watchdog auto-commit batch).

## Decision Summary

The 2I.C composition root Codex marker file
`claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
body now reads exactly `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`. The reconciliation addendum at
`claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`
adjudicates the 24_ Codex review's single observed blocker (the three pre-existing 015A docstring-only placeholders under `v2/backend/app/domain/execution/`) to PASS on the same 015A pre-existing scaffold cross-isolation precedent that closed 2H.A / 2H.B / 2H.C and on the corrected reading of the rubric rows that were marked FAIL solely because the Codex audit halted at the placeholder hard stop.

REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` is satisfied. Phase 2I is closed in its entirety. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` reduces from three milestones to two milestones remaining (`PAPER_MODE_MVP` and `SHADOW_MODE_READINESS`).

This planner turn fulfils the post-flip dispatch contract recorded in the prior pre-flip notes
`claude_worklog/phase2_core_rebuild/paper_mode_impl/PLANNER_TURN_2J_PRE_FLIP_PLANNING_BUNDLE_AUTHORED.md`
and
`claude_worklog/phase2_core_rebuild/paper_mode_impl/PLANNER_TURN_2J_PRE_FLIP_PLANNING_BUNDLE_MATERIALIZATION_COMPLETION.md`,
which committed to emitting "exactly one planner turn note `PLANNER_TURN_2J_OPEN_PAPER_MODE_MVP.md` and exactly two task definition files `150_paper_mode_2ja_runtime_flag_domain_implementation.json` and `151_paper_mode_2ja_runtime_flag_domain_codex_review.json`, both blocked on `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`, both referencing this turn's `02` / `03` / `04` files for spec / test plan / safety boundaries."

## Files Authored This Turn

Under `claude_worklog/phase2_core_rebuild/paper_mode_impl/`:

- `PLANNER_TURN_2J_OPEN_PAPER_MODE_MVP.md` (this file)

Under `claude_worklog/agent_supervisor/tasks/`:

- `150_paper_mode_2ja_runtime_flag_domain_implementation.json`
- `151_paper_mode_2ja_runtime_flag_domain_codex_review.json`

No other files are authored this turn. No file under `v2/` is modified. No GO/NO-GO marker file is modified. No prior-milestone planning, implementation, Codex review, or reconciliation artifact is modified. The master planner prompt is not modified by this planner turn; the existing dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` remains in the worktree-isolation exclusion list of tasks 150 and 151 so the supervisor can dispatch from a clean dispatch worktree without requiring the planner-prompt drift to land first.

## Phase 2J Sub-Phase Sequence (Re-Stated for the Open Turn)

Phase 2J implements REQ_0017 milestone 6 `PAPER_MODE_MVP`. Sub-phases land sequentially per `00_PHASE_2J_SUB_PHASE_BREAKDOWN.md`:

- 2J.A — paper-mode runtime-flag domain (this turn dispatches via task 150 and Codex-reviews via task 151).
- 2J.B — paper-mode runtime-flag assembler service (later milestone, gated on `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`).
- 2J.C — paper-mode runtime-flag composition root (later milestone, gated on `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`).

Phase 2J closes when the 2J.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 6 (`PAPER_MODE_MVP`) is satisfied and the planner opens REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`). No live execution behavior, no live trader process, no paper trader process, no strategy library, no replay engine, no scheduler, and no FastAPI surface is opened in between.

## 2J.A Authored Surface (Exact Set, From Spec 02 and Test Plan 03)

Source files (3):

- `v2/backend/app/domain/paper_mode/__init__.py`
- `v2/backend/app/domain/paper_mode/errors.py`
- `v2/backend/app/domain/paper_mode/flag.py`

Tests (27):

- `v2/backend/tests/unit/domain/paper_mode/__init__.py` (zero bytes)
- 26 single-test files enumerated in `03_PHASE_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_TEST_PLAN.md` items 2–27.

Implementation report and GO/NO-GO marker (2):

- `claude_worklog/phase2_core_rebuild/paper_mode_impl/06_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/07_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_GO_NO_GO.md`

Codex review report and Codex GO/NO-GO marker (2, after task 151):

- `claude_worklog/phase2_core_rebuild/paper_mode_impl/08_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md`

Public surface (exact `__all__` per spec 02 section "Public surface"):

1. `PaperModeDomainError`
2. `PaperModeFlag`
3. `PAPER_MODE_PAPER`
4. `PAPER_MODE_LIVE_BLOCKED`

There is NO `PAPER_MODE_LIVE` constant, NO `PAPER_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, and NO live-execution affordance at any layer of the 2J.A package. This absence is locked in by `test_no_live_enabled_constant_in_module.py` (test plan item 15) and `test_flag_rejects_live_enabled_mode.py` (test plan item 21).

## Predecessor Markers Required (Verified On Disk)

- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
  (PASS — body now reads the exact marker; reconciled per
  `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`).
- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at
  `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/23_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO.md` (PASS).
- `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/17_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` (PASS).
- `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md` (PASS).

The supervisor's predecessor-marker check on tasks 150 and 151 is governed by file `25_` content. Because the 25_ marker rewrite is currently uncommitted but on disk, the next watchdog auto-commit batch lands the rewrite together with the new 26_ addendum, this planner turn note, and the two new task definitions; supervisor dispatch of task 150 occurs only from a clean worktree where the rewritten 25_ marker is committed.

## Lane / MVP Relevance / Gates

- Lane: `paper_backtest_mvp` (REQ_0018 lane A approved).
- MVP relevance: opens REQ_0017 milestone 6 `PAPER_MODE_MVP` via the typed `PaperModeFlag` value-object surface. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2J open: two milestones remain (`PAPER_MODE_MVP` and `SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` (now PASS).
- Next gate (task 150): `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Next gate (task 151): `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 Legacy Mapping

- Legacy evidence consulted: `claude_worklog/phase2_core_rebuild/paper_mode_impl/01_PHASE_2J_LEGACY_EVIDENCE_REVIEW.md`, plus the underlying read-only audit artifacts at `claude_worklog/legacy_runtime_audit/00`, `07`, `09`, `10`, `11`, `12` and `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind / squeeze case, REQ_0022).
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact. No mutation of any GO/NO-GO marker. No mutation of the dispatch bridge repair task. No mutation of the master planner prompt.
- Legacy failure addressed: ambiguous live-vs-paper posture at the trader entry point, where legacy `trader.py` and `rl.orchestrator_worker` carried implicit live-mode posture through environment variables and per-call argument passing, and where the LAB hedge-unwind / squeeze failure (REQ_0022) closed the protective leg in a code path that did not type-check the runtime mode. The 2J.A typed `PaperModeFlag` introduces a typed boundary that downstream consumers can pattern-match on to refuse any live-execution path until the V2 live-readiness gate flips. The default constructor value is `PAPER_MODE_PAPER`; the only other constant is `PAPER_MODE_LIVE_BLOCKED`; there is NO `live_enabled` constant in 2J.A, 2J.B, or 2J.C.
- V2 proof gate: the 2J.A unit tests assert that constructing a `PaperModeFlag` with any non-paper / non-live-blocked value raises `PaperModeDomainError`; `test_no_live_enabled_constant_in_module.py` and `test_flag_rejects_live_enabled_mode.py` lock in the absence of any live-execution affordance at the 2J.A layer.

## Safety

- Live trading remains BLOCKED.
- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis access at any layer.
- No live service restart.
- No exchange action.
- No leverage or margin change.
- No deployment.
- No production migration.
- No secret exposure.
- No modification of any file under `v2/` by this planner turn.
- No modification of any GO/NO-GO marker file by this planner turn.
- No modification of any prior `PLANNER_TURN_*` note.
- No modification of the master planner prompt.
- No modification of the recovery task definition `codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json`.
- No modification of the dispatch bridge repair task definition `codex_watchdog_supervisor_scheduler_dispatch_bridge_repair_for_2ic_recovery.json`.
- No new lineage ID introduced.
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler, or background loop introduced in any artifact.

## Stop Conditions

If task 150 returns `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_FAILED` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2J.A source files plus the 26 new test files only and re-runs the implementation flow.

If task 151 returns `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2J.A source files plus the 26 new test files only and re-runs the implementation flow.

If either task encounters a safety violation (any live behavior, any Redis access, any legacy mutation, any release intent, any FastAPI/wall-clock/subprocess/socket import in a 2J.A source file, any URL or credential leakage, any introduction of a `PAPER_MODE_LIVE_ENABLED` / `live_enabled` / `PAPER_MODE_LIVE` constant, any successful construction of a `PaperModeFlag` with `live_blocked == False`, any modification of a prior-milestone artifact, any modification of any GO/NO-GO marker, any modification of any 2J.A planning artifact 00-05, any modification of the placeholder `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py`, any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`, any modification of `v2/backend/app/domain/paper_execution_ledger/` or `v2/backend/app/domain/replay_backtest_runner/`, any introduction of a `v2/backend/app/domain/paper_mode.py` flat-file placeholder, any introduction of ledger persistence, any introduction of PnL / position sizing / quantity / price / fees / slippage, any introduction of a paper trader process / paper executor / shadow executor / strategy library / replay engine / scheduler / background loop, or any new lineage ID at the 2J.A value-object layer), the planner stops, surfaces to human attention, and does not auto-retry.

PHASE2J_PAPER_MODE_MVP_OPEN_READY
