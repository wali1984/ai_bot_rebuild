# Planner Turn — Phase 2G.B Codex Review Queued

## Active requirement and intersection

- REQ_0006 — Phase 2 implement V2 trainer parity service (umbrella for the V2 service-layer rebuild including the risk gateway).
- REQ_0017 — Force paper / backtest MVP track. Current MVP milestone in flight is `RISK_GATEWAY_DEFAULT_DENY_MVP`.
- REQ_0018 / REQ_0020 — Lane lock enforced. This turn lane is `paper_backtest_mvp` (Lane A).

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 6 milestones remaining. Current MVP milestone target after `RISK_GATEWAY_DEFAULT_DENY_MVP` closes is `PAPER_EXECUTION_LEDGER_MVP`.

## State observed at turn open

- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md` contains exactly `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS`. Phase 2G.A (risk gateway domain value-object surface) is closed.
- `claude_worklog/agent_supervisor/tasks/128_risk_gateway_2gb_assembler_service_implementation.json` exists and is `pending`. It is the consolidated 2G.B implementation task; required outputs include `v2/backend/app/services/risk_gateway/__init__.py`, `errors.py`, `service.py`, the 29 sibling test files plus a zero-byte `__init__.py` under `v2/backend/tests/unit/services/risk_gateway/`, the implementation report `14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`, and the GO/NO-GO marker `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`. The placeholder file `v2/backend/app/services/risk_gateway.py` is listed in `allowed_deletion_paths` and is deleted by task 128.
- `claude_worklog/agent_supervisor/tasks/codex_recover_128_risk_gateway_2gb_assembler_service_implementation.json` is `pending` as a Codex watchdog wrapper for non-live recovery if task 128 stalls.
- The 2G.B Codex review task (`129`) does NOT yet exist in `claude_worklog/agent_supervisor/tasks/`. Task 128 already references it forward as the Codex review task that emits `16_..._CODEX_REVIEW.md` and `17_..._CODEX_GO_NO_GO.md`.
- Working tree is dirty only for the planner-prompt file `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. The supervisor's worktree-isolation contract excludes that path from dispatch worktrees, so dispatched tasks see a clean tree.

## Decision

Emit a single new task definition this turn:

- `claude_worklog/agent_supervisor/tasks/129_risk_gateway_2gb_assembler_service_codex_review.json`

Do NOT emit any 2G.C planning artifact, any new 2G.B artifact 10-15 edit, any v2/ source or test file, any task definition outside 129, or any planner-prompt edit.

Do NOT emit a frontend task. Do NOT emit a broad scaffold task. Do NOT open a parallel Lane B / Lane C / Lane D task in this turn — the explainability/website lane and the codex_watchdog lane already have in-flight artifacts that do not require new dispatch.

Consolidated default granularity is preserved: one Codex review task pairs with one implementation task, no microsplit.

## Rationale

The pair pattern across 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, and 2G.A is impl + Codex review. Phase 2G.B currently has only the impl half. The dispatch bridge cannot transparently chain to the next gate (`PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`) without the Codex review task in the queue. Emitting `129` now closes the chain and lets the supervisor dispatch automatically as soon as task 128 emits `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at file 15.

The Codex review task is gated:

- `predecessor_required_marker = PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`
- `predecessor_required_marker_file = claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`
- `requires_clean_worktree = true`
- `depends_on = [128_risk_gateway_2gb_assembler_service_implementation]`

So `129` cannot dispatch ahead of `128` and cannot dispatch on a dirty tree. This honors the immediate REQ_0006 constraint pattern (Codex review must wait for local validation PASS) and the parallel-Codex lane rule that Codex must not run a milestone's required review before that milestone's local validation marker passes.

The review rubric scope is fixed in `13_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md` (38 rubric rows). The review safety boundary is fixed in `12_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md` (forbidden runtime behaviors, placeholder-deletion verification, cross-isolation paths). Task `129` reuses both verbatim as authoritative read-only inputs.

## Lane lock checklist (REQ_0018 / REQ_0020)

- `lane`: `paper_backtest_mvp`.
- `mvp_relevance`: closes the Codex review gate for the risk gateway assembler service surface, the 2G.B sub-phase of the `RISK_GATEWAY_DEFAULT_DENY_MVP` milestone, the third milestone on the path to `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `blocked_by`: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `next_gate`: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`.
- `legacy_evidence_consulted`: 2G legacy evidence review (01), 2G.A Codex pass marker (09), 2G.B implementation report (14, emitted by task 128), 2F.C orchestrator decision composition root pass marker (the upstream record consumed by 2G.B), legacy signal-to-execution audit stub (09 of legacy_runtime_audit), legacy failure/gap register (11 of legacy_runtime_audit).
- `legacy_failure_addressed`: typed default-deny risk decision derivation surface hardened against legacy-style untyped allow/deny strings, missing risk_decision_id / decision_id / prediction_id / feature_snapshot_id lineage, ad-hoc wall-clock reads, hidden module-level state, redis/url_env/factory imports at construction, FastAPI lifespan registration at the service layer, and 'deny_default' emission for orchestrator-decision inputs.

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
- Final live approval remains human-only and BLOCKED.

## Next planner turn

Wait for `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` at `17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`. On PASS, open Phase 2G.C (risk gateway composition root) under a fresh consolidated milestone turn that authors only the composition-root binder for the 2G.B assembler service, with no execution-side surface, no paper executor, no shadow executor, no Redis adapter, and no FastAPI surface. On FAIL with concrete code/test blockers and no safety violation, dispatch a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2G.B source files plus the 29 new test files only and re-run the implementation flow. On any safety violation, surface to human attention; no autofix permitted.

PLANNER_TURN_2G_B_CODEX_REVIEW_QUEUED_READY
