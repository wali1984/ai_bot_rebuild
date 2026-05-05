# Planner Turn — Open Phase 2F.A Orchestrator Decision Domain

Date: 2026-05-05
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0019_LEGACY_MONITOR_AUDIT_EVIDENCE_IN_BUILD.md
Lane: paper_backtest_mvp
Profile: Claude Code Max20 consolidated_default
Granularity: consolidated milestone task per sub-phase
Live gate: blocked

## Predecessor closure evidence

`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/205_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` contains exactly `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS`. Recent commits `9121650`, `cb60ca2`, `e50f135` confirm the 2E3.C composition root closure is committed. Per `178_PHASE_2E3_SUB_PHASE_BREAKDOWN.md` "Phase exit (closing Phase 2E3 → opening REQ_0017 Milestone 2)", REQ_0017 milestone 1 `TRAINER_PREDICTION_OUTPUT_MVP` is satisfied. The planner now opens REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP`.

The trainer prediction output Stage A contract is now consumable by the next milestone via `from v2.backend.app.composition.trainer_prediction_output import build_trainer_prediction_output_evaluator, TrainerPredictionOutputEvaluator, TrainerPredictionOutputCompositionError` returning a single-call evaluator that emits a frozen `TrainerPredictionRecord` with `prediction_id`, `feature_snapshot_id`, `symbol`, `model_version`, `checkpoint_id`, `prediction_ts_ms`, `direction`, `confidence_raw`, `confidence_calibrated`, `worker_id`, `worker_health_status`, `freshness_flag`, `source_freshness_age_ms`, `top_positive_feature_codes`, `top_negative_feature_codes`.

## Lane lock confirmation

REQ_0018 lane lock for this turn:

- `lane`: `paper_backtest_mvp`
- `mvp_relevance`: 2F.A opens the orchestrator decision domain layer that the orchestrator decision service (2F.B) and composition root (2F.C) will consume. The frozen `OrchestratorDecisionRecord` value object emits `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `decision_ts_ms`, `decision_action`, `decision_reason_code`, and the input prediction lineage fields needed by `RISK_GATEWAY_DEFAULT_DENY_MVP` (next milestone) without any redis, fastapi, or wall-clock helper boundary crossing. This is the smallest concrete advance toward `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `next_gate`: `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS`
- `blocked_by`: `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS` (already materialized in 205).

No Lane B / Lane C / Lane D work is opened in this turn.

## Dirty-tree dispatch hold

`git status --short` reports a single dirty file: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. This file is the planner-prompt path managed by the harness operator. The planner does NOT modify that file in this turn. The Codex watchdog under REQ_0014 / REQ_0016 / REQ_0007 owns reconciliation of harness-managed planner-prompt dirty state when no active Claude/Codex child is running. Task `117_orchestrator_decision_2fa_domain_implementation` carries `requires_clean_worktree: true` so dispatch will wait for clean tree; the planner does not advance dispatch in this turn.

## REQ_0017 scope discipline

REQ_0017 forbids broad infrastructure expansion that does not advance the backtest/paper MVP path. 2F.A is constrained to value-object validation only:

- No FastAPI surface.
- No redis access at any layer.
- No service-layer assembly.
- No composition-root binder.
- No subprocess, no socket, no os.environ, no wall-clock helper.
- No risk-gateway logic. Risk default-deny is `RISK_GATEWAY_DEFAULT_DENY_MVP` (REQ_0017 milestone 3).
- No execution-side surface. Paper ledger is `PAPER_EXECUTION_LEDGER_MVP` (REQ_0017 milestone 4).
- No model evaluation. The trainer prediction output Stage A contract is the only authoritative input source.
- The decision record is not assembled in this milestone; the assembler service is `2F.B` (later turn).

## Module location decision

The new package is `v2/backend/app/domain/orchestrator_decision/`. It is a sibling of `v2/backend/app/domain/trainer_liveness/`, `v2/backend/app/domain/trainer_worker_health/`, `v2/backend/app/domain/trainer_parity/`, `v2/backend/app/domain/trainer_prediction_output/`. It does NOT modify the existing empty `v2/backend/app/domain/decisions/` placeholder.

A naming-collision risk exists at the services layer: `v2/backend/app/services/orchestrator_decision.py` is a single-line placeholder string. This collision is OUT of scope for 2F.A (which is domain-only) and is documented in the 2F sub-phase breakdown as a known concern to be resolved at the start of 2F.B (services layer) by the supervisor. 2F.A does NOT touch the services placeholder.

## Legacy evidence anchor

Per REQ_0019, the legacy runtime audits at `claude_worklog/legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md` and `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` are read-only stubs ("Read-only posture captured. No service restart executed.") with no concrete prior-art to mine. The orchestrator decision domain is therefore designed strictly from REQ_0009 explainability lineage requirements (decision_id, prediction_id, feature_snapshot_id), REQ_0017 default-deny safety posture (live_blocked must be true), and the already-validated `TrainerPredictionRecord` contract. No legacy decision file is mutated. `01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md` documents this read.

## Consolidated tasks emitted this turn

- `claude_worklog/agent_supervisor/tasks/117_orchestrator_decision_2fa_domain_implementation.json`
- `claude_worklog/agent_supervisor/tasks/118_orchestrator_decision_2fa_domain_codex_review.json`

The planner stays consolidated; no per-test microsplit. Implementation, tests, and impl/GO-NO-GO reports land in a single dispatch.

## Authoring artifacts emitted this turn

- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/00_PHASE_2F_SUB_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/02_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SPEC.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/03_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/04_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/05_PHASE_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO_REQUEST.md`

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

## Next milestone after 2F.A closes

When `PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_CODEX_PASS` is materialized, the planner opens 2F.B (orchestrator decision assembler service) under a fresh consolidated turn. After 2F.C composition root closes, REQ_0017 milestone 2 `ORCHESTRATOR_DECISION_MVP` is satisfied and milestone 3 `RISK_GATEWAY_DEFAULT_DENY_MVP` opens.

PLANNER_TURN_2F_A_OPEN_ORCHESTRATOR_DECISION_DOMAIN_READY
