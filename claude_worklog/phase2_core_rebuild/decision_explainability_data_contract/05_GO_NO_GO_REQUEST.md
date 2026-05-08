# Phase 2R — GO/NO-GO Request

## Scope

Phase 2R authors a deterministic, pure-function, paper-mode-gated typed-mirror **decision-explainability data contract** harness driving the existing `PaperModeRuntime` composition root once at harness level against a four-scenario typed evidence pack (12 typed input rows mirroring the typed `RiskDecisionRecord` carrier of Phase 2N / 2O / 2P / 2Q). The harness produces typed `(PaperModeFlag, per-row DecisionExplainabilityEnvelope)` rows for offline inspection by subsequent Lane B UI panel milestones, per REQ_0009 § "Required UI visibility" and REQ_0018 lane B (no fake reasoning, real lineage IDs only). Phase 2R is the **first Lane B post-consolidation milestone**.

## Required output files

Test-only (under `v2/backend/tests/unit/decision_explainability_data_contract/`):

- `__init__.py`.
- `fixtures.py`.
- `harness.py`.
- `test_decision_explainability_data_contract.py`.

Phase 2R documentation (under `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/`):

- `06_IMPLEMENTATION_REPORT.md`.
- `07_GO_NO_GO.md`.

The planning packet authored by this planner turn (`01_LEGACY_FAILURE_EVIDENCE.md`, `02_TYPED_INPUT_FIXTURE_SPEC.md`, `03_HARNESS_PIPELINE_SPEC.md`, `04_TEST_PLAN.md`, `05_GO_NO_GO_REQUEST.md`, `PLANNER_TURN_2R_OPEN_IMPLEMENTATION.md`) is read-only at the implementation milestone and must NOT be modified by the implementer.

## Predecessor evidence

Phase 2R is blocked by all of:

- `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `V2_BACKTEST_AND_PAPER_MVP_READY` and `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.
- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`.
- `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS`.
- `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS`.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS`.
- `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS`.

All thirteen predecessor markers are materialized at the planner turn open per the evidence cited in `PLANNER_TURN_2R_OPEN_IMPLEMENTATION.md` § "State at planner turn open".

## Lane / MVP relevance / next gate

- Lane: `explainability_ui` (Lane B).
- MVP relevance: First Lane B post-consolidation milestone backed strictly by real lineage IDs (`feature_snapshot_id`, `prediction_id`, `decision_id`, `risk_decision_id`) and existing typed surface fields (`RiskDecisionRecord` action / reason / live-blocked / decision-timestamp; harness-level `PaperModeFlag` mode / live-blocked). Establishes the typed `DecisionExplainabilityEnvelope` as the deterministic offline-inspectable backend contract that subsequent Lane B UI panel milestones (Mission Control, Signal Explainability, Risk Gateway, Audit Ledger) consume per REQ_0009 § "Required UI visibility" and REQ_0018 lane B. No new code surface beyond test-only fixtures, a pure-function harness module, and a pytest module. Does not introduce a `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row. Does not introduce confidence-attribution, top-feature-contributors, feature-freshness flags, regime context, calibration, or PnL fields. Does not introduce a FastAPI route, a frontend page, a scheduler, a background loop, a Redis adapter, or any persistence layer. Does not flip the live-readiness gate.
- Blocked by: see "Predecessor evidence" above.
- Next gate: `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/07_GO_NO_GO.md`. Codex review marker on Codex PASS: `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_CODEX_PASS`.

## Hard safety boundaries (restated)

- No `/home/wali/Desktop/AI BOT` mutation.
- No Redis read or write; no Redis adapter.
- No live service restart; no live-trader / live-orchestrator / live-trainer process modification.
- No exchange order placement or cancellation; no leverage / margin change; no live trading enablement.
- No deployment; no production migration.
- No secret read, print, or commit.
- No Binance read-only account-history endpoint invocation.
- No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- No file under `v2/backend/app/` modified.
- No file under `v2/frontend/` modified.
- No prior-milestone Phase 2 artifact byte content modified.
- No Phase 2R planning artifact (01–05) modified by the implementer; the planning packet is read-only at the implementation milestone.
- No import of a test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`.
- No standalone harness framing token marker line in any authored file body.

## Codex review posture

On `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_IMPLEMENTATION_READY`, the planner authors a Codex review task (`174_phase2r_decision_explainability_data_contract_codex_review`) scoped to the Phase 2R packet (01 through 07) and the four test-only files under `v2/backend/tests/unit/decision_explainability_data_contract/`. Codex review verifies the typed envelope projection per `03_HARNESS_PIPELINE_SPEC.md`, the fixture invariants per `02_TYPED_INPUT_FIXTURE_SPEC.md`, the test plan per `04_TEST_PLAN.md`, the forbidden-token and forbidden-import scans, the out-of-scope explainability fields list, and that no file under `v2/backend/app/` is modified, no `/home/wali/Desktop/AI BOT` mutation, no Redis access, no live action, no Binance read-only account-history call, no secret exposure, and no live-readiness gate flip.

PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_GO_NO_GO_REQUEST_READY
