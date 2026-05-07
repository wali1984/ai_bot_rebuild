# Typed Surface Inventory at V2_BACKTEST_AND_PAPER_MVP_READY

The seven REQ_0017 MVP milestones produce typed surfaces in three layers: domain (immutable value objects + error class + typed constants), services (pure assembler functions), and composition (slotted single-call runtime binder + composition error class). All public exports below are verified against the `__init__.py` re-export tuple of the corresponding package at HEAD 550799d.

## Trainer prediction output (REQ_0017 milestone 1)

- `v2/backend/app/domain/trainer_prediction_output/__init__.py` exports:
  - `TrainerPredictionDomainError`
  - `TrainerPredictionRecord`
  - `PREDICTION_DIRECTION_LONG`, `PREDICTION_DIRECTION_SHORT`, `PREDICTION_DIRECTION_FLAT`
  - `PREDICTION_FRESHNESS_FRESH`, `PREDICTION_FRESHNESS_STALE`, `PREDICTION_FRESHNESS_MISSING`
- `v2/backend/app/services/trainer_prediction_output/` exposes the assembler service that produces a frozen `TrainerPredictionRecord` from the raw subprocess-boundary fields plus the typed worker-health surface.
- `v2/backend/app/composition/trainer_prediction_output/__init__.py` exports:
  - `build_trainer_prediction_output_evaluator`
  - `TrainerPredictionOutputEvaluator`
  - `TrainerPredictionOutputCompositionError`

Trainer-side neighboring typed surfaces produced under the same REQ_0017 milestone 1 umbrella:

- `v2/backend/app/domain/trainer_liveness/`, `v2/backend/app/domain/trainer_liveness_observation_collector/`, `v2/backend/app/domain/trainer_liveness_stream_growth/`, `v2/backend/app/domain/trainer_worker_health/` (each with errors / record / `__init__.py`).
- `v2/backend/app/composition/trainer_worker_health/` (worker-health composition root binder).
- `v2/backend/app/composition/trainer_parity/` (subprocess-boundary parity adapter binder).

## Orchestrator decision (REQ_0017 milestone 2)

- `v2/backend/app/domain/orchestrator_decision/__init__.py` exports:
  - `OrchestratorDecisionDomainError`
  - `OrchestratorDecisionRecord`
  - `DECISION_ACTION_OPEN_LONG`, `DECISION_ACTION_OPEN_SHORT`, `DECISION_ACTION_HOLD`, `DECISION_ACTION_ABSTAIN`
  - `DECISION_REASON_PROCEED_LONG`, `DECISION_REASON_PROCEED_SHORT`, `DECISION_REASON_HOLD_FLAT_DIRECTION`
  - `DECISION_REASON_ABSTAIN_LOW_CONFIDENCE`, `DECISION_REASON_ABSTAIN_FRESHNESS_STALE`, `DECISION_REASON_ABSTAIN_FRESHNESS_MISSING`
  - `DECISION_REASON_ABSTAIN_WORKER_DEGRADED`, `DECISION_REASON_ABSTAIN_WORKER_CRITICAL`, `DECISION_REASON_ABSTAIN_WORKER_UNKNOWN`
- `v2/backend/app/services/orchestrator_decision/` exposes the assembler that maps a typed `TrainerPredictionRecord` (plus the typed worker-health surface) to a frozen `OrchestratorDecisionRecord`.
- `v2/backend/app/composition/orchestrator_decision/__init__.py` exports:
  - `build_orchestrator_decision_evaluator`
  - `OrchestratorDecisionEvaluator`
  - `OrchestratorDecisionCompositionError`

## Risk-gateway default-deny (REQ_0017 milestone 3)

- `v2/backend/app/domain/risk_gateway/__init__.py` exports:
  - `RiskGatewayDomainError`
  - `RiskDecisionRecord`
  - `RISK_DECISION_ACTION_ALLOW`, `RISK_DECISION_ACTION_DENY`
  - `RISK_DECISION_REASON_ALLOW_PROCEED_LONG`, `RISK_DECISION_REASON_ALLOW_PROCEED_SHORT`
  - `RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED`, `RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD`, `RISK_DECISION_REASON_DENY_DEFAULT`
- `v2/backend/app/services/risk_gateway/` exposes the assembler that maps a typed `OrchestratorDecisionRecord` to a frozen `RiskDecisionRecord` whose default branch is DENY.
- `v2/backend/app/composition/risk_gateway/__init__.py` exports:
  - `build_risk_decision_evaluator`
  - `RiskDecisionEvaluator`
  - `RiskGatewayCompositionError`

## Paper-execution ledger (REQ_0017 milestone 4)

- `v2/backend/app/domain/paper_execution_ledger/__init__.py` exports:
  - `PaperExecutionLedgerDomainError`
  - `PaperExecutionLedgerEntry`
  - `PAPER_LEDGER_ACTION_RECORD_ALLOW`, `PAPER_LEDGER_ACTION_RECORD_DENY`
  - `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG`, `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT`
  - `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED`, `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD`, `PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT`
