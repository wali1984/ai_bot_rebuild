# Planner Turn 2J.C Open — Paper-Mode Runtime-Flag Composition-Root Codex Review

Planner date: 2026-05-07.

## Decision Summary

The 2J.B paper-mode runtime-flag assembler-service Codex marker file `claude_worklog/phase2_core_rebuild/paper_mode_impl/17_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` body now reads exactly `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`. The 2J.A paper-mode runtime-flag domain Codex marker file `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` body reads exactly `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`. The 2I.C replay/backtest runner composition-root Codex marker at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body reads exactly `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` (reconciled per the `26_` addendum at the same directory).

REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` remains satisfied. Phase 2J.A and Phase 2J.B are closed. Phase 2J.C composition-root implementation task `154_paper_mode_2jc_runtime_flag_composition_root_implementation.json` was emitted by the prior planner turn and remains queued under the consolidated_default granularity policy. This planner turn opens the paired Codex review gate for Phase 2J.C by emitting `155_paper_mode_2jc_runtime_flag_composition_root_codex_review.json`. Both tasks 154 and 155 reference the same 2J.C planning bundle (`18` / `19` / `20` / `21`) authored by the pre-flip planning bundle turns.

The 2J.C planning bundle was authored under the prior planner turns `PLANNER_TURN_2J_PRE_FLIP_PLANNING_BUNDLE_AUTHORED.md` and `PLANNER_TURN_2J_PRE_FLIP_PLANNING_BUNDLE_MATERIALIZATION_COMPLETION.md`. No 2J.C planning artifact is modified by this turn. No 2J.B Codex review or marker artifact is modified by this turn. No 2J.A Codex review or marker artifact is modified by this turn. No file under `v2/` is modified by this turn. No prior-milestone planning, implementation, Codex review, or reconciliation artifact is modified by this turn. The master planner prompt is not modified by this planner turn; the existing dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` and the durable Lane C parallel-capacity readonly-review marker JSONs under `claude_worklog/agent_supervisor/tasks/` are placed in the worktree-isolation exclusion list of task 155 so the supervisor can dispatch from a clean dispatch worktree without requiring those drift entries to land first. The new planner-turn note `PLANNER_TURN_2J_C_OPEN_2J_C_CODEX_REVIEW.md` is also placed in the worktree-isolation exclusion list of task 155 in case the supervisor's commit batch lands the planner-turn note simultaneously with the task-155 dispatch attempt.

## Files Authored This Turn

Under `claude_worklog/phase2_core_rebuild/paper_mode_impl/`:

- `PLANNER_TURN_2J_C_OPEN_2J_C_CODEX_REVIEW.md` (this file)

Under `claude_worklog/agent_supervisor/tasks/`:

- `155_paper_mode_2jc_runtime_flag_composition_root_codex_review.json`

No other files are authored this turn.

## Phase 2J Sub-Phase Sequence (Re-Stated for the 2J.C Codex Review Open Turn)

Phase 2J implements REQ_0017 milestone 6 `PAPER_MODE_MVP`. Sub-phases land sequentially per `00_PHASE_2J_SUB_PHASE_BREAKDOWN.md`:

