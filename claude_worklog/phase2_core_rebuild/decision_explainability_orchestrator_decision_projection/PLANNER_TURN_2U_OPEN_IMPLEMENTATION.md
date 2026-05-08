# Planner Turn 2U — Open Phase 2U Implementation

## State at planner turn open

- HEAD at authoring: `23a4e5c` ("Codex watchdog recover dirty non-live automation artifacts").
- Pending unstaged change is limited to `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (in-flight planner-prompt MVP-counter rotation; covered by the standing `worktree_excluded_paths` precedent established under tasks 165 / 167 / 169 / 171 / 173 / 175 / 177 and does not block dispatch).
- `V2_BACKTEST_AND_PAPER_MVP_READY` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md`.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`.
- `PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/decision_explainability_replay_backtest_projection/09_CODEX_GO_NO_GO.md`.
- `PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/decision_explainability_paper_ledger_projection/09_CODEX_GO_NO_GO.md`.
- `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/09_CODEX_GO_NO_GO.md`.
- All upstream MVP and post-consolidation Codex PASS markers materialized (see `05_GO_NO_GO_REQUEST.md` § "Predecessor evidence").
- Per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane B — explainability_ui (post-consolidation; backed only by real lineage)" and per the typed surface inventory at `02_TYPED_SURFACE_INVENTORY.md`, the per-row identity of `OrchestratorDecisionRecord` (mirror-row identity carrying `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `decision_ts_ms`, `decision_action`, `decision_reason_code`, `input_prediction_direction`, `input_prediction_confidence_calibrated`, `input_prediction_freshness_flag`, `input_worker_health_status`, `live_blocked`) is eligible Lane B lineage at consolidation HEAD.

## Decision

Open Phase 2U — Decision Explainability Orchestrator Decision Mirror Projection Harness — as the **fourth post-consolidation Lane B `explainability_ui` milestone**, immediately following Phase 2T. Phase 2U authors a deterministic, pure-function, per-row typed-mirror **orchestrator-decision explainability projection** harness. The harness drives the existing `OrchestratorDecisionEvaluator` composition root once at harness level (built via `build_orchestrator_decision_evaluator(low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD, now_ms_clock=build_orchestrator_clock())`), constructs a typed `TrainerPredictionRecord` per fixture row, invokes the evaluator closure once per row to obtain a typed `OrchestratorDecisionRecord`, and projects each typed decision record into a typed `OrchestratorDecisionExplainabilityEnvelope`. The envelope is the typed offline-inspectable backend contract that subsequent Lane B UI panel milestones (Mission Control orchestrator-decision timeline, Signal Explainability orchestrator-decision panel, Trainer Prediction Monitor orchestrator-decision overlay, Audit Ledger orchestrator-decision trace per REQ_0009 § "Website pages") consume per REQ_0009 § "Required UI visibility" without fabricated reasoning.

Phase 2U authors:

- A deterministic four-scenario typed orchestrator-decision-explainability evidence pack (`orchestrator_decision_explainability_pack_btc_winner_long` ×3, `orchestrator_decision_explainability_pack_eth_winner_short` ×3, `orchestrator_decision_explainability_pack_lab_loser_short` ×3 [LAB hedge-unwind / squeeze legacy-failure pointer per REQ_0022], `orchestrator_decision_explainability_pack_sol_orchestrator_abstained_low_confidence` ×3; total 12 typed `OrchestratorDecisionExplainabilityFixtureInput` rows).
- A pure-function projection harness that builds the existing composition root once at harness level (`build_orchestrator_decision_evaluator(low_confidence_threshold=LOW_CONFIDENCE_THRESHOLD, now_ms_clock=build_orchestrator_clock())`).
- 12 produced typed `OrchestratorDecisionExplainabilityEnvelope` mirror rows (one per typed input row) carrying only the 12 fields of the per-row `OrchestratorDecisionRecord` (mirrored exactly) plus 3 deterministic test-only metadata fields (`source_scenario_slug`, `step_index`, `legacy_evidence_pointer`).
- pytest coverage for harness-result shape, evaluator-build-once invariant, per-row lineage carry-over, per-row decision-side action / reason mirror, per-row symbol mirror, per-row input-prediction-side mirror (direction / confidence_calibrated / freshness / worker health), per-row decision_ts_ms strictly-monotonic-within-clock-window, per-row live_blocked invariant, LAB-scenario pointer literal, envelope allowed-fields-only invariant (15 fields), evaluator-build-once factory determinism under repeated harness invocations, forbidden-token scan, forbidden-import scan, and forbidden-cross-test-import scan.

## Lane / MVP relevance / next gate

