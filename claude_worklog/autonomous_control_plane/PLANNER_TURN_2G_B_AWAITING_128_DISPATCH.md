# PLANNER TURN 2G.B — AWAITING 128 RISK GATEWAY ASSEMBLER SERVICE DISPATCH

## Active requirement and intersection

- REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md — umbrella for the V2 service-layer rebuild including the risk gateway.
- REQ_0017 — Force paper / backtest MVP track. Active MVP milestone in flight is `RISK_GATEWAY_DEFAULT_DENY_MVP` (Phase 2G).
- REQ_0018 / REQ_0020 — Lane lock enforced. This turn lane is `codex_watchdog` (Lane C, observation/reconciliation only).
- REQ_0007 / REQ_0011 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0021 — Codex non-live human-replacement watchdog and parallel capacity scheduler.

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 6 milestones remaining. The MVP milestone after `RISK_GATEWAY_DEFAULT_DENY_MVP` is `PAPER_EXECUTION_LEDGER_MVP`.

## Active MVP target

`V2_BACKTEST_AND_PAPER_MVP_READY`.

## Active MVP milestone

`RISK_GATEWAY_DEFAULT_DENY_MVP` (Phase 2G).

## Sub-phase state at turn open

- Phase 2G.A risk gateway domain: PASSED. `claude_worklog/phase2_core_rebuild/risk_gateway_impl/09_2G_A_RISK_GATEWAY_DOMAIN_CODEX_GO_NO_GO.md` records exactly `PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS`. The 2G.A domain value-object surface is closed.
- Phase 2G.B risk gateway assembler service: implementation queued. `claude_worklog/agent_supervisor/tasks/128_risk_gateway_2gb_assembler_service_implementation.json` is `pending`, with `predecessor_required_marker = PHASE2G_A_RISK_GATEWAY_DOMAIN_CODEX_PASS` already satisfied at file 09, `requires_clean_worktree = true`, allowed output prefixes scoped to `v2/backend/app/services/risk_gateway/`, `v2/backend/tests/unit/services/risk_gateway/`, and `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`, and `allowed_deletion_paths = [v2/backend/app/services/risk_gateway.py]` for the placeholder removal. The 2G.B Codex review task `129_risk_gateway_2gb_assembler_service_codex_review.json` is also `pending`, gated by `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at file `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`. `codex_recover_128_risk_gateway_2gb_assembler_service_implementation.json` is `pending` as a Codex watchdog wrapper for non-live recovery if 128 stalls.
- Phase 2G.C risk gateway composition root: not opened. Will open under a fresh consolidated milestone turn only after 129 emits `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` at file 17.

## Pending tasks already on disk

- `128_risk_gateway_2gb_assembler_service_implementation.json` — Codex agent, L1, dispatch-ready as soon as the worktree is clean. The 2G.A predecessor PASS marker already exists.
- `129_risk_gateway_2gb_assembler_service_codex_review.json` — Codex agent, L1, gated by 128 PASS at file 15. Will dispatch automatically on the chain.
- `codex_recover_128_risk_gateway_2gb_assembler_service_implementation.json` — Codex watchdog wrapper. Triggered by the supervisor only if 128 stalls or fails non-safety blockers; not separately dispatched.

## Dirty worktree at the start of this turn

`git status --porcelain` reports exactly one dirty path: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. The supervisor's worktree-isolation contract excludes the planner-prompt path from dispatch worktrees, so dispatched tasks see a clean tree. The added planner-prompt content remains durable instructions only — Claude Code Max 20x consolidated profile, Codex Pro parallel lane policy, REQ_0018 / REQ_0020 lane lock policy, and REQ_0006 / REQ_0017 / REQ_0019 / REQ_0020 / REQ_0021 guidance text. No live behavior. No Redis writes. No legacy mutation. No exchange action. No leverage / margin change. No deployment. No production migration. No secrets.

## Decision

No new task is generated this turn. The 2G.B dispatch chain is correct and complete:

1. `128_risk_gateway_2gb_assembler_service_implementation` → emits `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`.
2. `129_risk_gateway_2gb_assembler_service_codex_review` → emits `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` at `17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
3. `codex_recover_128_*` runs only on stall.

Re-emitting a duplicate 128 / 129 / codex_recover_128 task definition would create conflicting allowed_output_prefixes, fight on the same scope, and not advance any approved lane. Opening Phase 2G.C now would violate the dependency ordering (`PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS` is the gate). Authoring any additional `risk_gateway_impl/` file 14, 15, 16, or 17 from this planner turn would race task 128 / 129 on identical paths.

This is therefore a Lane C `codex_watchdog` observation turn that records "no new decision; awaiting 128 dispatch" so the dashboard, queue, and current_status reconcile cleanly against the on-disk task definitions.

## Lane lock compliance (REQ_0018 / REQ_0020)

- `lane`: `codex_watchdog`.
- `mvp_relevance`: confirms the existing 128 → 129 → 2G.C dispatch chain that closes Phase 2G.B and advances `RISK_GATEWAY_DEFAULT_DENY_MVP` toward `V2_BACKTEST_AND_PAPER_MVP_READY`. Does not open new scope.
- `blocked_by`: dispatch tick on `128_risk_gateway_2gb_assembler_service_implementation` (waiting for the supervisor to pick up the pending task on a clean dispatch worktree).
- `next_gate`: `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md`.
- `legacy_evidence_consulted`: `git status --porcelain`, `git log --oneline -20`, presence of the 2G.A CODEX PASS marker at file 09, presence of 128 / 129 / codex_recover_128 task definitions on disk, the 2G.B fixed rubric in file 13 (38 rows) and the safety boundaries in file 12, the 2F.C composition root pass marker upstream of 2G, the legacy signal-to-execution audit stub `09_legacy_signal_to_execution_audit_stub.md` of `legacy_runtime_audit/`, and the legacy failure / gap register `11_legacy_failure_and_gap_register.md` of `legacy_runtime_audit/`.
- `legacy_failure_addressed`: planner-loop noise where the planner repeatedly re-emits a queued task that already exists, producing duplicate task IDs, conflicting allowed_output_prefixes, and dispatch confusion. Under the legacy bot this surfaced as repeat dispatch holds and operator fatigue; this turn explicitly refuses the duplicate emission and records the await state instead.

