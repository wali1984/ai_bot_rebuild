# PLANNER TURN 2H.A — OPEN PAPER EXECUTION LEDGER DOMAIN

## Active requirement
REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md, with REQ_0017 / REQ_0018 / REQ_0020 paper-backtest MVP lane lock, REQ_0014 / REQ_0015 / REQ_0016 / REQ_0007 Codex non-live human-replacement watchdog authority, and REQ_0011 Codex parallel review/autofix lane.

## Active MVP target
V2_BACKTEST_AND_PAPER_MVP_READY (4 milestones distance after this turn closes the predecessor; this turn opens REQ_0017 milestone 4 PAPER_EXECUTION_LEDGER_MVP, sub-phase 2H.A, value-object domain).

## Active MVP milestone
PAPER_EXECUTION_LEDGER_MVP (Phase 2H).

## Predecessor closure
- Phase 2G.A risk gateway domain: PASSED. Implementation marker `PHASE2G_A_RISK_GATEWAY_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/07_2G_A_RISK_GATEWAY_DOMAIN_GO_NO_GO.md`. Codex marker `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS` at `09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md`.
- Phase 2G.B risk gateway assembler service: PASSED. Implementation marker `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`. Codex marker `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` at `17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
- Phase 2G.C risk gateway composition root: PASSED. Implementation marker `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED` at `23_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_GO_NO_GO.md`. Codex marker `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS` at `25_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`.

REQ_0017 milestone 3 RISK_GATEWAY_DEFAULT_DENY_MVP is therefore satisfied. Phase 2G is closed. The lane-lock condition that gated 2H opens: `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS` exists, the worktree contains only the durable dirty `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` planner-prompt entry plus the durable Lane C task file `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2g_c_risk_gateway_composition_root_codex_pass.json`, both excluded from the dispatch worktree by the 963ea89 worktree-isolation contract, and no concrete safety violation is open.

## Decision
Open Phase 2H consolidated milestone for PAPER_EXECUTION_LEDGER_MVP. Phase 2H splits into three sub-phases that mirror the 2F / 2G decomposition:

- 2H.A — paper execution ledger domain (THIS TURN): pure value-object surface that defines `PaperExecutionLedgerEntry`, `PaperExecutionLedgerDomainError`, two ledger-action constants, and five ledger-reason constants. No service. No composition root. No FastAPI surface. No adapter. No Redis. No persistence layer. No PnL. No quantity. No price. No fees. No replay runner. No paper trader process. No execution-side. No model-loading. No GPU. No checkpoint. No live behavior.
- 2H.B — paper execution ledger assembler service (LATER): pure function `assemble_paper_execution_ledger_entry(*, risk_decision: RiskDecisionRecord, now_ms_clock: Callable[[], int]) -> PaperExecutionLedgerEntry`. The mirror taxonomy is enumerated in 2H.B. 2H.A only validates the resulting strings via membership.
- 2H.C — paper execution ledger composition root (LATER): pure binder `build_paper_execution_ledger_recorder(*, now_ms_clock: Callable[[], int]) -> PaperExecutionLedgerRecorder` that captures static configuration at build time and returns a single-call recorder that adapts the 2H.B service.

The 2H.A scope cap is intentional: the value-object layer ONLY validates self-consistency. It does NOT compute paper-ledger entries. It does NOT import the risk_gateway domain at the value-object layer. The input risk action and reason are propagated as plain strings and validated by membership in frozensets. 2H.B service-layer composition consumes the risk_gateway domain. The new lineage ID `paper_trade_id` is introduced at the value-object layer; 2H.B owns its derivation from `risk_decision_id`.

## Lane lock compliance (REQ_0018 / REQ_0020)
- lane: paper_backtest_mvp
- mvp_relevance: opens REQ_0017 milestone 4 PAPER_EXECUTION_LEDGER_MVP by authoring the value-object surface that the 2H.B mirror-recording assembler service and 2H.C composition root will consume. Without this domain, the paper execution ledger cannot produce a typed mirror entry and downstream REPLAY_BACKTEST_RUNNER_MVP, PAPER_MODE_MVP, and SHADOW_MODE_READINESS milestones cannot consume a canonical paper-trade lineage.
- blocked_by: PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS (satisfied at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/25_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`).
- next_gate: PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_IMPL_AND_VALIDATION_PASSED (emitted by task 133 via `07_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_GO_NO_GO.md`).
- legacy_evidence_consulted: read-only review captured in `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/01_PHASE_2H_LEGACY_EVIDENCE_REVIEW.md`. Reads: `claude_worklog/legacy_runtime_audit/00_AUDIT_SCOPE_AND_SAFETY.md`, `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`, `11_FAILURE_MODE_AND_GAP_REGISTER.md`, `12_LEGACY_AUDIT_GO_NO_GO.md`. Directory listing of `legacy_reference/` for naming evidence only. The pre-existing `v2/backend/app/services/paper_loop.py` placeholder string and the empty `v2/backend/app/services/paper_execution/`-style directories (none currently present) are read-only and NOT modified by 2H.A. The existing empty `v2/backend/app/domain/execution/` directory is NOT reused.
- legacy_failure_addressed: legacy paper-side execution had no typed mirror of risk decisions, no `paper_trade_id` lineage, and no machine-checked invariant that paper actions never escape into a live order path. The 2H.A value-object pins this at the type level: `live_blocked` MUST be `True` for every constructed entry, ledger-action `record_allow` MUST be paired with a `mirror_allow_*` reason, ledger-action `record_deny` MUST be paired with a `mirror_deny_*` reason, and the cross-field rules tie every mirror reason back to the upstream risk-action / risk-reason pair so a paper entry cannot silently drift from the risk decision it was supposed to mirror. Building the typed surface first (before the assembler service) eliminates the class of legacy bugs where a paper-side recorder could record an "allow" without a corresponding upstream allow chain or could omit the live-blocked flag.

