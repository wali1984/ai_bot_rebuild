# Planner Turn — Open Phase 2J.C Paper Mode Runtime Flag Composition Root

## State observation (HEAD 9627cf9)

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body reads `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`. Phase 2I (`REPLAY_BACKTEST_RUNNER_MVP`) is fully closed.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` body reads `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/17_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` body reads `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`.
- The only worktree-dirty entry is `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`, restated in this turn to reflect `PAPER_MODE_MVP` / 2 remaining (the prior dirty diff still recorded `REPLAY_BACKTEST_RUNNER_MVP` / 3 remaining and is now superseded by this turn's prompt body).
- 2J.C composition-root planning bundle (`18-21`) is NOT YET authored at the time of this turn. The 2J phase breakdown at `00_PHASE_2J_SUB_PHASE_BREAKDOWN.md` already commits the 2J.C scope and the predecessor marker; this turn materializes the four planning artifacts and the consolidated implementation task `154`.

## Decision

Open Phase 2J.C — Paper Mode Runtime Flag Composition Root. Materialize the four planning bundle documents at `18-21` under `claude_worklog/phase2_core_rebuild/paper_mode_impl/` and the consolidated implementation task `154_paper_mode_2jc_runtime_flag_composition_root_implementation.json` under `claude_worklog/agent_supervisor/tasks/`. Defer the `155` Codex review task to the next planner turn after the `15_2J_C_..._GO_NO_GO.md` IMPL_AND_VALIDATION marker materializes, per the consolidated_default sub-phase pattern used at 2H.C, 2I.A, 2I.B, 2I.C, 2J.A, and 2J.B.

## Lane / MVP relevance

- Lane: `paper_backtest_mvp`.
- MVP relevance: Phase 2J.C is the third and final sub-phase of REQ_0017 milestone 6 `PAPER_MODE_MVP`. After 2J.C Codex pass, REQ_0017 milestone 6 is satisfied and the planner opens REQ_0017 milestone 7 `SHADOW_MODE_READINESS` (Phase 2K). Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` after 2J.C closes: one milestone remains (`SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS` (already materialized).
- Next gate: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.

## Legacy evidence consulted, behavior preserved, failure addressed

- Legacy evidence consulted: `claude_worklog/phase2_core_rebuild/paper_mode_impl/01_PHASE_2J_LEGACY_EVIDENCE_REVIEW.md`, `claude_worklog/legacy_readonly_audit/02_STARTUP_SCRIPT_MAP.md`, `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`, and the read-only inventories for `legacy_reference/AI BOT/scripts/start_all_services_production.sh`, `legacy_reference/AI BOT/trading/trader.py`, and `legacy_reference/AI BOT/rl/orchestrator_worker.py`.
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact. The 2J.B assembler service surface is consumed unchanged.
- Legacy failure addressed: legacy `trader.py` and `rl.orchestrator_worker` carried implicit live-mode posture through environment variables and per-call argument passing, which made it impossible to assert the live-blocked posture by typed value (REQ_0022 LAB hedge-unwind / squeeze failure; REQ_0017 / REQ_0020 paper-mode boundary requirement). The 2J.A typed flag introduced the typed value object; the 2J.B service introduced the validated assembler; 2J.C now exposes the slotted single-closure composition surface that downstream consumers (paper execution ledger consumers, replay/backtest runner consumers, future `shadow_decision_id` consumers) bind to without importing any live-execution surface and without re-deriving the live-blocked posture from environment variables.
- V2 proof gate: the 2J.C unit tests assert (a) `PaperModeRuntime.__slots__ == ("paper_mode_now",)` exactly, (b) `build_paper_mode_runtime` raises `PaperModeRuntimeCompositionError` with `code == "must_be_callable"` for any non-callable `now_ms_clock`, (c) the slotted runtime exposes a single `paper_mode_now` attribute that adapts the 2J.B service unchanged, (d) the closure forwards `assemble_paper_mode_flag(requested_mode=requested_mode, now_ms_clock=_now_ms_clock)` exactly once per call, (e) the closure propagates `PaperModeServiceError` and `PaperModeDomainError` unwrapped, (f) the redis-clean / fastapi-clean / url_env-clean import invariants hold, and (g) the cross-isolation diff returns zero lines outside the additive 2J.C scope.

## Risk

- Live gate: blocked. 2J.C does not change live posture.
- Safety: cross-isolation paths enforced per `20_PHASE_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`; no Redis, FastAPI, adapter, or live-execution surface introduced.
- Worktree: dispatch requires clean worktree; the planner-prompt path remains in `worktree_excluded_paths` per the supervisor isolation contract.

## Hard stops

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write or delete any Redis key.
- Do not invoke any Redis command.
- Do not place, cancel, or modify any exchange order.
- Do not change leverage or margin.
- Do not restart any live service.
- Do not enable live trading.
- Do not deploy.
- Do not run any production migration.
- Do not expose or commit any credential.
- Do not approve the live gate.
- Do not author any 2J.C source or test file outside the additive scope set in `18` / `19` / `20`.

## Authored artifacts in this turn

- `claude_worklog/phase2_core_rebuild/paper_mode_impl/18_PHASE_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_SPEC.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/19_PHASE_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/20_PHASE_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/21_PHASE_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md`
- `claude_worklog/agent_supervisor/tasks/154_paper_mode_2jc_runtime_flag_composition_root_implementation.json`
- `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (milestone update from `REPLAY_BACKTEST_RUNNER_MVP` / 3 remaining to `PAPER_MODE_MVP` / 2 remaining)
- `claude_worklog/autonomous_control_plane/PLANNER_TURN_2J_C_OPEN_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT.md` (this turn note)

PHASE2J_C_OPEN_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT
