# PLANNER TURN — Phase 2M Awaiting Codex Review Dispatch (No New Decision; Lane C codex_watchdog cleanup hold)

## Active requirement

REQ_0006 (Phase 2 trainer-parity rebuild) under concurrent enforcement of REQ_0017 (force paper/backtest MVP track), REQ_0018 (planner lane lock and parallel build policy), REQ_0020 (full autonomous legacy-mapped paper/backtest performance target), REQ_0022 (legacy failure: hedge-unwind and short-squeeze risk; LAB replay-case authoring), REQ_0014 / REQ_0015 / REQ_0016 (Codex non-live human-replacement watchdog and planner-level human-attention autorecovery), REQ_0011 / REQ_0021 (parallel Codex review and capacity scheduler), REQ_0019 / REQ_0023 (legacy monitor / read-only audit evidence consulted during V2 build), and REQ_0010 (safe path remap autorecovery).

## Active milestone

REQ_0017 milestone 8 `V2_BACKTEST_AND_PAPER_MVP_READY` closed at HEAD `d5beba5`:

- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` body line one — `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` body line one — `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.

The first post-consolidation Lane A evidence-collection sub-task (Phase 2M LAB hedge-unwind / short-squeeze replay-case authoring) implementation packet is closed at HEAD `d5beba5`:

- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/__init__.py`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md` (`PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_REPORT_READY`)
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/07_GO_NO_GO.md` (`PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY`)

The Phase 2M Codex review task `164_phase2m_replay_case_lab_hedge_unwind_squeeze_codex_review.json` and its dispatch note `PLANNER_TURN_2M_OPEN_CODEX_REVIEW.md` were authored by the prior planner turn and are present on disk untracked (not yet committed). The master planner prompt at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` carries an uncommitted 3-insertion / 3-deletion update to the milestone tracker (the tracker now reads `Current MVP milestone: REPLAY_BACKTEST_RUNNER_MVP` / `Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 3 milestones remaining`, which is itself stale post-`V2_BACKTEST_AND_PAPER_MVP_READY` closure but is queued for the watchdog cleanup commit and is left for a future planner turn to reconcile post-Phase-2M Codex PASS).

## Trigger

Routine planner re-invocation while:

- the Phase 2M Codex review task definition is staged untracked,
- the Phase 2M dispatch note is staged untracked,
- the master planner prompt carries an uncommitted milestone-tracker update,
- both staged files carry a trailing standalone `END_FILE: <path>` line as the last byte sequence of the body — the recurring END_FILE marker leakage pattern that the Codex watchdog cleans (cf. recent watchdog recovery commits `d5beba5`, `3724067`, `7b46dbf`, `bff9210`, `550799d`, `44a6570`, `01ba5c4`, `53d5c21`, `9e587c7`, `d796f73`, `88e1d80`, `31f4f05`, `452f098`, `a0f9c43`, `66ee259`, `5bf3d64`, `73f5e90`, `9627cf9`, `b40b45b`, `04be785`, `fcc68f7` and the established `PLANNER_TURN_2L_END_FILE_MARKER_LEAKAGE_RECOVERY.md` / `PLANNER_TURN_2H_B_END_FILE_MARKER_LEAKAGE_RECOVERY.md` reconciliation precedents).

The supervisor dispatch bridge holds task 164 because of `requires_clean_worktree: true` colliding with the staged dirty automation tree (the planner prompt path is already in the task's `worktree_excluded_paths` allow-list; the two staged Phase 2M planner-turn files are NOT in that allow-list and they carry the leakage byte that blocks dispatch).

## Classification

Lane C `codex_watchdog` cleanup hold. No new milestone task creation, no new lineage IDs, no new typed surfaces, no new execution-side surfaces, no Redis access, no `/home/wali/Desktop/AI BOT` mutation, no live-readiness gate flip, no live-trading enablement.

## Decision

This planner turn issues no new milestone task. Task 164 is already the correct next dispatch target on disk. The Codex watchdog cycle must:

1. Strip the standalone trailing `END_FILE: claude_worklog/agent_supervisor/tasks/164_phase2m_replay_case_lab_hedge_unwind_squeeze_codex_review.json` line from the staged 164 task JSON (the file body proper ends one line earlier, on the closing `}` of the JSON object).
2. Strip the standalone trailing `END_FILE: claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/PLANNER_TURN_2M_OPEN_CODEX_REVIEW.md` line from the staged 2M dispatch note (the file body proper ends one line earlier, after the `Hard-stop reaffirmation` section).
3. Optionally strip the trailing standalone `END_FILE: claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/PLANNER_TURN_2M_AWAITING_CODEX_REVIEW_DISPATCH.md` line from this note if the harness materializes it as a body byte (same recurring pattern).
4. Commit the cleaned 164 task JSON, the cleaned 2M dispatch note, this no-new-decision note, and the planner prompt milestone-tracker update under a `Codex watchdog recover dirty non-live automation artifacts` commit per the established precedent.
5. Return control to the supervisor dispatch bridge from a clean tree.
6. Supervisor dispatches task 164 against the existing Phase 2M packet on disk.
7. Codex executes task 164 and emits `08_CODEX_REVIEW.md` + `09_CODEX_GO_NO_GO.md` under `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/`.

## Sequencing rule for the next planner turn

The next planner turn opens after task 164 produces its Codex review marker (`PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` or `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_FAIL` with autofix-eligible blockers). On Codex PASS, the planner opens the next post-consolidation Lane A evidence-collection category per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp (post-consolidation evidence collection per REQ_0020 § 'Required proof before live')" — paper-mode evidence-collection harness authoring (a non-live, non-FastAPI, non-scheduler harness that replays a sequence of typed prediction inputs through the existing seven REQ_0017 typed surfaces and records the resulting `PaperExecutionLedgerEntry` mirror sequence and `ReplayBacktestSummary` for offline inspection; pure-function pipeline; no scheduler, no background loop, no FastAPI surface, no persistence, no Redis adapter at this stage). The next planner turn at that point will also reconcile the planner prompt milestone-tracker line (currently uncommitted at `Current MVP milestone: REPLAY_BACKTEST_RUNNER_MVP` / `Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 3 milestones remaining`) to reflect the closed `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation gate and the active post-consolidation Phase 2M Codex review / Phase 2N paper-mode evidence-collection harness sub-task layer.

On Codex FAIL with concrete documentation blockers and no safety violation, supervisor dispatches a REQ_0007 / REQ_0014 autofix scoped to the Phase 2M packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A / 2H.B / 2H.C / 2I.A / 2I.B / 2I.C / 2J.C / 2L reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

## Live-gate posture (restated)

Live trading remains blocked. Phase 2M does not advance the live-readiness gate. `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval, and is NOT requested by this turn, by the Phase 2M Codex review, or by the next-after-Phase-2M paper-mode evidence-collection harness sub-task.

## Hard-stop reaffirmation

No modification of `/home/wali/Desktop/AI BOT`. No Redis read or write of any kind by Phase 2M, by its Codex review, by the watchdog cleanup, or by this no-new-decision turn. No live service restart. No exchange-side action of any kind. No leverage / margin change. No live-trading enablement. No deployment. No production migration. No secret exposure. The Codex watchdog cleanup must independently confirm each of these hard-stop invariants for the staged Phase 2M packet, the staged Phase 2M dispatch note, this no-new-decision note, and the planner prompt milestone-tracker update before committing.
