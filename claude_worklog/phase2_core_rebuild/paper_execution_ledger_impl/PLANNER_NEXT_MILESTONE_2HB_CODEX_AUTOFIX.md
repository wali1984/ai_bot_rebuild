# Planner next milestone selection — Phase 2H.B Codex closed-loop autofix-and-reconciliation

## Active requirement

REQ_0006 (trainer parity) remains the current active inbox header, but the prime directive under REQ_0017 / REQ_0018 / REQ_0020 / REQ_0021 holds the planner lane lock to the paper / backtest MVP track until `V2_BACKTEST_AND_PAPER_MVP_READY` exists.

## MVP progress map

- Milestone 1 `TRAINER_PREDICTION_OUTPUT_MVP`: closed (trainer prediction output domain, service, composition root, plus trainer worker health and trainer parity sub-services committed; 18-suite pytest baseline green).
- Milestone 2 `ORCHESTRATOR_DECISION_MVP`: closed (orchestrator decision domain, service, composition root committed; orchestrator decision suites green).
- Milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`: closed (risk gateway domain, service, composition root committed; default-deny invariants enforced; risk gateway suites green).
- Milestone 4 `PAPER_EXECUTION_LEDGER_MVP`: in progress.
  - Phase 2H.A domain: PASS (file 09 marker `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS`; reconciliation addendum at file 10).
  - Phase 2H.B assembler service: implementation PASS at file 16 marker `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`; Codex review at file 17 returned `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_FAIL` (file 18) on exactly two rubric rows (5 and 43 of 55).
  - Phase 2H.C composition root: pre-staged at task 138 (implementation) and 139 (Codex review); blocked on 2H.B Codex PASS.
- Milestones 5–7 (`REPLAY_BACKTEST_RUNNER_MVP`, `PAPER_MODE_MVP`, `SHADOW_MODE_READINESS`): not yet opened.

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 4 sub-milestones remaining (2H.C composition root, replay/backtest runner, paper mode, shadow readiness).

## Next milestone selected

**Phase 2H.B Codex closed-loop autofix-and-reconciliation (task 140).**

Rationale:

- The 17/18 Codex review is the only blocker between the committed 2H.B implementation (file 16 PASS) and the pre-staged 2H.C dispatch (task 138).
- Both blockers are recoverable inside Codex watchdog scope (REQ_0007 / REQ_0011 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0021):
  - Blocker 1 (rubric row 5) is a stale-rubric-premise divergence already adjudicated in the 2H.A reconciliation at file 10. The `v2/backend/app/domain/execution/` directory carries three pre-existing 015A docstring-only placeholders since commit `26e49b7 Materialize 015A V2 repo package skeleton`; the 2H.B milestone diff does not touch them. The reconciliation reproduces the file-10 evidence set against the current committed tree.
  - Blocker 2 (rubric row 43) is a real concrete test-source defect at `v2/backend/tests/unit/services/paper_execution_ledger/test_assembler_service_forbidden_tokens.py` lines 25 and 26: the value tuple constructs `"datetime" + ".now"` and `"datetime" + ".utcnow"`, embedding the bare 8-character `datetime` token in the test source body. The fix is the minimum byte-deterministic split mirroring the already-correct `"date" + "time"` line at 27, preserving the same 28 forbidden-token literals at runtime, the same tuple ordering, and the same assertion shape.
- The composition root (2H.C) cannot dispatch until 2H.B Codex PASS is recorded.
- Closing 2H.B unblocks 2H.C and ends `PAPER_EXECUTION_LEDGER_MVP`; the deterministic `paper_trade_id` derived from `risk_decision_id` by the 2H.B service is the canonical lineage ID that `REPLAY_BACKTEST_RUNNER_MVP` will consume.

## Lane and gate

- Lane: `codex_watchdog`.
- Approved-lane policy: meets REQ_0018 Lane C scope (Codex review of latest committed milestone, autofix for non-live blockers, evidence reconciliation, dispatch bridge fix).
- Risk level: L1 (test-file edit + marker rewrite + single deterministic-append edit to `claude_worklog/tools/reconcile_evidence_status.py`).
- Next gate: `PHASE2H_B_CODEX_FAIL_AUTOFIX_AND_RECONCILIATION_PASSED` (task 140).
- Downstream gate after PASS: supervisor pre-dispatch gate clears for task 138 (`PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`).

## Legacy evidence consulted

- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/01_PHASE_2H_LEGACY_EVIDENCE_REVIEW.md` — legacy executor and paper-loop runtime audit.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/10_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_RECONCILIATION_ADDENDUM.md` — prior 015A placeholder adjudication.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/15_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` — 2H.B implementation evidence.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/17_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_REVIEW.md` — 55-row Codex rubric, two FAIL rows.
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` — legacy signal-to-execution failure surface that the V2 paper ledger replaces.
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` — failure modes the V2 paper ledger explicitly addresses (no live blocking, no lineage capture, no deterministic ledger entry).

## Legacy failure addressed

The legacy paper/shadow path had no deterministic mechanism to (a) reinterpret a stale-rubric-premise audit row when the rubric assumption was contradicted by committed git history, or (b) auto-patch a narrow test-source defect while preserving every other invariant. The closed-loop autofix-and-reconciliation surface is the V2 proof that committed evidence overrides stale-premise rubric noise (pattern (a) from 2H.A file 10) AND that real concrete test-source defects can be auto-patched under a narrow byte-deterministic scope (pattern (b) from prior trainer / orchestrator / risk-gateway closed-loop recoveries) without any change to the V2-side service code that already PASSED 53 of 55 rubric rows.

## V2 proof gate

- Test-source autofix pinned to entries 18 and 19 of the 28-entry forbidden-token tuple; entry 20 unchanged; line count delta zero; bare 8-character `datetime` substring removed from test source body.
- Full 18-suite pytest regression re-run (paper execution ledger domain + assembler service + risk gateway + orchestrator decision + trainer prediction output + trainer worker health + trainer parity + trainer liveness + composition roots).
- 28-token forbidden-token sweep over both the test source and the authored 2H.B service sources (`v2/backend/app/services/paper_execution_ledger/`) — all 28 must exit 1 with zero matches in each scope.
- Fresh-subprocess `sys.modules` import-isolation probe — must print `[]` for `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env`.
- Marker rewrites: file 18 overwrites FAIL → PASS; file 19 reconciliation addendum emitted; one EVIDENCE_MARKERS tuple appended at the top of the list in `claude_worklog/tools/reconcile_evidence_status.py`; reconcile script run produces `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS` under `found_markers` and `137_paper_execution_ledger_2hb_assembler_service_codex_review` under `superseded_tasks`.

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
- The 2H.B authored service sources at `v2/backend/app/services/paper_execution_ledger/` remain byte-stable; no source-code edit in this milestone.
- The 015A placeholders at `v2/backend/app/domain/execution/` remain byte-stable since commit `26e49b7`.
- No 2H.A artifact (00–10) modified.
- No 2H.B artifact (11–17) modified; only file 18 marker rewrite and new file 19 emission.
- No 135-prefixed automation_reliability artifact modified.
- No master planner prompt or task-definition edit beyond this 140 task.
- One deterministic single-tuple append in `claude_worklog/tools/reconcile_evidence_status.py`; no other helper, def, class, or constant change.

## Failure path

On `PHASE2H_B_CODEX_FAIL_AUTOFIX_AND_RECONCILIATION_FAILED` with no safety violation, supervisor dispatches a follow-up REQ_0007 / REQ_0014 narrow autofix task scoped to the same six output paths and re-runs the closed-loop. On any safety violation, the planner surfaces to human attention and stops; no autofix is permitted.

PLANNER_NEXT_MILESTONE_2HB_CODEX_AUTOFIX_READY
