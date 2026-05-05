# Planner Turn — Open Phase 2F.B Orchestrator Decision Assembler Service

Date: 2026-05-05
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0019_LEGACY_MONITOR_AUDIT_EVIDENCE_IN_BUILD.md ∩ REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md
Lane: paper_backtest_mvp
Profile: Claude Code Max20 consolidated_default
Granularity: consolidated milestone task per sub-phase
Live gate: blocked

## Predecessor closure evidence

`claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/09_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_GO_NO_GO.md` contains exactly `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS`. Companion `07_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO.md` contains exactly `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPL_AND_VALIDATION_PASSED`. The 2F.A domain layer at `v2/backend/app/domain/orchestrator_decision/` (`__init__.py`, `errors.py`, `record.py`) is materialized with the 35-file test suite under `v2/backend/tests/unit/domain/orchestrator_decision/`. Per `00_PHASE_2F_SUB_PHASE_BREAKDOWN.md` 'Sequencing rule', a Codex PASS at task `118` opens 2F.B in a new consolidated turn.

The 2F.A domain layer is now consumable by the next milestone via `from v2.backend.app.domain.orchestrator_decision import (DECISION_ACTION_*, DECISION_REASON_*, OrchestratorDecisionRecord, OrchestratorDecisionDomainError)`. The frozen `OrchestratorDecisionRecord` value object constrains 12 fields with default-deny invariants: `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `decision_ts_ms`, `decision_action`, `decision_reason_code`, `input_prediction_direction`, `input_prediction_confidence_calibrated`, `input_prediction_freshness_flag`, `input_worker_health_status`, `live_blocked` (must be `True`).

## Lane lock confirmation

REQ_0018 lane lock for this turn:

- `lane`: `paper_backtest_mvp`
- `mvp_relevance`: 2F.B opens the orchestrator decision assembler service that converts a validated `TrainerPredictionRecord` into a frozen `OrchestratorDecisionRecord` under the default-deny taxonomy fixed by 2F.A. This is the second of three Phase 2F sub-phases needed to satisfy REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP`. The pure assembler function `assemble_orchestrator_decision_record(*, prediction, low_confidence_threshold, now_ms_clock)` is the consumable derivation surface for Phase 2F.C (composition root) and REQ_0017 milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP`. This is the smallest concrete advance toward `V2_BACKTEST_AND_PAPER_MVP_READY` after 2F.A.
- `next_gate`: `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS`
- `blocked_by`: `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS` (already materialized in `09_2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_GO_NO_GO.md`).

No Lane B / Lane C / Lane D work is opened in this turn.

## Dirty-tree dispatch hold

`git status --short` reports a single dirty file: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. This file is the planner-prompt path managed by the harness operator. The planner does NOT modify that file in this turn. The Codex watchdog under REQ_0014 / REQ_0016 / REQ_0007 owns reconciliation of harness-managed planner-prompt dirty state when no active Claude/Codex child is running. Task `119_orchestrator_decision_2fb_assembler_service_implementation` carries `requires_clean_worktree: true` so dispatch will wait for clean tree; the planner does not advance dispatch in this turn.

## REQ_0017 scope discipline

REQ_0017 forbids broad infrastructure expansion that does not advance the backtest/paper MVP path. 2F.B is constrained to a pure derivation surface only:

- No FastAPI surface.
- No redis access at any layer.
- No composition-root binder. Composition is `2F.C` (later turn).
- No subprocess (outside the four permitted import-isolation test files), no socket, no os.environ, no wall-clock helper. The clock is injected via the `now_ms_clock` parameter only.
- No risk-gateway logic. Risk default-deny is `RISK_GATEWAY_DEFAULT_DENY_MVP` (REQ_0017 milestone 3).
- No execution-side surface. Paper ledger is `PAPER_EXECUTION_LEDGER_MVP` (REQ_0017 milestone 4).
- No model evaluation. The trainer prediction output Stage A contract is the only authoritative input source via the `prediction: TrainerPredictionRecord` parameter.
- No new lineage ID at the service layer beyond the derived `decision_id = "dec_" + prediction.prediction_id`.

## Module location decision and placeholder deletion

The new package is `v2/backend/app/services/orchestrator_decision/`. It is a sibling of `v2/backend/app/services/trainer_prediction_output/`, `v2/backend/app/services/trainer_worker_health/`, and `v2/backend/app/services/trainer_parity/`.

The pre-existing one-line placeholder file `v2/backend/app/services/orchestrator_decision.py` (whose sole content is the docstring `"""Orchestrator decision service placeholder. No behavior in scaffold."""`) collides with the new package on the import path. Task `119` opens by deleting that placeholder file BEFORE creating the new package. Task `120` Codex review re-runs `git ls-files` against both the placeholder path and the three new package paths and confirms the expected results.

## Legacy evidence anchor

Per REQ_0019 / REQ_0020, the legacy runtime audits at `claude_worklog/legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md` and `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` are read-only stubs ("Read-only posture captured. No service restart executed.") with no concrete prior-art to mine. The orchestrator decision derivation is therefore designed strictly from the 2F.A domain invariants, the trainer prediction output Stage A contract (already validated through `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS`), and the REQ_0017 default-deny ordering posture. The default-deny derivation table fixes the order: freshness_missing → freshness_stale → worker_critical → worker_degraded → worker_unknown → low_confidence → hold_flat → open_long → open_short. The legacy failure addressed is the absence of an explainable abstain surface: legacy decision routing could silently propagate stale or low-confidence inputs into trade-eligible signals. 2F.B fixes that with an explicit abstain-reason taxonomy and a fixed evaluation order.

## Consolidated tasks emitted this turn

- `claude_worklog/agent_supervisor/tasks/119_orchestrator_decision_2fb_assembler_service_implementation.json`
- `claude_worklog/agent_supervisor/tasks/120_orchestrator_decision_2fb_assembler_service_codex_review.json`

The planner stays consolidated; no per-test microsplit. Implementation, tests, placeholder deletion, and impl/GO-NO-GO reports land in a single dispatch.

## Authoring artifacts emitted this turn

- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/10_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/11_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/12_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/13_PHASE_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO_REQUEST.md`

The 2F sub-phase breakdown at `00_PHASE_2F_SUB_PHASE_BREAKDOWN.md` already documents 2F.B at high level; the planner does NOT re-emit `00_*` in this turn.

## Non-live safety

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

## Next milestone after 2F.B closes

When `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS` is materialized, the planner opens 2F.C (orchestrator decision composition root) under a fresh consolidated turn. After 2F.C composition root closes, REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP` is satisfied and milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP` opens.

PLANNER_TURN_2F_B_OPEN_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_READY
