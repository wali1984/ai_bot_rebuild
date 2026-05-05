# PLANNER TURN 2F.B — DIRTY PLANNER PROMPT DISPATCH HOLD RECOVERY

## Active requirement
REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md, with REQ_0017 / REQ_0018 / REQ_0020 paper-backtest MVP lane lock and REQ_0014 / REQ_0015 / REQ_0016 / REQ_0007 Codex non-live human-replacement watchdog authority.

## Active MVP target
V2_BACKTEST_AND_PAPER_MVP_READY (6 milestones distance).

## Active MVP milestone
ORCHESTRATOR_DECISION_MVP (Phase 2F).

## Sub-phase state
- Phase 2F.A orchestrator decision domain: PASSED. Implementation, Codex review, and Codex GO/NO-GO markers are committed under claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/06..09.
- Phase 2F.B orchestrator decision assembler service: implementation files are committed in the git index under v2/backend/app/services/orchestrator_decision/ and v2/backend/tests/unit/services/orchestrator_decision/, but the local GO/NO-GO marker (15_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO.md) still records the sandbox-era FAILED text and the codex_recover_119 GO/NO-GO records BLOCKED.
- Phase 2F.C orchestrator decision composition root: not opened. Will open after 2F.B Codex review PASS.

## Pending tasks
- 120_orchestrator_decision_2fb_assembler_service_codex_review.json (pending; gated by 121 PASS)
- 121_orchestrator_decision_2fb_evidence_reconciliation.json (pending; gated by clean worktree)
- codex_recover_119_orchestrator_decision_2fb_assembler_service_implementation.json (pending; will be reconciled by 121)

## Dispatch hold root cause
121_orchestrator_decision_2fb_evidence_reconciliation declares requires_clean_worktree = true and explicitly names "harness-managed dirty claude_master_rebuild_planner_prompt.txt cleanup by Codex watchdog under REQ_0014 / REQ_0016 / REQ_0007" as its only blocker.

`git status --porcelain` reports exactly one dirty path: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. The diff is a 1610-line addition with zero removals. The added content is durable planner instructions only (Claude Code Max 20x consolidated profile, Codex Pro parallel lane policy, REQ_0018 / REQ_0020 planner lane lock policy). No live behavior. No Redis writes. No legacy mutation. No exchange action. No leverage / margin change. No deployment. No production migration. No secrets.

## Decision
Open consolidated Codex watchdog recovery task 122_codex_watchdog_dirty_planner_prompt_recovery to:
1. Re-validate the dirty file is exactly the planner prompt and that the diff is insertion-only.
2. Run forbidden-token, live-behavior-token, and high-confidence secret sweeps over the dirty diff.
3. On all-clear, commit the dirty file with subject `Codex watchdog recover dirty non-live automation artifacts` (the established durable subject) and emit the 122 recovery REPORT and GO/NO-GO markers.
4. On any failure, emit `CODEX_NON_LIVE_RECOVERY_BLOCKED` and surface to human attention without autofix.

This is a Lane C codex_watchdog task. It is the smallest concrete advance toward V2_BACKTEST_AND_PAPER_MVP_READY available right now because every other 2F.B path is gated on a clean worktree or on 121's reconciliation marker.

## Lane lock compliance (REQ_0018 / REQ_0020)
- lane: codex_watchdog
- mvp_relevance: clears the only blocker on 121, which clears the only blocker on 120, which closes Phase 2F.B, which is the second milestone in REQ_0017's required MVP sequence (ORCHESTRATOR_DECISION_MVP).
- blocked_by: none
- next_gate: CODEX_NON_LIVE_RECOVERY_READY
- legacy_evidence_consulted: git status, git diff, git log of prior watchdog dirty-non-live-automation-artifact recovery commits, 121 task definition's blocked_by entry.
- legacy_failure_addressed: dispatch holds caused by uncommitted durable planner instructions on the legacy bot.

## Safety boundaries
- Hard stops: no /home/wali/Desktop/AI BOT mutation, no Redis access, no live service restart, no exchange action, no leverage / margin change, no live trading, no deployment, no production migration, no secret exposure.
- The recovery task does NOT modify the planner prompt content beyond what the harness already wrote; it only commits the existing dirty bytes.
- The recovery task does NOT modify any V2 source or test file.
- The recovery task does NOT modify any 2F.A or 2F.B authored source / test / marker file.
- The recovery task does NOT modify any task definition under claude_worklog/agent_supervisor/tasks/.

## Next dispatch chain
1. 122_codex_watchdog_dirty_planner_prompt_recovery (this turn) → CODEX_NON_LIVE_RECOVERY_READY.
2. 121_orchestrator_decision_2fb_evidence_reconciliation → PHASE2F_B_EVIDENCE_RECONCILIATION_PASSED.
3. 120_orchestrator_decision_2fb_assembler_service_codex_review → PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS.
4. Open consolidated 2F.C orchestrator decision composition root milestone task.
5. Open consolidated 2F.D orchestrator decision integration / parity proof milestone task if not already covered by 2F.C composition root scope.
6. Close ORCHESTRATOR_DECISION_MVP and open RISK_GATEWAY_DEFAULT_DENY_MVP (Phase 2G).

## Output policy
This planner turn emits exactly two BEGIN_FILE / END_FILE blocks: the 122 task definition and this turn document. No other artifacts. No standalone harness framing tokens in any authored body.

PLANNER_TURN_2F_B_DIRTY_PLANNER_PROMPT_DISPATCH_HOLD_RECOVERY_READY
