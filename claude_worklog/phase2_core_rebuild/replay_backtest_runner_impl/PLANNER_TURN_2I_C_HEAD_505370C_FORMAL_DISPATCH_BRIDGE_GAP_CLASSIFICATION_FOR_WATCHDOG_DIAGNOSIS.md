# Planner Turn — 2I.C HEAD 505370c Formal Dispatch Bridge Gap Classification for Watchdog Diagnosis

## Purpose

Formally classify the persistent non-dispatch of the existing 2I.C Codex FAIL marker recovery task as a `dispatch_bridge_gap` per REQ_0014, REQ_0015, and REQ_0016, so the codex_watchdog has explicit planner-side authorization to diagnose why the supervisor scheduler is not picking up the already-staged recovery task definition. This turn intentionally does not re-emit any task definition, does not duplicate the prior `PLANNER_TURN_2I_C_CONSOLIDATED_STATE_2026_05_07_NO_NEW_ARTIFACTS_RECOVERY_PENDING.md` content, does not duplicate the prior `PLANNER_TURN_2I_C_POST_PRE_STAGE_2J_RECOVERY_DISPATCH_GAP_SIX_WATCHDOG_CYCLES.md` content, and does not re-enter the `RESTAND_DOWN` iteration-cap loop pattern that the consolidated-state note already formally superseded. It records a single objectively-new evidence dimension: HEAD progression to `505370c` and five additional watchdog auto-commit cycles after the consolidated-state note, with no progress on the recovery dispatch.

## Observed State

- HEAD: `505370c` ("Codex watchdog recover dirty non-live automation artifacts").
- Date: 2026-05-07.
- Working tree dirty path (sole entry): `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. Already enumerated in the recovery task's `worktree_excluded_paths`, therefore this dirty path does NOT block dispatch under the recovery task's documented worktree-isolation contract.
- 2I.C Codex GO/NO-GO marker file `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body still contains the literal token `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_FAIL`.
- 2I.C Codex review file `24_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_REVIEW.md` records the only concrete blocker as the row-60 placeholder hard stop on `git ls-files v2/backend/app/domain/execution/`, where the three observed paths (`__init__.py`, `intent.py`, `paper.py`) are pre-existing 015A scaffold artifacts from commit `26e49b7` and the 2I.C diff against those paths is zero bytes.
- Reconciliation addendum file `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` does not yet exist.
- Recovery task `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json` exists with `status = pending`, `lane = codex_watchdog`, `risk_level = L1`, allowed output prefixes scoped to the 25_ marker rewrite, the 26_ reconciliation addendum, and the two `automation_reliability/` reports. Worktree exclusions cover the dirty planner-prompt path, the recovery task definition file itself, and the durable `PLANNER_TURN_2I_C_DISPATCH_CODEX_FAIL_MARKER_RECONCILIATION.md` note.
- 2H closure markers remain intact: `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS`, `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS`, `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` (the 2H.C precedent body authoritative for the reconciliation pattern).
- 2I closure markers in place for 2I.A and 2I.B: `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`, `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS`.
- 2J pre-staged open inventory remains stable in `PLANNER_TURN_2I_C_PRE_STAGE_2J_PAPER_MODE_MVP_OPEN.md`. No re-emission required from this turn.

## Watchdog Cycle Accounting Since Consolidated-State Note

The consolidated-state note `PLANNER_TURN_2I_C_CONSOLIDATED_STATE_2026_05_07_NO_NEW_ARTIFACTS_RECOVERY_PENDING.md` was authored at HEAD `2c2a578`. Subsequent commit chain observed:

1. `41a6df7` — Codex watchdog recover dirty non-live automation artifacts.
2. `a88ed53` — Codex watchdog recover dirty non-live automation artifacts.
3. `5ab647e` — Codex watchdog recover dirty non-live automation artifacts.
4. `7d5208d` — Codex watchdog recover dirty non-live automation artifacts.
5. `505370c` — Codex watchdog recover dirty non-live automation artifacts (current HEAD).