- `v2/backend/app/services/paper_execution_ledger/` exposes the assembler that mirrors the upstream `RiskDecisionRecord` into a frozen `PaperExecutionLedgerEntry` (no PnL, no sizing, no fees, no slippage, no persistence).
- `v2/backend/app/composition/paper_execution_ledger/__init__.py` exports:
  - `build_paper_execution_ledger_recorder`
  - `PaperExecutionLedgerRecorder`
  - `PaperExecutionLedgerCompositionError`

## Replay/backtest runner (REQ_0017 milestone 5)

- `v2/backend/app/domain/replay_backtest_runner/__init__.py` exports:
  - `ReplayBacktestRunnerDomainError`
  - `ReplayBacktestRun`
  - `ReplayBacktestStep`
  - `ReplayBacktestSummary`
  - `RUN_MODE_REPLAY`, `RUN_MODE_BACKTEST`
  - `STEP_ACTION_RECORD_ALLOW`, `STEP_ACTION_RECORD_DENY`
  - `STEP_REASON_MIRROR_ALLOW_PROCEED_LONG`, `STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT`
  - `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD`, `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED`, `STEP_REASON_MIRROR_DENY_DEFAULT`
- `v2/backend/app/services/replay_backtest_runner/` exposes the assembler that maps a sequence of typed step inputs to a frozen `ReplayBacktestRun` plus per-step `ReplayBacktestStep` records and a final `ReplayBacktestSummary` (no scheduler, no background loop, no persistence).
- `v2/backend/app/composition/replay_backtest_runner/__init__.py` exports:
  - `build_replay_backtest_runner`
  - `ReplayBacktestRunner`
  - `ReplayBacktestRunnerCompositionError`

## Paper-mode runtime flag (REQ_0017 milestone 6)

- `v2/backend/app/domain/paper_mode/__init__.py` exports:
  - `PaperModeDomainError`
  - `PaperModeFlag` (carries `live_blocked: bool == True` invariant; constructing with `live_blocked == False` raises `PaperModeDomainError`)
  - `PAPER_MODE_PAPER`, `PAPER_MODE_LIVE_BLOCKED`
- `v2/backend/app/services/paper_mode/` exposes the pure-function assembler `assemble_paper_mode_flag` that maps a requested-mode string and a `now_ms_clock` callable to a frozen `PaperModeFlag` (no I/O, no env var reads, no Redis, no FastAPI registration, no log line, no live-execution surface import).
- `v2/backend/app/composition/paper_mode/__init__.py` exports:
  - `build_paper_mode_runtime`
  - `PaperModeRuntime`
  - `PaperModeRuntimeCompositionError`

## Shadow-mode-readiness flag (REQ_0017 milestone 7)

- `v2/backend/app/domain/shadow_mode_readiness/__init__.py` exports:
  - `ShadowModeReadinessDomainError`
  - `ShadowModeReadinessFlag` (carries `live_blocked: bool == True` invariant; constructing with `live_blocked == False` raises `ShadowModeReadinessDomainError`)
  - `SHADOW_MODE_NOT_READY`, `SHADOW_MODE_READY`
- `v2/backend/app/services/shadow_mode_readiness/` exposes the pure-function assembler `assemble_shadow_mode_readiness_flag` (same purity discipline as 2J.B; no shadow-execution surface import; no live-execution surface import; no new lineage ID).
- `v2/backend/app/composition/shadow_mode_readiness/__init__.py` exports:
  - `build_shadow_mode_readiness_runtime`
  - `ShadowModeReadinessRuntime`
  - `ShadowModeReadinessRuntimeCompositionError`

## Surfaces explicitly NOT introduced at this consolidation

- No `v2/backend/app/composition/v2_backtest_and_paper_mvp_ready/` package.
- No `v2/backend/app/services/v2_backtest_and_paper_mvp_ready/` package.
- No `v2/backend/app/domain/v2_backtest_and_paper_mvp_ready/` package.
- No new lineage ID. The lineage IDs that exist at HEAD 550799d are exactly: `feature_snapshot_id`, `prediction_id` (both produced by milestone 1), and the implicit per-record identity carried by `OrchestratorDecisionRecord` / `RiskDecisionRecord` / `PaperExecutionLedgerEntry` / `ReplayBacktestStep` (mirror-row identity sufficient for downstream lineage assembly without a new typed lineage row at this consolidation).
- No `paper_trade_id` row beyond the existing `PaperExecutionLedgerEntry` mirror identity.
- No `shadow_decision_id` row. The `ShadowModeReadinessFlag` is a precondition flag, not a decision row.
- No `execution_intent_id` row.
- No FastAPI surface, router, background loop, scheduler, model-loading subsystem, GPU runner, Redis adapter, exchange adapter, persistence layer.
- No modifications to placeholder files: `v2/backend/app/services/paper_loop.py`, `v2/backend/app/services/replay_runner.py`, `v2/backend/app/domain/replay/`, `v2/backend/app/domain/execution/` remain unchanged.

V2_BACKTEST_AND_PAPER_MVP_READY_TYPED_SURFACE_INVENTORY_READY
END_FILE: claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/02_TYPED_SURFACE_INVENTORY.md
