# PLANNER TURN 2G.B — OPEN RISK GATEWAY ASSEMBLER SERVICE

## Active requirement
REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md, with REQ_0017 / REQ_0018 / REQ_0020 paper-backtest MVP lane lock, REQ_0014 / REQ_0015 / REQ_0016 / REQ_0007 Codex non-live human-replacement watchdog authority, and REQ_0011 Codex parallel review/autofix lane.

## Active MVP target
V2_BACKTEST_AND_PAPER_MVP_READY (5 milestones distance from REQ_0017 milestone 3; this turn opens REQ_0017 milestone 3 RISK_GATEWAY_DEFAULT_DENY_MVP, sub-phase 2G.B, default-deny assembler service).

## Active MVP milestone
RISK_GATEWAY_DEFAULT_DENY_MVP (Phase 2G), sub-phase 2G.B.

## Predecessor closure
- Phase 2G.A risk gateway domain: PASSED. Implementation marker `PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md`. Codex marker `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`.

The lane-lock condition that gated 2G.B is open: the 2G.A Codex pass marker exists, the worktree contains only the durable dirty `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` planner-prompt entry that does NOT block child dispatch under the 963ea89 worktree-isolation contract, and no concrete safety violation is open.

## Decision
Open Phase 2G.B consolidated milestone for the risk gateway default-deny assembler service. 2G.B authors a NEW services-layer package `v2/backend/app/services/risk_gateway/` whose only purpose is a single pure function `assemble_risk_decision_record(*, decision: OrchestratorDecisionRecord, now_ms_clock: Callable[[], int]) -> RiskDecisionRecord`. The function consumes a 2F.A-validated `OrchestratorDecisionRecord` and a `now_ms_clock` callable, and returns a frozen 2G.A `RiskDecisionRecord` constructed under the default-deny taxonomy fixed by 2G.A and 00 sub-phase breakdown.

The 2G.B scope cap is intentional: the service layer is a pure derivation surface. It does NOT compose a composition root (deferred to 2G.C). It does NOT touch I/O, Redis, files, HTTP, GPU, model loading, checkpoints, or FastAPI surfaces. It does NOT add any execution-side surface, paper executor, shadow executor, or strategy library. It does NOT introduce any module-level singleton, cache, or lock.

The placeholder file `v2/backend/app/services/risk_gateway.py` (a 4-line docstring file) collides with the new `v2/backend/app/services/risk_gateway/` package on the import path. Phase 2G.B opens by deleting that placeholder file in the same supervisor task that authors the new package, mirroring the 2F.B placeholder-deletion pattern at `v2/backend/app/services/orchestrator_decision.py`. The placeholder file MUST NOT be reintroduced.

The reserved 2G.A taxonomy member `RISK_DECISION_REASON_DENY_DEFAULT` is held for a future enrichment of 2G.B (e.g., a tradable input that fails an exposure or freshness gate added to the assembler). 2G.B does NOT exercise the `deny_default` branch and does NOT import the `RISK_DECISION_REASON_DENY_DEFAULT` constant. The 2G.A value-object layer continues to validate `deny_default` records as part of its cross-field rules, and 2G.B authors a regression test that confirms its derivation table never emits `deny_default` for any orchestrator-decision input.