Five additional watchdog auto-commit cycles have completed without dispatching the existing recovery task. The watchdog is sweeping dirty-tree noise (the planner-prompt edit) but is not invoking the supervisor scheduler entry that would actually run the recovery task and emit the four required output files.

This is the formal definition of a `dispatch_bridge_gap` under REQ_0014 / REQ_0015 / REQ_0016: a non-live blocker where (a) all preconditions for autonomous recovery are met, (b) the recovery artifact already exists in the supervisor task queue, (c) no Claude or Codex child is actively producing output, (d) git is clean modulo documented exclusions, and (e) the supervisor is not picking up the recovery task across multiple watchdog cycles.

## Lane / MVP Relevance

- Lane: `codex_watchdog` (planner records the classification only; watchdog autonomously diagnoses the dispatch path).
- MVP relevance: closing this `dispatch_bridge_gap` unblocks the existing recovery task, which closes `REPLAY_BACKTEST_RUNNER_MVP` (REQ_0017 milestone 5). Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` after the marker flip and the 2J open trigger note: two milestones (`PAPER_MODE_MVP` and `SHADOW_MODE_READINESS`).
- Blocked by:
  - Watchdog autonomous diagnosis of why the supervisor scheduler is not advancing the existing recovery task `codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json` despite five additional cycles since the consolidated-state note.
- Next gate: watchdog dispatch / supervisor execution → `CODEX_FAIL_MARKER_RECOVERY_READY` → `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` marker flip → `PHASE2J_PAPER_MODE_MVP_OPEN_READY` planner-turn note from a future planner turn (only after the marker flip is observed).

## Watchdog Diagnostic Authorization Per REQ_0014 / REQ_0015 / REQ_0016

Under REQ_0014 the watchdog has explicit authority to:
- inspect failed task stdout/stderr
- inspect runtime state
- inspect task definitions
- patch planner/supervisor reliability code
- create recovery task definitions

Under REQ_0015 the watchdog has explicit authority for `dispatch_bridge_gap` recovery whenever:
- `human_attention_required` appears
- planner emits no-progress/halt loop
- git dirty with no active process
- materialization path mismatch occurs
- stale status conflicts with PASS evidence

Under REQ_0016 the watchdog must:
- recover `BEGIN_FILE` outputs
- patch supervisor/planner/dashboard scripts
- restart the master planner only when clean
- continue until final live gate

This planner turn explicitly grants the watchdog the planner-side classification it needs to diagnose the supervisor scheduler dispatch bridge gap autonomously. Allowed watchdog actions for this `dispatch_bridge_gap` include: inspecting why the supervisor scheduler is not picking up the pending recovery task definition, patching `claude_worklog/tools/` supervisor / scheduler / dispatch / watchdog scripts as required to restore the dispatch path, validating, secret-scanning, committing, and re-running the dispatch attempt. The watchdog must not introduce any new task definition for the 2I.C reconciliation itself; the existing recovery task is correct and authoritative.

## Planner Action This Turn

- No new task definition emitted. Existing recovery task is correct and pending.
- No re-emission of the 2J pre-staged inventory.
- No `RESTAND_DOWN` note emitted; the consolidated-state note remains the authoritative supersession of that pattern.
- No `CONSOLIDATED_STATE` re-emission; the prior consolidated-state note remains valid at the new HEAD.
- No `DISPATCH_GAP_ESCALATION` re-emission; this turn upgrades the prior six-cycle dispatch-gap observation to a formal `dispatch_bridge_gap` classification under REQ_0014 / REQ_0015 / REQ_0016 instead of duplicating the cycle-counting pattern.
- No mutation of any GO/NO-GO marker file.
- No mutation of any prior PLANNER_TURN note.
- No mutation of the recovery task definition.
- No mutation of any file under `v2/`.
- No mutation of any 2H or earlier milestone artifact.
- No mutation of any 2I.A, 2I.B, or 2I.C planning, implementation, review, or reconciliation artifact other than this single classification note authored under the `replay_backtest_runner_impl/` subdomain at a unique filename.
- No mutation of the master planner prompt.
- No mutation of supervisor, scheduler, watchdog, or dashboard tooling — only the formal classification grant authorizing the watchdog to do that under REQ_0014 / REQ_0015 / REQ_0016.

## Legacy Evidence Consulted, Behavior Preserved, Failure Addressed

- Legacy evidence consulted:
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/24_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_REVIEW.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_CONSOLIDATED_STATE_2026_05_07_NO_NEW_ARTIFACTS_RECOVERY_PENDING.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_POST_PRE_STAGE_2J_RECOVERY_DISPATCH_GAP_SIX_WATCHDOG_CYCLES.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_PRE_STAGE_2J_PAPER_MODE_MVP_OPEN.md`
  - `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
  - `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`
  - `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json`
  - REQ_0014, REQ_0015, REQ_0016, REQ_0017, REQ_0018, REQ_0021 requirement bodies
- Legacy behavior preserved: read-only adjudication only. No mutation of `v2/`. No mutation of any 2H or earlier artifact. No mutation of any 2I.A, 2I.B, or 2I.C planning, implementation, review, or reconciliation file. No mutation of any GO/NO-GO marker file. No mutation of the recovery task definition. No mutation of supervisor, scheduler, watchdog, or dashboard tooling from this planner turn itself.
- Legacy failure addressed: prior automation patterns where a stale FAIL marker from a placeholder rubric premise required manual human dispatch intervention. The 2H.A, 2H.B, and 2H.C reconciliation addendums established the pattern for automated marker reconciliation; this 2I.C case must follow that pattern. The current additional failure surfaced this turn is the supervisor scheduler not advancing the already-staged recovery task across five additional watchdog cycles after the consolidated-state note. Formally classifying this as a `dispatch_bridge_gap` is the planner's only permitted action; the watchdog autonomously executes the diagnosis and fix per REQ_0014 / REQ_0015 / REQ_0016.
- V2 proof gate: the four recovery-task output files plus the post-flip 2J open trigger note emission together close `REPLAY_BACKTEST_RUNNER_MVP` and open `PAPER_MODE_MVP`. No additional planner artifact is required to reach that gate.

## Safety

- Live trading remains BLOCKED.
- Final live approval remains human-only.
- No modification of `/home/wali/Desktop/AI BOT`.
- No Redis access at any layer.
- No Redis command at any time.
- No live service restart.
- No exchange action.
- No order placement or cancellation.
- No leverage or margin change.
- No position-mode change.
- No live-trading enablement.
- No deployment.
- No production migration.
- No secret exposure.
- No credential commit.
- No modification of any file under `v2/`.
- No modification of any GO/NO-GO marker file.
- No modification of any prior PLANNER_TURN note.
- No modification of the master planner prompt.
- No modification of the recovery task definition.
- No new task definition emitted.
- No new lineage ID introduced.
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler, or background loop introduced in any artifact.

## Stop Conditions

The planner stops and surfaces to human attention only if any of the following appears before the 25_ marker flip:

- Any modification of `/home/wali/Desktop/AI BOT`.
- Any Redis access or command.
- Any live service restart, exchange action, leverage or margin change, deployment, production migration, or live-trade enablement.
- Any secret exposure or credential commit.
- Any modification of any V2 source or test file.
- Any modification of any 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, or 2I.C artifact other than the recovery-task-scoped 25_ marker rewrite, the new 26_ reconciliation addendum, and the two `automation_reliability/` report files emitted by the recovery task.
- A `CODEX_FAIL_MARKER_RECOVERY_BLOCKED` result from the recovery task with a specific failed verification check.
- A watchdog diagnostic conclusion that the dispatch bridge gap requires an L4/L5 action or an ambiguous trading/business decision.

PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_DISPATCH_BRIDGE_GAP_FORMAL_CLASSIFICATION_NOTE_READY
