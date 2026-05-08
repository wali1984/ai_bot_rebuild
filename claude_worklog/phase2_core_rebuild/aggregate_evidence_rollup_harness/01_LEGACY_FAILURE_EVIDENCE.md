# Phase 2Q — Legacy Failure Evidence Consulted

## Read-only legacy evidence consulted

The Phase 2Q aggregate-evidence roll-up harness is a typed-mirror aggregation over the typed-record outputs of Phase 2N (paper-mode evidence-collection harness), Phase 2O (shadow-mode evidence-collection harness), and Phase 2P (historical-PnL replay wiring). No legacy file is mutated. No `/home/wali/Desktop/AI BOT` source file is opened, read, or modified. No Redis key is read or written. No live service is restarted. No Binance read-only account-history endpoint is called at Phase 2Q.

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
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`.
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`.
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`.
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/03_LEGACY_EVIDENCE_AND_FAILURE_MAPPING.md`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/04_SAFETY_BOUNDARIES_AND_LIVE_GATE_POSTURE.md`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md`.
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/07_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/07_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/07_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`.
- `claude_worklog/requirements_inbox/REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md`.
- `claude_worklog/requirements_inbox/REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md`.
- `claude_worklog/requirements_inbox/REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md`.
- `claude_worklog/requirements_inbox/REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md`.
- `claude_worklog/requirements_inbox/REQ_0023_FULL_LEGACY_READONLY_AUDIT_SENTINEL.md`.
- `claude_worklog/requirements_inbox/REQ_0024_HISTORICAL_PNL_TRADE_TRAINER_AUDIT.md`.

## Legacy behavior preserved

The legacy bot operated without a typed cross-source aggregate roll-up of paper-mode, shadow-mode, and historical-PnL evidence. Realized-trade and decision evidence was scattered across legacy logs, the legacy account-history record set, and assorted monitor scripts, with no parallel typed projection that aggregates per-source / per-scenario / per-symbol counts of typed `(input_risk_action, input_risk_reason)` distributions, no offline-inspectable per-source typed roll-up record, and no paper-mode-gated typed harness producing typed cross-source summary records. There was no deterministic, pure-function offline aggregation harness that could read a sequence of typed source-record packs (mirroring the typed-record outputs of Phase 2N / 2O / 2P) and produce per-source and cross-source typed roll-up records keyed against the existing typed surfaces (`PaperModeFlag`, `RiskDecisionRecord`). Phase 2Q preserves the legacy runtime by NOT mutating it; the legacy bot, the legacy ingestors, the legacy trainer, the legacy orchestrator, the legacy trader, the legacy Redis keyspace, the legacy startup script, and the legacy account-history record set are not touched in any way at Phase 2Q.

## Legacy failure addressed

Phase 2Q records the legacy aggregate-evidence-projection gap as the fifth post-consolidation Lane A typed mirror evidence-collection artifact (after Phase 2M LAB hedge-unwind / squeeze replay-case authoring, Phase 2N paper-mode evidence-collection harness, Phase 2O shadow-mode evidence-collection harness, and Phase 2P historical-PnL replay wiring). The harness does NOT introduce an aggregation strategy, an aggregation trader process, an aggregation background loop, an aggregation scheduler, an aggregation FastAPI surface, an aggregation Redis adapter, an aggregation persistence layer, an aggregation GPU runner, or any Binance read-only API client. The harness records a pure-function projection of three deterministic typed source-record packs (mirroring the structure of typed records produced by Phase 2N / 2O / 2P) into typed per-source roll-up records and a single typed cross-source summary record. The summary record is consumable offline by subsequent decision-explainability UI milestones (Lane B) as a real backend contract per REQ_0009 § "Required UI visibility" and REQ_0018 lane B (no fake reasoning, real lineage IDs only).

The richer aggregation work (per-day / per-symbol / per-side realized-PnL bucket aggregation, fees / funding / commission aggregation, per-confidence-bucket performance comparison, drawdown / loss-streak aggregation, win/loss-by-feature-regime aggregation, bad-trade-avoided counter against legacy realized trades, legacy-trainer-decision-evidence join) belongs to separate, later milestones explicitly out of scope at Phase 2Q. The LAB hedge-unwind / squeeze loser-trade evidence is included at Phase 2Q only as a deterministic typed pointer-presence count (the per-source `lab_pointer_presence_count` field of `AggregateRollupPerSourceRecord`) keyed against the LAB-tagged input rows; Phase 2Q does NOT introduce a hedge / residual-exposure / squeeze-risk model.

## Hard safety boundary statement

No file under `/home/wali/Desktop/AI BOT` is opened, read, or modified at Phase 2Q. No Redis key is read or written. No live service is restarted. No exchange order is placed or cancelled. No leverage or margin is changed. No live trading is enabled. No deployment is performed. No production migration is run. No secret value is read, printed, or committed. No Binance read-only API call is made at Phase 2Q. The live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` is not flipped or substituted by Phase 2Q.

PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_LEGACY_FAILURE_EVIDENCE_READY
END_FILE: claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/01_LEGACY_FAILURE_EVIDENCE.md
