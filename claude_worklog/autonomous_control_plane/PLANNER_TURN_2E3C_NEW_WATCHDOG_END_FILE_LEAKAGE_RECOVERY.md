# Planner Turn — Phase 2E3.C New Codex Watchdog for END_FILE Marker Leakage Recovery

Date: 2026-05-05
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0007_CODEX_AUTOFIX_NON_LIVE_BLOCKERS.md ∩ REQ_0014_CODEX_HUMAN_ATTENTION_AUTONOMOUS_RECOVERY.md ∩ REQ_0015_PLANNER_LEVEL_HUMAN_ATTENTION_CODEX_AUTORECOVERY.md ∩ REQ_0016_CODEX_NON_LIVE_HUMAN_REPLACEMENT_WATCHDOG.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md
Lane: codex_watchdog
Profile: Claude Code Max20 consolidated_default
Granularity: consolidated single-task watchdog recovery
Live gate: blocked

## New diagnostic finding beyond the prior turn

The two prior planner turns (`PLANNER_TURN_2E3C_OPEN_PREDICTION_OUTPUT_COMPOSITION_ROOT.md`, `PLANNER_TURN_2E3C_AWAITING_115_DISPATCH.md`) treated task 115's dispatch hold as caused only by the dirty worktree and assumed the existing watchdog `codex_recover_114_trainer_parity_2e3b_prediction_record_assembler_codex_review` would clean it up. Direct file inspection in this turn shows two new facts:

1. The existing watchdog has already run to completion — `claude_worklog/agent_supervisor/runs/codex_recover_114_trainer_parity_2e3b_prediction_record_assembler_codex_review/summary.json` reports `status: completed` with end time 2026-05-05T17:12:35Z. It successfully materialized the missing 196 / 197 review artifacts but it did not — and was not scoped to — strip the END_FILE leakage in the 2E3.C planner emission files.

2. Every one of the six untracked 2E3.C emission files carries a trailing standalone `END_FILE: <repo-relative-path>` line in its file body, where the suffix path equals the file's own repo-relative path:

   - `claude_worklog/agent_supervisor/tasks/115_trainer_parity_2e3c_prediction_output_composition_root_implementation.json` — line 144 leaked; breaks `json.load`.
   - `claude_worklog/agent_supervisor/tasks/116_trainer_parity_2e3c_prediction_output_composition_root_codex_review.json` — line 82 leaked; breaks `json.load`.
   - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/198_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_SPEC.md` — line 256 leaked.
   - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/199_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_TEST_PLAN.md` — line 74 leaked.
   - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/200_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md` — line 107 leaked.
   - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/201_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md` — line 41 leaked.

The 200 file's own "Safety Boundaries" content forbids exactly this pattern: "Any standalone harness BEGIN/END framing token marker line in any authored file body." The 200 file therefore violates its own forbidden behavior at line 107. The 115 and 116 JSON files are unparseable by `json.load` and the supervisor cannot dispatch them. Even if the dirty worktree were cleaned by a generic add-and-commit, task 115 dispatch would immediately fail at the supervisor's task-definition load step.

The prior turns' assumption that "the staged Codex watchdog recovery task is the authorized actor to inspect, validate, secret-scan, and commit this dirty file together with the seven untracked Phase 2E3.C planner-emission files" was wrong on three counts: (a) the watchdog has already completed and cannot be re-triggered, (b) the watchdog's scope was 196 / 197 materialization, not 2E3.C strip, and (c) a generic add-and-commit would lock in the unparseable JSON state.

## Decision for this turn

Open exactly one new Lane C `codex_watchdog` recovery task that surgically strips the trailing `END_FILE: <repo-relative-path>` line from each of the six listed 2E3.C emission files when and only when the suffix path equals the file's own repo-relative path, validates `json.load` of 115 and 116, validates the absence of remaining harness framing token marker lines, runs the high-confidence secret scan, commits all eleven dirty entries plus the two recovery outputs in a single durable commit, pushes, and reports.

## Worktree state at this turn

`git status --porcelain` reports exactly nine entries inside AI BOT REBUILD:

```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
?? claude_worklog/agent_supervisor/tasks/115_trainer_parity_2e3c_prediction_output_composition_root_implementation.json
?? claude_worklog/agent_supervisor/tasks/116_trainer_parity_2e3c_prediction_output_composition_root_codex_review.json
?? claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3C_AWAITING_115_DISPATCH.md
?? claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3C_OPEN_PREDICTION_OUTPUT_COMPOSITION_ROOT.md
?? claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/198_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_SPEC.md
?? claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/199_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_TEST_PLAN.md
?? claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/200_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md
?? claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/201_PHASE_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md
```

After this turn's two emissions land, the count rises to eleven by adding:

```
?? claude_worklog/agent_supervisor/tasks/codex_recover_2e3c_planner_emission_end_file_marker_leakage_cleanup.json
?? claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3C_NEW_WATCHDOG_END_FILE_LEAKAGE_RECOVERY.md
```

All eleven entries are inside `/home/wali/Desktop/AI BOT REBUILD`. None are inside `/home/wali/Desktop/AI BOT`. None touch Redis, exchange, leverage, margin, secrets, deployment, live trading, or any L4 / L5 surface. All eleven are inside REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016 non-live recovery scope.

## Lane gating reaffirmed

REQ_0018 lane lock confirmed for this turn:

- `lane`: `codex_watchdog`
- `mvp_relevance`: clears the END_FILE marker leakage on the six 2E3.C emission files so task 115 JSON parses, returns the worktree to clean, and unblocks dispatch of supervisor task 115 on Lane A `paper_backtest_mvp`. Without this turn the supervisor would either continue an indefinite no-progress dispatch hold loop or commit the unparseable 115 JSON into history.
- `next_gate`: `PHASE2E3C_PLANNER_EMISSION_END_FILE_MARKER_LEAKAGE_RECOVERY_PASS`
- `blocked_by`: none — this turn opens a Lane C watchdog recovery task that has no upstream gate dependency beyond standing non-live approval.

