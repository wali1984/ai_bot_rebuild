# Planner Turn — Phase 2G.B Parallel Readonly Review Misclassification Reconciled

Turn date: 2026-05-05
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0011_PARALLEL_CODEX_REVIEW_AND_AUTOFIX_LANE.md ∩ REQ_0016_CODEX_NON_LIVE_HUMAN_REPLACEMENT_WATCHDOG.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md ∩ REQ_0021_PARALLEL_CAPACITY_SCHEDULER_FOR_CLAUDE_CODEX.md
Active MVP target: V2_BACKTEST_AND_PAPER_MVP_READY
Active MVP milestone: RISK_GATEWAY_DEFAULT_DENY_MVP (REQ_0017 milestone 3)
Active sub-phase: Phase 2G.B (risk gateway assembler service)
Lane: codex_watchdog (Lane C)
Profile: Claude Code Max20 consolidated_default; Codex Pro parallel lane active.

## Decision

No new build task is authored. No new dispatch task is authored. No re-emission of tasks 128 / 129 / codex_recover_128. No edit to any `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` file 00..17. No edit to any V2 source or test file. No edit to the master planner prompt. No edit to the in-flight `parallel_capacity_readonly_review_codex_parallel_readonly_review_ready_REPORT.md` or its `_GO_NO_GO.md` — both stand as Codex's read-only output and are not the planner's to mutate.

This turn records that the parallel-capacity readonly review (`parallel_capacity_readonly_review_codex_parallel_readonly_review_ready`, Lane C) emitted `CODEX_PARALLEL_READONLY_REVIEW_BLOCKED` against a misclassified scope, and explains why that BLOCKED marker is not a defect against the committed Phase 2G.A milestone, and therefore must not block the 128 → 129 dispatch chain that already covers Phase 2G.B.

## Worktree posture at turn open

`git status --porcelain`:

```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
?? claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json
?? claude_worklog/autonomous_control_plane/PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW.md
?? claude_worklog/phase2_core_rebuild/risk_gateway_impl/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready_GO_NO_GO.md
?? claude_worklog/phase2_core_rebuild/risk_gateway_impl/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready_REPORT.md
```

Classification:

- The modified planner-prompt is durable instructions only (Claude Code Max20 consolidated profile, Codex Pro parallel lane policy, REQ_0006 / REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0021 guidance text). No live behavior. The supervisor's worktree-isolation contract excludes this path from dispatch worktrees.
- The previous planner observation `PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW.md` is durable planner-self output and is safe to commit by the supervisor watchdog.
- The Lane C readonly review task JSON `parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json` is durable supervisor task definition under `claude_worklog/agent_supervisor/tasks/` and is safe to commit by the supervisor watchdog.
- The Lane C readonly review report `..._REPORT.md` and its single-line GO/NO-GO `..._GO_NO_GO.md` are Codex's authored read-only review output. They are durable evidence and are safe to commit by the supervisor watchdog. Their content is not edited by this planner turn.

None of the dirty paths land in any of task 128's `forbidden_output_paths` or task 129's `allowed_output_prefixes` write surface. None lands under `v2/`. None lands inside the planner-emitted 00..13 docs at `risk_gateway_impl/`. None lands in any prior-milestone artifact.

## Misclassification analysis of the parallel readonly review BLOCKED finding

The Lane C task `parallel_capacity_readonly_review_codex_parallel_readonly_review_ready` was scoped, by both its `mvp_relevance` and its `prompt`, to a parallel **read-only review of the latest committed milestone** with the explicit pointer:

> "review of committed milestone CODEX_PARALLEL_READONLY_REVIEW_READY from claude_worklog/phase2_core_rebuild/risk_gateway_impl/parallel_capacity_readonly_review_phase2g_a_risk_gateway_domain_codex_pass_GO_NO_GO.md"

That input pointer is the Phase 2G.A pass. The scope is the **committed** 2G.A milestone — value-object surface in `v2/backend/app/domain/risk_gateway/`, the 2G.A domain test suite, and the planner-emitted 00..09 docs that describe and gate it. It is not the in-flight 2G.B implementation; 2G.B has not dispatched yet (task 128 is still `pending`).

The `..._REPORT.md` actually written by Codex enumerates seven blockers:

