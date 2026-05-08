# PLANNER TURN — Phase 2T — Open Decision Explainability Replay-Backtest Projection Harness (Lane B `explainability_ui`)

Date: 2026-05-08
Active requirement: REQ_0006 ∩ REQ_0007 ∩ REQ_0009 ∩ REQ_0011 ∩ REQ_0014 ∩ REQ_0015 ∩ REQ_0016 ∩ REQ_0017 ∩ REQ_0018 ∩ REQ_0019 ∩ REQ_0020 ∩ REQ_0021 ∩ REQ_0022 ∩ REQ_0023
Lane: explainability_ui (Phase 2T) under codex_watchdog dispatch supervision
Profile: Claude Code Max20 consolidated_default
Live gate: blocked
Distance to `V2_BACKTEST_AND_PAPER_MVP_READY`: 0 milestones remain (closed at `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`).

## Trigger

`PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_CODEX_PASS` is materialized at HEAD `2417cdc` at `claude_worklog/phase2_core_rebuild/decision_explainability_paper_ledger_projection/09_CODEX_GO_NO_GO.md` body line one. Per REQ_0014 / REQ_0015 evidence-first reconciliation, this PASS marker overrides any stale queue `pending` status of supervisor task 176; the predecessor surface area for the next Lane B milestone is the file marker, not the queue task status.

## Decision

Open Phase 2T — Decision Explainability Replay-Backtest Projection Harness — as the **third post-consolidation Lane B `explainability_ui` milestone** (after Phase 2R decision-explainability data contract and Phase 2S paper-ledger-explainability projection). Phase 2T authors a deterministic, pure-function, per-row typed-mirror **replay-backtest-step / replay-backtest-summary explainability projection** harness. The harness drives the existing `ReplayBacktestRunner` composition root once at harness level via `build_replay_backtest_runner(now_ms_clock=build_replay_clock())` and the existing `PaperExecutionLedgerRecorder` composition root once at harness level via `build_paper_execution_ledger_recorder(now_ms_clock=build_paper_ledger_clock())`, invokes the recorder per-row to produce a typed `PaperExecutionLedgerEntry`, invokes `assemble_step` per-row to obtain a typed `ReplayBacktestStep`, invokes `assemble_summary` per-scenario to obtain a typed `ReplayBacktestSummary`, and projects each typed step into a typed `ReplayBacktestStepExplainabilityEnvelope` and each typed summary into a typed `ReplayBacktestSummaryExplainabilityEnvelope`. The envelopes are the typed offline-inspectable backend contracts that subsequent Lane B UI panel milestones (Mission Control replay timeline, Signal Explainability replay panel, Paper / Shadow Trading replay overlay, Audit Ledger replay-step trace per REQ_0009 § "Website pages") consume per REQ_0009 § "Required UI visibility" without fabricated reasoning.

## Authored task

This planner turn authors:

- The Phase 2T planning packet (01–05) under `claude_worklog/phase2_core_rebuild/decision_explainability_replay_backtest_projection/`.
- A milestone-internal planner-turn note `PLANNER_TURN_2T_OPEN_IMPLEMENTATION.md` under the same directory.
- This autonomous-control-plane planner-turn note.
- The supervisor task `177_phase2t_decision_explainability_replay_backtest_projection_implementation.json` under `claude_worklog/agent_supervisor/tasks/`.
- The queued `codex_recover_177_phase2t_decision_explainability_replay_backtest_projection_implementation.json` shadow recovery task per the standing `codex_recover_<task_id>` precedent.

## Lane / MVP relevance / next gate

- `lane`: `explainability_ui`.
- `mvp_relevance`: third Lane B post-consolidation milestone backed by real lineage IDs only (`replay_step_id`, `replay_run_id`, `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`) and the existing typed surface fields on `ReplayBacktestStep` / `ReplayBacktestSummary`. Establishes the typed `ReplayBacktestStepExplainabilityEnvelope` and `ReplayBacktestSummaryExplainabilityEnvelope` as the deterministic offline-inspectable backend contracts for the per-row replay projection.
- `next_gate`: `PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/decision_explainability_replay_backtest_projection/07_GO_NO_GO.md` after task 177 dispatch; subsequently `PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_CODEX_PASS` at `09_CODEX_GO_NO_GO.md` after the queued Phase 2T Codex review task.
- `blocked_by`: `PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_CODEX_PASS` (satisfied at HEAD `2417cdc`).
- `legacy_evidence_consulted`: Phase 2S packet (01–07, 09); `replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`; `legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` and `11_FAILURE_MODE_AND_GAP_REGISTER.md`; `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`; `historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md` and `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`; `v2/backend/app/domain/replay_backtest_runner/step.py` and `summary.py`; `v2/backend/app/composition/replay_backtest_runner/runtime.py`.
- `legacy_failure_addressed`: legacy bot operated without a typed, deterministic, offline-inspectable per-row replay-backtest-step explainability data contract that lifts a typed `ReplayBacktestStep` into a typed envelope row carrying mirrored replay/lineage IDs, mirrored step-side and input-side action/reason codes, mirrored step timestamp, mirrored live-blocked flag, and deterministic test-only metadata; replay evidence was scattered across legacy logs and ad-hoc monitor scripts. Phase 2T introduces the typed offline-inspectable per-row replay-step / per-scenario replay-summary explainability backend contracts.

## Hard safety posture

Live trading: BLOCKED. Phase 2T is non-live by construction. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. No live Binance API call. No file under `v2/backend/app/` modified. No file under `v2/frontend/` modified. No file under any prior-milestone Phase 2 directory modified. No standalone harness framing-token marker line in any authored file body.

PHASE2T_DECISION_EXPLAINABILITY_REPLAY_BACKTEST_PROJECTION_PLANNER_TURN_OPEN_READY
