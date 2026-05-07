# Planner Turn — 2I.C HEAD 351d806 New Dispatch Bridge Repair Task Authorization

## Purpose

Record a single objectively-new evidence dimension at HEAD `351d806` (two further watchdog auto-commit cycles past `505370c` with the existing 2I.C recovery task still un-dispatched) and emit one new Lane C `codex_watchdog` task definition scoped specifically to the supervisor scheduler dispatch-bridge repair under `claude_worklog/tools/`, distinct from and non-overlapping with the existing 2I.C marker reconciliation task. This turn does not re-emit the consolidated-state note, does not re-emit the dispatch-bridge-gap formal classification note, does not RESTAND_DOWN, does not mutate the existing recovery task definition, does not mutate any GO/NO-GO marker file, does not mutate any prior planner-turn note, and does not mutate the master planner prompt.

## New Evidence Dimension at HEAD 351d806

Commit chain since the consolidated-state note `PLANNER_TURN_2I_C_CONSOLIDATED_STATE_2026_05_07_NO_NEW_ARTIFACTS_RECOVERY_PENDING.md` (authored at HEAD `2c2a578`):

1. `41a6df7` — Codex watchdog recover dirty non-live automation artifacts.
2. `a88ed53` — Codex watchdog recover dirty non-live automation artifacts.
3. `5ab647e` — Codex watchdog recover dirty non-live automation artifacts.
4. `7d5208d` — Codex watchdog recover dirty non-live automation artifacts.
5. `505370c` — Codex watchdog recover dirty non-live automation artifacts.
6. `e503a52` — Codex watchdog recover dirty non-live automation artifacts.
7. `351d806` — Codex watchdog recover dirty non-live automation artifacts (current HEAD).

Seven watchdog auto-commit cycles have completed without dispatching the existing recovery task `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json`. The watchdog continues to sweep the single dirty path `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (already enumerated in the recovery task's `worktree_excluded_paths`) but has not invoked the supervisor scheduler entry that would actually run the recovery task and emit its four required output files.

The dispatch bridge gap is persistent. The cause is in the supervisor scheduler / dispatch path itself, not in the recovery task definition or in the GO/NO-GO marker file.

## Planner-Level Authorization for Lane C Dispatch Bridge Repair

Under REQ_0014 the watchdog has explicit authority to:
- inspect failed task stdout/stderr
- inspect runtime state
- inspect task definitions
- patch planner/supervisor reliability code
- patch supervisor/planner/dashboard scripts

Under REQ_0015 the watchdog has explicit `dispatch_bridge_gap` authority.

Under REQ_0016 the watchdog must patch supervisor/planner/dashboard scripts and continue until the final live gate.

Under REQ_0021 the watchdog parallel capacity scheduler authorizes Codex autofix in the `codex_watchdog` lane to fix dispatch bridge gaps when git is dirty only on documented exclusions and no Claude child is producing output.

The prior `PLANNER_TURN_2I_C_HEAD_505370C_FORMAL_DISPATCH_BRIDGE_GAP_CLASSIFICATION_FOR_WATCHDOG_DIAGNOSIS.md` note already recorded the planner-side classification. Two further watchdog cycles after that note still have not produced a scheduler-tooling diff. This planner turn therefore emits one new task definition that specifically targets `claude_worklog/tools/` supervisor / scheduler / dispatch / watchdog scripts so the watchdog has an explicitly-staged, scheduler-pickable Lane C recovery entry whose sole purpose is to restore the dispatch path. This new task is non-overlapping with the existing 2I.C marker reconciliation task: it does NOT touch the 25_ marker, does NOT emit a 26_ reconciliation addendum, does NOT mutate any V2 file, and does NOT mutate any phase2_core_rebuild milestone artifact.

## New Task Emitted This Turn

`claude_worklog/agent_supervisor/tasks/codex_watchdog_supervisor_scheduler_dispatch_bridge_repair_for_2ic_recovery.json`

- Agent: codex
- Risk level: L1
- Lane: codex_watchdog
- Status: pending
- MVP relevance: restoring the supervisor scheduler dispatch path unblocks the existing 2I.C recovery task, which closes REPLAY_BACKTEST_RUNNER_MVP (REQ_0017 milestone 5). After the marker flip, the next paper/backtest milestone PAPER_MODE_MVP can be opened. Distance to V2_BACKTEST_AND_PAPER_MVP_READY drops from 3 milestones to 2 milestones once this dispatch repair lands and the 2I.C marker reconciliation task is then dispatched.
- Allowed output prefixes: scoped to `claude_worklog/tools/`, `claude_worklog/phase2_core_rebuild/automation_reliability/`, and `claude_worklog/agent_supervisor_reliability/`.
- Forbidden output paths: `v2/`, every `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/` file, every `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` file, every prior phase2 milestone implementation file, the existing 2I.C recovery task definition, the master planner prompt, every other supervisor task definition, and `/home/wali/Desktop/AI BOT/`.
- Required output files: a scheduler dispatch bridge diagnosis report, the patched supervisor/scheduler/dispatch script(s) under `claude_worklog/tools/`, a re-dispatch-attempt log report, and a GO/NO-GO file under `claude_worklog/phase2_core_rebuild/automation_reliability/` with one of two literal markers.
- Worktree excluded paths: the dirty planner-prompt path, this new task definition file itself, the existing 2I.C recovery task definition file, this planner-turn note, and the prior dispatch-bridge-gap formal classification note.

## Lane / MVP Relevance for This Planner Turn

- Lane: `codex_watchdog`.
- MVP relevance: this planner-turn note authorizes one new scheduler dispatch-bridge repair task that, once executed by the watchdog, restores the dispatch path so the existing 2I.C marker reconciliation task can run and flip the 25_ marker, closing REPLAY_BACKTEST_RUNNER_MVP and enabling 2J PAPER_MODE_MVP to open.
- Blocked by: supervisor scheduler / dispatch path failing to pick up the existing 2I.C recovery task across seven consecutive watchdog auto-commit cycles.
- Next gate: dispatch bridge repair → existing 2I.C recovery task dispatched → `CODEX_FAIL_MARKER_RECOVERY_READY` → 25_ marker flipped to `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` → `PHASE2J_PAPER_MODE_MVP_OPEN_READY` planner-turn note from a future planner turn.

## Legacy Evidence Consulted, Behavior Preserved, Failure Addressed

- Legacy evidence consulted:
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/24_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_REVIEW.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_HEAD_505370C_FORMAL_DISPATCH_BRIDGE_GAP_CLASSIFICATION_FOR_WATCHDOG_DIAGNOSIS.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_CONSOLIDATED_STATE_2026_05_07_NO_NEW_ARTIFACTS_RECOVERY_PENDING.md`
  - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_PRE_STAGE_2J_PAPER_MODE_MVP_OPEN.md`
  - `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
  - `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`
  - `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json`
  - REQ_0007, REQ_0011, REQ_0014, REQ_0015, REQ_0016, REQ_0017, REQ_0018, REQ_0021 requirement bodies