1. "The 2G-B assembler service implementation is absent."
2. "The legacy placeholder risk-gateway service module is still present."
3. "The 2G-B implementation report and implementation GO/NO-GO artifact are absent."
4. "Risk-gateway handoff is incomplete." (no service-layer assembler)
5. "Paper/backtest MVP compatibility is not established." (no service handoff surface)
6. "Lineage and explainability handoff is incomplete." (no service-layer propagation)
7. "Test hardening required by the milestone is missing." (no service tests)

All seven items are predicted-state observations against Phase 2G.B, not defects against committed Phase 2G.A. Task 128's `required_output_files` is the exact authority that creates each of those artifacts:

- `v2/backend/app/services/risk_gateway/{__init__.py, errors.py, service.py}` (closes blockers 1, 4, 5, 6).
- Placeholder deletion of `v2/backend/app/services/risk_gateway.py` is enumerated under `allowed_deletion_paths` and required as the first filesystem mutation of task 128 (closes blocker 2).
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` and `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md` (closes blocker 3).
- The 29 service test files plus the zero-byte `__init__.py` under `v2/backend/tests/unit/services/risk_gateway/` (closes blocker 7).

In other words, every blocker raised by the readonly review is the exact contract that task 128 will satisfy. Treating the BLOCKED marker as a stop signal for the 128 dispatch chain would deadlock the lane: the only way to clear the BLOCKED finding is to dispatch 128 itself.

## Reclassification

For dashboard/queue/current-status reconciliation only:

- `parallel_capacity_readonly_review_codex_parallel_readonly_review_ready` GO/NO-GO line `CODEX_PARALLEL_READONLY_REVIEW_BLOCKED`: classified as `superseded_by_evidence_pre_2g_b_dispatch`. Reason: the review's blockers are the exact deliverables of pending task `128_risk_gateway_2gb_assembler_service_implementation`. The Phase 2G.A milestone, which was the actual scope target for the parallel readonly review, has its own independent PASS marker `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS` recorded at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md` and is not affected by this Lane C BLOCKED line.
- Dispatch impact: zero. Task 128 remains the next dispatch under Lane A. Task 129 remains gated on `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at file 15. Task `codex_recover_128_risk_gateway_2gb_assembler_service_implementation` remains pending only as a stall-recovery wrapper.
- Codex parallel-capacity utilization (REQ_0021): the next safe Lane C work, if Codex capacity remains free while 128 is mid-build, is read-only review of already-committed 2G.A artifacts (files 02..09 of `risk_gateway_impl/`) and the upstream 2F.C composition root pass marker — without authoring under any 2G.B forbidden output prefix. No race with task 128.

## Watchdog reconciliation actions for the supervisor (no planner-self mutation)

The planner does not commit, push, or run the supervisor itself. The supervisor's Codex watchdog cycle (REQ_0016 / REQ_0021) is the right venue to:

1. Stage and commit the four durable additions plus the durable planner-prompt edit:
   - `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (modified).
   - `claude_worklog/autonomous_control_plane/PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW.md` (new).
   - `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json` (new).
   - `claude_worklog/phase2_core_rebuild/risk_gateway_impl/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready_REPORT.md` (new).
   - `claude_worklog/phase2_core_rebuild/risk_gateway_impl/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready_GO_NO_GO.md` (new).
   - Plus this planner turn document (`PLANNER_TURN_2G_B_READONLY_REVIEW_MISCLASSIFICATION_RECONCILED.md`).
2. Run a high-confidence secret scan against the staged set. None of the listed paths under `claude_worklog/` should contain credentials. Only authored content is durable observation prose, planner-policy text, supervisor task JSON, and Codex's read-only review output. No `.env`, no key file, no token, no URL with embedded secret.
3. Push the commit to keep the dispatch worktree synchronization clean.
4. Pre-dispatch tick: pick up `128_risk_gateway_2gb_assembler_service_implementation` for Lane A. The dispatch worktree excludes the planner-prompt path; once the four other dirty paths are committed, the dispatch worktree is clean and 128 may dispatch.
5. On `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` written to file 15 by task 128, supervisor pre-dispatch tick picks up `129_risk_gateway_2gb_assembler_service_codex_review` for the matching Codex review.
6. On `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` written to file 17 by task 129, the next planner turn opens consolidated Phase 2G.C composition root work as one task.

