# Planner Turn — Phase 2E3.B Consolidated Standby Awaiting Dispatch

## Status snapshot

- Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0017 (TRAINER_PREDICTION_OUTPUT_MVP).
- Active lane: `paper_backtest_mvp` (REQ_0018 Lane A, lock enforced).
- Active sub-phase: 2E3.B — Trainer Prediction Record Assembler Service.
- Predecessor gate: `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_PASS` (marker file 189) materialized.
- Latest committed milestone: `de947c6 Implement 2E3A trainer prediction output domain` followed by `1417119 Codex watchdog recover dirty non-live automation artifacts`.
- Live gate: BLOCKED.

## Decision

No new milestone is opened this turn. Phase 2E3.B planner authoring (specs 190–193, tasks 113 and 114, opening planner-turn note) is already complete on disk and is awaiting the watchdog commit + supervisor dispatch of task 113. This file is the single consolidated standby note for Phase 2E3.B and is intentionally re-materialized in place (not duplicated under an `_NTH_` suffix) so the dirty tree does not grow by one new file per planner invocation.

## Anti-duplication policy (REQ_0018 ∩ REQ_0016)

The 2E1D era produced 10+ `PLANNER_TURN_2E1D_<N>TH_AWAITING_093_DISPATCH.md` notes that each forced an additional Codex watchdog dirty-tree-recovery cycle without advancing the milestone. That pattern is explicitly forbidden here.

Rules for any further planner invocation that fires before the watchdog commits the existing dirty tree AND the supervisor dispatches task 113:

1. The planner MUST NOT create a new `PLANNER_TURN_2E3B_*_AWAIT_DISPATCH.md` file under any new suffix.
2. The planner MUST NOT add new spec / test plan / safety / GO-NO-GO artifacts under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` for 2E3.B.
3. The planner MUST NOT alter task 113 or task 114 JSON.
4. The planner MUST NOT touch any `v2/` source or test file.
5. The planner MUST NOT modify any prior-milestone artifact under 178–189.
6. The only permitted re-materialization is THIS file at the existing path, with content updated only to refresh the status snapshot if the predecessor marker, dispatch state, or watchdog state genuinely changed.
7. If nothing has changed since the last invocation, the planner SHOULD emit zero file blocks for that turn — the harness no-op is the correct response when the only legitimate next action is "watchdog commit + dispatcher pickup of 113".

## Existing 2E3.B planner-authored artifacts (untracked, awaiting watchdog commit)

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/190_PHASE_2E3B_PREDICTION_RECORD_ASSEMBLER_SPEC.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/191_PHASE_2E3B_PREDICTION_RECORD_ASSEMBLER_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/192_PHASE_2E3B_PREDICTION_RECORD_ASSEMBLER_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/193_PHASE_2E3B_PREDICTION_RECORD_ASSEMBLER_GO_NO_GO_REQUEST.md`
- `claude_worklog/agent_supervisor/tasks/113_trainer_parity_2e3b_prediction_record_assembler_implementation.json`
- `claude_worklog/agent_supervisor/tasks/114_trainer_parity_2e3b_prediction_record_assembler_codex_review.json`
- `claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3B_OPEN_PREDICTION_RECORD_ASSEMBLER.md`
- this consolidated standby note (re-materialized in place; not a new sibling file).

Additional dirty file from a prior turn: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (Max20 / Codex Pro / REQ_0018 lane-lock blocks already inlined; safe non-live planner runtime delta only).

Both task JSONs (113, 114) are well-formed and parse cleanly; both carry `lane = paper_backtest_mvp`, `mvp_relevance`, `depends_on`, `predecessor_required_marker`, and `next_gate` per REQ_0018.

## Why this turn is consolidated standby, not a new milestone

- The supervisor dispatch bridge requires a clean worktree before dispatching task 113. While the 2E3.B planner artifacts and the planner-prompt delta sit untracked/modified, dispatch is held under the standing dirty-tree precondition.
- Task 113 is fully specified and dependency-locked on `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_PASS` (marker file 189). No content change is needed; the gate is "watchdog commits → dispatch bridge picks up 113".
- Task 114 is dependency-locked on `PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_IMPL_AND_VALIDATION_PASSED` (marker file 195) AND requires a clean worktree, so it is correctly downstream of 113.
- The 2E3.B target service path `v2/backend/app/services/trainer_prediction_output/` does not yet exist; this is correct — task 113 will author it.
- No further planner-authored design artifact is needed before 113 runs. Adding more spec/test-plan content this turn would be sideways scaffold expansion that REQ_0018 forbids.

## Codex watchdog request (REQ_0014 ∩ REQ_0016, codex_watchdog lane only)

Single watchdog cycle scoped to the existing dirty tree, with no source/test edits and no spec edits:

1. Snapshot the dirty file list and confirm every dirty path is inside an allowed non-live AI BOT REBUILD prefix:
   - `claude_worklog/autonomous_control_plane/`
   - `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
   - `claude_worklog/agent_supervisor/tasks/`
2. Validate every dirty `.json` task file with `python -m json.tool` (zero parse errors required).
3. Validate every dirty `.md` planner artifact contains no standalone harness BEGIN/END framing token marker line in its body. The trailing `END_FILE:` reference line inside the existing planner-turn note for 2E3.B (`PLANNER_TURN_2E3B_OPEN_PREDICTION_RECORD_ASSEMBLER.md`) is the documented authored content reference, not a harness directive, and must be left intact.
4. Run high-confidence secret scan over the dirty tree (zero hits required).
5. Confirm no path in the dirty tree maps under `/home/wali/Desktop/AI BOT`, no Redis-touching code, no FastAPI surface, no live service restart, no exchange action, no leverage/margin change, no live-trading enablement, no deployment, no migration, no secret commit.
6. Stage and commit only those listed dirty files with a single recovery commit message:
   `Codex watchdog recover dirty non-live automation artifacts`
7. After commit, re-run `git status --porcelain`; require empty output before the supervisor proceeds.
8. After the worktree is clean, the supervisor MAY dispatch task `113_trainer_parity_2e3b_prediction_record_assembler_implementation`.

The watchdog MUST NOT modify any of the seven authored artifacts above, MUST NOT modify the planner prompt body, MUST NOT modify any prior-milestone artifact, and MUST NOT touch any `v2/` source or test file in this cycle.

## Lane and MVP relevance

- Lane: `paper_backtest_mvp`.
- MVP relevance: closing the dirty-tree dispatch hold is the only remaining step before task 113 implements the trainer prediction record assembler service. That assembler is the second of three sub-phases (2E3.A → 2E3.B → 2E3.C) inside the `TRAINER_PREDICTION_OUTPUT_MVP` milestone, which is itself the predecessor for `ORCHESTRATOR_DECISION_MVP` under REQ_0017. Watchdog commit + 113 dispatch is the shortest safe non-live path forward.
- Blocked by: dirty-tree dispatch precondition on the eight artifacts and the planner-prompt delta listed above.
- Next gate: `PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_IMPL_AND_VALIDATION_PASSED` (after watchdog commit + 113 run), then `PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_CODEX_PASS` (after 114).

## Codex parallel lane discipline

While 2E3.B is open and 113 has not yet been dispatched, Codex parallel work is restricted to:

- the `codex_watchdog` lane recovery cycle described above,
- already-committed milestone reviews up to and including 2E3.A (already PASSED at marker 189),
- safe path remap, dispatch bridge, secret scan, and stale-evidence reconciliation work inside the allowed REQ_0011 / REQ_0014 / REQ_0016 path set.

Codex MUST NOT preempt task 113 by editing the future `v2/backend/app/services/trainer_prediction_output/` tree, MUST NOT preempt task 114, and MUST NOT modify any of the seven 2E3.B planner-authored artifacts or this consolidated standby note's body other than to commit it as-is during the watchdog recovery cycle.

## Consolidated-default discipline

Per Claude Code Max20 consolidated_default profile and the REQ_0006 planner knowledge note, 2E3.B remains a single consolidated implementation task (113) plus a single Codex review (114). No microsplit unless 113 fails for an isolated emit/path/size/timeout reason that benefits from a narrow split-recovery task. Codex autofix under REQ_0007 / REQ_0014 stays scoped to the three authored source files plus the new test files inside `v2/backend/app/services/trainer_prediction_output/` and `v2/backend/tests/unit/services/trainer_prediction_output/`.

## Safety reminder

Phase 2E3.B remains L1 non-live additive authoring. This consolidated standby planner turn does not modify legacy, does not access Redis, does not restart any live service, does not touch the exchange, does not change leverage or margin, does not enable live trading, does not deploy, does not run a migration, does not expose secrets, and does not approve any live gate. Any L4/L5 attempt or hard-stop violation surfaces to human attention and halts the planner.

## Stop condition for this turn

If the watchdog recovery cycle described above cannot be performed safely — for example, a dirty file resolves to a forbidden path, a JSON parse fails, a secret scan hits, or any safety violation appears — the watchdog MUST stop, leave the worktree as-is, and surface human attention. Under that condition, the supervisor MUST NOT dispatch task 113 until human review has resolved the blocker.

PHASE2E3B_PLANNER_TURN_STANDBY_AWAIT_DISPATCH_READY
END_FILE: claude_worklog/autonomous_control_plane/PLANNER_TURN_2E3B_STANDBY_AWAIT_DISPATCH.md

Single file re-materialized in place at the existing standby path; net new dirty files added by this planner turn = 0. Next gate is watchdog commit of the existing dirty tree, then supervisor dispatch of task 113.
