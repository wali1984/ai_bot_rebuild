# Planner Turn 2K.B Open — Shadow-Mode-Readiness Flag Assembler Service

Planner date: 2026-05-07.
Planner HEAD at this turn: 88e1d80 (the latest watchdog dirty-tree recovery commit, with the pre-existing planner-prompt drift still unstaged in the worktree pending the next watchdog auto-commit batch and the prior-turn untracked task `159_shadow_mode_readiness_2kb_flag_assembler_service_codex_review.json` still unstaged for the same reason).

## Decision Summary

The 2K.A domain Codex marker file
`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/09_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_GO_NO_GO.md`
body reads exactly `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS`. The 2K.A domain implementation marker
`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/07_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_GO_NO_GO.md`
body reads exactly `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`. The 2J.C composition-root Codex marker
`claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
body reads exactly `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`. The 2K.A sub-phase is closed; Phase 2K advances to 1/3 closed and 2K.B opens.

This planner turn authors the 2K.B planning bundle (10 spec, 11 test plan, 12 safety boundaries, 13 GO_NO_GO_REQUEST) and the 2K.B implementation task definition (158). The 2K.B Codex-review task definition (159) was already authored in a prior planner turn at HEAD prior to 2K.A close and is currently untracked in the worktree; this turn does NOT modify 159 — its predecessor-marker check on `15_2K_B_…` content remains correct without modification.

## Files Authored This Turn

Under `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/`:

- `10_PHASE_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_SPEC.md`
- `11_PHASE_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `12_PHASE_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `13_PHASE_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`
- `PLANNER_TURN_2K_B_OPEN_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE.md` (this file)

Under `claude_worklog/agent_supervisor/tasks/`:

- `158_shadow_mode_readiness_2kb_flag_assembler_service_implementation.json`

No other files are authored this turn. No file under `v2/` is modified. No GO/NO-GO marker file is modified. No prior-milestone planning, implementation, Codex review, or reconciliation artifact is modified. No 2K.A artifact 00–09 is modified. The pre-existing untracked task `159_shadow_mode_readiness_2kb_flag_assembler_service_codex_review.json` is NOT modified by this planner turn. The master planner prompt is not modified by this planner turn; the existing dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` remains in the worktree-isolation exclusion list of task 158 so the supervisor can dispatch from a clean dispatch worktree without requiring the planner-prompt drift to land first.

## 2K.B Authored Surface (Exact Set, From Spec 10 and Test Plan 11)

Source files (3):

- `v2/backend/app/services/shadow_mode_readiness/__init__.py`
- `v2/backend/app/services/shadow_mode_readiness/errors.py`
- `v2/backend/app/services/shadow_mode_readiness/service.py`

Tests (31):

- `v2/backend/tests/unit/services/shadow_mode_readiness/__init__.py` (zero bytes)
- 30 single-test files enumerated in `11_PHASE_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_TEST_PLAN.md` items 2–31.

Implementation report and GO/NO-GO marker (2):

- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/14_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/15_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_GO_NO_GO.md`

Codex review report and Codex GO/NO-GO marker (2, after task 159):

- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/16_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/17_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`

Public surface (exact `__all__` per spec 10 section "Public surface"):

1. `assemble_shadow_mode_readiness_flag`
2. `ShadowModeReadinessServiceError`

There is NO `SHADOW_MODE_LIVE` constant, NO `SHADOW_MODE_LIVE_ENABLED` constant, NO `live_enabled` constant, NO `shadow_decision_id` lineage row, and NO live-execution affordance at any layer of the 2K.B service. This absence is locked in by `test_assemble_rejects_live_requested_state.py` (test plan item 29) and `test_assemble_rejects_live_enabled_requested_state.py` (test plan item 30) and the source-side forbidden-token scan in `test_assembler_service_forbidden_tokens.py` (test plan item 14).

## Predecessor Markers Required (Verified On Disk)

- `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/09_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_GO_NO_GO.md` (PASS).
- `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED` at
  `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/07_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_GO_NO_GO.md` (PASS).
- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` at
  `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (PASS).

The supervisor's predecessor-marker check on task 158 is governed by the 09 / 07 / 25_2J_C content. Supervisor dispatch of task 158 occurs only from a clean worktree where the planner-prompt drift and the prior-turn untracked 159 task are committed by the next watchdog auto-commit batch (the planner-prompt path and the 159 task path are in `worktree_excluded_paths` for task 158 so the dispatch worktree can be clean despite the existing drift).

## Lane / MVP Relevance / Gates