This sequence honors REQ_0011 (Codex must not run a milestone's required review before that milestone's local validation marker passes), REQ_0021 (Codex parallel-capacity utilization without racing the active builder), and REQ_0016 (Codex watchdog reconciles dirty trees, planner-loop noise, and stale or misclassified status against PASS evidence).

## Lane lock checklist (REQ_0018 / REQ_0020)

| Field | Value |
|---|---|
| `lane` | `codex_watchdog` |
| `mvp_relevance` | Reconciles a Lane C BLOCKED marker that, if mishandled, would deadlock the Lane A 128 → 129 chain that closes Phase 2G.B and advances RISK_GATEWAY_DEFAULT_DENY_MVP toward V2_BACKTEST_AND_PAPER_MVP_READY. |
| `blocked_by` | dispatch tick on `128_risk_gateway_2gb_assembler_service_implementation` (queued, on a clean dispatch worktree). |
| `next_gate` | `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`. |
| `legacy_evidence_consulted` | `git status --porcelain`; `01_PHASE_2G_LEGACY_EVIDENCE_REVIEW.md`; `09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`; `10_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SPEC.md`; `11_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_TEST_PLAN.md`; `12_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`; `13_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`; pending task definitions `128_risk_gateway_2gb_assembler_service_implementation.json`, `129_risk_gateway_2gb_assembler_service_codex_review.json`, `codex_recover_128_risk_gateway_2gb_assembler_service_implementation.json`, `parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json`; the Codex readonly review's `..._REPORT.md` body; the prior planner turn note `PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW.md`; `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` (read-only stub); `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`. |
| `legacy_failure_addressed` | Planner-loop misreaction to a misclassified parallel review marker. Under the legacy bot, ambiguous external review signals would either be ignored (causing real defects to go uncaptured) or treated as hard stops (causing dispatch deadlocks). This turn explicitly catalogues the seven blockers as predicted Phase 2G.B deliverables already covered by task 128, preserves the BLOCKED marker as durable evidence, and does not perturb the queued 128 → 129 chain. |

## What this turn deliberately does NOT do

- Does NOT modify the dirty planner-prompt content. The prompt edit is durable instructions only and the supervisor excludes the prompt path from dispatch worktrees.
- Does NOT modify the prior planner turn note `PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW.md`. It stands as the prior turn's record.
- Does NOT modify the readonly review task JSON `parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json`. It stands as the supervisor's authoritative dispatched-task definition.
- Does NOT modify the readonly review's `..._REPORT.md` or `..._GO_NO_GO.md`. They stand as Codex's read-only review output. The planner is not the right venue to overwrite Codex's review record. Reclassification happens in this planner observation document only.
- Does NOT re-emit task `128_risk_gateway_2gb_assembler_service_implementation` — already pending on disk.
- Does NOT re-emit task `129_risk_gateway_2gb_assembler_service_codex_review` — already pending on disk.
- Does NOT re-emit `codex_recover_128_risk_gateway_2gb_assembler_service_implementation` — already pending on disk.
- Does NOT author any V2 source under `v2/backend/app/services/risk_gateway/`.
- Does NOT author any V2 test under `v2/backend/tests/unit/services/risk_gateway/`.
- Does NOT author files 14, 15, 16, or 17 under `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` — those are owned by tasks 128 (14, 15) and 129 (16, 17).
- Does NOT delete the placeholder `v2/backend/app/services/risk_gateway.py` — that is owned by task 128 via `allowed_deletion_paths`.
- Does NOT open Phase 2G.C composition-root work — that gate opens only after `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`.
- Does NOT open a Lane B explainability_ui task — Phase 2G.B does not yet emit a real `risk_decision_id` lineage contract for the explainability UI to bind to. Any Lane B task today would violate the "real data contracts only" rule.
- Does NOT open a Lane D legacy_parity task — none of the in-flight legacy_parity work is unblocked or perturbed by this turn.
- Does NOT open a new Lane C readonly review task targeting 2G.A. The next safe Lane C window is read-only review of already-committed artifacts (e.g. 2G.A 02..09 or the upstream 2F.C composition-root pass), and only when no Claude child is actively writing into `risk_gateway_impl/` and no race exists with task 128.
- Does NOT touch `/home/wali/Desktop/AI BOT`.
- Does NOT touch Redis, exchange, leverage, margin, deploy, secrets, or live trading.

