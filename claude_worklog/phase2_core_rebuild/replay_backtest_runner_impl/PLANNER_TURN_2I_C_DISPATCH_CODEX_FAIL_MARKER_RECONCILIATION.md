# Planner Turn 2I.C Dispatch Codex Fail Marker Reconciliation

Planner date: 2026-05-07.

## Decision

Dispatch a single consolidated Codex Lane C watchdog recovery task to reconcile
the 2I.C Replay/Backtest Runner Composition Root Codex GO/NO-GO marker from
`PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_FAIL` to
`PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` and emit a new
`26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`
that documents the placeholder cross-isolation conflict adjudication.

The dispatched task is
`claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json`.

## Evidence-First Reconciliation

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/23_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO.md`
  body is `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.
  The 2I.C implementation and local validation passed.

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/24_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_REVIEW.md`
  marked every authored 2I.C source-level rubric row PASS up to the placeholder
  hard stop and recorded the only concrete blocker as the row-60 expectation that
  `git ls-files v2/backend/app/domain/execution/` would return zero output lines.

- The three tracked paths under `v2/backend/app/domain/execution/`
  (`__init__.py`, `intent.py`, `paper.py`) are pre-existing 015A scaffold
  placeholders introduced by commit `26e49b7 Materialize 015A V2 repo package
  skeleton`. They contain no executable behavior, no Redis access, no live
  behavior, no FastAPI surface, no adapter binding, no ledger persistence, and no
  PnL or sizing computation.

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/20_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md`
  cross-isolation list explicitly forbids any byte change under
  `v2/backend/app/domain/`, so 2I.C cannot remove the placeholders.

- The identical placeholder cross-isolation conflict was already reconciled by
  the watchdog for 2H.A, 2H.B, and 2H.C via reconciliation addendums and
  reconciled GO/NO-GO marker rewrites. The 2H.C precedent at
  `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
  is the closest direct precedent: same placeholder set, same hard-stop rubric
  row, same reconciliation pattern.

## Lane / MVP Relevance

- Lane: `codex_watchdog`.
- MVP relevance: closes `REPLAY_BACKTEST_RUNNER_MVP` (REQ_0017 milestone 5).
  Once the 25_ marker flips to PASS, the planner can open `PAPER_MODE_MVP`
  (milestone 6). Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` drops from 3
  milestones to 2.
- Blocked by:
  `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
  still containing the FAIL marker AND the absence of
  `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`.
- Next gate: `CODEX_FAIL_MARKER_RECOVERY_READY` followed by the planner emitting
  a 2J PLANNER_TURN note opening `PAPER_MODE_MVP`.

## Legacy Evidence Consulted, Behavior Preserved, Failure Addressed, V2 Proof Gate

- Legacy evidence consulted: the 2H.A, 2H.B, and 2H.C reconciliation addendums
  and reconciled markers; the 015A scaffold materialization commit `26e49b7`;
  the 24_ Codex review of 2I.C; the 23_ implementation GO/NO-GO marker; and the
  authored 2I.C composition root source files
  (`v2/backend/app/composition/replay_backtest_runner/__init__.py`,
  `errors.py`, `runtime.py`).
- Legacy behavior preserved: read-only adjudication of pre-existing 015A
  scaffold placeholders; no mutation of `v2/backend/app/domain/execution/`; no
  mutation of any 2I.A, 2I.B, or 2I.C planning, implementation, review, or
  reconciliation file other than the single 25_ marker rewrite and the new 26_
  reconciliation addendum; no mutation of any 2H or earlier milestone artifact.
- Legacy failure addressed: the legacy automation loop required manual human
  intervention to reconcile a CODEX FAIL marker when the only observed failure
  was a pre-existing 015A scaffold placeholder cross-isolation conflict that
  the milestone itself forbids mutating. The 2H precedents established the
  watchdog reconciliation pattern, and this task applies the same pattern to
  2I.C so the planner can advance without human intervention.
- V2 proof gate: the new 26_ reconciliation addendum cites the 015A commit, the
  zero-byte 2I.C diff against `v2/backend/app/domain/execution/`, the
  per-row PASS evidence already recorded in 24_ before the placeholder hard
  stop, and the validation re-run from 22_ and 23_. The reconciled 25_ marker
  body is the literal one-line `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.

## Worktree Isolation

The dispatched task records three worktree-excluded paths:
- `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (planner prompt edit)
- `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go.json` (the task definition itself)
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_C_DISPATCH_CODEX_FAIL_MARKER_RECONCILIATION.md` (this note)

The supervisor's REQ_0016 / REQ_0021 auto-commit batch will sweep all three
alongside the 25_ marker rewrite, the new 26_ reconciliation addendum, and the
two automation_reliability report files in a single durable commit, matching the
2H.C dispatch worktree contract.

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
- No modification of any other GO/NO-GO marker file or any other prior-milestone artifact.

## Stop Conditions

If Codex returns `CODEX_FAIL_MARKER_RECOVERY_BLOCKED`, the planner stops and
surfaces the specific failed verification check to human attention without
auto-retry.
