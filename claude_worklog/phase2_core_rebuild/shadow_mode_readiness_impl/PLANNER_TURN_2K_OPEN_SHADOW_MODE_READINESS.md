# Planner Turn 2K Open — Shadow-Mode Readiness

Planner date: 2026-05-07.
Planner HEAD at this turn: a0f9c43 (the latest watchdog dirty-tree recovery commit, with the pre-existing planner-prompt 2I→2J pointer-update diff still unstaged in the worktree pending the next watchdog auto-commit batch).

## Decision Summary

The 2J.C composition root Codex marker file
`claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
body reads exactly `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` (PASS at HEAD 5565c25). REQ_0017 milestone 6 `PAPER_MODE_MVP` is satisfied. Phase 2J is closed in its entirety. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` reduces from two milestones at the prior pre-open intent to one milestone remaining (`SHADOW_MODE_READINESS`).

This planner turn fulfils the contract recorded in the prior pre-open-intent note
`claude_worklog/phase2_core_rebuild/paper_mode_impl/PLANNER_TURN_2J_C_CLOSED_PAPER_MODE_MVP_SATISFIED_2K_PRE_OPEN_INTENT.md`,
which committed to "emit the 2K.A planning bundle (02 spec, 03 test plan, 04 safety boundaries, 05 GO_NO_GO_REQUEST) and the 2K.A implementation/Codex-review task definitions in one step from a clean dispatch worktree".

## Files Authored This Turn

Under `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/`:

- `02_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_SPEC.md`
- `03_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_TEST_PLAN.md`
- `04_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_SAFETY_BOUNDARIES.md`
- `05_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_GO_NO_GO_REQUEST.md`
- `PLANNER_TURN_2K_OPEN_SHADOW_MODE_READINESS.md` (this file)

Under `claude_worklog/agent_supervisor/tasks/`:

- `156_shadow_mode_readiness_2ka_flag_domain_implementation.json`
- `157_shadow_mode_readiness_2ka_flag_domain_codex_review.json`

No other files are authored this turn. No file under `v2/` is modified. No GO/NO-GO marker file is modified. No prior-milestone planning, implementation, Codex review, or reconciliation artifact is modified. The master planner prompt is not modified by this planner turn; the existing dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` remains in the worktree-isolation exclusion list of tasks 156 and 157 so the supervisor can dispatch from a clean dispatch worktree without requiring the planner-prompt drift to land first. A subsequent planner turn will re-emit the prompt with the pointer advanced to `SHADOW_MODE_READINESS` and the distance restated as `1 milestone remaining` once the next watchdog auto-commit lands the existing 2I→2J pointer diff.

## Phase 2K Sub-Phase Sequence (Re-Stated for the Open Turn)

Phase 2K implements REQ_0017 milestone 7 `SHADOW_MODE_READINESS`. Sub-phases land sequentially per `00_PHASE_2K_SUB_PHASE_BREAKDOWN.md`:

- 2K.A — shadow-mode-readiness flag domain (this turn dispatches via task 156 and Codex-reviews via task 157).
- 2K.B — shadow-mode-readiness flag assembler service (later milestone, gated on `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS`).
- 2K.C — shadow-mode-readiness flag composition root (later milestone, gated on `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`).

Phase 2K closes when the 2K.C composition-root Codex pass marker is materialized at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/25_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` with body `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`. At that point REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`) is satisfied and the planner opens the `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation turn that authors the evidence packet under `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/` (NEW directory) summarizing the seven satisfied REQ_0017 milestones and the typed surfaces they produced. No live execution behavior, no shadow trader process, no paper trader process, no strategy library, no replay engine, no scheduler, and no FastAPI surface is opened in between.

## 2K.A Authored Surface (Exact Set, From Spec 02 and Test Plan 03)

Source files (3):

- `v2/backend/app/domain/shadow_mode_readiness/__init__.py`
- `v2/backend/app/domain/shadow_mode_readiness/errors.py`
- `v2/backend/app/domain/shadow_mode_readiness/flag.py`

Tests (27):

- `v2/backend/tests/unit/domain/shadow_mode_readiness/__init__.py` (zero bytes)
- 26 single-test files enumerated in `03_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_TEST_PLAN.md` items 2–27.

Implementation report and GO/NO-GO marker (2):

- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/06_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/07_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_GO_NO_GO.md`

Codex review report and Codex GO/NO-GO marker (2, after task 157):

- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/08_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/09_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_GO_NO_GO.md`

Public surface (exact `__all__` per spec 02 section "Public surface"):

1. `ShadowModeReadinessDomainError`
2. `ShadowModeReadinessFlag`
3. `SHADOW_MODE_NOT_READY`
4. `SHADOW_MODE_READY`