## Dispatch chain (unchanged)

1. Supervisor watchdog: stage and commit the five durable additions plus the durable planner-prompt edit listed under "Watchdog reconciliation actions". Run high-confidence secret scan; no expected hits. Push.
2. Supervisor pre-dispatch tick: pick up `128_risk_gateway_2gb_assembler_service_implementation` for Lane A. Dispatch worktree is clean once step 1 commits.
3. Task 128 emits `v2/backend/app/services/risk_gateway/{__init__.py, errors.py, service.py}`, the 29 sibling test files plus zero-byte `__init__.py` under `v2/backend/tests/unit/services/risk_gateway/`, deletes the placeholder `v2/backend/app/services/risk_gateway.py`, and writes `14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` and `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md` carrying `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
4. Supervisor pre-dispatch tick: pick up `129_risk_gateway_2gb_assembler_service_codex_review` once the predecessor marker at file 15 is observed and the worktree is clean. Codex emits files 16 and 17. On `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` the next planner turn opens consolidated Phase 2G.C composition root work.
5. On 128 or 129 FAIL with concrete code/test blockers and no safety violation, dispatch the matching REQ_0007 / REQ_0014 autofix task (already on disk for 128 as `codex_recover_128_*`) scoped only to the three authored 2G.B source files plus the 29 new test files, and re-run the implementation flow. On any safety violation, surface to human attention; no autofix permitted.
6. Close `RISK_GATEWAY_DEFAULT_DENY_MVP` on completion of 2G.C and open `PAPER_EXECUTION_LEDGER_MVP` (Phase 2H) as the next MVP milestone under a fresh consolidated milestone turn.

Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 5 milestones remaining once 2G.B closes (2G.C composition root → PAPER_EXECUTION_LEDGER_MVP → REPLAY_BACKTEST_RUNNER_MVP → PAPER_MODE_MVP → SHADOW_MODE_READINESS).

## Codex parallel-lane utilization (REQ_0021)

- Claude lane: idle for builder work this turn; planner-self only emits this observation document.
- Codex review lane: parallel readonly review of committed 2G.A is now CLOSED for this milestone (the BLOCKED marker is reclassified above). Next safe Lane C window opens when 128 finishes authoring and before 129 starts authoring, scoped to read-only review of 2G.A files 02..09 only — without authoring under any 2G.B output path. The supervisor MAY skip this re-review entirely because the 2G.A pass marker at file 09 already covers the same scope.
- Codex autofix lane: idle until task 128 / 129 emits a concrete blocker.
- Codex watchdog lane: this turn IS the watchdog observation. The next watchdog action is automatic — supervisor pre-dispatch picks up `128` whenever its `requires_clean_worktree` predicate holds against its dispatch worktree.

This honors REQ_0021 ("Codex should not sit at 2-3% utilization while non-live work remains") without violating REQ_0011 ("Codex must not run a milestone's required review before that milestone's local validation marker passes"). It also honors REQ_0016 by reconciling a misclassified status against PASS evidence rather than escalating to `human_attention_required`.

## Hard safety re-affirmation

- No edit to `/home/wali/Desktop/AI BOT`.
- No Redis read or write or delete.
- No live service restart.
- No exchange order place or cancel.
- No leverage or margin change.
- No live trading enablement.
- No deployment.
- No production migration.
- No secret value or credential-shaped string in any authored file.
- No standalone harness BEGIN / END framing token marker line in any authored body.
- Final live approval remains human-only and BLOCKED.

## Output policy

This planner turn emits exactly one BEGIN_FILE / END_FILE block: this turn document. No new task definitions. No V2 source / test files. No `risk_gateway_impl/` files 14, 15, 16, or 17. No edit to the existing `..._REPORT.md` or `..._GO_NO_GO.md`. No edit to the master planner prompt.

PLANNER_TURN_2G_B_READONLY_REVIEW_MISCLASSIFICATION_RECONCILED_READY

Planner turn complete. The Lane C parallel readonly review's BLOCKED marker is reconciled as `superseded_by_evidence_pre_2g_b_dispatch` (its seven blockers are exactly the deliverables of pending task 128); the queued 128 → 129 → codex_recover_128 chain stands; the next planner turn opens Phase 2G.C composition root only after `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` is recorded at file 17.
