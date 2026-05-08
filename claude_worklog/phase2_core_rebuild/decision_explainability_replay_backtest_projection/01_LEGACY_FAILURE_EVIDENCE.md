# Phase 2T — Legacy Failure Evidence

## Scope

Phase 2T addresses a single legacy explainability gap: the legacy bot operated without a **typed, deterministic, offline-inspectable per-row replay-backtest-step explainability data contract** and without a **typed per-scenario replay-backtest-summary explainability data contract** that lift the typed `ReplayBacktestStep` and `ReplayBacktestSummary` records into single typed envelope rows carrying mirrored lineage IDs, mirrored step-side and input-side action / reason codes, mirrored step / summary timestamps, mirrored partition counts, mirrored live-blocked flag, and deterministic test-only metadata. Replay evidence in legacy was scattered across:

- ad-hoc monitor scripts (`monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`).
- legacy logs (`live_*.log`, trader / orchestrator / hybrid-trainer process logs).
- legacy Redis stream metadata (read-only key inventory only; no values).
- legacy account-history records (Binance `/fapi/v1/userTrades`, `/fapi/v1/income` — read-only; not invoked at this phase).

There is no parallel typed projection in the legacy system that surfaces a fixed-shape per-row replay-step envelope or a fixed-shape per-scenario replay-summary envelope as offline-inspectable backend contracts that downstream UI panels consume.

## Specific legacy failures referenced

- LAB hedge-unwind / squeeze loser-trade scenario (REQ_0022; replay-case authoring at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/`): legacy did not surface the per-step typed projection that downstream Replay UI would need to explain why a SHORT was held / closed / re-opened around a hedge-close around break-even, and how the residual short responded to subsequent adverse pump.
- Stale signals: legacy did not project per-step staleness flags into a per-row envelope that the UI could pattern-match.
- Repeated loser patterns: legacy did not project a deterministic per-scenario summary envelope that the Replay overlay could use to compare BTC winner / ETH winner / LAB loser / SOL orchestrator-held outcomes side-by-side.

## Phase 2T positioning

Phase 2T is the third post-consolidation Lane B `explainability_ui` milestone, after Phase 2R (decision-explainability data contract) and Phase 2S (paper-ledger-explainability projection). Phase 2T projects the existing typed `ReplayBacktestStep` and `ReplayBacktestSummary` mirror rows into typed envelope rows that the Replay UI panels consume per REQ_0009 § "Required UI visibility" and REQ_0018 lane B (no fake reasoning, real lineage IDs only).

The richer explainability fields (top-positive / top-negative feature contributors, feature-freshness flags, regime context, calibration, model / checkpoint version, confidence delta, position-sizing reason, risk-check ledger, blocked-trade reason, paper / shadow / legacy comparison, full audit timeline) belong to separate, later milestones explicitly out of scope at Phase 2T; their underlying lineage / projection subsystems do not exist at consolidation HEAD.

The LAB hedge-unwind / squeeze loser-trade evidence is included at Phase 2T only as a deterministic typed pointer literal carried on the per-row envelope's `legacy_evidence_pointer` field for the `replay_step_explainability_pack_lab_loser_short` scenario steps; Phase 2T does not introduce a hedge / residual-exposure / squeeze-risk model.

## Read-only legacy evidence consulted

- `claude_worklog/legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/04_TRADER_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md`

## Hard safety

No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No secret exposure. No live-readiness gate flip. No live Binance API call. No file under `v2/backend/app/` modified. No file under `v2/frontend/` modified.

PHASE2T_LEGACY_FAILURE_EVIDENCE_READY