- Lane: `paper_backtest_mvp` (REQ_0018 lane A approved).
- MVP relevance: opens REQ_0017 milestone 7 second sub-step. Builds the pure derivation surface that binds the typed `ShadowModeReadinessFlag` from 2K.A under a deterministic 6-step validation pipeline plus a 2-element exhaustive mirror dispatch table; the absence of any live-execution affordance at the 2K.B service layer is locked in by the `live` and `live_enabled` requested-state rejection tests. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2K.B open: one milestone remains (`SHADOW_MODE_READINESS` closes after 2K.C).
- Blocked by: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS` (PASS); `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED` (PASS); `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` (PASS).
- Next gate (task 158): `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- Next gate (task 159, already authored): `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024 Legacy Mapping

- Legacy evidence consulted: `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md`, plus the underlying read-only audit artifacts at `claude_worklog/legacy_runtime_audit/00`, `06`, `07`, `09`, `10`, `11`, `12` and `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind / squeeze case, REQ_0022).
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact. No mutation of any GO/NO-GO marker. No mutation of the master planner prompt. No mutation of any 2K.A artifact 00–09.
- Legacy failure addressed: legacy `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`, and `monitor_portfolio_asjad.py` plus per-call argument passing in `trader.py` and `rl.orchestrator_worker` carried implicit shadow-mode-readiness assumptions through process-global state, which made it impossible to assert shadow-mode readiness by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022). The 2K.B assembler service binds the typed `ShadowModeReadinessFlag` from 2K.A under a deterministic 6-step validation pipeline and a 2-element exhaustive mirror dispatch table (`not_ready` / `ready`) plus the unconditional `live_blocked=True` literal at the call site to lock in the absence of any live-execution affordance at the service layer; the explicit rejection of `"live"` and `"live_enabled"` requested-state values guarantees that any future caller whose configuration accidentally surfaces a live-execution synonym is refused before producing a flag. The single-clock-call discipline removes any hidden wall-clock dependency.
- V2 proof gate: the 2K.B unit tests assert that calling the assembler with any non-`not_ready` / non-`ready` requested state raises `ShadowModeReadinessServiceError`; `test_assemble_rejects_live_requested_state.py` and `test_assemble_rejects_live_enabled_requested_state.py` lock in the absence of any live-execution affordance at the 2K.B layer; `test_assemble_calls_clock_exactly_once.py` locks the single-clock-call discipline; `test_assemble_returns_frozen_flag.py` locks the frozen / slotted invariant; the forbidden-token scan locks the absence of `SHADOW_MODE_LIVE` / `SHADOW_MODE_LIVE_ENABLED` / `shadow_decision_id` / sibling lineage tokens in the 2K.B source files.

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

If task 158 returns `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_FAILED` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2K.B source files plus the 30 new test files only and re-runs the implementation flow.

If task 159 (already authored, untracked at this HEAD) returns `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the same three authored source files plus the 30 new test files only and re-runs the implementation flow.

If either task encounters a safety violation (any live behavior, any Redis access, any legacy mutation, any release intent, any FastAPI/wall-clock/subprocess/socket import in a 2K.B source file, any URL or credential leakage, any introduction of a `SHADOW_MODE_LIVE_ENABLED` / `SHADOW_MODE_LIVE` / `live_enabled` constant, any successful construction of a `ShadowModeReadinessFlag` with `live_blocked == False`, any introduction of a `shadow_decision_id` lineage row at the 2K.B layer, any modification of a prior-milestone artifact, any modification of any GO/NO-GO marker, any modification of any 2K.A artifact 00–09, any modification of any 2K.B planning artifact 10–13, any modification of the placeholder `v2/backend/app/services/paper_loop.py` or `v2/backend/app/services/replay_runner.py`, any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`, any modification of `v2/backend/app/domain/shadow_mode_readiness/` or `v2/backend/app/domain/paper_mode/` or `v2/backend/app/domain/paper_execution_ledger/` or `v2/backend/app/domain/replay_backtest_runner/`, any introduction of a `v2/backend/app/services/shadow_mode_readiness.py` flat-file placeholder, any introduction of ledger persistence, any introduction of PnL / position sizing / quantity / price / fees / slippage, any introduction of a paper trader process / paper executor / shadow executor / shadow trader / strategy library / replay engine / scheduler / background loop, any new lineage ID at the 2K.B service layer, or any multiple now_ms_clock invocations per assemble_shadow_mode_readiness_flag call), the planner stops, surfaces to human attention, and does not auto-retry.

PHASE2K_B_SHADOW_MODE_READINESS_OPEN_READY
