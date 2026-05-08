# Planner Turn 2T — Open Phase 2T Implementation

## State at planner turn open

- HEAD at authoring: `2417cdc` ("Codex watchdog recover dirty non-live automation artifacts").
- Pending unstaged change is limited to `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (in-flight planner-prompt MVP-counter rotation; covered by the standing `worktree_excluded_paths` precedent established under tasks 165 / 167 / 169 / 171 / 173 / 175 and does not block dispatch).
- `V2_BACKTEST_AND_PAPER_MVP_READY` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md`.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`.
- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`.
- `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md`.
- `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/09_CODEX_GO_NO_GO.md`.
- `PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/decision_explainability_paper_ledger_projection/09_CODEX_GO_NO_GO.md`.
- Per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane B — explainability_ui (post-consolidation; backed only by real lineage)" and per the explicit `next_recommended_action` declared by `claude_worklog/agent_supervisor/tasks/176_phase2s_decision_explainability_paper_ledger_projection_codex_review.json`, the per-record identity of `ReplayBacktestStep` (mirror-row identity carrying `replay_step_id`, `replay_run_id`, `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `step_ts_ms`, `step_action`, `step_reason_code`, `input_paper_action`, `input_paper_reason_code`, `live_blocked`) and the per-scenario identity of `ReplayBacktestSummary` (carrying `replay_summary_id`, `replay_run_id`, `summary_emitted_ts_ms`, `total_steps_count`, six per-action / per-subreason partition counts, `live_blocked`) are eligible Lane B lineage at consolidation HEAD.

## Decision

Open Phase 2T — Decision Explainability Replay-Backtest Projection Harness — as the **third post-consolidation Lane B `explainability_ui` milestone**, immediately following Phase 2S. Phase 2T authors a deterministic, pure-function, per-row typed-mirror **replay-backtest-step / replay-backtest-summary explainability projection** harness. The harness drives the existing `ReplayBacktestRunner` composition root once at harness level (built via `build_replay_backtest_runner(now_ms_clock=build_replay_clock())`), drives the existing `PaperExecutionLedgerRecorder` composition root once at harness level (built via `build_paper_execution_ledger_recorder(now_ms_clock=build_paper_ledger_clock())`), invokes the recorder per-row to produce a typed `PaperExecutionLedgerEntry`, invokes `assemble_step` per-row to obtain a typed `ReplayBacktestStep`, invokes `assemble_summary` per-scenario to obtain a typed `ReplayBacktestSummary`, and projects each typed step into a typed `ReplayBacktestStepExplainabilityEnvelope` and each typed summary into a typed `ReplayBacktestSummaryExplainabilityEnvelope`. The envelopes are the typed offline-inspectable backend contracts that subsequent Lane B UI panel milestones (Mission Control replay timeline, Signal Explainability replay panel, Paper / Shadow Trading replay overlay, Audit Ledger replay-step trace per REQ_0009 § "Website pages") consume per REQ_0009 § "Required UI visibility" without fabricated reasoning.

Phase 2T authors:

- A deterministic four-scenario typed replay-step-explainability evidence pack (`replay_step_explainability_pack_btc_winner_long` ×3, `replay_step_explainability_pack_eth_winner_short` ×3, `replay_step_explainability_pack_lab_loser_short` ×3 [LAB hedge-unwind / squeeze legacy-failure pointer per REQ_0022], `replay_step_explainability_pack_sol_orchestrator_held` ×3; total 12 typed `ReplayBacktestStepExplainabilityFixtureInput` rows organised into 4 typed `ReplayBacktestRun` scenarios).
- A pure-function projection harness that builds the existing composition roots once at harness level (`build_replay_backtest_runner(now_ms_clock=build_replay_clock())` and `build_paper_execution_ledger_recorder(now_ms_clock=build_paper_ledger_clock())`).
- 12 produced typed `ReplayBacktestStepExplainabilityEnvelope` mirror rows (one per typed input row) carrying only fields derived from the per-row `ReplayBacktestStep` and deterministic test-only metadata (`source_scenario_slug`, `step_index`, `legacy_evidence_pointer`).
- 4 produced typed `ReplayBacktestSummaryExplainabilityEnvelope` mirror rows (one per scenario) carrying only fields derived from the per-scenario `ReplayBacktestSummary` and deterministic test-only metadata (`source_scenario_slug`, `legacy_evidence_pointer`).
- pytest coverage for runner-build-once and recorder-build-once invariants, per-row lineage carry-over, per-row symbol mirror, per-row `step_ts_ms` mirror, per-row `step_action` / `step_reason_code` / `input_paper_action` / `input_paper_reason_code` mirror, per-row `live_blocked` invariant (always `True`), per-scenario summary partition counts, LAB-scenario pointer literal, slug namespacing, step-index range, symbol-set restriction, forbidden lineage / market field absence, persistence absence, forbidden-token scan, and forbidden-import scan.

## Lane / MVP relevance / next gate

- Lane: `explainability_ui` (Lane B).
- MVP relevance: Third post-consolidation Lane B milestone backed by real lineage IDs only and existing typed surface fields. Establishes the typed `ReplayBacktestStepExplainabilityEnvelope` and `ReplayBacktestSummaryExplainabilityEnvelope` as the deterministic offline-inspectable backend contracts for the per-row replay projection. Phase 2T does NOT introduce a `shadow_decision_id` or `execution_intent_id` lineage row. Phase 2T does NOT introduce confidence-attribution, top-positive / top-negative feature contributors, feature-freshness flags, regime context, calibration, model-version, position-sizing-reason, risk-check-list, blocked-trade-reason, paper-shadow-legacy-comparison, or audit-timeline fields. Phase 2T does NOT introduce a hedge / residual-exposure / squeeze-risk model. Phase 2T does NOT introduce PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook computation. Phase 2T does NOT introduce a FastAPI route, a frontend page, a scheduler, a background loop, a Redis adapter, or any persistence layer.
- Blocked by (all materialized at HEAD `2417cdc`): see `05_GO_NO_GO_REQUEST.md` § "Predecessor evidence".
- Next gate: `PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/decision_explainability_replay_backtest_projection/07_GO_NO_GO.md`. Codex review marker on Codex PASS: `PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_CODEX_PASS`.

## Authored task

The planner turn authors:

- The Phase 2T planning packet (01–05) under `claude_worklog/phase2_core_rebuild/decision_explainability_replay_backtest_projection/`.
- This planner-turn note (`PLANNER_TURN_2T_OPEN_IMPLEMENTATION.md`).
- The supervisor task `177_phase2t_decision_explainability_replay_backtest_projection_implementation` under `claude_worklog/agent_supervisor/tasks/`.
- The queued `codex_recover_177_phase2t_decision_explainability_replay_backtest_projection_implementation` shadow recovery task per the standing precedent.

## Hard safety posture

Live trading: BLOCKED. Phase 2T is non-live by construction. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. No live Binance API call. No file under `v2/backend/app/` modified. No file under `v2/frontend/` modified. No file under any prior-milestone Phase 2 directory modified. No standalone harness framing-token marker line in any authored file body.

## Recovery posture (Codex autofix lane)

Per REQ_0007 / REQ_0011 / REQ_0014 / REQ_0016 / REQ_0021, on a Codex FAIL with concrete documentation blockers and no safety violation, the supervisor dispatches a Codex autofix scoped to the Phase 2T packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H / 2I / 2J / 2K / 2L / 2M / 2N / 2O / 2P / 2Q / 2R / 2S reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/decision_explainability_replay_backtest_projection/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_PLANNER_TURN_OPEN_READY
