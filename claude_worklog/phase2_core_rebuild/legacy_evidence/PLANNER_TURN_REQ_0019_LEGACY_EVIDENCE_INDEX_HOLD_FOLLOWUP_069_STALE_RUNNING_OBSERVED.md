# Planner Turn — REQ_0019 Legacy Evidence Index Hold Followup; Task 069 Stale-Running Observed; 2H.C Marker Still FAIL

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md (paper_backtest_mvp lane co-active under REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024).
Active MVP target: `V2_BACKTEST_AND_PAPER_MVP_READY` (3 milestones remaining once 2H.C marker reconciles: `REPLAY_BACKTEST_RUNNER_MVP`, `PAPER_MODE_MVP`, `SHADOW_MODE_READINESS`).
Active MVP milestone: `PAPER_EXECUTION_LEDGER_MVP` (closed by reconciled PASS on 2H.A/B/C; 2H.C marker file body still reads `_CODEX_FAIL` and awaits Codex watchdog reconciliation) → `REPLAY_BACKTEST_RUNNER_MVP` (2I.A planning bundle committed; tasks 143/144 committed; dispatch held by predecessor marker contract).
Lane: cross-lane consolidated hold note covering Lane A `paper_backtest_mvp`, Lane B `explainability_ui`, Lane C `codex_watchdog`, and Lane D `legacy_parity`.
Planner state: HOLD — no new planning artifact, no new task definition, no V2 source or test mutation, no marker flip.

## Why this turn emits only this one note

This turn is the second follow-up to `PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_OPEN.md` and the immediate follow-up to `PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_AWAITING_WATCHDOG_COMMIT.md`. The prior follow-up enumerated the watchdog dispatch sequence required to land the REQ_0019 pointer files and reconcile the 2H.C marker. That sequence has not yet executed. Re-emitting any of the five REQ_0019 pointer files would duplicate authored content under REQ_0018 drift guard. Re-emitting the same enumeration would duplicate intent under REQ_0021 capacity guidance. Authoring 2I.B / 2I.C / Lane B explainability / Lane C remediation / Lane D additional content would race the watchdog under REQ_0011 / REQ_0021. The disciplined planner output is one short cross-lane note that records the new evidence observed this turn and re-requests the same watchdog dispatch sequence. No BEGIN_FILE/END_FILE block other than this note is emitted.

## New evidence observed this turn

