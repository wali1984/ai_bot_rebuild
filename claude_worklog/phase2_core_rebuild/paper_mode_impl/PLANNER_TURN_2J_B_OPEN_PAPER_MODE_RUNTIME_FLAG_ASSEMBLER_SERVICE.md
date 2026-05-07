# Planner Turn 2J.B Open — Paper-Mode Runtime-Flag Assembler Service

Planner date: 2026-05-07.
Planner HEAD at this turn: fcc68f7 (with the 2J.B planning bundle 10/11/12/13, this planner turn note, and the two new task definitions 152/153 staged in the worktree pending the next durable supervisor commit batch).

## Decision Summary

The 2J.A paper-mode runtime-flag domain Codex marker file `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` body now reads exactly `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS` (committed in HEAD `fcc68f7`). The 2J.A implementation marker at `07_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_GO_NO_GO.md` body reads exactly `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED` (committed in HEAD `5e0c760`). The 2J.A authored surface lives at `v2/backend/app/domain/paper_mode/` with three source files plus `v2/backend/tests/unit/domain/paper_mode/` containing 27 tracked files (one zero-byte `__init__.py` plus 26 single-test files).

The 2I.C composition-root Codex marker at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` reads exactly `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` (reconciled per the 26_ addendum at the same directory).

REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` remains satisfied. Phase 2J.A is closed. Phase 2J.B opens. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` remains two milestones (`PAPER_MODE_MVP` partially complete via 2J.A, with 2J.B and 2J.C still to land before `PAPER_MODE_MVP` is satisfied; then `SHADOW_MODE_READINESS`).

This planner turn opens Phase 2J.B (paper-mode runtime-flag assembler service) under REQ_0017 milestone 6. It authors the planning bundle (10/11/12/13) for the 2J.B sub-phase and emits the two task definitions `152_paper_mode_2jb_runtime_flag_assembler_service_implementation.json` and `153_paper_mode_2jb_runtime_flag_assembler_service_codex_review.json`. Both tasks are gated on `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`. Both reference this turn's `10` / `11` / `12` files for spec / test plan / safety boundaries.

## Files Authored This Turn

Under `claude_worklog/phase2_core_rebuild/paper_mode_impl/`:

- `10_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_SPEC.md`
- `11_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `12_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `13_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`
- `PLANNER_TURN_2J_B_OPEN_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE.md` (this file)

Under `claude_worklog/agent_supervisor/tasks/`:

- `152_paper_mode_2jb_runtime_flag_assembler_service_implementation.json`
- `153_paper_mode_2jb_runtime_flag_assembler_service_codex_review.json`

No other files are authored this turn. No file under `v2/` is modified. No GO/NO-GO marker file is modified. No prior-milestone planning, implementation, Codex review, or reconciliation artifact is modified. The master planner prompt is not modified by this planner turn; the existing dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` and the untracked parallel-capacity readonly-review marker at `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2j_a_paper_mode_runtime_flag_domain_codex_pass.json` are both placed in the worktree-isolation exclusion list of tasks 152 and 153 so the supervisor can dispatch from a clean dispatch worktree without requiring the planner-prompt drift or the parallel-readonly-review JSON to land first.

## Phase 2J Sub-Phase Sequence (Re-Stated for the 2J.B Open Turn)

Phase 2J implements REQ_0017 milestone 6 `PAPER_MODE_MVP`. Sub-phases land sequentially per `00_PHASE_2J_SUB_PHASE_BREAKDOWN.md`:

- 2J.A — paper-mode runtime-flag domain (closed; PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS).
- 2J.B — paper-mode runtime-flag assembler service (this turn dispatches via task 152 and Codex-reviews via task 153).
- 2J.C — paper-mode runtime-flag composition root (later milestone, gated on `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`).

Phase 2J closes when the 2J.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 6 (`PAPER_MODE_MVP`) is satisfied and the planner opens REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`). No live execution behavior, no live trader process, no paper trader process, no strategy library, no replay engine, no scheduler, and no FastAPI surface is opened in between.

## 2J.B Authored Surface (Exact Set, From Spec 10 and Test Plan 11)

Source files (3):

- `v2/backend/app/services/paper_mode/__init__.py`
- `v2/backend/app/services/paper_mode/errors.py`
- `v2/backend/app/services/paper_mode/service.py`

Tests (31):

- `v2/backend/tests/unit/services/paper_mode/__init__.py` (zero bytes)
- 30 single-test files enumerated in `11_PHASE_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_TEST_PLAN.md` items 2–31.

Implementation report and GO/NO-GO marker (2):

- `claude_worklog/phase2_core_rebuild/paper_mode_impl/14_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/15_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_GO_NO_GO.md`

Codex review report and Codex GO/NO-GO marker (2, after task 153):

- `claude_worklog/phase2_core_rebuild/paper_mode_impl/16_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/17_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`

Public surface (exact `__all__` per spec 10 section "Public surface"):

1. `assemble_paper_mode_flag`
2. `PaperModeServiceError`

There is NO `PAPER_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, NO bare `PAPER_MODE_LIVE` constant, NO `live` requested-mode branch, NO `live_enabled` requested-mode branch, and NO live-execution affordance at any layer of the 2J.B service. This absence is locked in by `test_assemble_rejects_live_requested_mode.py` (test plan item 28) and `test_assemble_rejects_live_enabled_requested_mode.py` (test plan item 29).

