# Planner turn confirmation — Phase 2H.B Codex closed-loop autofix-and-reconciliation pre-staged

## Active requirement

REQ_0006 (trainer parity) remains the inbox header, but the prime directive under REQ_0017 / REQ_0018 / REQ_0020 / REQ_0021 holds the planner lane lock on the paper / backtest MVP track until `V2_BACKTEST_AND_PAPER_MVP_READY` exists.

## Planner decision (this turn)

Re-confirms the next milestone selection emitted in the prior planner turn:

**Phase 2H.B Codex closed-loop autofix-and-reconciliation — supervisor task 140.**

No new milestone selection, no new task definition, and no new planning artifact is required this turn. The selection and full prompt are already byte-stable on disk under untracked status, awaiting Codex-watchdog commit and supervisor dispatch.

## Pre-staged artifacts (already on disk, not yet committed)

- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/PLANNER_NEXT_MILESTONE_2HB_CODEX_AUTOFIX.md` — milestone selection rationale and proof gate.
- `claude_worklog/agent_supervisor/tasks/140_paper_execution_ledger_2hb_codex_fail_autofix_and_reconciliation.json` — full Codex prompt with predecessor gate checks, 015A pre-existing placeholder evidence checks, 2H.B diff isolation evidence checks, byte-deterministic test-source autofix specification (entries 18 and 19 split from `"datetime" + ".now"` / `"datetime" + ".utcnow"` to `"date" + "time" + ".now"` / `"date" + "time" + ".utcnow"`, entry 20 unchanged), 18-suite pytest regression set, 28-token forbidden-token sweep over both test source and authored 2H.B service sources, fresh-subprocess `sys.modules` import-isolation probe, marker rewrite ordering, and `claude_worklog/tools/reconcile_evidence_status.py` deterministic single-tuple append.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/17_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_REVIEW.md` — 55-row Codex rubric output from task 137 (53 PASS, 2 FAIL on rows 5 and 43).
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/18_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` — current FAIL marker, awaiting reconciliation rewrite to PASS by task 140.

## MVP progress map (unchanged)

- Milestone 1 `TRAINER_PREDICTION_OUTPUT_MVP`: closed.
- Milestone 2 `ORCHESTRATOR_DECISION_MVP`: closed.
- Milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`: closed.
- Milestone 4 `PAPER_EXECUTION_LEDGER_MVP`: in progress.
  - Phase 2H.A domain: PASS (file 09 `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS`).
  - Phase 2H.B assembler service: implementation PASS at file 16; Codex review FAIL at file 18 on rows 5 and 43; closed-loop reconciliation pre-staged as task 140.
  - Phase 2H.C composition root: pre-staged at task 138 (implementation) and 139 (Codex review); blocked on 2H.B Codex PASS.
- Milestones 5–7 (`REPLAY_BACKTEST_RUNNER_MVP`, `PAPER_MODE_MVP`, `SHADOW_MODE_READINESS`): not yet opened.

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 4 sub-milestones remaining (2H.C composition root, replay/backtest runner, paper mode, shadow readiness).

## Lane and gate

- Lane: `codex_watchdog` (REQ_0018 Lane C: review of latest committed milestone, autofix for non-live blockers, evidence reconciliation).
- Risk level: L1 (one test-file edit, one marker rewrite, one deterministic-append edit to `claude_worklog/tools/reconcile_evidence_status.py`, two new evidence reports).
- Next gate: `PHASE2H_B_CODEX_FAIL_AUTOFIX_AND_RECONCILIATION_PASSED`.
- Downstream gate after PASS: supervisor pre-dispatch gate clears for task 138 (`PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`) which closes `PAPER_EXECUTION_LEDGER_MVP`.

## Why no re-emission this turn

Task granularity mode is `consolidated_default`. The 140 task is already a single consolidated closed-loop milestone (autofix + reconciliation + marker rewrites + reconcile-script append + evidence report + GO/NO-GO in one Codex run). The full prompt, all six required output paths, all forbidden-action enumerations, all predecessor gate checks, all 015A evidence checks, all 2H.B diff isolation checks, all validation commands, and all marker write ordering are already byte-stable on disk. Re-emitting the 50KB+ JSON would be redundant and risks byte mismatch with the pre-staged file. The correct planner action this turn is confirmation and hand-off to the Codex watchdog dispatch cycle.

## Hand-off

The Codex watchdog (REQ_0014 / REQ_0016 / REQ_0021) should:

1. Commit the four untracked planner artifacts and this confirmation note as a single non-live `Codex watchdog recover dirty non-live automation artifacts` durable commit.
2. Confirm the dispatch worktree is clean modulo the harness-managed planner-prompt entry and the durable Lane C parallel-capacity readonly-review marker file already declared in `worktree_excluded_paths`.
3. Dispatch task 140.
4. On `PHASE2H_B_CODEX_FAIL_AUTOFIX_AND_RECONCILIATION_PASSED`, advance to task 138 (Phase 2H.C composition root implementation).
5. On `PHASE2H_B_CODEX_FAIL_AUTOFIX_AND_RECONCILIATION_FAILED` with no safety violation, dispatch a follow-up REQ_0007 / REQ_0014 narrow autofix scoped to the same six output paths.
6. On any safety violation, surface to human attention and stop.

## Legacy evidence consulted (this turn)

- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/01_PHASE_2H_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/10_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_RECONCILIATION_ADDENDUM.md` (prior 015A adjudication; same divergence pattern reused)
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/15_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/17_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_REVIEW.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`

## Legacy failure addressed

The 2H.B closed-loop autofix-and-reconciliation surface is the V2 proof that committed evidence overrides stale-premise rubric noise (pattern (a) inherited from 2H.A file 10) AND that real concrete test-source defects can be auto-patched under a narrow byte-deterministic scope (pattern (b) generalized from prior trainer parity / orchestrator decision / risk gateway closed-loop recovery precedents) without any change to V2-side service code that already PASSED 53 of 55 rubric rows. The legacy paper/shadow path had no such mechanism; this is the V2 gain.

## Safety boundaries

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
- No 2H.A artifact (00–10) modified by this turn or by task 140.
- No 2H.B artifact (11–17) modified by this turn or by task 140; only file 18 marker rewrite and new file 19 emission are authorized inside task 140.
- No master planner prompt or task-definition edit beyond the pre-staged 140 task JSON.

PLANNER_TURN_2HB_CODEX_AUTOFIX_PRESTAGED_CONFIRMATION_READY
