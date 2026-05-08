# Phase 2P — Legacy Failure Evidence Consulted

## Read-only legacy evidence consulted

The Phase 2P historical-PnL replay wiring is a typed-mirror replay of legacy historical-trade evidence gaps observed across the legacy runtime audit packets and the REQ_0024 historical-PnL audit scope. No legacy file is mutated. No `/home/wali/Desktop/AI BOT` source file is opened, read, or modified. No Redis key is read or written. No live service is restarted. No Binance read-only account-history endpoint is called at Phase 2P.

Evidence pointers (read-only):

- `claude_worklog/legacy_runtime_audit/00_AUDIT_INDEX.md`.
- `claude_worklog/legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md`.
- `claude_worklog/legacy_runtime_audit/04_TRADER_RUNTIME_AUDIT.md`.
- `claude_worklog/legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md`.
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`.
- `claude_worklog/legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`.
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`.
- `claude_worklog/legacy_readonly_audit/00_AUDIT_INDEX.md`.
- `claude_worklog/legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md`.
- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`.
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`.
- `claude_worklog/historical_pnl_audit/00_AUDIT_INDEX.md`.
- `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md`.
- `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md`.
- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md`.
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md`.
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md`.
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`.
- `claude_worklog/historical_pnl_audit/07_LEGACY_TRAINER_DECISION_EVIDENCE.md`.
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`.
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`.
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/03_LEGACY_EVIDENCE_AND_FAILURE_MAPPING.md`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/04_SAFETY_BOUNDARIES_AND_LIVE_GATE_POSTURE.md`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md`.
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/requirements_inbox/REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md`.
- `claude_worklog/requirements_inbox/REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md`.
- `claude_worklog/requirements_inbox/REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md`.
- `claude_worklog/requirements_inbox/REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md`.
- `claude_worklog/requirements_inbox/REQ_0023_FULL_LEGACY_READONLY_AUDIT_SENTINEL.md`.
- `claude_worklog/requirements_inbox/REQ_0024_HISTORICAL_PNL_TRADE_TRAINER_AUDIT.md`.

## Legacy behavior preserved

The legacy bot operated without a typed historical-PnL replay-wiring evidence layer: legacy realized trades (per-day, per-symbol, per-side) were recorded only in legacy logs and the legacy account-history record set, with no parallel typed projection of `(legacy_realized_trade_evidence_pointer, V2 typed PaperExecutionLedgerEntry)` per-trade comparison rows, no offline-inspectable per-trade typed mirror trio, and no paper-mode-gated typed harness driving the existing `PaperModeRuntime` and `PaperExecutionLedgerRecorder` composition roots end-to-end against historical-trade evidence pointers. There was no deterministic, pure-function offline historical-PnL replay-wiring harness that could replay a sequence of typed historical-PnL evidence inputs through the typed paper-execution-ledger composition root, gated on the typed paper-mode flag, and produce per-step typed comparison records keyed against read-only historical-trade evidence pointers under `claude_worklog/historical_pnl_audit/`. Phase 2P preserves the legacy runtime by NOT mutating it; the legacy bot, the legacy ingestors, the legacy trainer, the legacy orchestrator, the legacy trader, the legacy Redis keyspace, the legacy startup script, and the legacy account-history record set are not touched in any way at Phase 2P.

## Legacy failure addressed

Phase 2P records the legacy historical-PnL evidence-projection gap as the fourth post-consolidation Lane A typed mirror evidence-collection artifact (after Phase 2M LAB hedge-unwind / squeeze replay-case authoring, Phase 2N paper-mode evidence-collection harness, and Phase 2O shadow-mode evidence-collection harness). The harness does NOT introduce a historical-PnL strategy, a historical-PnL trader process, a historical-PnL background loop, a historical-PnL scheduler, a historical-PnL FastAPI surface, a historical-PnL Redis adapter, a historical-PnL GPU runner, a historical-PnL model-loading subsystem, or any Binance read-only API client. The harness records a pure-function projection of a deterministic typed historical-PnL evidence pack across the existing `PaperModeRuntime` and `PaperExecutionLedgerRecorder` composition roots; the projection produces typed comparison rows (`PaperModeFlag`, per-step `(legacy_realized_trade_evidence_pointer, PaperExecutionLedgerEntry)` pairs) that subsequent Binance read-only-pull milestones, decision-explainability UI milestones, and risk-gateway-extension milestones can read offline as a regression baseline.

The richer historical-PnL audit work (a live Binance read-only account-history pull per REQ_0024 § "Binance Read-Only Policy", multi-scenario per-trade PnL aggregation, per-day / per-symbol / per-side realized-PnL bucket aggregation, fees / funding / commission aggregation, large-winner / large-loser bucket aggregation, per-confidence-bucket performance comparison, legacy-trainer-decision-evidence join, account-balance snapshot collection) belongs to separate, later milestones explicitly out of scope at Phase 2P. The LAB hedge-unwind / squeeze loser-trade scenario is included at Phase 2P only as a deterministic typed pointer to the legacy-failure evidence already mapped under `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/`; Phase 2P does not introduce a hedge / residual-exposure / squeeze-risk model.

## Hard safety boundary statement

No file under `/home/wali/Desktop/AI BOT` is opened, read, or modified at Phase 2P. No Redis key is read or written. No live service is restarted. No exchange order is placed or cancelled. No leverage or margin is changed. No live trading is enabled. No deployment is performed. No production migration is run. No secret value is read, printed, or committed. No Binance read-only API call is made at Phase 2P. The live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` is not flipped or substituted by Phase 2P.

PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_LEGACY_FAILURE_EVIDENCE_READY
