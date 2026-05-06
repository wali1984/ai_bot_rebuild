# Planner turn human-attention diagnostic — Phase 2H.B Codex closed-loop autofix-and-reconciliation watchdog dispatch stall

## Trigger

This is the third consecutive planner turn entering with the same untracked pre-staged-task set on disk and no Codex watchdog progress on that specific set. The prior planner turn explicitly committed to this escalation in lines 113–115 of `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/PLANNER_TURN_2HB_CODEX_AUTOFIX_PRESTAGED_REAFFIRMATION.md`:

> "If a third consecutive planner turn finds the same untracked set still in place with no Codex watchdog progress, the planner should escalate by surfacing a `human_attention_required` diagnostic instead of emitting a third re-affirmation, since by then the watchdog dispatch cycle would itself be the blocker."

This diagnostic honors that commitment. No third re-affirmation is emitted. No new milestone is opened. No new task definition is created. No MVP advancement is performed.

## Active requirement

REQ_0006 (trainer parity) remains the inbox header. The prime directive under REQ_0017 / REQ_0018 / REQ_0020 / REQ_0021 holds the planner lane lock on the paper / backtest MVP track until `V2_BACKTEST_AND_PAPER_MVP_READY` exists. This diagnostic is itself a Lane C `codex_watchdog` / dispatch-bridge artifact and does not violate the lane lock.

## Status snapshot at planner-turn entry

`git status --short` returns exactly six untracked entries (no staged changes, no modified-tracked changes, no deleted entries):