- 2J.A — paper-mode runtime-flag domain (closed; `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`).
- 2J.B — paper-mode runtime-flag assembler service (closed; `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`).
- 2J.C — paper-mode runtime-flag composition root (this turn dispatches task 154 via the prior turn's emission and Codex-reviews via task 155 emitted in this turn).

Phase 2J closes when the 2J.C composition-root Codex pass marker is materialized at `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`. At that point REQ_0017 milestone 6 (`PAPER_MODE_MVP`) is satisfied and the planner opens REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`) under a fresh consolidated milestone turn. No live execution behavior, no live trader process, no paper trader process, no strategy library, no replay engine, no scheduler, and no FastAPI surface is opened in between.

## 2J.C Authored Surface (Exact Set, From Spec 18 and Test Plan 19)

Source files (3, authored by task 154):

- `v2/backend/app/composition/paper_mode/__init__.py`
- `v2/backend/app/composition/paper_mode/errors.py`
- `v2/backend/app/composition/paper_mode/runtime.py`

Tests (23, authored by task 154):

- `v2/backend/tests/unit/composition/paper_mode/__init__.py` (zero bytes)
- 22 single-test files enumerated in `19_PHASE_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_TEST_PLAN.md` items 1–22.

Implementation report and GO/NO-GO marker (2, authored by task 154):

- `claude_worklog/phase2_core_rebuild/paper_mode_impl/22_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/23_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_GO_NO_GO.md`

Codex review report and Codex GO/NO-GO marker (2, authored by task 155):

- `claude_worklog/phase2_core_rebuild/paper_mode_impl/24_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`

Public surface (exact `__all__` per spec 18 section "Public surface"):

1. `build_paper_mode_runtime`
2. `PaperModeRuntime`
3. `PaperModeRuntimeCompositionError`

There is NO `PAPER_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, NO bare `PAPER_MODE_LIVE` constant, NO `live` requested-mode branch, NO `live_enabled` requested-mode branch, and NO live-execution affordance at the 2J.C composition layer. The composition root is a pure binder that captures `now_ms_clock` at build time and returns a slotted `PaperModeRuntime` whose single attribute `paper_mode_now` is a keyword-only closure that adapts the 2J.B assembler-service surface to the captured-clock pattern. The composition root MUST NOT directly construct `PaperModeFlag`; the value object flows through unchanged from the 2J.B service. `PaperModeRuntimeCompositionError` is a plain `Exception` subclass — NOT a `ValueError` — so callers can discriminate build-time misconfiguration of the binder from call-time service-layer rejection (`PaperModeServiceError` is `ValueError`) and from value-object rejection (`PaperModeDomainError` is `ValueError`).

## Predecessor Markers Required (Verified On Disk)

- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/23_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_GO_NO_GO.md` (will be PASS once task 154 completes; task 155 dispatch is gated on this marker).
- `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/17_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` (PASS — body reads the exact marker).
- `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` (PASS — body reads the exact marker).
- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (PASS — body reads the exact marker; reconciled per `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`).

The supervisor's predecessor-marker check on task 155 is governed by file `23_2J_C` content and the upstream Codex pass markers. The supervisor dispatch of task 155 occurs only from a clean worktree where the 2J.A, 2J.B, 2J.C-impl, and 2I.C reconciled markers remain at their PASS bodies.

## Lane / MVP Relevance / Gates

- Lane: `codex_watchdog` (REQ_0011 / REQ_0018 lane C approved Codex review gate at the close of a paper_backtest_mvp sub-phase).
- MVP relevance: closes the Codex review gate for the 2J.C paper-mode runtime-flag composition root. PASS closes Phase 2J in full, satisfies REQ_0017 milestone 6 `PAPER_MODE_MVP`, and unblocks REQ_0017 milestone 7 `SHADOW_MODE_READINESS`. The 2J.C composition root is the slotted single-closure binder (`build_paper_mode_runtime` / `PaperModeRuntime` / `PaperModeRuntimeCompositionError`) that downstream consumers (paper execution ledger consumers, replay/backtest runner consumers, future `shadow_decision_id` consumers) bind to without importing any live-execution surface and without re-deriving the live-blocked posture from environment variables. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2J.C Codex review open: one milestone (`SHADOW_MODE_READINESS`) remains once 2J.C Codex passes.
- Blocked by: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`, `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`, `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`, `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- Next gate (task 155): `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 Legacy Mapping

- Legacy evidence consulted: `claude_worklog/phase2_core_rebuild/paper_mode_impl/01_PHASE_2J_LEGACY_EVIDENCE_REVIEW.md`, plus the underlying read-only audit artifacts at `claude_worklog/legacy_runtime_audit/00`, `07`, `09`, `10`, `11`, `12` and `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind / squeeze case, REQ_0022). The Codex review confirms task 154's implementation report (`22_`) cites the same legacy evidence chain consulted by 2J.A (`06_`) and 2J.B (`14_`).
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact. No mutation of any GO/NO-GO marker. No mutation of the master planner prompt.
- Legacy failure addressed: legacy `trader.py` and `rl.orchestrator_worker` carried implicit live-mode posture through environment variables and per-call argument passing, which made it impossible to assert the live-blocked posture by typed value at the runtime-binding boundary and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022) where the protective-leg close happened in a code path that did not type-check the runtime mode. The 2J.C composition root binds the typed `PaperModeFlag` to a slotted single-closure `PaperModeRuntime` whose single attribute `paper_mode_now` is a keyword-only closure that forwards `requested_mode` unchanged to the 2J.B assembler service with the captured clock injected by the binder; the composition root MUST NOT directly construct `PaperModeFlag` (the value object flows through unchanged from the 2J.B service which is the single boundary that constructs the value object with `live_blocked=True`); the binder MUST NOT invoke the clock or the assembler at build time (the only build-time validation is `callable(now_ms_clock)`); the inner closure MUST close over the same `_now_ms_clock` reference passed to the binder (clock-identity equality is asserted across `paper_mode_now` invocations); the inner closure MUST invoke the assembler exactly once per call (the assembler enforces single-clock-call discipline per the 2J.B contract); the inner closure MUST NOT catch, wrap, or rewrap `PaperModeServiceError` or `PaperModeDomainError` (consumers catch the most specific class directly); the binder accepts ONLY `now_ms_clock` (no run-id parameter, no symbol filter, no requested-mode pre-binding parameter, no persistence handle, no storage adapter, no PnL/position-sizing parameter, and no expansion of any kind). The accidental introduction of a `'live'` or `'live_enabled'` requested-mode branch at the composition layer, the accidental introduction of a `PAPER_MODE_LIVE_ENABLED` / `live_enabled` / bare `PAPER_MODE_LIVE` constant, or the accidental direct construction of `PaperModeFlag` at the composition layer is forbidden by the spec-18 forbidden-tokens list, the spec-18 module-level invariants, and the spec-18 build-time vs call-time invariants; the Codex review verifies all three.
- V2 proof gate: the 2J.C unit tests assert that `runtime.paper_mode_now(requested_mode='live')` raises `PaperModeServiceError(code='paper_mode_service_unrecognized_requested_mode', field='requested_mode')` unchanged, that the runtime-concatenated literal `'live' + '_enabled'` is similarly rejected, and that `'enable_live'` is similarly rejected; that `runtime.paper_mode_now(requested_mode=123)` raises `PaperModeServiceError(code='must_be_str', field='requested_mode')` unchanged; that the returned `PaperModeFlag` carries `live_blocked is True` for both accepted modes (`'paper'` and `'live_blocked'`); that the clock is invoked exactly once per inner-closure call; that the clock is NOT invoked at build time; that the assembler is NOT invoked at build time; that the binder returns a NEW callable (not the input clock); that `PaperModeRuntime` is slotted with the 1-tuple `('paper_mode_now',)` and rejects foreign-attribute attachment; and that `PaperModeRuntimeCompositionError` is a plain `Exception` subclass — NOT a `ValueError` — so callers can discriminate build-time misconfiguration from call-time service-layer rejection.

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
- No modification of any file under `v2/` by task 155 (Codex review is read-only except for emitting `24_` and `25_`).
- No modification of any GO/NO-GO marker file by this planner turn.
- No modification of any prior `PLANNER_TURN_*` note.
- No modification of the master planner prompt.
- No modification of any prior task definition under `claude_worklog/agent_supervisor/tasks/`.
- No new lineage ID introduced at the 2J.C composition layer; the typed `PaperModeFlag` returned by `runtime.paper_mode_now(...)` carries only the `mode`, `flag_emitted_ts_ms`, and `live_blocked` fields defined in 2J.A.
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler, or background loop introduced in any artifact.

## Stop Conditions

If task 155 returns `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2J.C source files plus the 22 new test files only and re-runs the implementation flow. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A / 2H.B / 2H.C / 2I.A / 2I.B / 2I.C reconciliation precedents, the supervisor authors a `26_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` addendum and rewrites the `25_` marker body to `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` per the established reconciliation precedent.

If task 155 encounters a safety violation (any live behavior, any Redis access, any legacy mutation, any release intent, any FastAPI/wall-clock/subprocess/socket import in a 2J.C source file, any URL or credential leakage, any introduction of a `PAPER_MODE_LIVE_ENABLED` / `live_enabled` / bare `PAPER_MODE_LIVE` constant, any successful direct construction of `PaperModeFlag` in a 2J.C source file, any modification of a prior-milestone artifact, any modification of any GO/NO-GO marker, any modification of any 2J.C planning artifact 18-21, any modification of any 2J.C implementation artifact 22-23, any modification of the placeholder `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py`, any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`, any modification of `v2/backend/app/domain/paper_mode/` (the 2J.A package) or `v2/backend/app/services/paper_mode/` (the 2J.B package), any modification of `v2/backend/app/domain/paper_execution_ledger/` or `v2/backend/app/domain/replay_backtest_runner/`, any introduction of a `v2/backend/app/composition/paper_mode.py` flat-file placeholder, any introduction of ledger persistence, any introduction of PnL / position sizing / quantity / price / fees / slippage, any introduction of a paper trader process / paper executor / shadow executor / strategy library / replay engine / scheduler / background loop, any new lineage ID at the 2J.C composition layer, any clock invocation at build time, any assembler invocation at build time, any multiple `now_ms_clock` invocations per inner-closure call, or any catch / wrap / rewrap of `PaperModeServiceError` or `PaperModeDomainError` in the inner closure), the planner stops, surfaces to human attention, and does not auto-retry.

PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_REVIEW_OPEN_READY