- Lane: `explainability_ui` (Lane B, REQ_0018 approved post-consolidation).
- MVP relevance: Fourth post-consolidation Lane B milestone backed by real lineage IDs only and existing typed surface fields. Establishes the typed `OrchestratorDecisionExplainabilityEnvelope` as the deterministic offline-inspectable backend contract for the per-row orchestrator-decision projection. Phase 2U does NOT introduce a `shadow_decision_id`, `execution_intent_id`, `risk_decision_id`, `paper_trade_id`, `replay_step_id`, `replay_run_id`, or `replay_summary_id` lineage row at the Phase 2U layer. Phase 2U does NOT introduce previous-confidence, confidence-delta, confidence-calibration, top-positive / top-negative feature contributors, feature-freshness flags, regime context, model-version change, checkpoint-version change, position-sizing reason, risk-check ledger, blocked-trade reason, paper-shadow-legacy comparison, or audit-timeline fields. Phase 2U does NOT introduce a hedge / residual-exposure / squeeze-risk model. Phase 2U does NOT introduce PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook computation. Phase 2U does NOT introduce a FastAPI route, a frontend page, a scheduler, a background loop, a Redis adapter, or any persistence layer. Phase 2U does NOT modify any V2 production source under `v2/backend/app/` or `v2/frontend/`.
- Blocked by (all materialized at HEAD `23a4e5c`): see `05_GO_NO_GO_REQUEST.md` § "Predecessor evidence".
- Next gate: `PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/decision_explainability_orchestrator_decision_projection/07_GO_NO_GO.md`. Codex review marker on Codex PASS (next planner turn after impl PASS): `PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_CODEX_PASS`.

## Authored task

The planner turn authors:

- The Phase 2U planning packet (01–05) under `claude_worklog/phase2_core_rebuild/decision_explainability_orchestrator_decision_projection/`.
- This planner-turn note (`PLANNER_TURN_2U_OPEN_IMPLEMENTATION.md`).
- The supervisor task `180_phase2u_decision_explainability_orchestrator_decision_projection_implementation` under `claude_worklog/agent_supervisor/tasks/`.
- The queued `codex_recover_180_phase2u_decision_explainability_orchestrator_decision_projection_implementation` shadow recovery task per the standing precedent (codex_recover_157 / 158 / 159 / 161 / 163 / 165 / 167 / 169 / 171 / 173 / 175 / 176 / 177).

The Codex review task for Phase 2U (analogous to task 179) is deliberately deferred to the next planner turn after `PHASE2U_..._IMPLEMENTATION_READY` is materialized, per the standing precedent that Codex review runs against committed milestone artifacts only.

## Hard safety posture

Live trading: BLOCKED. Phase 2U is non-live by construction. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. No live Binance API call. No file under `v2/backend/app/` modified. No file under `v2/frontend/` modified. No file under any prior-milestone Phase 2 directory modified. No standalone harness framing-token marker line in any authored file body.

## Recovery posture (Codex autofix lane)

Per REQ_0007 / REQ_0011 / REQ_0014 / REQ_0016 / REQ_0021, on a Codex FAIL with concrete documentation blockers and no safety violation, the supervisor dispatches a Codex autofix scoped to the Phase 2U packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H / 2I / 2J / 2K / 2L / 2M / 2N / 2O / 2P / 2Q / 2R / 2S / 2T reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/decision_explainability_orchestrator_decision_projection/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

## Treatment of existing unstaged work

One unstaged entry is present at this planner turn:

1. `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` — modified.
   - Source of the diff: prior 2I→2J / 2J→2K / 2K→2L pointer-update sequence; documentation-only and not a safety regression.
   - Planner action: leave for the next watchdog auto-commit. The planner does NOT re-emit the prompt this turn to avoid racing the watchdog auto-commit.

No other unstaged entry exists. No file under `v2/` is dirty. No GO/NO-GO marker is dirty. No prior-milestone implementation, review, or reconciliation artifact is dirty.

## Stop conditions

If task 180 returns `PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_IMPLEMENTATION_FAIL` with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the Phase 2U authored source and test files only and re-runs the implementation flow.

If any task encounters a safety violation (any live behavior, any Redis access, any legacy mutation, any release intent, any FastAPI / wall-clock / subprocess / socket import in a Phase 2U file, any URL or credential leakage, any modification of `v2/backend/app/`, any modification of `v2/frontend/`, any modification of a prior-milestone artifact, any modification of any GO/NO-GO marker, any introduction of a forbidden lineage ID at the Phase 2U layer, any introduction of PnL / position sizing / quantity / price / fees / slippage / funding / OI / liquidation map / orderbook depth / hedge-state / residual-exposure / squeeze-risk computation, any introduction of ledger persistence, any flip of the live-readiness gate, any introduction of `previous_confidence` / `confidence_delta` / `confidence_calibration` / `top_positive_feature_contributors` / `top_negative_feature_contributors` / `feature_freshness_flags` / `regime_context` / `position_sizing_reason` / `risk_check_list` / `blocked_trade_reason` / `paper_shadow_legacy_comparison` / `audit_timeline` field on the Phase 2U envelope), the planner stops, surfaces to human attention, and does not auto-retry.

PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_PLANNER_TURN_OPEN_READY