There is NO `SHADOW_MODE_LIVE` constant, NO `SHADOW_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, NO `shadow_decision_id` lineage row, and NO live-execution affordance at any layer of the 2K.A package. This absence is locked in by `test_no_live_enabled_constant_in_module.py` (test plan item 15) and `test_flag_rejects_live_enabled_state.py` (test plan item 21).

## Predecessor Markers Required (Verified On Disk)

- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (PASS at HEAD 5565c25).
- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at
  `claude_worklog/phase2_core_rebuild/paper_mode_impl/23_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_GO_NO_GO.md` (PASS).
- `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/paper_mode_impl/17_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` (PASS).
- `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` (PASS).

The supervisor's predecessor-marker check on tasks 156 and 157 is governed by file `25_2J_C_…` content. Supervisor dispatch of task 156 occurs only from a clean worktree where the planner-prompt 2I→2J pointer-update diff is committed by the next watchdog auto-commit batch (the planner-prompt path is in `worktree_excluded_paths` for tasks 156/157 so the dispatch worktree can be clean despite the prompt drift).

## Lane / MVP Relevance / Gates

- Lane: `paper_backtest_mvp` (REQ_0018 lane A approved).
- MVP relevance: opens REQ_0017 milestone 7 `SHADOW_MODE_READINESS` via the typed `ShadowModeReadinessFlag` value-object surface. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2K open: one milestone remains (`SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` (PASS at HEAD 5565c25).
- Next gate (task 156): `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Next gate (task 157): `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024 Legacy Mapping

- Legacy evidence consulted: `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md`, plus the underlying read-only audit artifacts at `claude_worklog/legacy_runtime_audit/00`, `06`, `07`, `09`, `10`, `11`, `12` and `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind / squeeze case, REQ_0022).
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact. No mutation of any GO/NO-GO marker. No mutation of the master planner prompt.
- Legacy failure addressed: legacy `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`, and `monitor_portfolio_asjad.py` inspect runtime state without a typed precondition flag, which made it impossible to assert shadow-mode readiness by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022) where decisions were made on stale or partially-initialized runtime state. The 2K.A typed `ShadowModeReadinessFlag` introduces a typed boundary that downstream consumers (`paper_trade_id`, `replay_run_id`, future `shadow_decision_id`) can pattern-match on to refuse any shadow-execution path until shadow-mode readiness is asserted, and to refuse any live-execution path always until the V2 live-readiness gate flips. The default value is `SHADOW_MODE_NOT_READY`; the only other constant is `SHADOW_MODE_READY`; there is NO `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, or `live_enabled` constant in 2K.A, 2K.B, or 2K.C.
- V2 proof gate: the 2K.A unit tests assert that constructing a `ShadowModeReadinessFlag` with any value other than the two named state constants raises `ShadowModeReadinessDomainError`; `test_no_live_enabled_constant_in_module.py` and `test_flag_rejects_live_enabled_state.py` lock in the absence of any live-execution affordance at the 2K.A layer.

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
- No new lineage ID introduced.
- No `shadow_decision_id` lineage row introduced.
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler, or background loop introduced in any artifact.

## Stop Conditions

If task 156 returns `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_FAILED` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2K.A source files plus the 26 new test files only and re-runs the implementation flow.

If task 157 returns `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2K.A source files plus the 26 new test files only and re-runs the implementation flow.

If either task encounters a safety violation (any live behavior, any Redis access, any legacy mutation, any release intent, any FastAPI/wall-clock/subprocess/socket import in a 2K.A source file, any URL or credential leakage, any introduction of a `SHADOW_MODE_LIVE_ENABLED` / `SHADOW_MODE_LIVE` / `live_enabled` constant, any successful construction of a `ShadowModeReadinessFlag` with `live_blocked == False`, any introduction of a `shadow_decision_id` lineage row at the 2K.A layer, any modification of a prior-milestone artifact, any modification of any GO/NO-GO marker, any modification of any 2K.A planning artifact 00-05, any modification of the placeholder `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py`, any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`, any modification of `v2/backend/app/domain/paper_mode/` or `v2/backend/app/domain/paper_execution_ledger/` or `v2/backend/app/domain/replay_backtest_runner/`, any introduction of a `v2/backend/app/domain/shadow_mode_readiness.py` flat-file placeholder, any introduction of ledger persistence, any introduction of PnL / position sizing / quantity / price / fees / slippage, any introduction of a paper trader process / paper executor / shadow executor / strategy library / replay engine / scheduler / background loop, or any new lineage ID at the 2K.A value-object layer), the planner stops, surfaces to human attention, and does not auto-retry.

PHASE2K_SHADOW_MODE_READINESS_OPEN_READY