## Sub-phase staging
- 2H.A — Implementation task `133_paper_execution_ledger_2ha_domain_implementation`. Emits `06_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_IMPLEMENTATION_REPORT.md` and `07_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_GO_NO_GO.md`. Predecessor marker `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS`. Implementation gate `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- 2H.A Codex review task — opened on 2H.A IMPL PASS as task `134_paper_execution_ledger_2ha_domain_codex_review` (NOT emitted in this turn; emitted only after 133 PASS).
- 2H.B and 2H.C — opened only after 2H.A and 2H.B Codex passes respectively. Specs are NOT pre-staged.

## Worktree at the start of this turn
`git status --porcelain` reports exactly two entries:
- ` M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` — durable insertion-only Claude Code Max 20x consolidated profile, Codex Pro parallel lane policy, and REQ_0018 / REQ_0020 planner lane-lock additions.
- `?? claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2g_c_risk_gateway_composition_root_codex_pass.json` — durable Lane C codex_watchdog parallel read-only review task definition for the just-closed 2G.C milestone.

No live behavior. No Redis writes. No legacy mutation. No exchange action. No leverage / margin change. No deployment. No production migration. No secrets.

Per commit `963ea89 Keep planner prompt noise out of child dispatch worktrees`, both dirty entries are excluded from child dispatch worktrees by the supervisor's worktree-isolation contract. Task 133's `requires_clean_worktree = true` is therefore honored against the dispatch worktree, not the planner worktree, and the dirty planner artifacts do NOT block dispatch.

## Hard scope cap (REQ_0017 milestone 4)
Phase 2H as a whole MUST NOT add any of the following:
- a paper trader process, scheduler, or background loop
- a replay runner or backtest runner (deferred to REQ_0017 milestone 5)
- PnL computation, position sizing, quantity, price, fees, or slippage modeling
- ledger persistence (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis)
- Redis read or write at any layer
- model-loading, GPU runner, or checkpoint subsystem
- FastAPI lifespan, dependency, router, or background task
- adapter expansion (no new `v2/backend/app/adapters/*` member; no edit to existing adapter)
- live trading enablement
- legacy mutation
- secret exposure

Phase 2H.A specifically MUST NOT add any of the following:
- a service-layer assembler (deferred to 2H.B)
- a composition-root binder (deferred to 2H.C)
- any function that derives a paper-ledger entry (the 2H.A surface is value-object only)
- any import of `v2.backend.app.domain.risk_gateway` (the input risk action and reason are validated as plain strings via membership in frozensets; the risk_gateway domain is consumed at the 2H.B service layer)
- any wall-clock helper invocation
- any module-level singleton, cache, or lock
- any subprocess call outside the permitted import-isolation test files
- construction of any `PaperExecutionLedgerEntry` with `live_blocked == False`

## Output policy
This planner turn emits exactly the following blocks: this planner turn document, the 2H sub-phase breakdown, the 2H legacy evidence review, the 2H.A spec, the 2H.A test plan, the 2H.A safety boundaries, the 2H.A GO/NO-GO request, and the task 133 definition. No prior-milestone artifact is modified. No supervisor task definition under 117..132 is modified. No 2G artifact is modified. No master planner prompt edit. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live trading enablement. The body of every authored document MUST NOT contain a standalone harness framing token marker line.
