# Planner Turn 2Q — Open Phase 2Q Implementation

## State at planner turn open

- HEAD: `5df78a5` ("Codex watchdog recover dirty non-live automation artifacts").
- Pending unstaged change is limited to `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (in-flight planner-prompt MVP-counter rotation; covered by the standing `worktree_excluded_paths` precedent established under tasks 165 / 167 / 169 and does not block dispatch).
- `V2_BACKTEST_AND_PAPER_MVP_READY` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md`.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`.
- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`.
- `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_IMPLEMENTATION_READY` body present at `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/07_GO_NO_GO.md`.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md`.
- Planner status JSON `current_mvp_milestone` field is stale (`REPLAY_BACKTEST_RUNNER_MVP` / three remaining); per REQ_0015 § "Evidence-first reconciliation", PASS markers under `claude_worklog/phase2_core_rebuild/` override stale queue / status / dashboard noise. The status JSON is rotated by the supervisor on next dispatch and does not block this planner turn. The dirty planner-prompt MVP-counter rotation is itself stale relative to the consolidation gate evidence and does not gate Phase 2Q.

## Decision

Open Phase 2Q — Aggregate Evidence Roll-up Harness — as the next post-consolidation Lane A evidence-collection milestone, per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp" (post-consolidation evidence collection per REQ_0020 § "Required proof before live") and per the explicit Lane B prerequisite stated in `claude_worklog/agent_supervisor/tasks/169_phase2p_historical_pnl_replay_wiring_implementation.json` `next_recommended_action` ("a Lane B explainability UI milestone backed by the typed lineage rows now certified across Phase 2N / 2O / 2P").

Phase 2Q is the fifth post-consolidation Lane A typed mirror evidence-collection artifact. It authors:

- A deterministic three-source-pack typed evidence pack (`paper_mode`, `shadow_mode`, `historical_pnl`; each pack defines four scenarios (`pack_btc_winner_long`, `pack_eth_winner_short`, `pack_lab_loser_short`, `pack_sol_orchestrator_held`) of three steps each, mirroring the typed-record structure produced by Phase 2N / 2O / 2P; total 36 typed `AggregateRollupSourceInput` rows).
- A pure-function harness that drives the existing `PaperModeRuntime` composition root once at harness level (no per-row composition-root invocation; no `PaperExecutionLedgerRecorder` invocation; no `RiskDecisionEvaluator` invocation; no new typed-record production beyond aggregate counts), gated on the typed paper-mode flag.
- 3 produced typed `AggregateRollupPerSourceRecord` rows.
- 1 typed `AggregateRollupSummary` row aggregating the three per-source records.
- 1 typed `PaperModeFlag` at the harness level.
- pytest coverage for harness paper-mode-flag invariants, per-source typed-row invariants, per-source action / per-symbol / LAB-pointer-presence counters, cross-source summary invariants, lineage carry-over, forbidden lineage / market field absence, forbidden-token scan, and forbidden-import scan.

Phase 2Q does NOT introduce a `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row. Phase 2Q does NOT introduce PnL / size / price / fees / slippage / funding / OI / liquidation / orderbook / hedge-state / residual-exposure / squeeze-risk computation. Phase 2Q does NOT call any Binance read-only account-history endpoint at this stage; the live Binance read-only pull described in REQ_0024 § "Binance Read-Only Policy" remains a separate, later milestone explicitly out of scope at Phase 2Q. Phase 2Q does NOT modify any file under `v2/backend/app/`. Phase 2Q does NOT flip the live-readiness gate.

## Lane / MVP relevance / next gate

- Lane: `paper_backtest_mvp`.
- MVP relevance: post-consolidation Lane A evidence collection. The aggregate roll-up harness produces typed cross-source `AggregateRollupSummary` records over the three preceding evidence-collection harnesses (paper-mode 2N, shadow-mode 2O, historical-PnL 2P), gated on the typed paper-mode flag, establishing the typed offline-inspectable cross-source baseline that subsequent Lane B decision-explainability UI milestones consume as real backend contracts (per REQ_0009 § "Required UI visibility" and REQ_0018 lane B). No new code surface beyond test-only fixtures, a pure-function harness module, and a pytest module.
- Blocked by (all materialized): see `05_GO_NO_GO_REQUEST.md` § "Predecessor evidence".
- Next gate: `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/07_GO_NO_GO.md`. Codex review marker: `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS`.

## Authored task

The planner turn authors:

- The Phase 2Q planning packet (01–05) under `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/`.
- This planner-turn note (`PLANNER_TURN_2Q_OPEN_IMPLEMENTATION.md`).
- The supervisor task `171_phase2q_aggregate_evidence_rollup_harness_implementation` under `claude_worklog/agent_supervisor/tasks/`.

## Hard safety posture

Live trading: BLOCKED. Phase 2Q is non-live by construction. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. No live Binance API call.

## Recovery posture (Codex autofix lane)

Per REQ_0007 / REQ_0011 / REQ_0014 / REQ_0016 / REQ_0021, on a Codex FAIL with concrete documentation blockers and no safety violation, the supervisor dispatches a Codex autofix scoped to the Phase 2Q packet only. If the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H / 2I / 2J / 2K / 2L / 2M / 2N / 2O / 2P reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_PLANNER_TURN_OPEN_READY
END_FILE: claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/PLANNER_TURN_2Q_OPEN_IMPLEMENTATION.md