- Legacy behavior preserved: read-only adjudication of the planner state. No mutation of `v2/`. No mutation of any GO/NO-GO marker file. No mutation of any prior planner-turn note. No mutation of the existing 2I.C recovery task definition. No mutation of the master planner prompt. No mutation of any 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, or 2I.C planning, implementation, review, or reconciliation file. The only artifacts authored by this planner turn are this planner-turn note and the one new dispatch-bridge-repair task definition file.
- Legacy failure addressed: prior automation patterns where a stale FAIL marker plus a non-dispatching supervisor scheduler required manual human dispatch intervention. The 2H.A, 2H.B, and 2H.C reconciliation addendums established the pattern for automated marker reconciliation; the supervisor scheduler dispatch bridge repair task authored this turn establishes the pattern for automated dispatch bridge repair when the existing recovery task is already correctly staged but not being picked up.
- V2 proof gate: dispatch bridge repair lands → existing 2I.C recovery task dispatched → 25_ marker flipped to PASS → REPLAY_BACKTEST_RUNNER_MVP closed → 2J PAPER_MODE_MVP open trigger note emitted by a future planner turn.

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
- No modification of the existing 2I.C recovery task definition.
- No modification of any 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, or 2I.C planning, implementation, review, or reconciliation file.
- No FastAPI surface, adapter expansion, ledger persistence, PnL or sizing, GPU or checkpoint subsystem, replay engine, scheduler runtime, or background loop introduced in any artifact.
- No new lineage ID introduced.

## Stop Conditions

The planner stops and surfaces to human attention only if any of the following appears before the dispatch bridge repair lands:

- Any modification of `/home/wali/Desktop/AI BOT`.
- Any Redis access or command.
- Any live service restart, exchange action, leverage or margin change, deployment, production migration, or live-trade enablement.
- Any secret exposure or credential commit.
- Any modification of any V2 source or test file.
- Any modification of any 2H.A, 2H.B, 2H.C, 2I.A, 2I.B, or 2I.C artifact other than the recovery-task-scoped 25_ marker rewrite, the new 26_ reconciliation addendum, and the two `automation_reliability/` report files emitted by the existing 2I.C recovery task.
- A diagnostic conclusion from the new dispatch-bridge-repair task that the dispatch bridge gap requires an L4/L5 action or an ambiguous trading/business decision.
- A repeated watchdog auto-commit pattern after the dispatch-bridge-repair task is itself not dispatched, in which case the planner will surface to human attention rather than emitting further dispatch-bridge-repair-of-the-dispatch-bridge-repair recursion.

PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_DISPATCH_BRIDGE_REPAIR_TASK_AUTHORIZATION_NOTE_READY