The downstream gate sequence is unchanged:

1. Lane C `codex_recover_2e3c_planner_emission_end_file_marker_leakage_cleanup` PASS marker `CODEX_NON_LIVE_RECOVERY_READY` with post-commit `git status --porcelain` empty.
2. Lane A supervisor dispatches `115_trainer_parity_2e3c_prediction_output_composition_root_implementation` against its now-parseable definition; gate `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.
3. Lane A supervisor dispatches `116_trainer_parity_2e3c_prediction_output_composition_root_codex_review`; gate `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS`.
4. Closure of REQ_0017 milestone 1 `TRAINER_PREDICTION_OUTPUT_MVP`. Fresh consolidated planner turn opens REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP`.

No Lane B / Lane D work is opened in this turn. No Lane A work is dispatched in this turn. The new watchdog task does not race the prior `codex_recover_114_*` recovery because that task is already in `status: completed` and cannot be re-triggered.

## Refusal to drift sideways

Per REQ_0017 'Hard Roadmap Constraint' and REQ_0018 'Forbidden drift', the planner explicitly refuses in this turn to:

- open a new trainer subsystem (no checkpoint runner, no GPU runner, no model-loading subsystem, no FastAPI surface, no adapter expansion).
- open generic scaffold expansion or generic architecture docs.
- open frontend polish work without a real Lane A data contract (the Phase 2E3.C contract is not yet committed).
- re-emit 115 / 116 / 198 / 199 / 200 / 201 from the planner — re-emission would create duplicate untracked content and risk byte drift against the prior authoritative emission, and the planner output stream itself triggered the original leakage so re-emission is the wrong tool.
- modify the planner-prompt diff, the two prior planner-turn markdown docs, any prior-milestone artifact, or any v2/ source or test file in this turn.
- open a parallel autofix that would race the new watchdog's commit window.

## Why the planner does not cleanup directly

The planner output policy is BEGIN_FILE / END_FILE only. The planner cannot run `git add`, `git commit`, `git push`, secret scans, or `python -m json.tool` from inside its emission stream. Codex CLI is the only allowed actor with shell capability inside AI BOT REBUILD that can perform the surgical strip, validate it, secret-scan, and durably commit-and-push under the standing non-live approval. Delegating to a Codex watchdog recovery task is the correct division of authority under REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016.

## Naming and ID reconciliation

The new task ID `codex_recover_2e3c_planner_emission_end_file_marker_leakage_cleanup` follows the established naming pattern from `093_codex_recovery_2e1d_end_file_marker_leakage_cleanup` and `codex_recover_114_trainer_parity_2e3b_prediction_record_assembler_codex_review`. The 093 task patched the planner parser regex; the new task does not need to re-patch the parser — that fix already landed on master per commit history reference in `PLANNER_TURN_2E1D_NO_NEW_DECISION.md`. The 2E3.C emission leakage occurred because the planner output stream embedded an `END_FILE: <path>` line inside each BEGIN_FILE block body before the closing `END_FILE` marker; the parser captures everything up to the last `END_FILE` due to the trailing `$` anchor, so the embedded line is included in the file body. The corrective behavior on the planner side is to never embed an `END_FILE: <path>` marker inside BEGIN_FILE block bodies and to always close with the bare `END_FILE` form. This planner turn complies with that rule on both of its own emissions.

## Non-live safety reaffirmed

- No `/home/wali/Desktop/AI BOT` mutation in this turn or in the staged dispatch sequence.
- No Redis read or write at any layer.
- No live service restart.
- No exchange action.
- No leverage or margin change.
- No live trading enable.
- No deployment.
- No production migration.
- No secret exposure or commit.
- Live gate remains blocked.
- This turn does not modify any v2/ source or test file.
- This turn does not modify any prior-milestone artifact byte content.
- This turn does not modify the body of any task definition under `claude_worklog/agent_supervisor/tasks/` other than authoring the new watchdog task definition.
- This turn does not modify the master planner prompt.
- This turn does not modify `claude_master_rebuild_planner_status.json` (status remains `ready` / `dry-run` / live gate `blocked`).
- This turn emits exactly two new files: this hold document and the new watchdog task definition.

## Files emitted by this turn

- `claude_worklog/agent_supervisor/tasks/codex_recover_2e3c_planner_emission_end_file_marker_leakage_cleanup.json`
- `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3C_NEW_WATCHDOG_END_FILE_LEAKAGE_RECOVERY.md` (this file)

Both files close with bare `END_FILE` markers and contain no embedded `END_FILE: <path>` line inside their bodies, so they do not recreate the same leakage pattern.

## Next planner turn trigger

The planner re-fires after one of:

- The new watchdog emits `CODEX_NON_LIVE_RECOVERY_READY` and post-commit `git status --porcelain` is empty (supervisor dispatches 115).
- The new watchdog emits `CODEX_NON_LIVE_RECOVERY_BLOCKED` (planner inspects the documented blocker and decides whether to open a narrower follow-up watchdog or surface to human attention for the specific safety issue).
- A safety stop or genuine human-attention condition appears that is outside Codex authority (live action, legacy mutation, Redis write/delete, service restart, exchange action, deployment, secret scan failure on real credentials, ambiguous trading/business decision, L4/L5 action, final live approval).

PLANNER_TURN_2E3C_NEW_WATCHDOG_END_FILE_LEAKAGE_RECOVERY_READY
