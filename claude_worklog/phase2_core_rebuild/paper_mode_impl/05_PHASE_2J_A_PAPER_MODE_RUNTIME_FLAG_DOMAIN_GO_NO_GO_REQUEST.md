# Phase 2J.A Paper-Mode Runtime-Flag Domain — GO/NO-GO Request

## Request

The planner requests authorization to dispatch the 2J.A implementation task `150_paper_mode_2ja_runtime_flag_domain_implementation` once the 2I.C composition root Codex PASS marker is materialized.

The request does NOT seek authorization to dispatch out of order. The 2J.A implementation task definition (emitted in the post-flip planner turn) MUST carry `predecessor_required_marker = PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` and `predecessor_required_marker_file = claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`. The supervisor enforces dispatch order at dispatch time.

## Predecessor markers required

- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`. Reconciliation precedent applies per the 2H.C / 2I.C addendum pattern; an addendum at `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` may be the artifact that flips the marker body. The 2J.A implementation task MUST NOT dispatch until the marker body reads `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/23_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO.md` (already PASS).
- `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/17_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` (already PASS).
- `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md` (already PASS).

## REQ_0018 lane and REQ_0017 MVP relevance

- Lane: `paper_backtest_mvp`.
- Lane authority: REQ_0018 lane A (`paper_backtest_mvp`) approved.
- MVP relevance: REQ_0017 milestone 6 `PAPER_MODE_MVP` is the active milestone target. Phase 2J.A introduces the typed `PaperModeFlag` value object that downstream consumers (`paper_trade_id`, `replay_run`, future `shadow_decision_id`) use to assert that the runtime is paper-mode without importing a live-execution surface and without re-deriving the live-blocked posture from environment variables. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2J.A authoring: two milestones remain (`PAPER_MODE_MVP` and `SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- Next gate: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 legacy mapping

- Legacy evidence consulted: see `01_PHASE_2J_LEGACY_EVIDENCE_REVIEW.md`.
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact.
- Legacy failure addressed: ambiguous live-vs-paper posture at the trader entry point (a contributing factor in the LAB hedge-unwind / squeeze case, REQ_0022). The 2J.A typed flag introduces a typed boundary that downstream consumers can pattern-match on to refuse any live-execution path until the V2 live-readiness gate flips.
- V2 proof gate: the 2J.A unit tests assert that constructing a `PaperModeFlag` with any value other than the two named constants raises `PaperModeDomainError`; the absence of a `live_enabled` constant is asserted by `test_no_live_enabled_constant_in_module.py`.

## Dispatch contract for the post-flip planner turn

The post-flip planner turn (after the 2I.C marker body reads `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`) emits exactly one planner turn note (`PLANNER_TURN_2J_OPEN_PAPER_MODE_MVP.md`) and exactly two task definition files (`150_paper_mode_2ja_runtime_flag_domain_implementation.json` and `151_paper_mode_2ja_runtime_flag_domain_codex_review.json`). The two task JSON files reference the committed spec, test plan, and safety-boundaries files at `02`/`03`/`04` so the task content is fully derivable from on-disk artifacts and does not drift across re-emission.

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
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler, or background loop introduced in any artifact.

PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_GO_NO_GO_REQUEST_READY
END_FILE: claude_worklog/phase2_core_rebuild/paper_mode_impl/05_PHASE_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_GO_NO_GO_REQUEST.md
