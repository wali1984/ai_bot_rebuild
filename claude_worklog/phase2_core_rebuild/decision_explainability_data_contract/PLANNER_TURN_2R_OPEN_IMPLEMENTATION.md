# Planner Turn 2R — Open Phase 2R Implementation

## State at planner turn open

- HEAD: `03a9645` ("Codex watchdog recover dirty non-live automation artifacts").
- Pending unstaged change is limited to `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (in-flight planner-prompt MVP-counter rotation; covered by the standing `worktree_excluded_paths` precedent established under tasks 165 / 167 / 169 / 171 and does not block dispatch).
- `V2_BACKTEST_AND_PAPER_MVP_READY` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md`.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`.
- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`.
- `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md`.
- `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/09_CODEX_GO_NO_GO.md`.
- Planner status JSON `current_mvp_milestone` field is stale (`REPLAY_BACKTEST_RUNNER_MVP` / three remaining); per REQ_0015 § "Evidence-first reconciliation", PASS markers under `claude_worklog/phase2_core_rebuild/` override stale queue / status / dashboard noise. The status JSON is rotated by the supervisor on next dispatch and does not block this planner turn.

## Decision

Open Phase 2R — Decision Explainability Data Contract Harness — as the **first post-consolidation Lane B `explainability_ui` milestone**, per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane B — explainability_ui (post-consolidation; backed only by real lineage)" and per the explicit `next_recommended_action` declared by `claude_worklog/agent_supervisor/tasks/171_phase2q_aggregate_evidence_rollup_harness_implementation.json` on `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS` ("the planner opens the first Lane B explainability UI milestone backed by the typed lineage rows now certified across Phase 2N / 2O / 2P / 2Q").

Phase 2R is the first Lane B post-consolidation milestone. It authors a deterministic, pure-function, paper-mode-gated typed-mirror **decision-explainability data contract** harness. The harness drives the existing `PaperModeRuntime` composition root once at harness level against a deterministic four-scenario typed evidence pack (12 typed input rows), and **projects each typed `RiskDecisionRecord` into a typed `DecisionExplainabilityEnvelope` row** that mirrors only the certified lineage IDs and existing typed surface fields. The envelope is the typed offline-inspectable backend contract that subsequent Lane B UI panel milestones consume.

Phase 2R authors:

- A deterministic four-scenario typed decision-explainability evidence pack (`pack_btc_winner_long` ×3, `pack_eth_winner_short` ×3, `pack_lab_loser_short` ×3 [LAB hedge-unwind / squeeze legacy-failure pointer], `pack_sol_orchestrator_held` ×3; total 12 typed `DecisionExplainabilityFixtureInput` rows).
- A pure-function projection harness that drives the existing `PaperModeRuntime` composition root once at harness level (no per-row composition-root invocation; no `RiskDecisionEvaluator` invocation; no `PaperExecutionLedgerRecorder` invocation; no `OrchestratorDecisionRouter` invocation; no `ReplayBacktestRunner` invocation).
- 12 produced typed `DecisionExplainabilityEnvelope` mirror rows (one per typed input row) carrying only fields derived from the existing `RiskDecisionRecord`, the harness-level `PaperModeFlag`, and deterministic test-only metadata (`source_scenario_slug`, `step_index`, `legacy_evidence_pointer`).
- 1 typed `PaperModeFlag` at the harness level.
- pytest coverage for harness-level paper-mode-flag invariants, lineage carry-over, action / reason mirror, per-row paper-mode-flag mirror, decision timestamp mirror, LAB-scenario pointer literal, slug namespacing, step-index range, symbol-set restriction, forbidden lineage / market field absence, persistence absence, harness-flag identity, forbidden-token scan, and forbidden-import scan.

## Lane / MVP relevance / next gate

- Lane: `explainability_ui` (Lane B).
- MVP relevance: First post-consolidation Lane B milestone backed by real lineage IDs only (`feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`, plus the existing per-record identity of `RiskDecisionRecord`). Establishes the typed `DecisionExplainabilityEnvelope` as the deterministic offline-inspectable backend contract that subsequent Lane B UI panel milestones (Mission Control, Signal Explainability, Risk Gateway, Audit Ledger pages per REQ_0009 § "Website pages") consume per REQ_0009 § "Required UI visibility" and REQ_0018 lane B (no fake reasoning, real lineage IDs only). Phase 2R does NOT introduce a `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row. Phase 2R does NOT introduce confidence-attribution, top-positive / top-negative feature contributors, feature freshness flags, regime context, calibration, or PnL fields (those belong to separate, later milestones explicitly out of scope at Phase 2R; their UI surfaces remain ineligible until the underlying lineage subsystems exist). Phase 2R does NOT introduce a FastAPI route, a frontend page, a scheduler, a background loop, a Redis adapter, or any persistence layer.
- Blocked by (all materialized): see `05_GO_NO_GO_REQUEST.md` § "Predecessor evidence".
- Next gate: `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/07_GO_NO_GO.md`. Codex review marker on Codex PASS: `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_CODEX_PASS`.

## Authored task

The planner turn authors:

- The Phase 2R planning packet (01–05) under `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/`.
- This planner-turn note (`PLANNER_TURN_2R_OPEN_IMPLEMENTATION.md`).
- The supervisor task `173_phase2r_decision_explainability_data_contract_implementation` under `claude_worklog/agent_supervisor/tasks/`.

## Hard safety posture

Live trading: BLOCKED. Phase 2R is non-live by construction. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. No live Binance API call. No file under `v2/backend/app/` modified. No file under `v2/frontend/` modified. No file under any prior-milestone Phase 2 directory modified. No standalone harness framing token marker line in any authored file body.

## Recovery posture (Codex autofix lane)

Per REQ_0007 / REQ_0011 / REQ_0014 / REQ_0016 / REQ_0021, on a Codex FAIL with concrete documentation blockers and no safety violation, the supervisor dispatches a Codex autofix scoped to the Phase 2R packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H / 2I / 2J / 2K / 2L / 2M / 2N / 2O / 2P / 2Q reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_PLANNER_TURN_OPEN_READY
END_FILE: claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/PLANNER_TURN_2R_OPEN_IMPLEMENTATION.md