## What this turn deliberately does NOT do

- Does NOT modify the dirty planner prompt content — this turn is the planner-self turn and the prompt edit is durable instructions only; the supervisor excludes the prompt path from dispatch worktrees.
- Does NOT re-emit task `128_risk_gateway_2gb_assembler_service_implementation` — already pending on disk.
- Does NOT re-emit task `129_risk_gateway_2gb_assembler_service_codex_review` — already pending on disk.
- Does NOT re-emit `codex_recover_128_risk_gateway_2gb_assembler_service_implementation` — already pending on disk.
- Does NOT author any V2 source under `v2/backend/app/services/risk_gateway/`.
- Does NOT author any V2 test under `v2/backend/tests/unit/services/risk_gateway/`.
- Does NOT author files 14, 15, 16, or 17 under `claude_worklog/phase2_core_rebuild/risk_gateway_impl/` — those are owned by tasks 128 (14, 15) and 129 (16, 17).
- Does NOT delete the placeholder `v2/backend/app/services/risk_gateway.py` — that is owned by task 128 via `allowed_deletion_paths`.
- Does NOT open Phase 2G.C composition-root work — that gate opens only after `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`.
- Does NOT open a parallel Lane B explainability_ui task — Phase 2G.B does not yet emit a real `risk_decision_id` lineage contract that the explainability UI can hang off, so any Lane B task today would violate the "real data contracts only" rule.
- Does NOT open a parallel Lane D legacy_parity task — the in-flight legacy_parity work is unchanged by this turn.
- Does NOT touch `/home/wali/Desktop/AI BOT`.
- Does NOT touch Redis, exchange, leverage, margin, deploy, secrets, or live trading.

## Dispatch chain (unchanged)

1. Supervisor pre-dispatch tick selects `128_risk_gateway_2gb_assembler_service_implementation` from the pending queue. Dispatch worktree excludes the dirty planner-prompt path, so the dispatch worktree is clean. Codex authors `v2/backend/app/services/risk_gateway/__init__.py`, `errors.py`, `service.py`, the 29 sibling test files plus the zero-byte `v2/backend/tests/unit/services/risk_gateway/__init__.py`, `claude_worklog/phase2_core_rebuild/risk_gateway_impl/14_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPLEMENTATION_REPORT.md`, and `15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md` carrying `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`. The placeholder `v2/backend/app/services/risk_gateway.py` is deleted under `allowed_deletion_paths`.
2. Supervisor pre-dispatch tick selects `129_risk_gateway_2gb_assembler_service_codex_review` once the predecessor marker at file 15 is observed and the worktree is clean. Codex emits `claude_worklog/phase2_core_rebuild/risk_gateway_impl/16_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_REVIEW.md` and `17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`.
3. On `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`, the next planner turn opens consolidated Phase 2G.C composition root work. The 2G.C task authors only the composition-root binder for the 2G.B assembler service — no execution-side surface, no paper executor, no shadow executor, no Redis adapter, no FastAPI surface.
4. On 129 FAIL with concrete code/test blockers and no safety violation, dispatch a REQ_0007 / REQ_0014 autofix task scoped only to the three authored 2G.B source files plus the 29 new test files, and re-run the implementation flow. On any safety violation, surface to human attention; no autofix permitted.
5. Close `RISK_GATEWAY_DEFAULT_DENY_MVP` on completion of 2G.C and open `PAPER_EXECUTION_LEDGER_MVP` (Phase 2H) as the next MVP milestone.

## Codex parallel-lane utilization (REQ_0021)

- Claude lane: idle for builder work this turn; planner-self only emits this observation document.
- Codex review lane: may read-only review committed 2G.A artifacts (`02..09` of `risk_gateway_impl/`) and the in-flight 2G.B request artifacts (`10..13`) without authoring under any forbidden output prefix. No race with task 128.
- Codex autofix lane: idle until task 128 / 129 emit a concrete blocker.
- Codex watchdog lane: this turn is the watchdog observation. The next watchdog action is automatic — supervisor pre-dispatch will pick up `128` whenever its `requires_clean_worktree` predicate holds against its dispatch worktree.

This honors REQ_0021 ("Codex should not sit at 2-3% utilization while non-live work remains") without violating REQ_0011's "Codex must not run a milestone's required review before that milestone's local validation marker passes" — Codex parallel review here is on already-committed 2G.A artifacts only.

## Safety boundaries (hard stops)

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

## Output policy

This planner turn emits exactly one BEGIN_FILE / END_FILE block: this turn document. No new task definitions. No V2 source / test files. No `risk_gateway_impl/` files 14, 15, 16, or 17. No standalone harness framing tokens in any authored body.

PLANNER_TURN_2G_B_AWAITING_128_DISPATCH_READY

Planner turn observation only — queue is correct, no new tasks emitted, no V2 source/test edits, no rubric-file edits. Awaiting supervisor dispatch on task 128 (clean dispatch worktree available; planner-prompt path is excluded from worktrees).
