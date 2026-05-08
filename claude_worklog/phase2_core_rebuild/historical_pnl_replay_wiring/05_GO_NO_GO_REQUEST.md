# Phase 2P — GO/NO-GO Request

## Scope

Phase 2P authors a deterministic, pure-function, paper-mode-gated typed-mirror historical-PnL replay-wiring harness driving the existing `PaperModeRuntime` and `PaperExecutionLedgerRecorder` composition roots end-to-end against a four-scenario typed historical-PnL evidence pack. The harness produces typed `(PaperModeFlag, per-step HistoricalPnLReplayComparisonRecord)` rows for offline inspection by subsequent 30-day Binance read-only-pull, decision-explainability UI, and risk-gateway-extension milestones.

## Required output files

Test-only (under `v2/backend/tests/unit/historical_pnl_replay_wiring/`):

- `__init__.py`
- `fixtures.py`
- `harness.py`
- `test_historical_pnl_replay_wiring.py`

Phase 2P documentation (under `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/`):

- `06_IMPLEMENTATION_REPORT.md`
- `07_GO_NO_GO.md`

The planning packet authored by this planner turn (`01_LEGACY_FAILURE_EVIDENCE.md`, `02_TYPED_INPUT_FIXTURE_SPEC.md`, `03_HARNESS_PIPELINE_SPEC.md`, `04_TEST_PLAN.md`, `05_GO_NO_GO_REQUEST.md`, `PLANNER_TURN_2P_OPEN_IMPLEMENTATION.md`) is read-only at the implementation milestone and must NOT be modified by the implementer.

## Predecessor evidence

Phase 2P is blocked by all of:

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

All eleven predecessor markers are materialized at the planner turn open per the evidence cited in `PLANNER_TURN_2P_OPEN_IMPLEMENTATION.md` § "State at planner turn open".

## Lane / MVP relevance / next gate

- Lane: `paper_backtest_mvp`.
- MVP relevance: Post-consolidation Lane A evidence collection. Fourth post-consolidation Lane A milestone, mirroring 2M / 2N / 2O post-consolidation precedent. The harness produces typed historical-PnL replay-wiring evidence rows that subsequent 30-day Binance read-only-pull, decision-explainability UI, and risk-gateway-extension milestones replay against. No new code surface beyond test-only fixtures, a pure-function harness module, and a pytest module.
- Blocked by: see "Predecessor evidence" above.
- Next gate: `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/07_GO_NO_GO.md`. Codex review marker on Codex PASS: `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS`.

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
- No prior-milestone Phase 2 artifact byte content modified.
- No Phase 2P planning artifact (01–05) modified by the implementer; the planning packet is read-only at the implementation milestone.

## Codex review posture

On `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_IMPLEMENTATION_READY`, the planner authors a Codex review task (`170_phase2p_historical_pnl_replay_wiring_codex_review`) scoped to the Phase 2P packet (01 through 07) and the four test-only files under `v2/backend/tests/unit/historical_pnl_replay_wiring/`. Codex review verifies the typed historical-PnL replay-wiring projection per `03_HARNESS_PIPELINE_SPEC.md`, the fixture invariants per `02_TYPED_INPUT_FIXTURE_SPEC.md`, the test plan per `04_TEST_PLAN.md`, and that no file under `v2/backend/app/` is modified, no `/home/wali/Desktop/AI BOT` mutation, no Redis access, no live action, no Binance read-only account-history call, no secret exposure, and no live-readiness gate flip.

PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_GO_NO_GO_REQUEST_READY
