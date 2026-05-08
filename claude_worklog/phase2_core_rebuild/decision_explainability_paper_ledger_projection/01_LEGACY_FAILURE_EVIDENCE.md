# Phase 2S — Legacy Failure Evidence Consulted

## Read-only legacy evidence consulted

The Phase 2S decision-explainability paper-ledger projection harness is the second Lane B `explainability_ui` post-consolidation milestone, authored immediately after Phase 2R. It is a typed-mirror per-row projection over the typed `PaperExecutionLedgerEntry` composition-root output. No legacy file is mutated. No `/home/wali/Desktop/AI BOT` source file is opened, read, or modified. No Redis key is read or written. No live service is restarted. No Binance read-only account-history endpoint is called at Phase 2S.

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
- `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/06_IMPLEMENTATION_REPORT.md`.
- `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/07_GO_NO_GO.md`.
- `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/09_CODEX_GO_NO_GO.md`.
- `claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`.
- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`.
- `claude_worklog/requirements_inbox/REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md`.
- `claude_worklog/requirements_inbox/REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md`.
- `claude_worklog/requirements_inbox/REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md`.
- `claude_worklog/requirements_inbox/REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md`.
- `claude_worklog/requirements_inbox/REQ_0023_FULL_LEGACY_READONLY_AUDIT_SENTINEL.md`.
- `v2/backend/app/domain/risk_gateway/__init__.py` (read-only typed surface usage).
- `v2/backend/app/domain/risk_gateway/record.py` (read-only typed surface usage).
- `v2/backend/app/domain/paper_execution_ledger/__init__.py` (read-only typed surface usage).
- `v2/backend/app/domain/paper_execution_ledger/record.py` (read-only typed surface usage).
- `v2/backend/app/services/paper_execution_ledger/service.py` (read-only typed surface usage).
- `v2/backend/app/composition/paper_execution_ledger/runtime.py` (read-only composition-root usage).

## Legacy behavior preserved

The legacy bot operated without a typed, deterministic, offline-inspectable per-row paper-ledger explainability projection. Per the legacy audits cited above and the Phase 2H paper-execution-ledger composition-root impl, paper-ledger evidence in the legacy runtime was scattered across legacy logs, ad-hoc monitor scripts, and the legacy account-history record set, with no parallel typed projection that lifts a typed `PaperExecutionLedgerEntry` into a single typed envelope row carrying mirrored ledger lineage IDs (`paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`), mirrored `symbol`, mirrored `ledger_entry_ts_ms`, mirrored ledger-side action / reason codes (`ledger_action`, `ledger_reason_code`), mirrored input-side risk action / reason codes (`input_risk_action`, `input_risk_reason_code`), the per-row `live_blocked` flag, and deterministic test-only metadata (`source_scenario_slug`, `step_index`, `legacy_evidence_pointer`). The legacy bot also operated without an explicit per-row mirror of the `paper_trade_id` derivation invariant (`paper_trade_id == "pt_" + risk_decision_id`), leaving paper-trade identity implicit in the legacy code path rather than carried as typed evidence on the explainability surface. Phase 2S preserves the legacy runtime by NOT mutating it; the legacy bot, the legacy ingestors, the legacy trainer, the legacy orchestrator, the legacy trader, the legacy Redis keyspace, the legacy startup script, and the legacy account-history record set are not touched in any way at Phase 2S.

## Legacy failure addressed

Phase 2S records the legacy paper-ledger-explainability-projection gap as the second Lane B post-consolidation typed-mirror evidence-collection artifact, complementing the Phase 2R `DecisionExplainabilityEnvelope` (keyed off `RiskDecisionRecord`) with a per-row paper-ledger projection (keyed off `PaperExecutionLedgerEntry`). The harness builds the existing `PaperExecutionLedgerRecorder` composition root once at harness level via `build_paper_execution_ledger_recorder(now_ms_clock=build_paper_ledger_clock())` and invokes the recorder per-row to obtain a typed `PaperExecutionLedgerEntry` from a typed input `RiskDecisionRecord`. For each typed `PaperExecutionLedgerEntry` produced, the harness lifts:

- the five certified ledger lineage IDs (`paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`);
- `symbol`;
- `ledger_entry_ts_ms`;
- the ledger-side action / reason codes (`ledger_action`, `ledger_reason_code`);
- the input-side risk action / reason codes (`input_risk_action`, `input_risk_reason_code`);
- the per-row `live_blocked` flag;
- deterministic test-only metadata (`source_scenario_slug`, `step_index`, `legacy_evidence_pointer`).

The richer explainability fields requested by REQ_0009 § "Required UI visibility" (top positive / negative feature contributors, source-freshness-by-ingestor, regime context, model / checkpoint version, confidence delta, calibration, position sizing reason, paper / shadow / legacy comparison, blocked-trade reason, risk checks, full audit timeline) belong to separate, later Lane B milestones explicitly out of scope at Phase 2S; Phase 2S does NOT introduce any of those fields, since they require underlying subsystems (confidence attribution, feature contributor projection, freshness flag projection, regime detection, model-version projection, position-sizing calculator, full risk-check ledger) that do not exist at consolidation HEAD. Phase 2S deliberately scopes itself to mirror the certified ledger lineage IDs and the existing typed surface fields, and leaves the richer fields to the explicit downstream milestones that build the underlying lineage / projection subsystems.

The LAB hedge-unwind / squeeze loser-trade evidence is included at Phase 2S only as a deterministic typed pointer literal (the per-row `legacy_evidence_pointer` field of `PaperLedgerExplainabilityEnvelope` for the `paper_ledger_explainability_pack_lab_loser_short` scenario steps); Phase 2S does NOT introduce a hedge / residual-exposure / squeeze-risk model.

## Hard safety boundary statement

No file under `/home/wali/Desktop/AI BOT` is opened, read, or modified at Phase 2S. No Redis key is read or written. No live service is restarted. No exchange order is placed or cancelled. No leverage or margin is changed. No live trading is enabled. No deployment is performed. No production migration is run. No secret value is read, printed, or committed. No Binance read-only API call is made at Phase 2S. The live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` is not flipped or substituted by Phase 2S. No file under `v2/backend/app/` is modified. No file under `v2/frontend/` is modified. No FastAPI route, scheduler, background loop, Redis adapter, persistence helper, or live trading process surface is introduced.

PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_LEGACY_FAILURE_EVIDENCE_READY