## Predecessor Markers Required (Verified On Disk)

- `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` (PASS — body reads the exact marker; committed in HEAD `fcc68f7`).
- `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/07_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_GO_NO_GO.md` (PASS — body reads the exact marker; committed in HEAD `5e0c760`).
- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (PASS — body reads the exact marker; reconciled per `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`).

The supervisor's predecessor-marker check on tasks 152 and 153 is governed by file `09_2J_A` content. The supervisor dispatch of task 152 occurs only from a clean worktree where the 2J.A markers and the 2I.C reconciled marker remain at their PASS bodies.

## Lane / MVP Relevance / Gates

- Lane: `paper_backtest_mvp` (REQ_0018 lane A approved).
- MVP relevance: advances REQ_0017 milestone 6 `PAPER_MODE_MVP` from 1/3 (2J.A closed) to 2/3 by binding the typed `PaperModeFlag` value-object surface to a pure assembler function whose validation order, single-clock-call discipline, and 2-element exhaustive mirror dispatch table guarantee that any future caller producing a flag carries the explicit live-blocked posture by typed value rather than by environment-variable scrape. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2J.B open: two milestones remain (`PAPER_MODE_MVP` partial via 2J.A + 2J.B, then `SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`, `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`, `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- Next gate (task 152): `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- Next gate (task 153): `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 Legacy Mapping

- Legacy evidence consulted: `claude_worklog/phase2_core_rebuild/paper_mode_impl/01_PHASE_2J_LEGACY_EVIDENCE_REVIEW.md`, plus the underlying read-only audit artifacts at `claude_worklog/legacy_runtime_audit/00`, `07`, `09`, `10`, `11`, `12` and `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind / squeeze case, REQ_0022).
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact. No mutation of any GO/NO-GO marker. No mutation of the master planner prompt.
- Legacy failure addressed: legacy `trader.py` and `rl.orchestrator_worker` carried implicit live-mode posture through environment variables and per-call argument passing, which made it impossible to assert the live-blocked posture by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022) where the protective-leg close happened in a code path that did not type-check the runtime mode. The 2J.B assembler service binds the typed `PaperModeFlag` to a pure function whose 2-element exhaustive mirror dispatch table (`paper` / `live_blocked`) plus the unconditional `live_blocked=True` literal at the call site lock in the absence of any live-execution affordance at the service layer; the explicit rejection of `"live"` and `"live_enabled"` requested-mode values by the allowed-set membership check guarantees that any future caller whose configuration accidentally surfaces a live-execution synonym is refused before producing a flag.
- V2 proof gate: the 2J.B unit tests assert that `assemble_paper_mode_flag(requested_mode="live", ...)` raises `PaperModeServiceError("paper_mode_service_unrecognized_requested_mode", field="requested_mode")` and that the runtime-concatenated literal `"live" + "_enabled"` is similarly rejected; `test_assemble_returned_flag_is_live_blocked_true.py` (re-derived from the happy-path tests) and the value-object layer's own `__post_init__` enforce `live_blocked is True` at every successful construction.

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
- No modification of any prior task definition under `claude_worklog/agent_supervisor/tasks/`.
- No new lineage ID introduced at the 2J.B service layer; the typed `PaperModeFlag` returned by the assembler carries only the `mode`, `flag_emitted_ts_ms`, and `live_blocked` fields defined in 2J.A.
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler, or background loop introduced in any artifact.

## Stop Conditions

If task 152 returns `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_FAILED` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2J.B source files plus the 30 new test files only and re-runs the implementation flow.

If task 153 returns `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2J.B source files plus the 30 new test files only and re-runs the implementation flow. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A / 2H.B / 2H.C / 2I.A / 2I.B / 2I.C addenda, the supervisor authors a `26_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_RECONCILIATION_ADDENDUM.md` addendum and rewrites the `17_` marker body to `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS` per the established reconciliation precedent.

If either task encounters a safety violation (any live behavior, any Redis access, any legacy mutation, any release intent, any FastAPI/wall-clock/subprocess/socket import in a 2J.B source file, any URL or credential leakage, any introduction of a `PAPER_MODE_LIVE_ENABLED` / `live_enabled` / bare `PAPER_MODE_LIVE` constant, any successful construction of a `PaperModeFlag` with `live_blocked == False`, any modification of a prior-milestone artifact, any modification of any GO/NO-GO marker, any modification of any 2J.B planning artifact 10-13, any modification of the placeholder `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py`, any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`, any modification of `v2/backend/app/domain/paper_mode/` (the 2J.A package), any modification of `v2/backend/app/domain/paper_execution_ledger/` or `v2/backend/app/domain/replay_backtest_runner/`, any introduction of a `v2/backend/app/services/paper_mode.py` flat-file placeholder, any introduction of ledger persistence, any introduction of PnL / position sizing / quantity / price / fees / slippage, any introduction of a paper trader process / paper executor / shadow executor / strategy library / replay engine / scheduler / background loop, or any new lineage ID at the 2J.B service layer), the planner stops, surfaces to human attention, and does not auto-retry.

PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_OPEN_READY
