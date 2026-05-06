# Planner Turn — Phase 2G.B Risk Gateway Assembler Service Awaiting Impl + Codex Review

Turn date: 2026-05-05
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md ∩ REQ_0021_PARALLEL_CAPACITY_SCHEDULER_FOR_CLAUDE_CODEX.md
Active MVP milestone: RISK_GATEWAY_DEFAULT_DENY_MVP (REQ_0017 milestone 3)
Active sub-phase: Phase 2G.B (risk gateway assembler service surface)
Lane: paper_backtest_mvp (Lane A)
Profile: Claude Code Max20 consolidated_default; Codex Pro parallel lane active.

## Decision

No new build or dispatch task is authored on this turn.

The 2G.B implementation/validation step (supervisor task `128_risk_gateway_2gb_assembler_service_implementation`) is the next dispatch. Its Codex review (`129_risk_gateway_2gb_assembler_service_codex_review`) is already queued and is gated on the predecessor local-validation marker `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` written to `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`.

Authoring any new MVP-relevant build task (e.g. Phase 2G.C composition root, PAPER_EXECUTION_LEDGER_MVP scaffolding, or further trainer parity work) before 2G.B passes would either duplicate queued work, race the supervisor's worktree isolation, or drift outside the lane lock under REQ_0018 / REQ_0020.

## Current build/queue posture

Pending supervisor tasks already on disk for this milestone:
- `claude_worklog/agent_supervisor/tasks/128_risk_gateway_2gb_assembler_service_implementation.json`
  - Lane A `paper_backtest_mvp`. Authors only:
    - `v2/backend/app/services/risk_gateway/__init__.py`
    - `v2/backend/app/services/risk_gateway/errors.py`
    - `v2/backend/app/services/risk_gateway/service.py`
    - `v2/backend/tests/unit/services/risk_gateway/__init__.py`
    - the 29 enumerated test files under `v2/backend/tests/unit/services/risk_gateway/`
    - `claude_worklog/phase2_core_rebuild/risk_gateway_impl/14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`
    - `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`
  - Predecessor markers required: `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS` (file 09) and `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`.
  - Required final marker: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` in file 15.
  - Recovery task `codex_recover_128_risk_gateway_2gb_assembler_service_implementation.json` is on disk for use only if 128 fails on a safe non-live blocker (path mismatch, harness END_FILE leakage, or compile/test failure).
- `claude_worklog/agent_supervisor/tasks/129_risk_gateway_2gb_assembler_service_codex_review.json`
  - Lane A. Read-only Codex review. Authors only files 16 and 17 in `risk_gateway_impl/`.
  - Predecessor marker: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` in file 15.
  - Required final marker: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` in file 17.

Pending Codex parallel-lane task:
- `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json`
  - Lane C `codex_watchdog`. Read-only review of the previously committed Phase 2G.A pass (`parallel_capacity_readonly_review_phase2g_a_risk_gateway_domain_codex_pass_GO_NO_GO.md`).
  - Authors only the two `..._REPORT.md` and `..._GO_NO_GO.md` files under `risk_gateway_impl/`.
  - Safe to run in parallel with 128 because it does not touch any path that 128 writes and does not modify dirty source files.

## Worktree posture

`git status --porcelain` at turn start:
```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
?? claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json
```

Both entries are automation/control-plane only; neither lives under v2/, neither is a Phase 2G.A or 2G.B implementation artifact, and per the supervisor's worktree-isolation contract the planner-prompt path is excluded from dispatch worktrees. The new readonly review task JSON is additive and outside the 128 / 129 forbidden_output_paths. Therefore:
- Task 128 may dispatch to its isolated worktree without dirty conflict.
- Task 129 must wait for the 128 marker (file 15) before dispatch.
- The parallel readonly review task may dispatch in parallel only when no Claude child is actively writing into `risk_gateway_impl/` — i.e. either before 128 starts, or after 128 commits and before 129 starts. It must not race 128's authoring window.

## Lane discipline check (REQ_0018 / REQ_0020)

Every queued task on disk passes the lane checklist:

| Task | lane | mvp_relevance | next_gate | legacy_evidence_consulted | legacy_failure_addressed |
|---|---|---|---|---|---|
| 128 | paper_backtest_mvp | typed RiskDecisionRecord derivation surface for default-deny risk decisions on the path to PAPER_EXECUTION_LEDGER_MVP | PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED | Phase 2G legacy evidence review (file 01); 2F.A OrchestratorDecisionRecord upstream | legacy untyped allow/deny strings, missing risk_decision_id / decision_id / prediction_id / feature_snapshot_id lineage, ad-hoc wall-clock reads, hidden module-level state, redis/url_env/factory imports at construction |
| 129 | paper_backtest_mvp | closes Codex review gate so planner can advance to Phase 2G.C composition root | PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS | files 01, 09, 14, 15; legacy_runtime_audit/09 and /11 | hardens default-deny posture against silent bypass between orchestrator decisions and downstream execution-side intents |
| parallel_capacity_readonly_review_codex_parallel_readonly_review_ready | codex_watchdog | parallel review of the committed 2G.A milestone for paper/backtest MVP compatibility, lineage gaps, stale evidence, and missing test-hardening recommendations | CODEX_PARALLEL_READONLY_REVIEW_READY | latest committed milestone evidence, runtime task states, paper/backtest MVP requirement set | serial review bottleneck and late discovery of paper/backtest compatibility gaps |

No drift tasks (no broad scaffold expansion, no generic architecture docs, no frontend polish without data contracts, no automation framework expansion outside REQ_0018 lanes).

## Next consolidated milestone (deferred)

After `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` is written to file 17, the next planner turn opens Phase 2G.C `RISK_GATEWAY_COMPOSITION_ROOT` as a single consolidated milestone task that authors only the composition-root binder for the 2G.B assembler service. Out of scope for 2G.C and rejected if proposed:
- any execution-side surface
- any paper executor or shadow executor
- any strategy library
- any Redis adapter
- any FastAPI surface
- any new lineage ID at the service layer beyond the derived `risk_decision_id`
- any module-level singleton
- any os.environ / os.getenv read in authored 2G.B / 2G.C source files
- any RISK_DECISION_REASON_DENY_DEFAULT import or `deny_default` emission for orchestrator-decision inputs
- any logging / print / socket import in authored source

After 2G.C Codex PASS, `RISK_GATEWAY_DEFAULT_DENY_MVP` closes and the planner opens REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP` under a fresh consolidated milestone.

Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 5 milestones remaining once 2G.B closes (2G.C composition root → PAPER_EXECUTION_LEDGER_MVP → REPLAY_BACKTEST_RUNNER_MVP → PAPER_MODE_MVP → SHADOW_MODE_READINESS).

## Hard stops still active

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write or delete any Redis key.
- Do not invoke any Redis command.
- Do not restart any live service.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy or run a production migration.
- Do not expose or commit secrets.
- Do not approve the live gate.
- Final live approval remains human-only. Larger consolidated task capacity does not grant live authority.

## Marker

PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW_NOTE_READY

Planner turn complete. No new dispatch task authored — the queued 128 (impl) → 129 (Codex review) chain plus the parallel-capacity readonly review task already cover Lane A and Lane C for this milestone, and authoring more before `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` would drift or race the supervisor's worktree isolation. The next planner turn opens Phase 2G.C composition root once 2G.B Codex PASS is recorded.
