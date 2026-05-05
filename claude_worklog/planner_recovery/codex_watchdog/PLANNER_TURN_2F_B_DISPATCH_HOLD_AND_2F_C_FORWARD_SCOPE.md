# Planner Turn — Phase 2F.B Dispatch Hold and Phase 2F.C Forward Scope

Date: 2026-05-05
Active requirement set: REQ_0006 ∩ REQ_0007 ∩ REQ_0014 ∩ REQ_0015 ∩ REQ_0016 ∩ REQ_0017 ∩ REQ_0018 ∩ REQ_0019 ∩ REQ_0020
Active MVP milestone: ORCHESTRATOR_DECISION_MVP (REQ_0017 milestone 2)
Lane (this turn): codex_watchdog (observational; no new task emitted)
Forward lane (next turn): paper_backtest_mvp (2F.C composition root)
Profile: Claude Code Max20 consolidated_default
Granularity: no new task this turn
Live gate: blocked

## Worktree state at this turn

`git status --porcelain` reports three dirty entries inside AI BOT REBUILD:

- ` M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` — harness-managed planner prompt absorbing the requirements-inbox snapshot.
- `?? claude_worklog/agent_supervisor/tasks/121_orchestrator_decision_2fb_evidence_reconciliation.json` — staged by the prior planner turn.
- `?? claude_worklog/autonomous_control_plane/PLANNER_TURN_2F_B_EVIDENCE_RECONCILIATION.md` — staged by the prior planner turn.

All three entries are inside allowed AI BOT REBUILD paths. None of them touch `/home/wali/Desktop/AI BOT`. None of them touch Redis. None of them touch a live service. The Codex watchdog under REQ_0014 / REQ_0016 / REQ_0007 commits exactly this dirty-artifact pattern in cycle (most recent example: commit `c6be482 Codex watchdog recover dirty non-live automation artifacts`).

## Why this turn does not re-emit task 121

Task `121_orchestrator_decision_2fb_evidence_reconciliation.json` is already on disk and is byte-correct against the committed 2F.B source/test surface. Its preconditions were verified at emission time:

- `git ls-files v2/backend/app/services/orchestrator_decision.py` → 0 lines.
- `git ls-files v2/backend/app/services/orchestrator_decision/__init__.py` → 1 line.
- `git ls-files v2/backend/app/services/orchestrator_decision/errors.py` → 1 line.
- `git ls-files v2/backend/app/services/orchestrator_decision/service.py` → 1 line.
- `git ls-files v2/backend/tests/unit/services/orchestrator_decision/__init__.py` → 1 line.
- `git ls-files v2/backend/tests/unit/services/orchestrator_decision/ | wc -l` → 37.

Re-emitting the same task this turn would be a no-op overwrite that does not advance dispatch. Task 121 dispatch is gated on `requires_clean_worktree=true`; the gate clears as soon as the watchdog commits the three dirty entries above.

## Why no parallel lane is opened this turn

REQ_0011 / REQ_0018 parallel-lane policy requires a clean worktree before Codex can fork onto a parallel review/autofix lane that does not touch active dirty Claude output. The current dirty tree is exactly the prior planner turn's output plus the harness-managed planner prompt, so any parallel Codex action right now risks racing the watchdog cleanup. Lane A advance is blocked by the same gate. Lane D legacy_parity work would not advance ORCHESTRATOR_DECISION_MVP. Therefore no new task is emitted this turn.

## Forward scope — Phase 2F.C orchestrator decision composition root