1. Lane B `explainability_ui` task `069_decision_explainability_2ha0_lineage_inventory` is in `stale_running` state. `claude_worklog/agent_supervisor/runs/069_decision_explainability_2ha0_lineage_inventory/summary.json` records `start_time: 2026-05-03T23:30:46.681867+00:00`, `end_time: null`, `status: running`, `run_pid: 946331`. `ps -p 946331` returns `PROCESS_NOT_FOUND`. The task's `required_output_files` (`05_DECISION_LINEAGE_INVENTORY_REPORT.md`, `06_DECISION_LINEAGE_GAP_MATRIX.md`, `07_DECISION_LINEAGE_GO_NO_GO.md` under `claude_worklog/phase2_core_rebuild/decision_explainability/`) do not exist on disk; only the prior planner-directive notes at filenames `05_PLANNER_THREE_LANE_STATUS_DIRECTIVE.md` and `06_PLANNER_THREE_LANE_STATUS_DIRECTIVE_2E1C_DELTA.md` are present and are not the required outputs. The standing `reconcile_stale_running_tasks()` reconciler in `claude_worklog/tools/agent_supervisor.py:1825` should reset 069 from `running` to a non-running status on the next supervisor daemon tick, because `stale_running_no_process` is satisfied (PID dead) and `check_required_outputs(task)` returns False (required outputs missing). No explicit Codex recovery task is authored this turn; the existing reconciler is the established mechanism.
2. Lane D REQ_0023 `claude_worklog/legacy_readonly_audit/` was refreshed at `2026-05-06T21:40:11.888957+00:00` by `claude_worklog/tools/legacy_readonly_audit_sentinel.py`. `git status --porcelain` reports ten modified files in that directory and zero new untracked audit files. `git diff --stat HEAD` shows nine of the ten files changed by 2 lines (timestamp-only refresh) and `05_REDIS_READONLY_KEY_STREAM_INVENTORY.md` changed by 812 lines (447 insertions / 447 deletions, consistent with stable-sort key reordering on equal keys at every poll). All ten modifications are read-only audit content under approved Lane D paths and contain zero exchange/order/leverage/margin/Redis-mutation/secret content. The Codex watchdog should commit the refresh.
3. Lane D REQ_0019 `claude_worklog/phase2_core_rebuild/legacy_evidence/` remains untracked with five pointer files (`00_EVIDENCE_INDEX.md`, `01_BUILD_IMPACT_MAP.md`, `02_CURRENT_LEGACY_FAILURE_SIGNALS.md`, `03_V2_REQUIREMENTS_FROM_RUNTIME_AUDIT.md`, `PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_OPEN.md`) plus the prior follow-up note `PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_AWAITING_WATCHDOG_COMMIT.md`. This turn adds this single follow-up note; the watchdog should commit all seven files in one Lane D commit.
4. Lane A 2H.C marker file `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body still reads exactly `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL`. The reconciliation addendum at `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` is committed at `afa7be1`. The watchdog recovery task `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` exists in `pending` status and is the sole vehicle to flip the marker per the 2H.A and 2H.B precedents (`10_…RECONCILIATION_ADDENDUM.md`, `19_…RECONCILIATION_ADDENDUM.md`). That recovery task itself sets `requires_clean_worktree: true` and therefore cannot dispatch until the Lane D commits in items 2 and 3 land.

## Watchdog dispatch sequence requested (unchanged from prior follow-up plus item 0)

0. Run `reconcile_stale_running_tasks()` to reset task `069_decision_explainability_2ha0_lineage_inventory` from `running` to `failed` or `retry_scheduled` based on the standing reconciler rule for `stale_running_no_process` with missing required outputs. This is independent of the dirty worktree and may execute first or last.
1. Commit the Lane D REQ_0023 legacy_readonly_audit refresh as one watchdog commit covering the ten modified files, with secret-scan and forbidden-token verification on the refreshed bodies.
2. Commit the Lane D REQ_0019 legacy_evidence pointer files as a separate watchdog commit covering the six already-staged files plus this single new follow-up note.
3. Worktree is now clean. Dispatch the queued recovery task `codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json`. Its sole effect is to rewrite `26_2H_C_..._CODEX_GO_NO_GO.md` body to the literal one-line marker `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` and emit its standard REPORT/GO_NO_GO pair under `claude_worklog/phase2_core_rebuild/automation_reliability/`.
4. Worktree is clean again. Dispatch task `143_replay_backtest_runner_2ia_domain_implementation.json`. Its predecessor marker contract is now satisfied.
5. Task `144_replay_backtest_runner_2ia_domain_codex_review.json` does not dispatch until task 143 emits `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` to `07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md`.

## Lane and MVP relevance

- Lane: cross-lane hold note. Direct effect on Lane A is zero in this turn; the watchdog dispatch sequence above is the operational unblocker.
- MVP relevance: the watchdog dispatch sequence directly opens REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` implementation via task 143. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` remains 3 milestones (`REPLAY_BACKTEST_RUNNER_MVP`, `PAPER_MODE_MVP`, `SHADOW_MODE_READINESS`) until task 143 emits its PASS marker.
- Blocked by: dirty worktree (items 2 and 3 above); 2H.C marker file body still `_CODEX_FAIL`; task 069 stale_running not yet reconciled.
- Next gate: `reconcile_stale_running_tasks()` resets 069; Codex watchdog commits items 2 and 3; Codex watchdog dispatches the 2H.C marker recovery task; `26_…CODEX_GO_NO_GO.md` body reads `_CODEX_PASS`; supervisor dispatches task 143; `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Legacy evidence consulted: `claude_worklog/agent_supervisor/runs/069_decision_explainability_2ha0_lineage_inventory/summary.json`; `claude_worklog/agent_supervisor/tasks/069_decision_explainability_2ha0_lineage_inventory.json`; `claude_worklog/tools/agent_supervisor.py:1770-1869` (`classify_running_task_alerts` / `stale_running_now` / `reconcile_stale_running_tasks`); `claude_worklog/legacy_readonly_audit/00_AUDIT_INDEX.md` and the nine sibling refreshed files; `claude_worklog/phase2_core_rebuild/legacy_evidence/00_EVIDENCE_INDEX.md` and the four sibling pointer files; `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`; `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`; `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_DISPATCH_HOLD_AWAITING_2HC_MARKER_RECONCILIATION.md`; `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_REEMIT_2IA_PLANNING_BUNDLE_AFTER_MATERIALIZATION_GAP.md`; `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json`; `claude_worklog/agent_supervisor/tasks/143_replay_backtest_runner_2ia_domain_implementation.json`; `claude_worklog/agent_supervisor/tasks/144_replay_backtest_runner_2ia_domain_codex_review.json`.
- Legacy failure addressed: legacy automation loop required manual human intervention to reconcile a stale_running task whose process had died and whose required outputs were missing, and to commit benign read-only audit refreshes. Both classes are autonomously handled by the existing supervisor reconciler and Codex watchdog under REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0021. This turn re-states the requested dispatch sequence and adds the newly-observed 069 evidence so the next watchdog cycle can act on it.

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
- did not modify any file under `v2/`
- did not modify any 2H.A, 2H.B, 2H.C, 2I.A, 2G, 2F, 2E1, 2E2, or 2E3 planning, implementation, review, GO/NO-GO, or reconciliation file
- did not modify the 2H.C `26_…CODEX_GO_NO_GO.md` marker file (the watchdog reconciles it per REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016)
- did not modify any task definition under `claude_worklog/agent_supervisor/tasks/`
- did not modify any run summary under `claude_worklog/agent_supervisor/runs/` (the supervisor reconciler at `claude_worklog/tools/agent_supervisor.py:1825` reconciles 069's run summary)
- did not modify the master planner prompt
- did not modify any 015A scaffold placeholder
- did not introduce any new lineage ID, FastAPI surface, adapter expansion, ledger persistence, PnL or sizing computation, GPU or checkpoint subsystem, replay engine, scheduler, or background loop in any artifact
- did not author any Codex recovery task definition (the existing `reconcile_stale_running_tasks()` and the queued `codex_recover_fail_marker_2hc_…` recovery task cover the observed states)

Final live approval remains human-only. Live trading remains BLOCKED.

PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_HOLD_FOLLOWUP_069_STALE_RUNNING_OBSERVED_READY
END_FILE: claude_worklog/phase2_core_rebuild/legacy_evidence/PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_HOLD_FOLLOWUP_069_STALE_RUNNING_OBSERVED.md