- `claude_worklog/agent_supervisor/tasks/140_paper_execution_ledger_2hb_codex_fail_autofix_and_reconciliation.json`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/17_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/18_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/PLANNER_NEXT_MILESTONE_2HB_CODEX_AUTOFIX.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/PLANNER_TURN_2HB_CODEX_AUTOFIX_PRESTAGED_CONFIRMATION.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/PLANNER_TURN_2HB_CODEX_AUTOFIX_PRESTAGED_REAFFIRMATION.md`

Recent commits at planner-turn entry (most recent first):

- `593cc81 Codex watchdog recover dirty non-live automation artifacts`
- `f802bd7 Codex watchdog recover dirty non-live automation artifacts`
- `be1a38c Clean paper execution ledger 2HC task JSON marker leakage`
- `a734d84 Codex watchdog recover dirty non-live automation artifacts`
- `22dcf52 Add Codex watchdog recovery task for fail marker 16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md`
- `68a6848 Codex watchdog recover dirty non-live automation artifacts`
- `2844d95 Codex watchdog recover dirty non-live automation artifacts`
- `4bb00b4 Codex watchdog recover dirty non-live automation artifacts`
- `6ed8298 Codex watchdog recover dirty non-live automation artifacts`
- `2cff1c9 Add Codex watchdog recovery task for fail marker 135_2H_A_EVIDENCE_RECONCILIATION_GO_NO_GO.md`

## Watchdog activity assessment

The recent commit set demonstrates the Codex watchdog is active and has been recovering dirty non-live automation artifacts repeatedly. However, the watchdog has NOT, in the interval covered by the prior two planner turns and this turn, swept the specific six-file 2H.B Codex-review-level autofix-and-reconciliation set listed above into a durable commit, and has NOT dispatched task 140. The watchdog dispatch cycle has therefore become the blocker for closing the 2H.B Codex review and for clearing the supervisor pre-dispatch gate of task 138 (Phase 2H.C composition root implementation).

## Candidate root causes (observations only)

The planner does not assert a single root cause. The candidate root causes the watchdog operator and human reviewer should consider, in observation order:

- The five untracked planner artifacts are inside `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` and `claude_worklog/agent_supervisor/tasks/`, which are inside REQ_0014 / REQ_0016 / REQ_0021 watchdog allowed paths. Their `git status --short` ?? prefix is consistent with file additions, not modifications.
- The `Codex watchdog recover dirty non-live automation artifacts` commit pattern shows the watchdog has been operating on a different dirty-file set in the same repository in the same interval; the dispatch cycle has not yet reached this specific set.
- The task 140 JSON declares `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` and `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_codex_fail_marker_recovery_ready.json` as `worktree_excluded_paths`. If the watchdog dispatch precondition rejects the dispatch worktree as dirty whenever any non-excluded path shows ??, the six untracked files themselves block their own dispatch. This is a self-blocking precondition pattern and is the most plausible single explanation.
- The watchdog may be picking up the same 2H.B impl-level fail marker at file 16 referenced by commit `22dcf52` instead of the Codex-review-level fail marker at file 18 created by task 137; both markers are 2H.B-prefixed and both are inside the same directory, and the impl-level recovery may have already been resolved by an earlier cycle while the review-level recovery has not been recognized as a separate dispatch.
- The watchdog dispatch cycle may require an explicit operator nudge to scan task 140 before it picks it up, since task 140 is a brand-new file added by the prior planner turn rather than a modification to an existing tracked task.
- Quota or rate-limit pressure in the 5-hour window may have caused the watchdog to defer dispatch of task 140 in favor of cheaper recovery actions; if so, the pause is correct, but the planner has no visibility into the quota probe and cannot disambiguate this from the other candidate causes.

## Recommended safe remediations (in priority order)

The remediation candidates below are all non-live, all inside AI BOT REBUILD, all within REQ_0014 / REQ_0016 / REQ_0021 watchdog scope, and all require neither modification of `/home/wali/Desktop/AI BOT` nor any Redis / live-service / exchange / leverage / margin / deployment / live-trading action. Any single one of them, executed by the human operator or by the watchdog operator with appropriate authority, resolves the dispatch stall.

1. The watchdog operator commits the six untracked planner artifacts plus this diagnostic note as a single non-live `Codex watchdog recover dirty non-live automation artifacts` durable commit and then dispatches task 140 manually with `claude_worklog/tools/dispatch_supervisor_task.py 140` (or equivalent). This is the lowest-friction option and matches the explicit hand-off prescribed by both prior planner turns.

2. The watchdog operator inspects the watchdog dispatch precondition and confirms whether the worktree dirty-state guard is rejecting dispatch of task 140 because task 140 itself is one of the untracked files. If yes, either (a) commit the six artifacts first as in option 1, or (b) extend the dispatch precondition to permit dispatching a task whose own JSON is the only newly-untracked file in the worktree. Option (b) is a watchdog-tool change and would be a new Lane C milestone; the planner does not propose it as the first remediation.

3. The watchdog operator inspects `claude_worklog/tools/` and `v2/` watchdog scripts for whether a recent change inadvertently restricted the file-pattern recognition of `\d{3}_*.json` task files, and if so, narrowly reverts. The planner does not author this change in this turn.

4. The human reviewer decides to re-stage the entire 140 task package by deleting the six untracked files and re-asking the planner to re-emit them. The planner does NOT recommend this because it carries byte-mismatch risk against the already-on-disk 50KB+ task JSON and would discard the prior two planner turns' confirmation history. Listed for completeness only.

5. The human reviewer escalates to a hard `human_attention_required` flag in `master_rebuild_planner_status.json` (if such a flag mechanism exists in the current control plane) and pauses planner re-entry until either the watchdog dispatch is unblocked or the dispatch precondition is updated. This diagnostic note is intended to be the surface artifact for that escalation; if the control plane has no automated `human_attention_required` flag at the planner-status JSON level, the diagnostic note itself is the surface artifact.

The first remediation is the planner's recommended path. It is the same hand-off prescribed by the prior two planner turns, simply applied by the human operator if the watchdog dispatch cycle has not yet reached it.

## What this planner turn does NOT do

- Does NOT re-emit any of the six pre-staged byte-stable artifacts.
- Does NOT modify the task 140 JSON.
- Does NOT advance the MVP milestone past Phase 2H.B Codex review.
- Does NOT open Phase 2H.C composition root implementation; task 138 remains pre-staged and blocked on `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS`.
- Does NOT create a new task definition under `claude_worklog/agent_supervisor/tasks/`.
- Does NOT modify any 2H.A artifact (00–10), any 2H.B artifact (11–17), the 2H.B Codex review GO/NO-GO marker (18), or any 135-prefixed automation_reliability artifact.
- Does NOT modify any V2 backend service or test source.
- Does NOT modify the master planner prompt at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
- Does NOT modify `claude_worklog/tools/reconcile_evidence_status.py` (the deterministic single-tuple append authorized to task 140 remains exclusively task 140's responsibility).
- Does NOT take any L4/L5 action.
- Does NOT request, prepare, or imply any final live gate authority.

## MVP progress map (unchanged this turn)

- Milestone 1 `TRAINER_PREDICTION_OUTPUT_MVP`: closed.
- Milestone 2 `ORCHESTRATOR_DECISION_MVP`: closed.
- Milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`: closed.
- Milestone 4 `PAPER_EXECUTION_LEDGER_MVP`: in progress.
  - Phase 2H.A domain: PASS at file 09 (`PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS`); reconciliation addendum at file 10.
  - Phase 2H.B assembler service: implementation PASS at file 16 (`PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`); Codex review FAIL at file 18 on rubric rows 5 and 43; closed-loop reconciliation pre-staged as task 140; dispatch stalled — this diagnostic.
  - Phase 2H.C composition root: pre-staged at task 138 (implementation) and 139 (Codex review); blocked on 2H.B Codex PASS.