Phase 2F.C is the next consolidated milestone after `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS` materializes. It closes Phase 2F and satisfies REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP`.

### Surface

`v2/backend/app/composition/orchestrator_decision/` (new package).

Files (planned):

- `__init__.py` — package marker.
- `errors.py` — composition-layer error type `OrchestratorDecisionCompositionError`.
- `binder.py` — pure binder `build_orchestrator_decision_evaluator(*, low_confidence_threshold: float, now_ms_clock: Callable[[], int]) -> OrchestratorDecisionEvaluator` that captures static configuration at build time and returns a single-call evaluator adapting `assemble_orchestrator_decision_record` from 2F.B.
- `evaluator.py` — frozen `OrchestratorDecisionEvaluator` (dataclass) holding the bound threshold and clock, exposing one method `evaluate(prediction: TrainerPredictionRecord) -> OrchestratorDecisionRecord` that delegates to the 2F.B service.

### Public surface (planned)

- `OrchestratorDecisionCompositionError`
- `OrchestratorDecisionEvaluator`
- `build_orchestrator_decision_evaluator`

### Test surface (planned)

`v2/backend/tests/unit/composition/orchestrator_decision/`:

- `__init__.py`
- `test_binder_returns_evaluator.py`
- `test_binder_keyword_only_params.py`
- `test_binder_rejects_threshold_above_one.py`
- `test_binder_rejects_threshold_below_zero.py`
- `test_binder_rejects_threshold_not_finite.py`
- `test_binder_rejects_threshold_not_float.py`
- `test_binder_rejects_non_callable_clock.py`
- `test_binder_rejects_clock_returning_negative.py`
- `test_binder_rejects_clock_returning_non_int.py`
- `test_evaluator_is_frozen.py`
- `test_evaluator_delegates_to_assemble.py`
- `test_evaluator_threshold_is_captured_at_build.py`
- `test_evaluator_clock_is_captured_at_build.py`
- `test_evaluator_calls_clock_exactly_once_per_evaluate.py`
- `test_evaluator_rejects_prediction_not_record.py`
- `test_evaluator_propagates_input_lineage_fields.py`
- `test_evaluator_does_not_import_redis.py`
- `test_evaluator_does_not_import_url_env.py`
- `test_evaluator_does_not_register_fastapi_lifespan.py`
- `test_composition_forbidden_tokens.py`
- `test_public_surface.py`

### Forbidden surface (carried from 2F.A and 2F.B)

The 2F.C composition layer must not:

- import `redis`, `aioredis`, `hiredis`.
- import `httpx`, `requests`.
- import `fastapi`, `FastAPI`, `uvicorn`.
- import `subprocess`, `socket`.
- read `os.environ` or call `os.getenv`.
- call `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`.
- call `logging` or `print(`.
- reference `url_env`.
- reintroduce `v2/backend/app/services/orchestrator_decision.py` as a file.

### Sequencing

- Predecessor marker: `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS`.
- Implementation gate: `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`.
- Phase 2F exit marker: `PHASE2F_ORCHESTRATOR_DECISION_MVP_CLOSED`.
- Implementation task id (planned): `122_orchestrator_decision_2fc_composition_root_implementation`.
- Codex review task id (planned): `123_orchestrator_decision_2fc_composition_root_codex_review`.

The 2F.C task is NOT emitted in this turn. It is emitted in the planner turn that fires immediately after `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS` materializes in `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/17_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` (or the canonical 2F.B Codex GO/NO-GO marker file produced by task 120).

### Legacy evidence anchors for 2F.C

The 2F.C composition root does not introduce new behavior; it binds existing 2F.B service behavior. The legacy evidence consulted for this scope is:

- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/00_PHASE_2F_SUB_PHASE_BREAKDOWN.md` — explicit 2F.C scope (`build_orchestrator_decision_evaluator` binder).
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md` — Phase 2F legacy evidence anchor.
- `claude_worklog/legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md` — read-only legacy orchestrator audit.
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` — read-only legacy signal-to-execution handoff audit.
- 2F.B authored package under `v2/backend/app/services/orchestrator_decision/` — committed at `c6be482`.

### Legacy failure addressed by 2F.C

Under the legacy bot, orchestrator-side configuration (low-confidence threshold, clock source) was implicit, mutable across runs, and not bound at construction time. The 2F.C composition root captures both at build time inside a frozen evaluator so that downstream consumers cannot silently reconfigure orchestrator decision behavior at call time. This is the V2 proof gate for the legacy "moving threshold" failure mode.

## Dispatch sequence anticipated by this turn

1. Codex watchdog commits the three dirty entries (planner prompt M, task 121, planner-turn doc) in a single `Codex watchdog recover dirty non-live automation artifacts` commit.
2. Worktree clean → supervisor pre-dispatch gate clears for `121_orchestrator_decision_2fb_evidence_reconciliation`.
3. Task 121 runs against the committed tree, re-validates 2F.B, rewrites the four stale marker files, and appends two `EVIDENCE_MARKERS` entries to `claude_worklog/tools/reconcile_evidence_status.py`.
4. On `PHASE2F_B_EVIDENCE_RECONCILIATION_PASSED`, supervisor pre-dispatch gate clears for `120_orchestrator_decision_2fb_assembler_service_codex_review`.
5. On `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS`, the next planner turn fires and emits the consolidated 2F.C composition-root implementation task `122` plus its Codex review task `123`.
6. On `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`, REQ_0017 milestone 2 closes and the planner opens REQ_0017 milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`.

## REQ_0017 / REQ_0018 lane discipline

This turn's observational note is itself in scope of Lane C codex_watchdog (it observes evidence/dispatch state and prepares the next consolidated advance toward `V2_BACKTEST_AND_PAPER_MVP_READY`). The forward 2F.C scope is anticipatory Lane A paper_backtest_mvp scoping; no Lane A task is emitted until the predecessor Codex gate materializes.

No infrastructure expansion. No frontend polish. No new automation framework. No dashboard, no docs-only drift, no scaffold widening.

## REQ_0019 legacy evidence usage

Legacy evidence was consulted (00 sub-phase breakdown, 01 legacy evidence review, 05 / 09 legacy runtime audits). No legacy mutation. No Redis read or write at any layer. No exchange action. No deployment.

## Hard non-live safety

- No `/home/wali/Desktop/AI BOT` mutation.
- No Redis read or write at any layer.
- No live service restart.
- No exchange action.
- No leverage or margin change.
- No live trading enable.
- No deployment.
- No production migration.
- No secret exposure or commit.
- Live gate remains blocked.

## Stop conditions honored

- No L4 / L5 action.
- No legacy mutation.
- No Redis access.
- No service restart.
- No exchange / order / leverage / margin action.
- No deployment / production migration.
- No final live approval requested.

## What this turn does NOT emit

- No new task definition under `claude_worklog/agent_supervisor/tasks/`.
- No new V2 source file under `v2/backend/app/`.
- No new V2 test file under `v2/backend/tests/`.
- No modification of the master planner prompt.
- No modification of any prior 2F.B authored marker file (those are reconciled by task 121, not by the planner).
- No re-emission of `121_orchestrator_decision_2fb_evidence_reconciliation.json` (already on disk).
- No re-emission of `PLANNER_TURN_2F_B_EVIDENCE_RECONCILIATION.md` (already on disk).
- No 2F.C spec, test plan, safety-boundaries, or GO_NO_GO_REQUEST doc (those land in the planner turn that follows the 2F.B Codex pass marker, paired with task 122).

PLANNER_TURN_2F_B_DISPATCH_HOLD_AND_2F_C_FORWARD_SCOPE_READY