## Lane lock compliance (REQ_0018 / REQ_0020)
- lane: paper_backtest_mvp
- mvp_relevance: opens REQ_0017 milestone 3 RISK_GATEWAY_DEFAULT_DENY_MVP service-layer derivation. Without this assembler, the risk gateway cannot produce a typed default-deny `RiskDecisionRecord` from a validated `OrchestratorDecisionRecord`, and downstream PAPER_EXECUTION_LEDGER_MVP cannot consume a canonical risk decision lineage.
- blocked_by: PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS (satisfied at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`).
- next_gate: PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED (emitted by task 128 via `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`).
- legacy_evidence_consulted: read-only review captured in `claude_worklog/phase2_core_rebuild/risk_gateway_impl/01_PHASE_2G_LEGACY_EVIDENCE_REVIEW.md`. The 2G.A implementation report `06_2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT.md` and Codex review `08_2G_A_RISK_GATEWAY_DOMAIN_CODEX_REVIEW.md` are read as authoritative for the 2G.A value-object surface that 2G.B consumes. The 2F.B service spec `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/10_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SPEC.md` is referenced as the analogous service-layer pattern. The pre-existing one-line placeholder at `v2/backend/app/services/risk_gateway.py` is read for confirmation that no behavior is encoded there before deletion. No legacy mutation, no Redis access, no live behavior.
- legacy_failure_addressed: the legacy bot routed orchestrator outputs to execution without an explicit, machine-checked allow/deny decision lineage tied to upstream prediction freshness, worker health, and orchestrator-confidence inputs. 2G.B fixes this by collapsing the four orchestrator action outcomes into a typed default-deny risk decision: `open_long` and `open_short` map to `allow_proceed_long` / `allow_proceed_short`; `hold` maps to `deny_orchestrator_held`; `abstain` (any abstain reason) maps to `deny_orchestrator_abstained`. Any unrecognized `decision.decision_action` is rejected with a service-layer error before construction, eliminating the class of legacy bugs where a non-tradable orchestrator action could silently slip through to execution.

## Sub-phase staging
- 2G.B — Implementation task `128_risk_gateway_2gb_assembler_service_implementation`. Emits `14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md` and `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`. Predecessor marker `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS`. Implementation gate `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- 2G.B Codex review task — opened on 2G.B IMPL PASS as task `129_risk_gateway_2gb_assembler_service_codex_review` (NOT emitted in this turn; emitted only after 128 PASS).
- 2G.C — opened only after 2G.B Codex pass. Spec is NOT pre-staged.

## Worktree at the start of this turn
`git status --porcelain` reports exactly one entry: ` M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. The diff content is the durable insertion-only Claude Code Max 20x consolidated profile, Codex Pro parallel lane policy, and REQ_0018 / REQ_0020 planner lane lock additions described in prior planner turns. No live behavior. No Redis writes. No legacy mutation. No exchange action. No leverage / margin change. No deployment. No production migration. No secrets.

Per commit `963ea89 Keep planner prompt noise out of child dispatch worktrees`, this dirty entry is excluded from child dispatch worktrees by the supervisor's worktree-isolation contract. Task 128's `requires_clean_worktree = true` is therefore honored against the dispatch worktree, not the planner worktree, and the dirty planner prompt does NOT block dispatch.

## Hard scope cap (REQ_0017 milestone 3)
Phase 2G as a whole MUST NOT add any of the following:
- execution-side surface, paper executor, shadow executor, or strategy library
- Redis read or write at any layer
- model-loading, GPU runner, or checkpoint subsystem
- FastAPI lifespan, dependency, router, or background task
- adapter expansion (no new `v2/backend/app/adapters/*` member; no edit to existing adapter)
- live trading enablement
- legacy mutation
- secret exposure

Phase 2G.B specifically MUST NOT add any of the following:
- a composition-root binder (deferred to 2G.C)
- any function beyond `assemble_risk_decision_record` and the service-error class
- any wall-clock helper invocation; the clock is injected via `now_ms_clock` only
- any module-level singleton, cache, or lock
- any subprocess call outside the permitted import-isolation test files
- any import of `RISK_DECISION_REASON_DENY_DEFAULT` (reserved for future enrichment)
- any reintroduction of the placeholder `v2/backend/app/services/risk_gateway.py` file
- any new `v2/backend/app/domain/*` member, any new `v2/backend/app/composition/*` member, any new `v2/backend/app/adapters/*` member, or any new `v2/backend/app/api/*`, `v2/backend/app/cli/*`, `v2/backend/app/jobs/*`, or `v2/backend/app/main.py` change

## Output policy
This planner turn emits exactly the following BEGIN/END framed blocks: this planner turn document, the 2G.B spec, the 2G.B test plan, the 2G.B safety boundaries, the 2G.B GO/NO-GO request, and the task 128 definition. No prior-milestone artifact is modified. No supervisor task definition under 117..127 is modified. No master planner prompt edit. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live trading enablement. The body of every authored document MUST NOT contain a standalone harness BEGIN/END framing token marker line.

PLANNER_TURN_2G_B_OPEN_RISK_GATEWAY_ASSEMBLER_SERVICE_READY
