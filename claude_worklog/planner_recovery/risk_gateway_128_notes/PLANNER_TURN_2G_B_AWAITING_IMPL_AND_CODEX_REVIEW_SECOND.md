# Planner Turn — Phase 2G.B Risk Gateway Assembler Service Awaiting Impl + Codex Review (Second)

Turn date: 2026-05-05
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md ∩ REQ_0021_PARALLEL_CAPACITY_SCHEDULER_FOR_CLAUDE_CODEX.md
Active MVP milestone: RISK_GATEWAY_DEFAULT_DENY_MVP (REQ_0017 milestone 3)
Active sub-phase: Phase 2G.B (risk gateway assembler service surface)
Lane: paper_backtest_mvp (Lane A); Lane C `codex_watchdog` parallel.
Profile: Claude Code Max20 consolidated_default; Codex Pro parallel lane active.

## Decision

No new build or dispatch task is authored on this turn. State has not advanced since `PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW.md`.

## Verified state

- 2G.A predecessor: `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md` contains exactly `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS`.
- 2G.B planning docs present: files `10`, `11`, `12`, `13` under `risk_gateway_impl/`.
- 2G.B impl report `14` and 2G.B impl GO/NO-GO `15` not yet on disk — supervisor task `128_risk_gateway_2gb_assembler_service_implementation` is the next dispatch.
- 2G.B Codex review `16` and 2G.B Codex GO/NO-GO `17` not yet on disk — supervisor task `129_risk_gateway_2gb_assembler_service_codex_review` is gated on the `15` PASS marker.
- Placeholder `v2/backend/app/services/risk_gateway.py` is still on disk; task 128's first filesystem mutation is `git rm` of that path before authoring the new package.
- Codex parallel readonly review task on disk: `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_codex_parallel_readonly_review_ready.json` (Lane C).
- Codex closed-loop recovery task on disk: `claude_worklog/agent_supervisor/tasks/codex_recover_128_risk_gateway_2gb_assembler_service_implementation.json` (used only on 128 fail with concrete non-live blocker and no safety violation).
- `git status --porcelain`:
  ```
   M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
  ```
  Single dirty path is the planner prompt; supervisor's worktree-isolation contract excludes it from dispatch worktrees, so 128 / 129 / parallel readonly review can each dispatch into a clean worktree.

## Why no new dispatch is authored

- Authoring a new 2G.B build task would duplicate `128`.
- Authoring 2G.C composition root or a Phase 2H/2I task would drift outside the lane lock under REQ_0018 / REQ_0020 — Phase 2G.C cannot open before `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` is written to file 17.
- Authoring trainer parity follow-on (Phase 2E4 / Phase 2E5) before 2G.B closes would race Lane A's prime directive (advance the MVP sequence in order).
- Authoring frontend explainability tasks (REQ_0008 / REQ_0009 Lane B) without the upstream `RiskDecisionRecord` lineage stable would produce frontend polish without real data contracts, which REQ_0018 forbids.
- Authoring further codex_watchdog tasks (Lane C) is already covered by the queued parallel readonly review task and the 128 recovery task; further watchdog work is not needed until a fail/dirty event occurs.
- Re-authoring task definitions for 128 / 129 / parallel readonly review would mutate task files already on disk and is forbidden by `forbidden_actions` of every active task.

## Lane discipline check (REQ_0018 / REQ_0020)

All on-disk pending tasks remain within approved lanes:

| Task | lane | mvp_relevance | next_gate |
|---|---|---|---|
| 128 | paper_backtest_mvp | typed RiskDecisionRecord derivation surface for default-deny risk decisions on the path to PAPER_EXECUTION_LEDGER_MVP | PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED |
| 129 | paper_backtest_mvp | closes Codex review gate so planner can advance to Phase 2G.C composition root | PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS |
| codex_recover_128 | codex_watchdog | safe non-live recovery scoped to the three authored 2G.B source files plus the 29 new test files only | PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED |
| parallel_capacity_readonly_review_codex_parallel_readonly_review_ready | codex_watchdog | parallel review of the committed 2G.A milestone for paper/backtest MVP compatibility, lineage gaps, stale evidence, missing test-hardening recommendations | CODEX_PARALLEL_READONLY_REVIEW_READY |

No drift tasks (no broad scaffold expansion, no generic architecture docs, no frontend polish without data contracts, no automation framework expansion outside REQ_0018 lanes, no new audit-only work outside MVP path).

## Dispatch ordering (still in effect)

1. Supervisor dispatches `128_risk_gateway_2gb_assembler_service_implementation` first into a clean dispatch worktree.
2. The Lane C `parallel_capacity_readonly_review_codex_parallel_readonly_review_ready` task may dispatch in parallel only when no Claude child is actively writing into `risk_gateway_impl/` — i.e. either before 128 starts, or after 128 commits and before 129 starts. It must not race 128's authoring window.
3. On `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` in file 15, supervisor dispatches `129_risk_gateway_2gb_assembler_service_codex_review`.
4. On `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_FAILED` in file 15 with concrete non-live blocker and no safety violation, supervisor dispatches `codex_recover_128_risk_gateway_2gb_assembler_service_implementation` and re-runs the impl flow.
5. On any safety violation in 128 or 129, surface to human attention; no autofix is permitted.

## Next consolidated milestone (deferred)

After `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` is written to file 17, the next planner turn opens Phase 2G.C `RISK_GATEWAY_COMPOSITION_ROOT` as a single consolidated milestone task that authors only the composition-root binder for the 2G.B assembler service. Out-of-scope for 2G.C and rejected if proposed:

- any execution-side surface
- any paper executor or shadow executor
- any strategy library
- any Redis adapter
- any FastAPI surface
- any new lineage ID at the service layer beyond the derived `risk_decision_id`
- any module-level singleton, cache, or lock
- any os.environ / os.getenv read in authored 2G.B / 2G.C source files
- any `RISK_DECISION_REASON_DENY_DEFAULT` import or `deny_default` emission for orchestrator-decision inputs
- any logging / print / socket import in authored source files
- any wall-clock helper call in authored 2G.C source files (now_ms_clock injected at composition only)

After 2G.C Codex PASS, `RISK_GATEWAY_DEFAULT_DENY_MVP` closes and the planner opens REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP` under a fresh consolidated milestone.

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 5 milestones remaining once 2G.B closes (2G.C composition root → PAPER_EXECUTION_LEDGER_MVP → REPLAY_BACKTEST_RUNNER_MVP → PAPER_MODE_MVP → SHADOW_MODE_READINESS).

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

PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW_SECOND_NOTE_READY
END_FILE: claude_worklog/autonomous_control_plane/PLANNER_TURN_2G_B_AWAITING_IMPL_AND_CODEX_REVIEW_SECOND.md