- Milestones 5–7 (`REPLAY_BACKTEST_RUNNER_MVP`, `PAPER_MODE_MVP`, `SHADOW_MODE_READINESS`): not yet opened.

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 4 sub-milestones remaining (2H.C composition root, replay/backtest runner, paper mode, shadow readiness).

## Lane and gate (unchanged)

- Lane: `codex_watchdog` (REQ_0018 Lane C: dispatch bridge fix / evidence reconciliation surfacing).
- Risk level: L1 (single new diagnostic markdown note; no test, code, marker, or task-definition edit).
- Next gate (still pending): `PHASE2H_B_CODEX_FAIL_AUTOFIX_AND_RECONCILIATION_PASSED` (task 140).
- Downstream gate after PASS (still pending): `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` (task 138).

## Legacy evidence consulted (this turn)

Same set as the prior two planner turns — no new legacy evidence consulted because no new milestone is selected:

- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/01_PHASE_2H_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/10_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_RECONCILIATION_ADDENDUM.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/15_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/17_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`

## Legacy failure addressed (this turn)

The legacy automation control plane had no deterministic mechanism to surface a stalled dispatch cycle separately from a stalled task; a stalled dispatch was indistinguishable from a stalled or dead automation operator. The V2 control plane's planner-level human-attention diagnostic surface (this artifact pattern) is the explicit V2 mechanism that exposes a watchdog dispatch stall as a planner-level diagnostic so a human or watchdog operator can act on the dispatch precondition itself rather than on the task it is blocked on. This is the same V2 gain pattern that the prior planner turn declared intent to honor on the third-consecutive-stall trigger.

## V2 proof gate (this turn)

This diagnostic does not advance the existing V2 proof gate (`PHASE2H_B_CODEX_FAIL_AUTOFIX_AND_RECONCILIATION_PASSED`). The proof gate remains pending and is unchanged. The diagnostic itself has no validation criterion beyond:

- This single new file appears as the seventh untracked entry under `git status --short` immediately after the planner turn closes.
- No other file under any of the watched paths is modified.
- No marker is rewritten.
- No task definition is added or modified.
- No V2 source or test is modified.

## Safety boundaries (unchanged)

- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis read or write.
- No live service restart.
- No exchange order placement or cancellation.
- No leverage or margin change.
- No live-trading enablement.
- No deployment.
- No production migration.
- No secret exposure.
- Final live gate remains human-only and blocked.
- The 2H.B authored service sources at `v2/backend/app/services/paper_execution_ledger/` remain byte-stable.
- The 015A placeholders at `v2/backend/app/domain/execution/` remain byte-stable since commit `26e49b7`.
- No 2H.A artifact (00–10) modified by this turn.
- No 2H.B artifact (11–17) modified by this turn.
- No 135-prefixed automation_reliability artifact modified by this turn.
- The six pre-staged untracked artifacts remain byte-stable; none is touched, deleted, replaced, or duplicated by this turn.

## Idempotency declaration

This human-attention diagnostic is the only new file emitted this planner turn. If a fourth consecutive planner turn finds the same untracked set still in place with no Codex watchdog dispatch progress and no human acknowledgement of this diagnostic, the planner will not emit a fifth artifact in the same series; instead, the planner will halt re-entry by emitting only a one-line acknowledgement that the diagnostic remains unaddressed and that further planner turns are wasted work until the dispatch precondition is investigated outside the planner. That one-line acknowledgement, if needed, will be emitted at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/PLANNER_TURN_2HB_CODEX_AUTOFIX_HUMAN_ATTENTION_DIAGNOSTIC_PERSISTED.md`.

PLANNER_TURN_2HB_CODEX_AUTOFIX_HUMAN_ATTENTION_DIAGNOSTIC_READY
