# Planner Turn 2P — Open Phase 2P Implementation

## State at planner turn open

- HEAD: `ea9aad9` ("Codex watchdog recover dirty non-live automation artifacts").
- Pending unstaged change is limited to `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (in-flight planner-prompt MVP-counter rotation; covered by the standing `worktree_excluded_paths` precedent established under tasks 165 / 167 and does not block dispatch).
- `V2_BACKTEST_AND_PAPER_MVP_READY` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md`.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`.
- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`.
- `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- Planner status JSON `current_mvp_milestone` field is stale (`REPLAY_BACKTEST_RUNNER_MVP` / three remaining); per REQ_0015 § "Evidence-first reconciliation", PASS markers under `claude_worklog/phase2_core_rebuild/` override stale queue / status / dashboard noise. The status JSON is rotated by the supervisor on next dispatch and does not block this planner turn. The dirty planner-prompt MVP-counter rotation is itself stale relative to the consolidation gate evidence and does not gate Phase 2P.

## Decision

Open Phase 2P — Historical PnL Replay Wiring — as the next post-consolidation Lane A evidence-collection milestone, per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp" fourth bullet (`30-day historical PnL audit (REQ_0024) wiring`), and per the explicit `next_recommended_action` declared by `claude_worklog/agent_supervisor/tasks/167_phase2o_shadow_mode_evidence_collection_harness_implementation.json` on `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` ("the planner opens the next post-consolidation lane A category - 30-day historical PnL audit (REQ_0024) wiring").

Phase 2P is the fourth post-consolidation Lane A typed mirror evidence-collection artifact. It authors:

- A deterministic four-scenario typed historical-PnL replay evidence pack (`BTCUSDT` realized-long winner ×3, `ETHUSDT` realized-short winner ×3, `LABUSDT` realized-short loser ×3 [LAB hedge-unwind / squeeze legacy failure pointer], `SOLUSDT` orchestrator-held blocked ×3; total 12 typed `HistoricalPnLReplayInput` rows).
- A pure-function harness that drives the existing `PaperModeRuntime` and `PaperExecutionLedgerRecorder` composition roots end-to-end, gated on the typed paper-mode flag.
- 12 produced typed `PaperExecutionLedgerEntry` mirror rows.
- 12 typed `HistoricalPnLReplayComparisonRecord` rows pairing a deterministic `legacy_realized_trade_evidence_pointer` with the produced `PaperExecutionLedgerEntry`.
- 1 typed `PaperModeFlag` at the harness level.
- pytest coverage for typed projection invariants, lineage carry-over, paper-mode-flag invariants, per-scenario per-step `(legacy_realized_trade_evidence_pointer, PaperExecutionLedgerEntry)` comparison-record correctness, and absence of disallowed lineage rows.

Phase 2P does NOT introduce a `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row. Phase 2P does NOT introduce PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook / hedge-state / residual-exposure / squeeze-risk computation. Phase 2P does NOT call any Binance read-only account-history endpoint at this stage; the live Binance read-only pull described in REQ_0024 § "Binance Read-Only Policy" is a separate, later milestone explicitly out of scope at Phase 2P. Phase 2P does NOT modify any file under `v2/backend/app/`. Phase 2P does NOT flip the live-readiness gate.

## Lane / MVP relevance / next gate

- Lane: `paper_backtest_mvp`.
- MVP relevance: post-consolidation Lane A evidence collection. The historical-PnL replay wiring produces typed `(PaperModeFlag, per-step HistoricalPnLReplayComparisonRecord)` evidence rows over a deterministic four-scenario typed evidence pack, gated on the typed paper-mode flag, establishing the typed offline-inspectable historical-PnL replay baseline that subsequent 30-day Binance read-only pull, decision-explainability UI, and risk-gateway-extension milestones replay against. No new code surface beyond test-only fixtures, a pure-function harness module, and a pytest module.
- Blocked by (all materialized): see `05_GO_NO_GO_REQUEST.md` § "Predecessor evidence".
- Next gate: `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/07_GO_NO_GO.md`. Codex review marker: `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS`.

## Authored task

The planner turn authors:

- The Phase 2P planning packet (01–05) under `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/`.
- This planner-turn note (`PLANNER_TURN_2P_OPEN_IMPLEMENTATION.md`).
- The supervisor task `169_phase2p_historical_pnl_replay_wiring_implementation` under `claude_worklog/agent_supervisor/tasks/`.

## Hard safety posture

Live trading: BLOCKED. Phase 2P is non-live by construction. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. No live Binance API call.

## Recovery posture (Codex autofix lane)

Per REQ_0007 / REQ_0011 / REQ_0014 / REQ_0016 / REQ_0021, on a Codex FAIL with concrete documentation blockers and no safety violation, the supervisor dispatches a Codex autofix scoped to the Phase 2P packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H / 2I / 2J / 2K / 2L / 2M / 2N / 2O reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_PLANNER_TURN_OPEN_READY
