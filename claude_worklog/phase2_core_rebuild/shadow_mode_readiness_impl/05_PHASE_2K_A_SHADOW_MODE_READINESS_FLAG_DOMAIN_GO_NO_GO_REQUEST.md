# Phase 2K.A Shadow-Mode-Readiness Flag Domain — GO/NO-GO Request

## Request

The planner requests authorization to dispatch the 2K.A implementation task `156_shadow_mode_readiness_2ka_flag_domain_implementation` once the 2J.C composition root Codex PASS marker has been verified on disk (already PASS at HEAD 5565c25).

The request does NOT seek authorization to dispatch out of order. The 2K.A implementation task definition (emitted in this planner turn at `156_shadow_mode_readiness_2ka_flag_domain_implementation.json`) carries `predecessor_required_marker = PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` and `predecessor_required_marker_file = claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`. The supervisor enforces dispatch order at dispatch time.

## Predecessor markers required

- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (PASS at HEAD 5565c25). The 2K.A implementation task MUST NOT dispatch until the marker body reads `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/23_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_GO_NO_GO.md` (already PASS).
- `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/17_2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` (already PASS).
- `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/09_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_GO_NO_GO.md` (already PASS).

## REQ_0018 lane and REQ_0017 MVP relevance

- Lane: `paper_backtest_mvp`.
- Lane authority: REQ_0018 lane A (`paper_backtest_mvp`) approved.
- MVP relevance: REQ_0017 milestone 7 `SHADOW_MODE_READINESS` is the active milestone target and the last sub-phase sequence on the path to `V2_BACKTEST_AND_PAPER_MVP_READY`. Phase 2K.A introduces the typed `ShadowModeReadinessFlag` value object that the future `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation turn will pattern-match on to assert that all upstream MVP milestones have produced typed surfaces ready for shadow-mode comparison. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2K.A authoring: one milestone remains (`SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- Next gate: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024 legacy mapping

- Legacy evidence consulted: see `01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md`.
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact.
- Legacy failure addressed: legacy `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`, and `monitor_portfolio_asjad.py` inspect runtime state without a typed precondition flag, which made it impossible to assert shadow-mode readiness by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022) and in the broader failure-class register where decisions were made on stale or partially-initialized runtime state (REQ_0023, REQ_0024). The 2K.A typed flag introduces a typed boundary that downstream consumers can pattern-match on to refuse any shadow-execution path until shadow-mode readiness is asserted, and to refuse any live-execution path always until the V2 live-readiness gate flips.
- V2 proof gate: the 2K.A unit tests assert that constructing a `ShadowModeReadinessFlag` with any value other than the two named state constants raises `ShadowModeReadinessDomainError`; the absence of `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, and `live_enabled` constants is asserted by `test_no_live_enabled_constant_in_module.py`; the absence of any live-execution affordance is locked in by `test_flag_rejects_live_enabled_state.py`.

## Dispatch contract for this planner turn

This planner turn (`PLANNER_TURN_2K_OPEN_SHADOW_MODE_READINESS.md`) emits exactly one planner turn note, the 2K.A planning bundle at `02`/`03`/`04`/`05`, and exactly two task definition files (`156_shadow_mode_readiness_2ka_flag_domain_implementation.json` and `157_shadow_mode_readiness_2ka_flag_domain_codex_review.json`). The two task JSON files reference the committed spec, test plan, and safety-boundaries files at `02`/`03`/`04` so the task content is fully derivable from on-disk artifacts and does not drift across re-emission.

The master planner prompt at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` is NOT modified by this planner turn. The existing dirty entry (the prior 2I→2J transition pointer-update from `PAPER_EXECUTION_LEDGER_MVP` to `REPLAY_BACKTEST_RUNNER_MVP`) remains in the worktree; the next watchdog auto-commit lands that diff, and a subsequent planner turn re-emits the prompt with the pointer further advanced to `SHADOW_MODE_READINESS` and the distance restated as `1 milestone remaining`. Re-emitting the prompt this turn would race the watchdog auto-commit and is unnecessary; the milestone-pointer staleness is a documentation-only off-by-one and is not load-bearing for any task dispatch (tasks 156 and 157 carry `worktree_excluded_paths` for the planner-prompt entry so the supervisor can dispatch from a clean dispatch worktree without requiring the planner-prompt drift to land first).

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
- No modification of any file under `v2/`.
- No modification of any GO/NO-GO marker file.
- No modification of any prior-milestone planning, implementation, Codex review, or reconciliation artifact.
- No modification of the master planner prompt.
- No modification of the recovery task definition.
- No new lineage ID introduced.
- No `shadow_decision_id` lineage row introduced.
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler, or background loop introduced in any artifact.

PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_GO_NO_GO_REQUEST_READY
