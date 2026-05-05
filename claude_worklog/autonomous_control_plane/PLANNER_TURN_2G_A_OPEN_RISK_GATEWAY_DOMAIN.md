# PLANNER TURN 2G.A — OPEN RISK GATEWAY DOMAIN

## Active requirement
REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md, with REQ_0017 / REQ_0018 / REQ_0020 paper-backtest MVP lane lock, REQ_0014 / REQ_0015 / REQ_0016 / REQ_0007 Codex non-live human-replacement watchdog authority, and REQ_0011 Codex parallel review/autofix lane.

## Active MVP target
V2_BACKTEST_AND_PAPER_MVP_READY (5 milestones distance from REQ_0017 milestone 3; this turn opens REQ_0017 milestone 3 RISK_GATEWAY_DEFAULT_DENY_MVP, sub-phase 2G.A, value-object domain).

## Active MVP milestone
RISK_GATEWAY_DEFAULT_DENY_MVP (Phase 2G).

## Predecessor closure
- Phase 2F.A orchestrator decision domain: PASSED. Implementation marker `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/07_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO.md`. Codex marker `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS` at `09_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_GO_NO_GO.md`.
- Phase 2F.B orchestrator decision assembler service: PASSED. Implementation marker `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `15_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO.md`. Codex marker `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS` at `17_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
- Phase 2F.C orchestrator decision composition root: PASSED. Implementation marker `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at `23_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_GO_NO_GO.md`. Codex marker `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS` at `25_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.

REQ_0017 milestone 2 ORCHESTRATOR_DECISION_MVP is therefore satisfied. The lane-lock condition that gated 2G is open: `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS` exists, the worktree contains only the durable dirty `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` planner-prompt entry that does NOT block child dispatch under the 963ea89 worktree-isolation contract, and no concrete safety violation is open.

## Decision
Open Phase 2G consolidated milestone for RISK_GATEWAY_DEFAULT_DENY_MVP. Phase 2G splits into three sub-phases that mirror the 2F decomposition:

- 2G.A — risk gateway domain (THIS TURN): pure value-object surface that defines `RiskDecisionRecord`, `RiskGatewayDomainError`, two risk-action constants, and five risk-reason constants. No service. No composition root. No FastAPI surface. No adapter. No Redis. No execution-side. No model-loading. No GPU. No checkpoint. No live behavior.
- 2G.B — risk gateway default-deny assembler service (LATER): pure function `assemble_risk_decision_record(*, decision: OrchestratorDecisionRecord, now_ms_clock: Callable[[], int]) -> RiskDecisionRecord`. Default-deny taxonomy is enumerated in 2G.B. 2G.A only validates the resulting strings via membership.
- 2G.C — risk gateway composition root (LATER): pure binder `build_risk_decision_evaluator(*, now_ms_clock: Callable[[], int]) -> RiskDecisionEvaluator` that captures static configuration at build time and returns a single-call evaluator that adapts the 2G.B service.

The 2G.A scope cap is intentional: the value-object layer ONLY validates self-consistency. It does NOT compute risk decisions. It does NOT import the orchestrator_decision domain at the value-object layer. The orchestrator action and reason are propagated as plain strings and validated by membership in frozensets. 2G.B service-layer composition consumes the orchestrator domain.

