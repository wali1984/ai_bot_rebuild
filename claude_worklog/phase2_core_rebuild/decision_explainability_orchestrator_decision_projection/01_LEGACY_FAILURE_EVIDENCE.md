# Phase 2U — Legacy Failure Evidence

## Phase 2U lane and post-consolidation positioning

Phase 2U opens as the **fourth post-consolidation Lane B `explainability_ui` milestone**, immediately following:

- Phase 2R — `decision_explainability_data_contract` — Codex PASS marker `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/09_CODEX_GO_NO_GO.md`. Projection scope: `RiskDecisionRecord` + `PaperModeFlag` → `DecisionExplainabilityEnvelope` (16 typed fields).
- Phase 2S — `decision_explainability_paper_ledger_projection` — Codex PASS marker `PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/decision_explainability_paper_ledger_projection/09_CODEX_GO_NO_GO.md`. Projection scope: `PaperExecutionLedgerEntry` → `PaperLedgerExplainabilityEnvelope` (15 typed fields).
- Phase 2T — `decision_explainability_replay_backtest_projection` — Codex PASS marker `PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/decision_explainability_replay_backtest_projection/09_CODEX_GO_NO_GO.md`. Projection scope: `ReplayBacktestStep` + `ReplayBacktestSummary` → `ReplayBacktestStep/SummaryExplainabilityEnvelope` (17 step + 14 summary typed fields).

The consolidation target `V2_BACKTEST_AND_PAPER_MVP_READY` and its Codex-PASS twin `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` are materialized at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` and `10_GO_NO_GO_CODEX.md` respectively. REQ_0017 / REQ_0018 / REQ_0020 lane-lock remains in force; Phase 2U is exclusively a post-consolidation Lane B explainability projection that introduces NO new lineage ID, NO live execution behavior, NO Redis access, NO FastAPI surface, NO scheduler, NO background loop, NO persistence layer, and NO modification of any prior-milestone V2 source or test artifact.

## Legacy failure addressed

The legacy bot operated without a typed, deterministic, offline-inspectable, per-row **orchestrator-decision** explainability data contract. Specifically:

- `legacy_reference/rl/orchestrator_worker.py` and the legacy `monitor_trainer_predictions.py` runtime path emit orchestrator decisions as ad-hoc Redis stream entries and free-form log lines; there is no parallel typed projection that lifts a single orchestrator decision record into a fixed-shape offline-inspectable envelope carrying mirrored lineage IDs (`decision_id`, `prediction_id`, `feature_snapshot_id`), mirrored decision-side action and reason codes (`decision_action`, `decision_reason_code`), mirrored input-prediction-side fields (`input_prediction_direction`, `input_prediction_confidence_calibrated`, `input_prediction_freshness_flag`, `input_worker_health_status`), the `live_blocked` invariant, and deterministic test-only metadata (`source_scenario_slug`, `step_index`, `legacy_evidence_pointer`).
- The legacy `claude_worklog/legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md` and `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` audits record that orchestrator decisions in the legacy bot are not produced as typed records but as free-form log strings keyed by symbol; downstream consumers (legacy trader, monitor scripts, manual operator review) cannot reconstruct why a particular decision was emitted without re-running the trainer process and the orchestrator process side-by-side.
- The legacy `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` and `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` failure registers cite the LAB hedge-unwind / squeeze incident (REQ_0022) as a case where the orchestrator's hold/proceed reasoning was not preserved as a typed offline-inspectable record; reconstruction required cross-referencing trainer logs, orchestrator logs, trader logs, and exchange-side trade history.

Phase 2U addresses this gap by establishing the typed `OrchestratorDecisionExplainabilityEnvelope` as the deterministic offline-inspectable backend contract that subsequent Lane B Orchestrator Decision UI panel milestones (Mission Control orchestrator-decision timeline, Signal Explainability orchestrator-decision panel, Trainer Prediction Monitor orchestrator-decision overlay, Audit Ledger orchestrator-decision trace per REQ_0009 § "Website pages") consume per REQ_0009 § "Required UI visibility" and REQ_0018 Lane B (no fake reasoning, real lineage IDs only).

## Legacy behavior preserved

Phase 2U does not modify any legacy artifact, any live runtime, any V2 production source, or any prior Phase 2 milestone artifact byte content. Phase 2U does not flip the live-readiness gate. Phase 2U does not introduce any live execution behavior. Phase 2U is read-only with respect to the legacy bot and the existing Phase 2E orchestrator-decision evaluator composition root.

## V2 proof gate

The 11 pytest functions in `04_TEST_PLAN.md` assert (i) the harness pipeline invariants (single-build evaluator, per-row evaluator-closure invocation, per-row envelope projection), (ii) the per-row mirrored-field invariants for all 12 fields of `OrchestratorDecisionRecord`, (iii) the test-only metadata fields, (iv) the LAB-scenario legacy_evidence_pointer literal per REQ_0022, (v) the envelope allowed-fields-only invariant (15 fields exactly), (vi) the determinism / build-once invariants under repeated invocation, and (vii) the forbidden-token / forbidden-import / forbidden-cross-test-import scans. The proof gate is `PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_IMPLEMENTATION_READY` at `07_GO_NO_GO.md` body line one, with Codex review marker `PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_CODEX_PASS` at `09_CODEX_GO_NO_GO.md`.

## Lane / MVP relevance / next gate

- Lane: `explainability_ui` (Lane B, REQ_0018 approved post-consolidation).
- MVP relevance: backed by real existing typed surface (`OrchestratorDecisionRecord`) and existing typed lineage IDs only (`decision_id`, `prediction_id`, `feature_snapshot_id`). Establishes the typed `OrchestratorDecisionExplainabilityEnvelope` as the deterministic offline-inspectable Lane B contract for orchestrator-decision-row mirroring. No new lineage ID is introduced. No execution / paper / shadow / live action is opened. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: zero remaining MVP milestones (consolidation marker closed); this milestone is post-consolidation Lane B build-out for downstream UI panel data contracts.
- Blocked by: `PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_CODEX_PASS` (immediate predecessor) plus all upstream MVP and post-consolidation Codex PASS markers transitively.
- Next gate: `PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_IMPLEMENTATION_READY` (after task 180 runs); Codex PASS marker `PHASE2U_DECISION_EXPLAINABILITY_ORCHESTRATOR_DECISION_PROJECTION_CODEX_PASS` (after the next planner turn authors the Codex review task).

PHASE2U_LEGACY_FAILURE_EVIDENCE_READY