## Lane lock compliance (REQ_0018 / REQ_0020)
- lane: paper_backtest_mvp
- mvp_relevance: opens REQ_0017 milestone 3 RISK_GATEWAY_DEFAULT_DENY_MVP by authoring the value-object surface that the 2G.B default-deny assembler service and 2G.C composition root will consume. Without this domain, the risk gateway cannot produce a typed default-deny decision and downstream PAPER_EXECUTION_LEDGER_MVP cannot consume a canonical risk decision lineage.
- blocked_by: PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS (satisfied at `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/25_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`).
- next_gate: PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPL_AND_VALIDATION_PASSED (emitted by task 126 via `07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md`).
- legacy_evidence_consulted: read-only review captured in `claude_worklog/phase2_core_rebuild/risk_gateway_impl/01_PHASE_2G_LEGACY_EVIDENCE_REVIEW.md`. Reads: `claude_worklog/legacy_runtime_audit/00_AUDIT_SCOPE_AND_SAFETY.md`, `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`, `11_FAILURE_MODE_AND_GAP_REGISTER.md`, `12_LEGACY_AUDIT_GO_NO_GO.md`. Directory listing of `legacy_reference/` for naming evidence only. The pre-existing `v2/backend/app/services/risk_gateway.py` placeholder string and `v2/backend/app/domain/risk/` legacy-style stubs (`kill_switch.py`, `live_readiness_state.py`, `phases.py`, `policy_bundle.py`) are read-only and NOT modified by 2G.A. The existing empty `v2/backend/app/domain/decisions/` directory is NOT reused.
- legacy_failure_addressed: legacy-style risk decisions were not strongly typed with default-deny semantics. The legacy bot routed orchestrator outputs to execution without an explicit, machine-checked allow/deny decision lineage that ties back to the trainer prediction freshness, worker health, and orchestrator confidence threshold inputs. The 2G.A value-object pins the default-deny taxonomy at the type level: ALLOW reasons MUST start with `allow_`, DENY reasons MUST start with `deny_`, and the cross-field invariants enforce that an ALLOW result is paired with a tradable orchestrator action and a `proceed_*` upstream reason. Building the typed surface first (before the assembler service) eliminates the class of legacy bugs where a non-tradable orchestrator action could silently slip through to execution.

## Sub-phase staging
- 2G.A — Implementation task `126_risk_gateway_2ga_domain_implementation`. Emits `06_2G_A_RISK_GATEWAY_DOMAIN_IMPLEMENTATION_REPORT.md` and `07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md`. Predecessor marker `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`. Implementation gate `PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- 2G.A Codex review task — opened on 2G.A IMPL PASS as task `127_risk_gateway_2ga_domain_codex_review` (NOT emitted in this turn; emitted only after 126 PASS).
- 2G.B and 2G.C — opened only after 2G.A and 2G.B Codex passes respectively. Specs are NOT pre-staged.

## Worktree at the start of this turn
`git status --porcelain` reports exactly one entry: ` M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. The diff content is the durable insertion-only Claude Code Max 20x consolidated profile, Codex Pro parallel lane policy, and REQ_0018 / REQ_0020 planner lane lock additions described in prior planner turns. No live behavior. No Redis writes. No legacy mutation. No exchange action. No leverage / margin change. No deployment. No production migration. No secrets.

Per commit `963ea89 Keep planner prompt noise out of child dispatch worktrees`, this dirty entry is excluded from child dispatch worktrees by the supervisor's worktree-isolation contract. Task 126's `requires_clean_worktree = true` is therefore honored against the dispatch worktree, not the planner worktree, and the dirty planner prompt does NOT block dispatch.

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

Phase 2G.A specifically MUST NOT add any of the following:
- a service-layer assembler (deferred to 2G.B)
- a composition-root binder (deferred to 2G.C)
- any function that derives a risk decision (the 2G.A surface is value-object only)
- any import of `v2.backend.app.domain.orchestrator_decision` (the input decision action and reason are validated as plain strings via membership in frozensets; the orchestrator domain is consumed at the 2G.B service layer)
- any wall-clock helper invocation
- any module-level singleton, cache, or lock
- any subprocess call outside the single permitted import-safety test file

## Output policy
This planner turn emits exactly the following BEGIN_FILE / END_FILE blocks: this planner turn document, the 2G sub-phase breakdown, the 2G legacy evidence review, the 2G.A spec, the 2G.A test plan, the 2G.A safety boundaries, the 2G.A GO/NO-GO request, and the task 126 definition. No prior-milestone artifact is modified. No supervisor task definition under 117..125 is modified. No master planner prompt edit. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live trading enablement. The body of every authored document MUST NOT contain a standalone harness BEGIN/END framing token marker line.

PLANNER_TURN_2G_A_OPEN_RISK_GATEWAY_DOMAIN_READY
